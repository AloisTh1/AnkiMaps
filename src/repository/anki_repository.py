import logging
import os
from datetime import datetime
from typing import Union

from anki.cards import CardId
from anki.collection import Collection
from anki.decks import Deck, DeckId, FilteredDeckConfig
from anki.errors import NotFoundError
from anki.notes import Note, NoteId
from aqt import mw
from aqt.utils import showWarning

from ..common.constants import ANKIMAPS_CONSTANTS

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class AnkiRepository:
    def __init__(self):
        self.collection: Collection = mw.col  # type: ignore

    def _ensure_collection(self) -> Union[Collection, None]:
        """Ensure we have access to the collection"""
        try:
            if mw and mw.col:
                self.collection = mw.col
            return self.collection
        except Exception as e:
            showWarning(f"Error while getting the collection : {str(e)}")
            return None

    def get_notes_by_ids(self, note_ids: list[NoteId]) -> list[Note]:
        """
        Retrieves full Anki Note objects for a given list of NoteIds.
        """
        anki_notes = []
        if col := self._ensure_collection():
            for note_id in note_ids:
                try:
                    note = col.get_note(id=note_id)
                    anki_notes.append(note)
                except NotFoundError:
                    logger.info(f"Note ID {note_id} was requested but not found in Anki. Skipping.")
                    continue
        return anki_notes

    def get_note_by_id(self, note_id: NoteId) -> Union[Note, None]:
        """Get a note by its ID"""
        if not self._ensure_collection():
            return None
        try:
            logger.info(f"[REPOSITORY] Getting note {note_id}")
            note = self.collection.get_note(note_id)
            return note
        except Exception as e:
            logger.info(f"[REPOSITORY] Error getting note {note_id}: {str(e)}")
            return None

    def get_session_cards_for_notes(self, note_ids: list[NoteId]) -> list[CardId]:
        """Finds all card IDs from a list of note IDs that are currently due for review."""
        if not note_ids or not self._ensure_collection():
            return []

        all_card_ids = []
        for note_id in note_ids:
            all_card_ids.extend(self.collection.card_ids_of_note(note_id))

        if not all_card_ids:
            return []

        chunk_size = 500  # A safe number well below the 1000 limit
        final_session_card_ids: list[CardId] = []

        for i in range(0, len(all_card_ids), chunk_size):
            chunk = all_card_ids[i : i + chunk_size]
            cids_string = " or ".join(f"cid:{cid}" for cid in chunk)
            search_query = f"(is:due or is:new or is:learn) and ({cids_string})"

            due_chunk_ids = self.collection.find_cards(search_query)
            final_session_card_ids.extend(due_chunk_ids)

        logger.info(
            f"Found {len(final_session_card_ids)} new, learning, or due cards for the current mind map."
        )
        return final_session_card_ids

    def get_note_ids_by_guids(self, note_guids: list[str]) -> dict[str, NoteId]:
        """
        Resolves note GUIDs to local note IDs.
        """
        if not note_guids or not self._ensure_collection():
            return {}

        unique_guids = list(dict.fromkeys(guid for guid in note_guids if guid))
        if not unique_guids:
            return {}

        resolved: dict[str, NoteId] = {}
        chunk_size = 500
        for index in range(0, len(unique_guids), chunk_size):
            chunk = unique_guids[index : index + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            query = f"SELECT id, guid FROM notes WHERE guid IN ({placeholders})"
            try:
                rows = self.collection.db.all(query, *chunk)
            except Exception as exc:
                logger.warning(f"Could not resolve note GUIDs for chunk starting at {index}: {exc}")
                continue

            for note_id, note_guid in rows:
                resolved[str(note_guid)] = NoteId(int(note_id))

        return resolved

    def export_notes_to_apkg(self, note_ids: list[NoteId], destination_file_path: str) -> None:
        """
        Exports notes as an .apkg by building a temporary filtered deck.
        """
        if not note_ids:
            raise ValueError("No notes selected for export.")
        if not self._ensure_collection():
            raise RuntimeError("Collection is not available.")

        destination_dir = os.path.dirname(destination_file_path)
        if destination_dir:
            os.makedirs(destination_dir, exist_ok=True)

        note_ids_unique = list(dict.fromkeys(int(note_id) for note_id in note_ids))
        export_deck_name = f"AnkiMaps Bundle Export {datetime.now().strftime('%Y%m%d_%H%M%S')}"

        deck_id: DeckId = DeckId(0)
        try:
            deck_id = DeckId(self.collection.decks.new_filtered(name=export_deck_name))
            deck = self.collection.sched.get_or_create_filtered_deck(deck_id)
            deck.config.reschedule = False

            search_order = getattr(
                Deck.Filtered.SearchTerm.Order, "ADDED", Deck.Filtered.SearchTerm.Order.DUE
            )
            search_terms = []
            chunk_size = 500
            for index in range(0, len(note_ids_unique), chunk_size):
                chunk = note_ids_unique[index : index + chunk_size]
                search_text = " or ".join(f"nid:{note_id}" for note_id in chunk)
                search_terms.append(
                    FilteredDeckConfig.SearchTerm(
                        search=search_text,
                        limit=9999,
                        order=search_order,
                    )
                )

            del deck.config.search_terms[:]
            deck.config.search_terms.extend(search_terms)
            self.collection.sched.add_or_update_filtered_deck(deck=deck)
            self.collection.sched.rebuild_filtered_deck(deck_id)

            from anki.exporting import AnkiPackageExporter

            exporter = AnkiPackageExporter(self.collection)
            exporter.did = deck_id
            if hasattr(exporter, "includeSched"):
                exporter.includeSched = True
            if hasattr(exporter, "includeMedia"):
                exporter.includeMedia = True
            exporter.exportInto(destination_file_path)
        finally:
            if deck_id and int(deck_id) > 0:
                try:
                    self.collection.decks.remove([deck_id])
                except Exception as exc:
                    logger.warning(f"Could not clean temporary export deck '{export_deck_name}': {exc}")

    def import_apkg(self, package_path: str) -> None:
        """
        Imports an .apkg file into the current collection.
        """
        if not package_path or not os.path.isfile(package_path):
            raise FileNotFoundError("APKG package not found.")
        if not self._ensure_collection():
            raise RuntimeError("Collection is not available.")

        try:
            from anki.collection import (
                ImportAnkiPackageOptions,
                ImportAnkiPackageRequest,
            )

            self.collection.import_anki_package(
                ImportAnkiPackageRequest(
                    package_path=package_path,
                    options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
                )
            )
            return
        except Exception as import_exc:
            logger.warning(f"Modern .apkg import path failed, trying legacy importer: {import_exc}")

        from anki.importing.apkg import AnkiPackageImporter

        importer = AnkiPackageImporter(self.collection, package_path)
        importer.run()
