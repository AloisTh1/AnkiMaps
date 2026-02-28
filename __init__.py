# __init__.py
import logging
import os
from logging import LogRecord
from typing import List, Optional, Sequence

from anki.hooks import notes_will_be_deleted
from anki.notes import Note, NoteId
from aqt import QKeySequence, Qt, gui_hooks, mw, qconnect
from aqt.qt import QAction, QDesktopServices, QDialog, QFileDialog, QUrl
from aqt.utils import showInfo, showWarning

from .src.common.constants import ANKIMAPS_CONSTANTS
from .src.common.io import (
    create_backup,
    delete_mindmap_file,
    export_all_mindmaps,
    get_mindmaps_storage_path,
    initialize_user_directories,
    rename_mindmap_file,
)
from .src.controller.addon_upgrade_controller import AddonUpgradeController
from .src.controller.landing_page_controller import LandingPageController
from .src.controller.mindmap_controller import MindmapController
from .src.repository.addon_upgrade_repository import AddonUpgradeRepository
from .src.repository.anki_repository import AnkiRepository
from .src.repository.db.sql_repository import SqlLiteRepository
from .src.repository.mindmap_files_repository import MindmapFilesRepository
from .src.view.landing_page import LandingWindow
from .src.view.mindmap_window import MindMapWindow


class ListLogHandler(logging.Handler):
    def __init__(self, log_list: list, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_list = log_list

    def emit(self, record: LogRecord) -> None:
        self.log_list.append(record)


addon_logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)
addon_logger.setLevel(logging.DEBUG)
addon_logger.propagate = False
log_buffer: list[LogRecord] = []
buffer_handler = ListLogHandler(log_buffer)
addon_logger.addHandler(buffer_handler)


def startup_cleanup():
    initialize_user_directories()

    if not mw or not mw.col:
        return
    deck_name = ANKIMAPS_CONSTANTS.FILTERED_DECK_NAME.value
    if deck_id := mw.col.decks.id_for_name(deck_name):
        addon_logger.info(f"AnkiMaps: Removed orphaned filtered deck '{deck_name}' on startup.")
        mw.col.decks.remove([deck_id])


class MindMapAddon:
    TUTORIAL_VIDEO_PLACEHOLDER_URL = "https://www.youtube.com/@ankimaps"

    def __init__(self):
        initialize_user_directories()
        self._mindmap_controller: Optional[MindmapController] = None
        self._view: Optional[MindMapWindow] = None
        self.review_action: Optional[QAction] = None
        self.notes_to_add_on_load: Optional[List[NoteId]] = None
        self.landing_controller: Optional[LandingPageController] = None
        self.landing_dialog = None
        self.upgrade_controller = AddonUpgradeController(AddonUpgradeRepository())

        gui_hooks.editor_did_fire_typing_timer.append(self._on_editor_update)
        notes_will_be_deleted.append(self._on_note_deleted)
        gui_hooks.profile_did_open.append(startup_cleanup)

    def _on_note_deleted(self, _, note_ids: Sequence[NoteId]):
        if controller := self._mindmap_controller:
            if mw:
                mw.taskman.run_on_main(lambda: controller.delete_notes_from_map(list(note_ids)))

    def _on_window_closed(self):
        addon_logger.info("[ADDON] MindMap window closed. Cleaning up.")
        if self._mindmap_controller:
            if self._mindmap_controller.model:
                mindmap_name = self._mindmap_controller.model.name
                addon_logger.info(f"Creating backup for '{mindmap_name}' on close...")
                success = create_backup(mindmap_name, ANKIMAPS_CONSTANTS.MAX_BACKUPS_PER_MAP.value)
                if success:
                    addon_logger.info("Backup created successfully.")
                else:
                    addon_logger.warning(
                        f"Failed to create backup for '{mindmap_name}'. Check file permissions."
                    )

            self._mindmap_controller.cleanup()
        if self.review_action and mw:
            mw.removeAction(self.review_action)
        self._mindmap_controller = None
        self._view = None
        self.review_action = None

    def _on_editor_update(self, note: "Note"):
        if self._mindmap_controller:
            self._mindmap_controller._on_note_updated_in_editor(note)

    def open_mindmap_ui(self):
        if self._view and not self._view.isHidden():
            self._view.activateWindow()
        else:
            self._show_map_selection()

    def _show_map_selection(self):
        if self._view:
            self._view.close()

        self.landing_controller = LandingPageController(
            MindmapFilesRepository(), SqlLiteRepository(), AnkiRepository()
        )
        mindmap_names, mindmap_infos = self.landing_controller.get_mindmaps_with_info()

        current_version = self.upgrade_controller.get_current_version()
        self.landing_dialog = LandingWindow(mindmap_names, mindmap_infos, current_version, mw)

        self.landing_dialog.delete_requested.connect(self._on_delete_map_requested)
        self.landing_dialog.rename_requested.connect(self._on_rename_map_requested)
        self.landing_dialog.tutorial_video_requested.connect(self._on_tutorial_video_requested)
        self.landing_dialog.upgrade_requested.connect(self._on_upgrade_requested)
        self.landing_dialog.open_folder_requested.connect(self._on_open_folder_requested)
        self.landing_dialog.export_selected_requested.connect(self._on_export_selected_requested)
        self.landing_dialog.export_all_requested.connect(self._on_export_all_requested)
        self.landing_dialog.import_requested.connect(self._on_import_requested)
        self.landing_dialog.export_bundle_requested.connect(self._on_export_bundle_requested)
        self.landing_dialog.import_bundle_requested.connect(self._on_import_bundle_requested)

        if self.landing_dialog.exec() == QDialog.DialogCode.Accepted and self.landing_dialog.selected_map:
            self._launch_mindmap_window(self.landing_dialog.selected_map)
        self.landing_dialog = None
        self.landing_controller = None

    def _on_upgrade_requested(self):
        dialog_parent = self.landing_dialog or mw
        archive_path, _ = QFileDialog.getOpenFileName(
            dialog_parent,
            "Select AnkiMaps Upgrade Package",
            "",
            "Anki Add-on Package (*.ankiaddon)",
        )
        if not archive_path:
            return

        try:
            result = self.upgrade_controller.upgrade_from_archive(archive_path)
            if self.landing_dialog:
                self.landing_dialog.set_version(result.package_version)

            showInfo(
                "Upgrade successful. "
                f"Version: {result.current_version} -> {result.package_version}. "
                f"Updated {result.copied_files} files.\n"
                "Please restart Anki to load the new version."
            )
        except Exception as exc:
            addon_logger.exception("Failed to apply upgrade package")
            showWarning(f"Upgrade failed: {exc}")

    def _on_rename_map_requested(self, old_name: str, new_name: str):
        if rename_mindmap_file(old_mindmap_name=old_name, new_mindmap_name=new_name):
            if self.landing_dialog:
                if items := self.landing_dialog.list_widget.findItems(old_name, Qt.MatchFlag.MatchExactly):
                    items[0].setText(new_name)

    def _on_delete_map_requested(self, mindmap_name: str):
        if delete_mindmap_file(mindmap_name):
            if self.landing_dialog:
                if items := self.landing_dialog.list_widget.findItems(
                    mindmap_name, Qt.MatchFlag.MatchExactly
                ):
                    self.landing_dialog.list_widget.takeItem(self.landing_dialog.list_widget.row(items[0]))

    def _on_open_folder_requested(self):
        folder_path = get_mindmaps_storage_path()
        if not folder_path:
            showWarning("Could not resolve the mindmaps folder path.")
            return

        os.makedirs(folder_path, exist_ok=True)
        folder_url = QUrl.fromLocalFile(folder_path)
        if not QDesktopServices.openUrl(folder_url):
            showWarning(f"Could not open folder: {folder_path}")

    def _on_tutorial_video_requested(self):
        if not QDesktopServices.openUrl(QUrl(self.TUTORIAL_VIDEO_PLACEHOLDER_URL)):
            showWarning("Could not open the YouTube tutorial placeholder URL.")

    def _refresh_landing_mindmaps(self, preferred_selection: Optional[str] = None):
        if not (self.landing_dialog and self.landing_controller):
            return
        mindmap_names, mindmap_infos = self.landing_controller.get_mindmaps_with_info()
        self.landing_dialog.update_mindmaps(
            mindmap_names=mindmap_names,
            mindmap_infos=mindmap_infos,
            preferred_selection=preferred_selection,
        )

    def _on_export_selected_requested(self, mindmap_name: str):
        dialog_parent = self.landing_dialog or mw
        destination_file, _ = QFileDialog.getSaveFileName(
            dialog_parent,
            f"Export Mindmap '{mindmap_name}'",
            f"{mindmap_name}.db",
            "Mindmap Database (*.db)",
        )
        if not destination_file:
            return
        if not destination_file.lower().endswith(".db"):
            destination_file = f"{destination_file}.db"

        try:
            if not self.landing_controller:
                raise RuntimeError("Landing controller is not initialized.")
            self.landing_controller.export_mindmap(mindmap_name, destination_file)
        except Exception as exc:
            showWarning(f"Export failed: {exc}")
            return

        showInfo(f"Exported '{mindmap_name}' to:\n{destination_file}")

    def _on_import_requested(self):
        dialog_parent = self.landing_dialog or mw
        source_file, _ = QFileDialog.getOpenFileName(
            dialog_parent,
            "Import Mindmap",
            "",
            "Mindmap Database (*.db)",
        )
        if not source_file:
            return

        try:
            if not self.landing_controller:
                raise RuntimeError("Landing controller is not initialized.")
            imported_name, renamed_on_import = self.landing_controller.import_mindmap(source_file)
        except Exception as exc:
            showWarning(f"Import failed: {exc}")
            return

        self._refresh_landing_mindmaps(preferred_selection=imported_name)
        if renamed_on_import:
            showInfo(
                "Import completed.\n"
                f"A map with the same name already existed, so it was saved as '{imported_name}'."
            )
        else:
            showInfo(f"Imported mindmap '{imported_name}'.")

    def _on_export_bundle_requested(self, mindmap_name: str):
        dialog_parent = self.landing_dialog or mw
        destination_file, _ = QFileDialog.getSaveFileName(
            dialog_parent,
            f"Export Bundle for '{mindmap_name}'",
            f"{mindmap_name}.ankimapsbundle",
            "AnkiMaps Bundle (*.ankimapsbundle)",
        )
        if not destination_file:
            return
        if not destination_file.lower().endswith(".ankimapsbundle"):
            destination_file = f"{destination_file}.ankimapsbundle"

        try:
            if not self.landing_controller:
                raise RuntimeError("Landing controller is not initialized.")
            result = self.landing_controller.export_mindmap_bundle(mindmap_name, destination_file)
        except Exception as exc:
            showWarning(f"Bundle export failed: {exc}")
            return

        showInfo(
            f"Bundle exported to:\n{destination_file}\n\n"
            f"Deck notes: {result['deck_notes_exported']}\n"
            f"Nodes: {result['nodes_exported']}/{result['nodes_total']} exported\n"
            f"Connections: {result['connections_exported']}/{result['connections_total']} exported"
        )

    def _on_import_bundle_requested(self):
        dialog_parent = self.landing_dialog or mw
        source_file, _ = QFileDialog.getOpenFileName(
            dialog_parent,
            "Import Bundle",
            "",
            "AnkiMaps Bundle (*.ankimapsbundle);;JSON Files (*.json)",
        )
        if not source_file:
            return

        try:
            if not self.landing_controller:
                raise RuntimeError("Landing controller is not initialized.")
            result = self.landing_controller.import_mindmap_bundle(source_file)
        except Exception as exc:
            showWarning(f"Bundle import failed: {exc}")
            return

        imported_name = result["imported_name"]
        self._refresh_landing_mindmaps(preferred_selection=imported_name)
        showInfo(
            f"Bundle imported as '{imported_name}'.\n\n"
            f"Deck imported: {'Yes' if result['deck_imported'] else 'No'}\n"
            f"Nodes: {result['nodes_imported']}/{result['nodes_total']} imported "
            f"({result['nodes_unresolved']} unresolved)\n"
            f"Connections: {result['connections_imported']}/{result['connections_total']} imported "
            f"({result['connections_skipped']} skipped)"
        )

    def _on_export_all_requested(self):
        dialog_parent = self.landing_dialog or mw
        destination_dir = QFileDialog.getExistingDirectory(
            dialog_parent,
            "Select Export Destination",
            "",
        )
        if not destination_dir:
            return

        try:
            exported_count = export_all_mindmaps(destination_dir)
        except Exception as exc:
            showWarning(f"Export failed: {exc}")
            return

        if exported_count == 0:
            showWarning("No mindmap database files were found to export.")
            return

        showInfo(f"Exported {exported_count} mindmap file(s) to:\n{destination_dir}")

    def _launch_mindmap_window(self, mindmap_name: str, notes_to_add_on_load: Optional[List[NoteId]] = None):
        if self._view:
            self._view.close()

        self.notes_to_add_on_load = notes_to_add_on_load

        anki_repo = AnkiRepository()
        sql_repo = SqlLiteRepository()

        self._mindmap_controller = MindmapController(anki_repo, sql_repo)

        qconnect(self._mindmap_controller.load_and_hydrate_ready, self._on_model_loaded)

        self._mindmap_controller.load_and_hydrate_model(
            mindmap_name=mindmap_name,
        )

    def _on_model_loaded(self):
        if c := self._mindmap_controller:
            model = c.model
            if model:
                mindmap_name = model.name

                addon_logger.info(f"Creating backup for '{mindmap_name}' on open...")
                success = create_backup(mindmap_name, ANKIMAPS_CONSTANTS.MAX_BACKUPS_PER_MAP.value)
                if success:
                    addon_logger.info("Backup created successfully.")
                else:
                    addon_logger.warning(
                        f"Failed to create backup for '{mindmap_name}'. Check file permissions."
                    )

                if self.notes_to_add_on_load:
                    c.save_selected_notes(self.notes_to_add_on_load)
                    self.notes_to_add_on_load = None

                self._view = MindMapWindow(
                    parent=mw,
                    mindmap_name=mindmap_name,
                    model=model,
                    log_buffer=log_buffer,
                    buffer_handler=buffer_handler,
                )

                qconnect(self._view.window_closed, self._on_window_closed)
                qconnect(self._view.open_another_map_requested, self._show_map_selection)

                qconnect(self._view.add_notes_requested, c.open_add_note_dialog)
                qconnect(self._view.edit_note_requested, c.edit_notes)
                qconnect(self._view.delete_notes_requested, c.delete_notes_from_map)

                qconnect(self._view.mindmap_view.notes_moved, c.update_note_positions)
                qconnect(
                    self._view.mindmap_view.note_double_clicked,
                    lambda nid_str: c.edit_notes([NoteId(nid_str)]),
                )
                qconnect(self._view.note_property_updated, c.update_note_property)
                qconnect(
                    self._view.mindmap_view.note_resized,
                    lambda nid_str, width: c.update_note_property(nid_str, "width", width),
                )

                qconnect(self._view.link_button_clicked, c.toggle_connection)
                qconnect(self._view.mindmap_view.connection_delete_requested, c.delete_connection)
                qconnect(self._view.mindmap_view.connection_label_updated, c.update_connection_label)
                qconnect(self._view.connection_property_updated, c.update_connection_property)

                qconnect(self._view.search_requested, c.perform_search)
                qconnect(c.search_results_found, self._view.highlight_search_results)
                qconnect(self._view.undo_requested, c.undo)
                qconnect(self._view.redo_requested, c.redo)

                self.review_action = QAction("Toggle AnkiMaps Review", mw)
                self.review_action.setShortcut(QKeySequence("s"))
                qconnect(self.review_action.triggered, c.toggle_review)
                if mw:
                    mw.addAction(self.review_action)
                qconnect(self._view.anki_review_session_requested, c.toggle_review)

                qconnect(c.review_state_changed, self._view._on_review_state_changed)
                qconnect(c.review_focus_changed, self._view._on_review_focus_changed)
                qconnect(c.review_progress_updated, self._view._on_review_progress_updated)

                model.model_loaded.emit()

                self._view.show()
                self._view.initial_zoom_to_fit()


mindmap_addon = MindMapAddon()
action = QAction("AnkiMaps", mw)
action.setShortcut(QKeySequence("Ctrl+Shift+M"))
qconnect(action.triggered, mindmap_addon.open_mindmap_ui)
if mw:
    mw.form.menuTools.addAction(action)
