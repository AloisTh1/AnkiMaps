import os
from datetime import datetime
from typing import Any, Optional

from aqt.qt import (
    QApplication,
    QComboBox,
    QDesktopServices,
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
    QMenu,
    QMessageBox,
    QPixmap,
    QPushButton,
    QScrollArea,
    QShortcut,
    Qt,
    QUrl,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from aqt.utils import showWarning

DARK_THEME = {
    "ink": "#101923",
    "panel": "#18232f",
    "panel_alt": "#223242",
    "border": "#314a5e",
    "text": "#edf3f8",
    "muted": "#9cb2c3",
    "input_bg": "#121b24",
    "button_fill": "#223242",
    "button_hover": "#294257",
    "button_pressed": "#1a2b3a",
    "button_border": "#46657c",
    "accent": "#4cc9c2",
    "accent_hover": "#63d8d1",
    "accent_pressed": "#31aea7",
    "accent_text": "#081317",
    "title": "#7fdad4",
    "selection": "rgba(76, 201, 194, 0.28)",
    "slider_groove": "#395062",
    "scroll_track": "#13202a",
    "scroll_handle": "#3e5d74",
}

LIGHT_THEME = {
    "ink": "#eef2f7",
    "panel": "#ffffff",
    "panel_alt": "#f6f8fc",
    "border": "#b9c7d5",
    "text": "#1a2230",
    "muted": "#516173",
    "input_bg": "rgba(255, 255, 255, 0.98)",
    "button_fill": "rgba(119, 84, 255, 0.10)",
    "button_hover": "rgba(119, 84, 255, 0.18)",
    "button_pressed": "rgba(119, 84, 255, 0.25)",
    "button_border": "#9d86ff",
    "accent": "#2d9cff",
    "accent_hover": "#57b0ff",
    "accent_pressed": "#2286e6",
    "accent_text": "#ffffff",
    "title": "#7754ff",
    "selection": "rgba(45, 156, 255, 0.20)",
    "slider_groove": "rgba(81, 97, 115, 0.22)",
    "scroll_track": "#dfe6ef",
    "scroll_handle": "#b4c2d2",
}

THEMES = {"Dark": DARK_THEME, "Light": LIGHT_THEME}


class LandingWindow(QDialog):
    delete_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    tutorial_video_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    export_selected_requested = pyqtSignal(str)
    export_all_requested = pyqtSignal()
    import_requested = pyqtSignal()
    export_bundle_requested = pyqtSignal(str)
    import_bundle_requested = pyqtSignal()

    SCREEN_MARGIN = 72
    DEFAULT_DIALOG_WIDTH = 820
    DEFAULT_DIALOG_HEIGHT = 560

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
        self._theme_mode = "Light"
        self.setWindowTitle("AnkiMaps")
        self.setObjectName("ankiMapsLanding")
        self.setMinimumWidth(400)

        # Outer layout for the dialog holds only the scroll area
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer_layout)

        # Scroll area wrapping all content
        scroll_area = QScrollArea()
        scroll_area.setObjectName("landingScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll_area)

        # Inner content widget
        content_widget = QWidget()
        content_widget.setObjectName("landingContent")
        self.layout: QVBoxLayout = QVBoxLayout()
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(8)
        content_widget.setLayout(self.layout)
        scroll_area.setWidget(content_widget)

        # --- Header row: logo | spacer | meta + controls ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        logo_label = QLabel()
        logo_label.setObjectName("dialogLogo")
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            device_ratio = logo_label.devicePixelRatioF()
            scaled_width = int(160 * device_ratio)
            scaled_pixmap = pixmap.scaledToWidth(scaled_width, Qt.TransformationMode.SmoothTransformation)
            scaled_pixmap.setDevicePixelRatio(device_ratio)
            logo_label.setPixmap(scaled_pixmap)
        header_layout.addWidget(logo_label)

        header_layout.addStretch()

        header_right = QVBoxLayout()
        header_right.setSpacing(6)
        header_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.made_by_label = QLabel("An add-on made by alois_devlp")
        self.made_by_label.setObjectName("made_by_label")
        self.made_by_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_right.addWidget(self.made_by_label)

        self.version_label = QLabel(f"Version: {self.addon_version}")
        self.version_label.setObjectName("version_label")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_right.addWidget(self.version_label)

        header_controls = QHBoxLayout()
        header_controls.setSpacing(8)

        theme_label = QLabel("Theme:")
        theme_label.setObjectName("footer_label")
        header_controls.addWidget(theme_label)

        self.theme_selector = QComboBox()
        self.theme_selector.setObjectName("theme_selector")
        self.theme_selector.addItems(THEMES.keys())
        self.theme_selector.setCurrentText(self._theme_mode)
        header_controls.addWidget(self.theme_selector)

        self.support_button = QPushButton("Support")
        self.support_button.setObjectName("btn_support")
        header_controls.addWidget(self.support_button)

        header_right.addLayout(header_controls)
        header_layout.addLayout(header_right)
        self.layout.addLayout(header_layout)

        self.lost_mindmaps_button = QPushButton("READ THIS IF YOU LOST YOUR MINDMAPS !")
        self.lost_mindmaps_button.setObjectName("btn_lost_mindmaps")
        self.layout.addWidget(self.lost_mindmaps_button)

        self.mindmap_names = list(mindmap_names)
        self.sort_options: dict[str, tuple[str, bool]] = {
            "Name (A-Z)": ("name", False),
            "Name (Z-A)": ("name", True),
            "Created (Newest)": ("created_at", True),
            "Created (Oldest)": ("created_at", False),
            "Modified (Newest)": ("modified_at", True),
            "Modified (Oldest)": ("modified_at", False),
        }

        # Two-column layout: left = list + details, right = actions
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(12)

        # --- Left column: search, list, details ---
        left_column = QVBoxLayout()
        left_column.setSpacing(8)

        controls_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mind maps...")
        controls_layout.addWidget(self.search_input)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(self.sort_options.keys())
        controls_layout.addWidget(self.sort_combo)
        left_column.addLayout(controls_layout)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(170)
        left_column.addWidget(self.list_widget)

        self.info_title_label = QLabel("Mind Map Details")
        self.info_title_label.setObjectName("section_title")
        left_column.addWidget(self.info_title_label)

        self.info_label = QLabel("Select a mind map to see details.")
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("info_label")
        left_column.addWidget(self.info_label)

        columns_layout.addLayout(left_column, 1)

        # --- Right column: action groups ---
        right_column = QVBoxLayout()
        right_column.setSpacing(8)

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

        map_actions_group = QGroupBox("Map")
        map_actions_layout = QGridLayout()
        map_actions_layout.setHorizontalSpacing(8)
        map_actions_layout.setVerticalSpacing(6)
        map_actions_layout.addWidget(self.open_button, 0, 0)
        map_actions_layout.addWidget(self.new_button, 0, 1)
        map_actions_layout.addWidget(self.rename_button, 1, 0)
        map_actions_layout.addWidget(self.delete_button, 1, 1)
        map_actions_group.setLayout(map_actions_layout)
        right_column.addWidget(map_actions_group)

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
        right_column.addWidget(transfer_actions_group)

        tools_actions_group = QGroupBox("Tools")
        tools_actions_layout = QGridLayout()
        tools_actions_layout.setHorizontalSpacing(8)
        tools_actions_layout.setVerticalSpacing(6)
        tools_actions_layout.addWidget(self.open_folder_button, 0, 0)
        tools_actions_layout.addWidget(self.tutorial_button, 0, 1)
        tools_actions_group.setLayout(tools_actions_layout)
        right_column.addWidget(tools_actions_group)

        right_column.addStretch()
        columns_layout.addLayout(right_column, 1)

        self.layout.addLayout(columns_layout)

        self._apply_site_palette()
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
        self.theme_selector.currentTextChanged.connect(self._on_theme_changed)
        self.support_button.clicked.connect(self._on_support_clicked)
        self.lost_mindmaps_button.clicked.connect(self._on_lost_mindmaps_clicked)

        self.return_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self.enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        self.return_shortcut.activated.connect(self._on_enter_shortcut)
        self.enter_shortcut.activated.connect(self._on_enter_shortcut)

        self.refresh_mindmap_list()

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _on_support_clicked(self) -> None:
        menu = QMenu(self)
        links = [
            ("Website", "https://aloisthibert.dev/en/anki"),
            ("YouTube", "https://www.youtube.com/@Alois_dvlp"),
            ("Patreon", "https://www.patreon.com/c/alois_anki"),
            ("Buy Me a Coffee", "https://buymeacoffee.com/alois_devlp"),
        ]
        for label, url in links:
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked, u=url: self._open_url(u))
        menu.exec(self.support_button.mapToGlobal(self.support_button.rect().bottomLeft()))

    def _on_lost_mindmaps_clicked(self) -> None:
        QMessageBox.information(
            self,
            "Lost Mindmaps",
            "I am deeply sorry if your mindmaps disappeared after updating AnkiMaps.\n\n"
            "They may not be deleted. Please check these places:\n\n"
            "1. Open your Anki add-ons folder and look for an 'AnkiMaps' folder.\n"
            "2. Inside it, check: user_files/mindmaps\n"
            "3. Also check your Recycle Bin / Trash for an 'AnkiMaps' folder.\n"
            "4. If you find .db files there, those are your mindmaps.\n\n"
            "Please do not empty your Trash until you have checked it.",
        )

    def _on_theme_changed(self, theme_name: str) -> None:
        self._theme_mode = theme_name
        self._apply_site_palette()

    def _apply_site_palette(self) -> None:
        c = THEMES.get(self._theme_mode, DARK_THEME)
        d = "#ankiMapsLanding"

        self.setStyleSheet(f"""
            {d} {{
                background: {c["ink"]};
                color: {c["text"]};
            }}

            {d} QScrollArea#landingScrollArea,
            {d} QScrollArea#landingScrollArea > QWidget > QWidget {{
                background: {c["ink"]};
                border: 0;
            }}

            {d} QWidget#landingContent {{
                background: {c["ink"]};
            }}

            {d} QWidget {{
                color: {c["text"]};
                font-size: 13px;
                font-family: "Segoe UI", Arial, sans-serif;
            }}

            {d} QLabel#dialogLogo {{
                min-height: 80px;
                padding: 0;
            }}

            {d} QLabel#version_label {{
                color: {c["muted"]};
                font-size: 12px;
            }}

            {d} QLabel#made_by_label {{
                color: {c["text"]};
                font-family: "Segoe UI Semibold", "Segoe UI", Arial, sans-serif;
                font-size: 12px;
                font-weight: 700;
            }}

            {d} QLabel#section_title {{
                color: {c["title"]};
                font-family: "Segoe UI Semibold", "Segoe UI", Arial, sans-serif;
                font-size: 15px;
                font-weight: 700;
            }}

            {d} QLabel#info_label {{
                color: {c["muted"]};
                font-size: 12px;
                line-height: 1.5;
            }}

            {d} QLabel#transfer_help {{
                color: {c["muted"]};
                font-size: 11px;
                padding: 2px 2px 0 2px;
            }}

            {d} QLabel#footer_label {{
                color: {c["muted"]};
                font-size: 12px;
            }}

            /* --- Inputs --- */

            {d} QLineEdit,
            {d} QComboBox {{
                background: {c["input_bg"]};
                border: 1px solid {c["border"]};
                border-radius: 0px;
                padding: 8px 10px;
                color: {c["text"]};
                selection-background-color: {c["selection"]};
            }}

            {d} QLineEdit:focus,
            {d} QComboBox:focus {{
                border: 1px solid {c["accent"]};
            }}

            {d} QComboBox::drop-down {{
                border: 0;
                width: 28px;
            }}

            {d} QComboBox QAbstractItemView {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                selection-background-color: {c["selection"]};
                selection-color: {c["text"]};
                color: {c["text"]};
            }}

            /* --- List widget --- */

            {d} QListWidget {{
                background: {c["input_bg"]};
                border: 1px solid {c["border"]};
                border-radius: 0px;
                color: {c["text"]};
                padding: 4px;
            }}

            {d} QListWidget::item {{
                padding: 6px 8px;
                border-radius: 0px;
            }}

            {d} QListWidget::item:selected {{
                background: {c["selection"]};
                color: {c["text"]};
            }}

            {d} QListWidget::item:hover {{
                background: {c["button_hover"]};
            }}

            /* --- Group boxes --- */

            {d} QGroupBox {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {c["panel"]},
                    stop:1 {c["panel_alt"]});
                border: 1px solid {c["border"]};
                border-radius: 0px;
                margin-top: 18px;
                padding: 18px 14px 14px 14px;
                font-weight: 700;
            }}

            {d} QGroupBox::title {{
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: {c["title"]};
                font-family: "Segoe UI Semibold", "Segoe UI", Arial, sans-serif;
                font-size: 14px;
            }}

            /* --- Buttons (default) --- */

            {d} QPushButton {{
                background: {c["button_fill"]};
                color: {c["text"]};
                border: 1px solid {c["button_border"]};
                border-radius: 0px;
                padding: 8px 14px;
                font-weight: 600;
            }}

            {d} QPushButton:hover {{
                background: {c["button_hover"]};
                border: 1px solid {c["accent"]};
            }}

            {d} QPushButton:pressed {{
                background: {c["button_pressed"]};
            }}

            /* --- Primary action button (Open) --- */

            {d} QPushButton#btn_open {{
                background: {c["accent"]};
                color: {c["accent_text"]};
                border: 1px solid {c["accent"]};
            }}

            {d} QPushButton#btn_open:hover {{
                background: {c["accent_hover"]};
                border: 1px solid {c["accent_hover"]};
            }}

            {d} QPushButton#btn_open:pressed {{
                background: {c["accent_pressed"]};
                border: 1px solid {c["accent_pressed"]};
            }}

            {d} QPushButton#btn_support {{
                padding: 5px 12px;
                font-size: 12px;
                min-width: 78px;
            }}

            {d} QPushButton#btn_lost_mindmaps {{
                background: #dc2626;
                border: 1px solid #991b1b;
                color: #ffffff;
                font-size: 13px;
                font-weight: 800;
                padding: 10px 14px;
            }}

            {d} QPushButton#btn_lost_mindmaps:hover {{
                background: #b91c1c;
                border: 1px solid #7f1d1d;
            }}

            {d} QPushButton#btn_lost_mindmaps:pressed {{
                background: #991b1b;
            }}

            /* --- Delete button (danger) --- */

            {d} QPushButton#btn_delete {{
                color: #ef4444;
                border: 1px solid #ef4444;
            }}

            {d} QPushButton#btn_delete:hover {{
                background: #ef4444;
                color: {c["accent_text"]};
                border: 1px solid #ef4444;
            }}

            {d} QPushButton#btn_delete:pressed {{
                background: #dc2626;
                border: 1px solid #dc2626;
            }}

            /* --- Scrollbar --- */

            {d} QScrollBar:vertical {{
                width: 12px;
                background: {c["scroll_track"]};
                margin: 0;
            }}

            {d} QScrollBar::handle:vertical {{
                min-height: 32px;
                background: {c["scroll_handle"]};
                border: 0;
            }}

            {d} QScrollBar::add-line:vertical,
            {d} QScrollBar::sub-line:vertical,
            {d} QScrollBar::add-page:vertical,
            {d} QScrollBar::sub-page:vertical {{
                background: transparent;
                border: 0;
            }}

            /* --- Theme selector (compact) --- */

            {d} QComboBox#theme_selector {{
                max-width: 80px;
                padding: 4px 8px;
                font-size: 12px;
            }}

            {d} QMenu {{
                background: {c["panel"]};
                border: 1px solid {c["border"]};
                color: {c["text"]};
                padding: 4px;
            }}

            {d} QMenu::item {{
                padding: 6px 18px;
            }}

            {d} QMenu::item:selected {{
                background: {c["selection"]};
            }}
        """)

    def _apply_initial_window_size(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(self.DEFAULT_DIALOG_WIDTH, available.width() - self.SCREEN_MARGIN)
            height = min(self.DEFAULT_DIALOG_HEIGHT, available.height() - self.SCREEN_MARGIN)
            self.resize(width, height)
        else:
            self.resize(self.DEFAULT_DIALOG_WIDTH, self.DEFAULT_DIALOG_HEIGHT)

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
