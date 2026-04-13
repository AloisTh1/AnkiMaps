import os
from datetime import datetime
from typing import Any, Optional

from aqt.qt import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequence,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPixmap,
    QPushButton,
    QScrollArea,
    QShortcut,
    Qt,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from aqt.utils import showWarning


class LandingWindow(QDialog):
    delete_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)  # old_name, new_name
    tutorial_video_requested = pyqtSignal()
    upgrade_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    export_selected_requested = pyqtSignal(str)
    export_all_requested = pyqtSignal()
    import_requested = pyqtSignal()
    export_bundle_requested = pyqtSignal(str)
    import_bundle_requested = pyqtSignal()
    STYLESHEET_FILE_NAME = "landing_page.qss"

    SCREEN_MARGIN = 72
    DEFAULT_DIALOG_WIDTH = 560
    DEFAULT_DIALOG_HEIGHT = 780

    def __init__(
        self,
        mindmap_names: list[str],
        mindmap_infos: dict[str, dict[str, Any]],
        addon_version: str,
        parent=None,
    ):
        super().__init__(parent)
        self.addon_version = addon_version
        self.mindmap_infos = mindmap_infos
        self.setWindowTitle("AnkiMaps")
        self.setMinimumWidth(400)

        # Outer layout for the dialog holds only the scroll area
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer_layout)

        # Scroll area wrapping all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll_area)

        # Inner content widget
        content_widget = QWidget()
        self.layout: QVBoxLayout = QVBoxLayout()
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(8)
        content_widget.setLayout(self.layout)
        scroll_area.setWidget(content_widget)

        logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(pixmap.scaledToWidth(230, Qt.TransformationMode.SmoothTransformation))
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(logo_label)

        self.version_label = QLabel(f"Version: {self.addon_version}")
        self.version_label.setObjectName("version_label")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.version_label)

        self.mindmap_names = list(mindmap_names)
        self.sort_options: dict[str, tuple[str, bool]] = {
            "Name (A-Z)": ("name", False),
            "Name (Z-A)": ("name", True),
            "Created (Newest)": ("created_at", True),
            "Created (Oldest)": ("created_at", False),
            "Modified (Newest)": ("modified_at", True),
            "Modified (Oldest)": ("modified_at", False),
        }

        controls_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mind maps...")
        controls_layout.addWidget(self.search_input)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(self.sort_options.keys())
        controls_layout.addWidget(self.sort_combo)
        self.layout.addLayout(controls_layout)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(170)
        self.layout.addWidget(self.list_widget)

        self.info_title_label = QLabel("Mind Map Details")
        self.info_title_label.setObjectName("section_title")
        self.layout.addWidget(self.info_title_label)

        self.info_label = QLabel("Select a mind map to see details.")
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("info_label")
        self.layout.addWidget(self.info_label)

        self.tutorial_button = QPushButton("Watch Tutorial (YouTube)")
        self.open_folder_button = QPushButton("Open Mindmap Folder")

        self.open_button = QPushButton("Open")
        self.new_button = QPushButton("New...")
        self.rename_button = QPushButton("Rename")
        self.delete_button = QPushButton("Delete")
        self.export_selected_button = QPushButton("Export Selected...")
        self.import_button = QPushButton("Import Mindmap...")
        self.export_bundle_button = QPushButton("Export Bundle...")
        self.import_bundle_button = QPushButton("Import Bundle...")
        self.export_all_button = QPushButton("Export All Mindmaps...")
        self.upgrade_button = QPushButton("Upgrade Add-on...")
        self.transfer_help_label = QLabel(
            "Same user / same collection: Import/Export Mindmap (.db).\n"
            "Different users/devices: Export/Import Bundle (includes notes + map)."
        )
        self.transfer_help_label.setObjectName("transfer_help")
        self.transfer_help_label.setWordWrap(True)

        self.open_button.setObjectName("btn_open")
        self.new_button.setObjectName("btn_new")
        self.rename_button.setObjectName("btn_rename")
        self.delete_button.setObjectName("btn_delete")
        self.tutorial_button.setObjectName("btn_tutorial")
        self.open_folder_button.setObjectName("btn_folder")
        self.export_selected_button.setObjectName("btn_export_selected")
        self.import_button.setObjectName("btn_import")
        self.export_bundle_button.setObjectName("btn_export_bundle")
        self.import_bundle_button.setObjectName("btn_import_bundle")
        self.export_all_button.setObjectName("btn_export_all")
        self.upgrade_button.setObjectName("btn_upgrade")

        self.actions_title_label = QLabel("Actions")
        self.actions_title_label.setObjectName("section_title")
        self.layout.addWidget(self.actions_title_label)

        map_actions_group = QGroupBox("Map")
        map_actions_layout = QGridLayout()
        map_actions_layout.setHorizontalSpacing(8)
        map_actions_layout.setVerticalSpacing(6)
        map_actions_layout.addWidget(self.open_button, 0, 0)
        map_actions_layout.addWidget(self.new_button, 0, 1)
        map_actions_layout.addWidget(self.rename_button, 1, 0)
        map_actions_layout.addWidget(self.delete_button, 1, 1)
        map_actions_group.setLayout(map_actions_layout)
        self.layout.addWidget(map_actions_group)

        transfer_actions_group = QGroupBox("Transfer")
        transfer_actions_layout = QGridLayout()
        transfer_actions_layout.setHorizontalSpacing(8)
        transfer_actions_layout.setVerticalSpacing(6)
        transfer_actions_layout.addWidget(self.export_selected_button, 0, 0)
        transfer_actions_layout.addWidget(self.import_button, 0, 1)
        transfer_actions_layout.addWidget(self.export_bundle_button, 1, 0)
        transfer_actions_layout.addWidget(self.import_bundle_button, 1, 1)
        transfer_actions_layout.addWidget(self.export_all_button, 2, 0, 1, 2)
        transfer_actions_layout.addWidget(self.transfer_help_label, 3, 0, 1, 2)
        transfer_actions_group.setLayout(transfer_actions_layout)
        self.layout.addWidget(transfer_actions_group)

        tools_actions_group = QGroupBox("Tools")
        tools_actions_layout = QGridLayout()
        tools_actions_layout.setHorizontalSpacing(8)
        tools_actions_layout.setVerticalSpacing(6)
        tools_actions_layout.addWidget(self.open_folder_button, 0, 0)
        tools_actions_layout.addWidget(self.tutorial_button, 0, 1)
        tools_actions_layout.addWidget(self.upgrade_button, 1, 0, 1, 2)
        tools_actions_group.setLayout(tools_actions_layout)
        self.layout.addWidget(tools_actions_group)

        self._apply_stylesheet()
        self._apply_initial_window_size()

        self.selected_map = None

        self.open_button.clicked.connect(self.on_open)
        self.list_widget.itemDoubleClicked.connect(self.on_open)
        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        self.search_input.textChanged.connect(self.on_filter_or_sort_changed)
        self.sort_combo.currentIndexChanged.connect(self.on_filter_or_sort_changed)
        self.new_button.clicked.connect(self.on_new)
        self.delete_button.clicked.connect(self.on_delete)
        self.rename_button.clicked.connect(self.on_rename)
        self.export_selected_button.clicked.connect(self.on_export_selected)
        self.import_button.clicked.connect(self.import_requested.emit)
        self.export_bundle_button.clicked.connect(self.on_export_bundle)
        self.import_bundle_button.clicked.connect(self.import_bundle_requested.emit)
        self.tutorial_button.clicked.connect(self.tutorial_video_requested.emit)
        self.open_folder_button.clicked.connect(self.open_folder_requested.emit)
        self.export_all_button.clicked.connect(self.export_all_requested.emit)
        self.upgrade_button.clicked.connect(self.upgrade_requested.emit)

        self.return_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self.enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        self.return_shortcut.activated.connect(self._on_enter_shortcut)
        self.enter_shortcut.activated.connect(self._on_enter_shortcut)

        self.refresh_mindmap_list()

    def _apply_initial_window_size(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(self.DEFAULT_DIALOG_WIDTH, available.width() - self.SCREEN_MARGIN)
            height = min(self.DEFAULT_DIALOG_HEIGHT, available.height() - self.SCREEN_MARGIN)
            self.resize(width, height)
        else:
            self.resize(self.DEFAULT_DIALOG_WIDTH, self.DEFAULT_DIALOG_HEIGHT)

    def _apply_stylesheet(self) -> None:
        stylesheet_path = os.path.join(
            os.path.dirname(__file__),
            "assets",
            self.STYLESHEET_FILE_NAME,
        )
        try:
            with open(stylesheet_path, "r", encoding="utf-8") as stylesheet_file:
                self.setStyleSheet(stylesheet_file.read())
        except OSError:
            pass

    def set_version(self, addon_version: str):
        self.addon_version = addon_version
        self.version_label.setText(f"Version: {self.addon_version}")

    def update_mindmaps(
        self,
        mindmap_names: list[str],
        mindmap_infos: dict[str, dict[str, Any]],
        preferred_selection: Optional[str] = None,
    ):
        self.mindmap_names = list(mindmap_names)
        self.mindmap_infos = mindmap_infos
        self.refresh_mindmap_list(preferred_selection=preferred_selection)

    def on_filter_or_sort_changed(self, *_args):
        self.refresh_mindmap_list()

    def refresh_mindmap_list(self, preferred_selection: Optional[str] = None):
        current_item = self.list_widget.currentItem()
        current_name = preferred_selection
        if not current_name and current_item and (current_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            current_name = current_item.text()

        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        self.list_widget.addItem("Select or create a Mind Map")
        self.list_widget.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.list_widget.item(0).setForeground(Qt.GlobalColor.gray)

        visible_names = self._get_visible_mindmap_names()
        if not visible_names:
            self.list_widget.addItem("No mind maps found.")
            self.list_widget.item(1).setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.item(1).setForeground(Qt.GlobalColor.gray)
        else:
            self.list_widget.addItems(visible_names)
            if current_name in visible_names:
                matching_items = self.list_widget.findItems(current_name, Qt.MatchFlag.MatchExactly)
                if matching_items:
                    self.list_widget.setCurrentItem(matching_items[0])

        self.list_widget.blockSignals(False)
        self.on_selection_changed(self.list_widget.currentItem())

    def _get_visible_mindmap_names(self) -> list[str]:
        search_term = self.search_input.text().strip().lower()
        names = [name for name in self.mindmap_names if search_term in name.lower()]

        sort_label = self.sort_combo.currentText()
        sort_key, reverse = self.sort_options.get(sort_label, ("name", False))

        if sort_key == "name":
            return sorted(names, key=lambda n: n.lower(), reverse=reverse)

        return sorted(
            names,
            key=lambda n: self._safe_number(self.mindmap_infos.get(n, {}).get(sort_key)),
            reverse=reverse,
        )

    def _safe_number(self, value: Optional[Any]) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def on_delete(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item or not (selected_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        map_name = selected_item.text()

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete the AnkiMap '{map_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(map_name)
            self.mindmap_infos.pop(map_name, None)
            self.mindmap_names = [name for name in self.mindmap_names if name != map_name]
            self.refresh_mindmap_list()

    def on_open(self, item=None):
        selected_item = item or self.list_widget.currentItem()
        if selected_item and selected_item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.selected_map = selected_item.text()
            self.accept()

    def on_export_selected(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item or not (selected_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            showWarning("Please select a mind map to export.")
            return
        self.export_selected_requested.emit(selected_item.text())

    def on_export_bundle(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item or not (selected_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            showWarning("Please select a mind map to export as a bundle.")
            return
        self.export_bundle_requested.emit(selected_item.text())

    def _on_enter_shortcut(self):
        self.on_open()

    def on_new(self):
        text, ok = QInputDialog.getText(self, "New AnkiMap", "Enter name for new AnkiMap:")
        map_name = text.strip() if ok else ""
        if map_name:
            if map_name in self.mindmap_infos:
                showWarning(f"AnkiMap '{map_name}' already exists.")
                return
            self.selected_map = map_name
            self.accept()

    def on_rename(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item or not (selected_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return

        old_name = selected_item.text()
        new_name, ok = QInputDialog.getText(self, "Rename AnkiMap", "Enter new name:", text=old_name)
        new_name = new_name.strip()

        if not (ok and new_name):
            return

        if old_name == new_name:
            return

        if new_name in self.mindmap_infos:
            showWarning(f"AnkiMap '{new_name}' already exists. Please enter a different name.")
            return
        self.rename_requested.emit(old_name, new_name)
        if old_name in self.mindmap_infos:
            self.mindmap_infos[new_name] = self.mindmap_infos.pop(old_name)
        self.mindmap_names = [new_name if name == old_name else name for name in self.mindmap_names]
        self.refresh_mindmap_list(preferred_selection=new_name)

    def on_selection_changed(self, current_item, _previous_item=None):
        if not current_item or not (current_item.flags() & Qt.ItemFlag.ItemIsEnabled):
            self.info_label.setText("Select a mind map to see details.")
            return

        map_name = current_item.text()
        info = self.mindmap_infos.get(map_name, {})
        self.info_label.setText(self._format_map_info(map_name, info))

    def _format_map_info(self, map_name: str, info: dict[str, Any]) -> str:
        created_at = self._format_timestamp(info.get("created_at"))
        modified_at = self._format_timestamp(info.get("modified_at"))
        size_text = self._format_size(info.get("size_bytes"))
        nodes = info.get("nodes_count")
        connections = info.get("connections_count")
        backups = info.get("backup_count")

        return "\n".join(
            [
                f"Name: {map_name}",
                f"Created: {created_at}",
                f"Last Modified: {modified_at}",
                f"File Size: {size_text}",
                f"Nodes: {nodes if nodes is not None else 'Unknown'}",
                f"Connections: {connections if connections is not None else 'Unknown'}",
                f"Backups: {backups if backups is not None else 'Unknown'}",
            ]
        )

    def _format_timestamp(self, timestamp: Optional[Any]) -> str:
        if timestamp is None:
            return "Unknown"
        try:
            return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OSError):
            return "Unknown"

    def _format_size(self, size_bytes: Optional[Any]) -> str:
        if size_bytes is None:
            return "Unknown"

        try:
            size = float(size_bytes)
        except (ValueError, TypeError):
            return "Unknown"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_idx = 0
        while size >= 1024 and unit_idx < len(units) - 1:
            size /= 1024
            unit_idx += 1
        return f"{size:.1f} {units[unit_idx]}"
