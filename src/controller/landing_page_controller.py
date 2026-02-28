import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Any

from anki.notes import NoteId

from ..common.constants import ANKIMAPS_CONSTANTS
from ..model.connections import CONNECTION_TYPES, MindMapConnection
from ..model.node import MindMapNode
from ..repository.anki_repository import AnkiRepository
from ..repository.db.sql_repository import SqlLiteRepository
from ..repository.mindmap_files_repository import MindmapFilesRepository

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)
BUNDLE_FORMAT_V1 = "ankimaps_bundle_v1"
BUNDLE_FORMAT_V2 = "ankimaps_bundle_v2"


class LandingPageController:
    def __init__(
        self,
        files_repository: MindmapFilesRepository,
        sql_repository: SqlLiteRepository,
        anki_repository: AnkiRepository,
    ):
        self.files_repository = files_repository
        self.sql_repository = sql_repository
        self.anki_repository = anki_repository

    def get_mindmaps_with_info(self) -> tuple[list[str], dict[str, dict[str, Any]]]:
        mindmap_names = self.files_repository.get_mindmap_names()
        mindmap_infos: dict[str, dict[str, Any]] = {}

        for mindmap_name in mindmap_names:
            map_info = self.files_repository.get_mindmap_file_metadata(mindmap_name)
            map_info["backup_count"] = self.files_repository.get_mindmap_backup_count(mindmap_name)

            try:
                map_info.update(self.sql_repository.get_map_statistics(mindmap_name))
            except Exception as exc:
                logger.warning(f"Could not read sqlite stats for '{mindmap_name}': {exc}")

            mindmap_infos[mindmap_name] = map_info

        return mindmap_names, mindmap_infos

    def export_mindmap(self, mindmap_name: str, destination_file_path: str) -> None:
        self.files_repository.export_mindmap(mindmap_name, destination_file_path)

    def import_mindmap(self, source_file_path: str) -> tuple[str, bool]:
        return self.files_repository.import_mindmap(source_file_path)

    def export_mindmap_bundle(self, mindmap_name: str, destination_file_path: str) -> dict[str, Any]:
        conn = self.sql_repository.get_connection(mindmap_name)
        try:
            nodes_data, connections_data = self.sql_repository.load_entire_map_data(conn)
        finally:
            conn.close()

        note_ids = [NoteId(int(row["noteId"])) for row in nodes_data]
        notes_by_id = {int(note.id): note for note in self.anki_repository.get_notes_by_ids(note_ids)}

        exported_nodes = []
        guid_by_note_id: dict[int, str] = {}
        skipped_nodes = 0
        for row in nodes_data:
            note_id = int(row["noteId"])
            anki_note = notes_by_id.get(note_id)
            note_guid = str(anki_note.guid) if anki_note and getattr(anki_note, "guid", None) else ""
            if not note_guid:
                skipped_nodes += 1
                continue

            guid_by_note_id[note_id] = note_guid
            exported_nodes.append(
                {
                    "guid": note_guid,
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "width": float(row["width"]),
                    "fontSize": float(row["fontSize"]),
                    "fieldsToShow": str(row.get("fieldsToShow", "0")),
                }
            )

        exported_connections = []
        skipped_connections = 0
        for row in connections_data:
            from_note_id = int(row["fromNoteId"])
            to_note_id = int(row["toNoteId"])
            from_guid = guid_by_note_id.get(from_note_id)
            to_guid = guid_by_note_id.get(to_note_id)
            if not from_guid or not to_guid:
                skipped_connections += 1
                continue

            exported_connections.append(
                {
                    "fromGuid": from_guid,
                    "toGuid": to_guid,
                    "connectionType": int(row["connectionType"]),
                    "color": str(row["color"]),
                    "size": int(row["size"]),
                    "label": str(row["label"]),
                    "labelSize": int(row["labelSize"]),
                }
            )

        payload = {
            "format": BUNDLE_FORMAT_V2,
            "map_name": mindmap_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "nodes": exported_nodes,
            "connections": exported_connections,
        }
        note_ids_for_deck = [NoteId(note_id) for note_id in guid_by_note_id.keys()]
        if not note_ids_for_deck:
            raise ValueError("Bundle export failed: no resolvable notes were found in the mind map.")

        temp_dir = tempfile.mkdtemp(prefix="ankimaps_bundle_export_")
        try:
            apkg_path = os.path.join(temp_dir, "notes.apkg")
            self.anki_repository.export_notes_to_apkg(note_ids_for_deck, apkg_path)
            self.files_repository.write_bundle_archive(destination_file_path, payload, apkg_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            "nodes_total": len(nodes_data),
            "nodes_exported": len(exported_nodes),
            "nodes_skipped": skipped_nodes,
            "connections_total": len(connections_data),
            "connections_exported": len(exported_connections),
            "connections_skipped": skipped_connections,
            "deck_notes_exported": len(note_ids_for_deck),
        }

    def import_mindmap_bundle(self, source_file_path: str) -> dict[str, Any]:
        payload: dict[str, Any]
        apkg_file_path = None

        temp_dir = tempfile.mkdtemp(prefix="ankimaps_bundle_import_")
        try:
            if zipfile.is_zipfile(source_file_path):
                payload, apkg_file_path = self.files_repository.read_bundle_archive(
                    source_file_path, temp_dir
                )
            else:
                payload = self.files_repository.read_bundle(source_file_path)

            bundle_format = payload.get("format")
            if bundle_format not in (BUNDLE_FORMAT_V1, BUNDLE_FORMAT_V2):
                raise ValueError("Unsupported bundle format.")

            if apkg_file_path:
                self.anki_repository.import_apkg(apkg_file_path)

            raw_nodes = payload.get("nodes", [])
            raw_connections = payload.get("connections", [])
            if not isinstance(raw_nodes, list) or not isinstance(raw_connections, list):
                raise ValueError("Invalid bundle structure.")

            preferred_name = str(payload.get("map_name", "Imported Bundle")).strip() or "Imported Bundle"
            imported_name, renamed_on_import = self.files_repository.resolve_available_mindmap_name(
                preferred_name
            )

            bundle_guids = [str(node.get("guid", "")).strip() for node in raw_nodes if isinstance(node, dict)]
            guid_to_note_id = self.anki_repository.get_note_ids_by_guids(bundle_guids)

            all_mapped_note_ids = list(dict.fromkeys(guid_to_note_id.values()))
            notes_by_id = {
                int(note.id): note
                for note in self.anki_repository.get_notes_by_ids(list(all_mapped_note_ids))
            }

            nodes_to_insert: list[MindMapNode] = []
            guid_to_local_note_id: dict[str, NoteId] = {}
            unresolved_node_guids: set[str] = set()
            inserted_note_ids: set[int] = set()
            for raw_node in raw_nodes:
                if not isinstance(raw_node, dict):
                    continue
                note_guid = str(raw_node.get("guid", "")).strip()
                if not note_guid:
                    continue

                local_note_id = guid_to_note_id.get(note_guid)
                if local_note_id is None:
                    unresolved_node_guids.add(note_guid)
                    continue

                note_id_int = int(local_note_id)
                if note_id_int in inserted_note_ids:
                    guid_to_local_note_id[note_guid] = local_note_id
                    continue

                if not (anki_note := notes_by_id.get(note_id_int)):
                    unresolved_node_guids.add(note_guid)
                    continue

                fields_to_show_raw = str(raw_node.get("fieldsToShow", "0"))
                shown_fields = [int(i) for i in fields_to_show_raw.split(",") if i.strip().isdigit()]
                if not shown_fields:
                    shown_fields = [0]

                nodes_to_insert.append(
                    MindMapNode(
                        note_id=local_note_id,
                        anki_note=anki_note,
                        x=self._as_float(raw_node.get("x"), 0.0),
                        y=self._as_float(raw_node.get("y"), 0.0),
                        width=self._as_float(
                            raw_node.get("width"), float(ANKIMAPS_CONSTANTS.DEFAULT_NOTE_WIDTH.value)
                        ),
                        shown_field_indices=shown_fields,
                        font_size=self._as_float(
                            raw_node.get("fontSize"), float(ANKIMAPS_CONSTANTS.DEFAULT_NOTE_FONT_SIZE.value)
                        ),
                    )
                )
                guid_to_local_note_id[note_guid] = local_note_id
                inserted_note_ids.add(note_id_int)

            if not nodes_to_insert:
                raise ValueError("Import aborted: no bundle notes were found in this collection.")

            connections_to_insert: list[MindMapConnection] = []
            skipped_connections = 0
            seen_connections: set[tuple[int, int]] = set()
            for raw_connection in raw_connections:
                if not isinstance(raw_connection, dict):
                    continue
                from_guid = str(raw_connection.get("fromGuid", "")).strip()
                to_guid = str(raw_connection.get("toGuid", "")).strip()
                from_note_id = guid_to_local_note_id.get(from_guid)
                to_note_id = guid_to_local_note_id.get(to_guid)
                if not from_note_id or not to_note_id:
                    skipped_connections += 1
                    continue

                connection_key = (int(from_note_id), int(to_note_id))
                if connection_key in seen_connections:
                    continue

                connection_type_value = self._as_int(raw_connection.get("connectionType"), 0)
                try:
                    connection_type = CONNECTION_TYPES(connection_type_value)
                except ValueError:
                    connection_type = CONNECTION_TYPES.FULL_DIRECTED

                connections_to_insert.append(
                    MindMapConnection(
                        connection_id=0,
                        from_note_id=from_note_id,
                        to_note_id=to_note_id,
                        connection_type=connection_type,
                        color=str(
                            raw_connection.get(
                                "color",
                                ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value,
                            )
                        ),
                        size=max(
                            1,
                            self._as_int(
                                raw_connection.get("size"),
                                int(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_SIZE.value),
                            ),
                        ),
                        label=str(raw_connection.get("label", "")),
                        label_size=max(
                            1,
                            self._as_int(
                                raw_connection.get("labelSize"),
                                int(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_LABEL_FONT_SIZE.value),
                            ),
                        ),
                    )
                )
                seen_connections.add(connection_key)

            conn = self.sql_repository.get_connection(imported_name)
            imported_connections = 0
            try:
                self.sql_repository.add_nodes(conn, nodes_to_insert)
                for connection in connections_to_insert:
                    try:
                        self.sql_repository.add_connection(conn, connection)
                        imported_connections += 1
                    except Exception:
                        skipped_connections += 1
            finally:
                conn.close()

            return {
                "imported_name": imported_name,
                "renamed_on_import": renamed_on_import,
                "nodes_total": len(raw_nodes),
                "nodes_imported": len(nodes_to_insert),
                "nodes_unresolved": len(unresolved_node_guids),
                "connections_total": len(raw_connections),
                "connections_imported": imported_connections,
                "connections_skipped": skipped_connections,
                "deck_imported": bool(apkg_file_path),
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _as_int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _as_float(self, value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback
