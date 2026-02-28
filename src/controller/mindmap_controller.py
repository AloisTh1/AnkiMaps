import logging
import math
import sqlite3
from typing import Any, Optional, Union

from anki.cards import Card
from anki.collection import Collection
from anki.decks import Deck, DeckId, FilteredDeckConfig
from anki.notes import Note, NoteId
from aqt import QObject, dialogs, gui_hooks, mw, pyqtSignal
from aqt.operations import QueryOp
from aqt.utils import showCritical, showInfo, showWarning

from ..common.constants import ANKIMAPS_CONSTANTS
from ..model.connections import CONNECTION_TYPES, MindMapConnection
from ..model.mindmap import MindMap
from ..model.node import MindMapNode
from ..repository.anki_repository import AnkiRepository
from ..repository.db.sql_repository import SqlLiteRepository
from .history_commands import (
    MoveNodesCommand,
    UpdateConnectionColorCommand,
    UnlinkConnectionCommand,
    LinkConnectionCommand,
    build_link_snapshot,
    build_snapshot_from_existing,
)
from .history_manager import HistoryCommand, HistoryManager

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)
PROPERTY_TO_COLUMN_MAP = {
    "width": "width",
    "font_size": "fontSize",
    "shown_field_indices": "fieldsToShow",
}

CONN_PROPERTY_TO_COLUMN_MAP = {
    "connection_type": "connectionType",
    "color": "color",
    "size": "size",
}


class MindmapController(QObject):
    """
    The "brain" of the application. It is headless and knows nothing of the view.
    It holds the authoritative in-memory model and orchestrates all changes.
    It emits signals about ephemeral state changes, like review mode.
    """

    review_state_changed = pyqtSignal(bool)  # is_reviewing, due_note_ids
    review_progress_updated = pyqtSignal(int, int)  # remaining, total
    review_focus_changed = pyqtSignal(object, bool)  # nid, answer_visible
    load_and_hydrate_ready = pyqtSignal()
    search_results_found = pyqtSignal(list)  # list of NoteIds

    def __init__(self, anki_repository: AnkiRepository, sql_repository: SqlLiteRepository):
        super().__init__()
        self.anki_repository = anki_repository
        self.sql_repository = sql_repository

        self.model: Optional[MindMap] = None
        self.db_connection: Optional[sqlite3.Connection] = None

        self.is_reviewing = False
        self._review_deck_id: Optional[DeckId] = None
        self._total_review_count = 0
        self._due_note_ids_in_session: set[NoteId] = set()
        self._active_note_id: Optional[NoteId] = None
        self._answer_is_visible = False
        self._history = HistoryManager(max_size=100)

        gui_hooks.editor_did_fire_typing_timer.append(self._on_note_updated_in_editor)
        gui_hooks.reviewer_did_show_question.append(self.on_will_show_question)
        gui_hooks.reviewer_did_show_answer.append(self.on_will_show_answer)
        gui_hooks.state_did_change.append(self.on_state_change)

    def _execute_history_command(self, command: HistoryCommand) -> None:
        try:
            if not self._history.execute(command):
                logger.info(
                    "History command skipped (execute returned False): %s",
                    command.__class__.__name__,
                )
                return
            logger.info(
                "History command executed: %s (undo_stack=%s redo_stack=%s)",
                command.__class__.__name__,
                self._history.undo_size(),
                self._history.redo_size(),
            )
        except Exception as exc:
            showWarning(f"Could not apply action: {exc}")

    def undo(self) -> None:
        if not self._history.can_undo():
            logger.info("Undo requested but history is empty.")
            return
        try:
            self._history.undo()
            logger.info(
                "Undo applied. undo_stack=%s redo_stack=%s",
                self._history.undo_size(),
                self._history.redo_size(),
            )
        except Exception as exc:
            showWarning(f"Could not undo action: {exc}")

    def redo(self) -> None:
        if not self._history.can_redo():
            logger.info("Redo requested but redo stack is empty.")
            return
        try:
            if self._history.redo():
                logger.info(
                    "Redo applied. undo_stack=%s redo_stack=%s",
                    self._history.undo_size(),
                    self._history.redo_size(),
                )
        except Exception as exc:
            showWarning(f"Could not redo action: {exc}")

    def load_and_hydrate_model(
        self,
        mindmap_name: str,
    ) -> None:
        """
        Loads and hydrates the model from the database on a background thread.
        """
        if not mw:
            return

        def op(_: Collection) -> tuple:
            conn = self.sql_repository.get_connection(mindmap_name)
            if not conn:
                raise Exception(f"Could not connect to database for {mindmap_name}")

            try:
                nodes_data, connections_data = self.sql_repository.load_entire_map_data(conn)
                all_note_ids = [NoteId(row["noteId"]) for row in nodes_data]
                anki_notes_map = {n.id: n for n in self.anki_repository.get_notes_by_ids(all_note_ids)}
                return nodes_data, connections_data, anki_notes_map
            finally:
                conn.close()

        def on_success(result: tuple) -> None:
            nodes_data, connections_data, anki_notes_map = result

            self.model = MindMap(name=mindmap_name)

            if nodes_data:
                for row in nodes_data:
                    note_id = NoteId(row["noteId"])
                    if anki_note := anki_notes_map.get(note_id):
                        fields_str = row.get("fieldsToShow", "0")  # Use .get() for safety
                        node = MindMapNode(
                            note_id=note_id,
                            anki_note=anki_note,
                            x=row["x"],
                            y=row["y"],
                            width=row["width"],
                            font_size=row["fontSize"],
                            shown_field_indices=[int(i) for i in fields_str.split(",") if i.isdigit()],
                        )
                        self.model.add_node(node)

            for row in connections_data:
                try:
                    from_id, to_id = NoteId(row["fromNoteId"]), NoteId(row["toNoteId"])
                    if self.model and from_id in self.model.nodes and to_id in self.model.nodes:
                        connection = MindMapConnection(
                            connection_id=row["connectionId"],
                            from_note_id=from_id,
                            to_note_id=to_id,
                            connection_type=CONNECTION_TYPES(row["connectionType"]),
                            color=row["color"],
                            size=row["size"],
                            label=row["label"],
                            label_size=row["labelSize"],
                        )
                        self.model.add_connection(connection)
                except (ValueError, KeyError):
                    continue

            self.db_connection = self.sql_repository.get_connection(mindmap_name)
            self._history.clear()
            self.model.model_loaded.emit()
            self.load_and_hydrate_ready.emit()
            logger.info("Controller: Model hydration and quadtree creation complete.")

        def on_failure(err: Exception) -> None:
            logger.critical(f"Failed to load mind map: {err}")
            showWarning(f"Could not load the mind map. The error was: {err}")

        self.db_connection = None

        QueryOp(parent=mw, op=op, success=on_success).failure(on_failure).with_progress(
            "Opening mind map..."
        ).run_in_background()

    def perform_search(self, search_term: str):
        if not self.model:
            return

        search_term = search_term.strip().lower()

        if not search_term:
            self.search_results_found.emit([])
            return

        found_ids = []
        for mindmap_node in self.model.nodes.values():
            anki_note = mindmap_node.anki_note
            for field_content in anki_note.fields:
                if search_term in field_content.lower():
                    found_ids.append(mindmap_node.note_id)
                    break

        self.search_results_found.emit(found_ids)

    def save_selected_notes(self, notes_ids: list[NoteId], fields_to_show_str="0"):
        def _layout_grid_pattern(
            nodes: list[MindMapNode],
            start_x: float,
            start_y: float,
            node_width: float,
            grid_padding: int = 40,
        ):
            if not nodes:
                return

            num_nodes = len(nodes)
            cols = int(math.ceil(math.sqrt(num_nodes)))
            rows = int(math.ceil(num_nodes / cols))

            cell_size = node_width + grid_padding
            grid_width = (cols - 1) * cell_size
            grid_height = (rows - 1) * cell_size

            grid_start_x = start_x - grid_width / 2
            grid_start_y = start_y - grid_height / 2

            for i, node in enumerate(nodes):
                row = i // cols
                col = i % cols
                node.x = grid_start_x + col * cell_size
                node.y = grid_start_y + row * cell_size

        if not self.model or not self.db_connection:
            return

        existing_node_ids = set(self.model.nodes.keys())
        bounds_rect = self.model.get_bounds()

        def op(_col: Collection) -> list[MindMapNode]:
            anki_notes = self.anki_repository.get_notes_by_ids(notes_ids)
            if not anki_notes:
                raise Exception("Could not fetch selected notes from Anki.")

            if not self.model:
                raise Exception("Model is not initialized")

            nodes_to_add = [
                MindMapNode(
                    note_id=n.id,
                    anki_note=n,
                    x=0,
                    y=0,
                    width=ANKIMAPS_CONSTANTS.DEFAULT_NOTE_WIDTH.value,
                    font_size=ANKIMAPS_CONSTANTS.DEFAULT_NOTE_FONT_SIZE.value,
                    shown_field_indices=[int(i) for i in fields_to_show_str.split(",") if i.isdigit()],
                )
                for n in anki_notes
                if n.id not in existing_node_ids
            ]

            if not nodes_to_add:
                raise Exception("Selected notes are already in the map !")

            center_pos = bounds_rect.center()
            if len(nodes_to_add) == 1:
                nodes_to_add[0].x = center_pos.x()
                nodes_to_add[0].y = center_pos.y()
            else:
                _layout_grid_pattern(
                    nodes_to_add, center_pos.x(), center_pos.y(), ANKIMAPS_CONSTANTS.DEFAULT_NOTE_WIDTH.value
                )

            return nodes_to_add

        def on_success(result: list[MindMapNode]) -> None:
            nodes_to_add = result

            if not self.db_connection or not self.model:
                showCritical("Model or database connection broken")
                return
            try:
                self.sql_repository.add_nodes(self.db_connection, nodes_to_add)
            except Exception as e:
                showWarning(f"Error saving new notes: {e}")
                return

            self.model.add_nodes_batch(nodes_to_add)
            showInfo(f"Added {len(nodes_to_add)} notes to AnkiMaps.")

        def on_failure(e: Exception) -> None:
            if isinstance(e, Exception):
                showInfo(str(e))
            else:
                showWarning(f"An unexpected error occurred: {e}")
                logger.exception("Hard failure in save_selected_notes")

        if mw:
            QueryOp(parent=mw, op=op, success=on_success).failure(on_failure).with_progress(
                "Preparing notes..."
            ).run_in_background()
        else:
            showCritical("Main window not initialized")

    def update_note_positions(self, moved_notes_data: list[dict]):
        if not self.model or not self.db_connection:
            return

        previous_positions = []
        new_positions = []

        try:
            for data in moved_notes_data:
                note_id = NoteId(int(data["id"]))
                if not (node := self.model.nodes.get(note_id)):
                    continue

                target_x = float(data["x"])
                target_y = float(data["y"])
                if node.x == target_x and node.y == target_y:
                    continue

                previous_positions.append({"id": int(note_id), "x": float(node.x), "y": float(node.y)})
                new_positions.append({"id": int(note_id), "x": target_x, "y": target_y})
        except (KeyError, TypeError, ValueError) as e:
            showCritical(f"Couldn't parse positions : {e}")
            return

        if not new_positions:
            return

        self._execute_history_command(
            MoveNodesCommand(
                sql_repository=self.sql_repository,
                db_connection=self.db_connection,
                model=self.model,
                previous_positions=previous_positions,
                new_positions=new_positions,
            )
        )

    def update_note_property(self, note_id_str: str, prop_name: str, value):
        if not self.model or not self.db_connection:
            return
        if prop_name not in PROPERTY_TO_COLUMN_MAP:
            logger.warning(f"Attempted to update an unknown property: {prop_name}")
            return
        column_name = PROPERTY_TO_COLUMN_MAP[prop_name]
        try:
            note_id = NoteId(int(note_id_str))
            db_value = value
            if prop_name == "shown_field_indices":
                db_value = ",".join(map(str, value))
            self.sql_repository.update_node_property(self.db_connection, note_id, column_name, db_value)
            self.model.update_node_property(note_id, prop_name, value)
        except (ValueError, TypeError) as e:
            logger.error(f"Error updating property '{prop_name}': {e}")

    def update_connection_property(self, note_id_1_str: str, note_id_2_str: str, prop_name: str, value: Any):
        if not self.model or not self.db_connection:
            return
        if prop_name not in CONN_PROPERTY_TO_COLUMN_MAP:
            logger.warning(f"Attempted to update an unknown connection property: {prop_name}")
            return

        column_name = CONN_PROPERTY_TO_COLUMN_MAP[prop_name]
        try:
            id1, id2 = NoteId(int(note_id_1_str)), NoteId(int(note_id_2_str))

            if prop_name == "color":
                connection = self.model.get_connection(id1, id2)
                if not connection:
                    return
                self._execute_history_command(
                    UpdateConnectionColorCommand(
                        sql_repository=self.sql_repository,
                        db_connection=self.db_connection,
                        model=self.model,
                        id1=id1,
                        id2=id2,
                        old_color=connection.color,
                        new_color=str(value),
                    )
                )
                return

            self.sql_repository.update_connection_property(self.db_connection, id1, id2, column_name, value)

            if conn := self.model.get_connection(id1, id2):
                if prop_name == "connection_type":
                    conn.connection_type = CONNECTION_TYPES(value)
                else:
                    setattr(conn, prop_name, value)

                self.model.connection_updated.emit(conn)
        except (ValueError, TypeError) as e:
            logger.error(f"Error updating connection property '{prop_name}': {e}")

    def delete_notes_from_map(self, note_ids: list[NoteId]):
        if not self.model or not self.db_connection:
            return

        try:
            self.sql_repository.delete_nodes(self.db_connection, note_ids)
        except Exception as e:
            showCritical(f"Error deleting notes from DB, please report to developper : {e}")
            raise
        self.model.remove_nodes_batch(note_ids)

    def toggle_connection(
        self,
        note_id_1_str: str,
        note_id_2_str: str,
        connection_type: int,
        color: str,
        size: int,
        label: str,
        label_size: int,
    ):
        if not self.model or not self.db_connection:
            return
        try:
            id1, id2 = NoteId(int(note_id_1_str)), NoteId(int(note_id_2_str))
            if existing_connection := self.model.get_connection(id1, id2):
                self._execute_history_command(
                    UnlinkConnectionCommand(
                        sql_repository=self.sql_repository,
                        db_connection=self.db_connection,
                        model=self.model,
                        snapshot=build_snapshot_from_existing(existing_connection),
                    )
                )
            else:
                self._execute_history_command(
                    LinkConnectionCommand(
                        sql_repository=self.sql_repository,
                        db_connection=self.db_connection,
                        model=self.model,
                        snapshot=build_link_snapshot(
                            from_note_id=id1,
                            to_note_id=id2,
                            connection_type=connection_type,
                            color=color,
                            size=size,
                            label=label,
                            label_size=label_size,
                        ),
                    )
                )
        except (ValueError, TypeError) as e:
            logger.info(f"Invalid data for connection: {e}")

    def update_connection_label(self, note_id_1_str: str, note_id_2_str: str, new_label: str):
        if not self.model or not self.db_connection:
            return
        try:
            id1, id2 = NoteId(int(note_id_1_str)), NoteId(int(note_id_2_str))
            self.sql_repository.update_connection_label(self.db_connection, id1, id2, new_label)
            if conn := self.model.get_connection(id1, id2):
                conn.label = new_label
                self.model.connection_updated.emit(conn)
        except (ValueError, TypeError) as e:
            logger.info(f"Invalid data for label update: {e}")

    def delete_connection(self, note_id_1_str: str, note_id_2_str: str):
        if not self.model or not self.db_connection:
            return
        try:
            id1, id2 = NoteId(int(note_id_1_str)), NoteId(int(note_id_2_str))
            self.sql_repository.delete_connection(self.db_connection, id1, id2)
            self.model.remove_connection(id1, id2)
        except (ValueError, TypeError) as e:
            logger.info(f"Invalid Note ID for deletion: {e}")

    def _on_note_updated_in_editor(self, note: Note):
        if self.model and self.model.nodes.get(note.id):
            self.model.nodes[note.id].anki_note = note
            self.model.node_properties_changed.emit([note.id])

    def on_state_change(self, new_state: str, old_state: str):
        if self.is_reviewing and old_state == "review":
            if new_state == "overview":
                logger.info("Review session completed. Cleaning up and returning to deck browser.")
                self.is_reviewing = False
                self.review_state_changed.emit(False)
                self._end_anki_review_session(change_state=True)
            elif new_state != "review":
                logger.info("Review session ended by user navigation. Cleaning up AnkiMaps state.")
                self.is_reviewing = False
                self.review_state_changed.emit(False)
                self._end_anki_review_session(change_state=False)

    def toggle_review(self):
        if self.is_reviewing:
            self.is_reviewing = False
            self.review_state_changed.emit(False)
            self._end_anki_review_session(change_state=True)
        else:
            self._start_anki_review_session()

    def _start_anki_review_session(self):
        if not (mw and mw.col and self.model):
            return
        if not (note_ids_on_map := list(self.model.nodes.keys())):
            return showInfo("This mind map is empty.")

        card_ids_for_session = self.anki_repository.get_session_cards_for_notes(note_ids_on_map)

        if not card_ids_for_session:
            return showInfo("No new, learning, or due cards from this mind map were found.")

        self.is_reviewing = True
        self.review_state_changed.emit(True)

        self._due_note_ids_in_session = {mw.col.get_card(cid).nid for cid in card_ids_for_session}

        deck_name = ANKIMAPS_CONSTANTS.FILTERED_DECK_NAME.value

        deck_id = mw.col.decks.new_filtered(name=deck_name)
        deck = mw.col.sched.get_or_create_filtered_deck(DeckId(deck_id))

        deck.config.reschedule = True

        search_terms = []
        chunk_size = 500
        for i in range(0, len(card_ids_for_session), chunk_size):
            chunk = card_ids_for_session[i : i + chunk_size]
            search_text = " or ".join(f"cid:{cid}" for cid in chunk)
            new_term = FilteredDeckConfig.SearchTerm(
                search=search_text,
                limit=9999,
                order=Deck.Filtered.SearchTerm.Order.DUE,
            )
            search_terms.append(new_term)

        del deck.config.search_terms[:]
        deck.config.search_terms.extend(search_terms)

        mw.col.sched.add_or_update_filtered_deck(deck=deck)

        rebuild_result = mw.col.sched.rebuild_filtered_deck(deck_id)
        logger.info(f"Rebuilt filtered deck. New card count: {rebuild_result.count}")

        if rebuild_result.count > 0:
            self._review_deck_id = deck_id
            mw.col.decks.select(self._review_deck_id)
            mw.moveToState("review")
            mw.activateWindow()

        else:
            showInfo("No matching due cards found after building the deck.")
            mw.col.decks.remove([deck_id])
            self.is_reviewing = False
            self.review_state_changed.emit(False)

    def _end_anki_review_session(self, change_state: bool):
        if mw and mw.col and self._review_deck_id:
            try:
                mw.col.decks.remove([self._review_deck_id])
            except Exception as e:
                logger.warning(f"Could not remove filtered deck (it might already be gone): {e}")
            finally:
                self._review_deck_id = None

        self._total_review_count = 0
        self._due_note_ids_in_session.clear()
        self._active_note_id = None
        self._answer_is_visible = False

        if change_state and mw:
            mw.moveToState("deckBrowser")

    def on_will_show_question(self, card: Card):
        if self.is_reviewing:
            if self._review_deck_id and mw and mw.col:
                counts = mw.col.sched.counts()
                remaining = sum(counts)
                self.review_progress_updated.emit(remaining, self._total_review_count)

            self._active_note_id = card.nid
            self._answer_is_visible = False
            self.review_focus_changed.emit(self._active_note_id, self._answer_is_visible)

    def on_will_show_answer(self, card: Card):
        if self.is_reviewing:
            self._answer_is_visible = True
            self.review_focus_changed.emit(self._active_note_id, self._answer_is_visible)

    def cleanup(self):
        if self.is_reviewing:
            self._end_anki_review_session(change_state=False)

        if self.db_connection:
            self.db_connection.close()
            self.db_connection = None
        self._history.clear()
        logger.info("[CONTROLLER] Cleaned up controller.")

        hooks_to_remove = [
            (gui_hooks.editor_did_fire_typing_timer, self._on_note_updated_in_editor),
            (gui_hooks.reviewer_did_show_question, self.on_will_show_question),
            (gui_hooks.reviewer_did_show_answer, self.on_will_show_answer),
            (gui_hooks.state_did_change, self.on_state_change),
        ]

        for hook, func in hooks_to_remove:
            try:
                hook.remove(func)
            except (ValueError, TypeError):
                pass

    def open_add_note_dialog(self):
        if browser := dialogs.open("Browser", mw):
            menu = browser.form.menu_Notes
            menu.addSeparator()
            action = menu.addAction("Add to AnkiMaps")
            action.setShortcut("ctrl+m")
            action.triggered.connect(lambda: self.save_selected_notes(browser.selectedNotes()))

    def edit_notes(self, note_ids: Union[list[int], list[NoteId]]):
        if mw and mw.col:
            if len(note_ids) > 900:
                showInfo("Opening a large number of notes in the browser. This may take a moment.")

            search_str = " or ".join(f"nid:{nid}" for nid in note_ids)
            if browser := dialogs.open("Browser", mw):
                browser.search_for(search_str)
