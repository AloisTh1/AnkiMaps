import logging
import os
from typing import List, Optional

from anki.notes import NoteId
from aqt import QAction, QCursor, QPixmap, QPoint, mw
from aqt.qt import (
    QApplication,
    QCheckBox,
    QColor,
    QColorDialog,
    QEvent,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QImage,
    QKeySequence,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QObject,
    QPainter,
    QPdfWriter,
    QPushButton,
    QRectF,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QShortcut,
    Qt,
    QTimer,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    pyqtSignal,
)
from aqt.utils import showInfo

from ..common.constants import ANKIMAPS_CONSTANTS
from ..common.utils import LOGGING_ON

from ..model.connections import CONNECTION_TYPES, MindMapConnection
from ..model.mindmap import MindMap
from .line_type_selector import LineTypeSelectorWidget
from .log_viewer import LogViewer
from .mindmap_view import MindMapView
from .nodes.notes import MindMapNoteView

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)

MIN_ZOOM = 0.1
MAX_ZOOM = 5.0


class NonClosingCheckableAction(QWidgetAction):
    toggled = pyqtSignal(bool)

    def __init__(self, text: str, parent: QObject):
        super().__init__(parent)
        widget = QCheckBox(text)
        widget.toggled.connect(self.toggled.emit)
        self.setDefaultWidget(widget)

    def isChecked(self) -> bool:
        widget = self.defaultWidget()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return False

    def setChecked(self, state: bool):
        widget = self.defaultWidget()
        if isinstance(widget, QCheckBox):
            widget.setChecked(state)


class MindMapWindow(QMainWindow):
    link_button_clicked = pyqtSignal(
        str, str, int, str, int, str, int
    )  # note_1, note_2, conn_type, color, width, label, fontsize
    add_notes_requested = pyqtSignal()
    edit_note_requested = pyqtSignal(list)
    connection_property_updated = pyqtSignal(str, str, str, object)
    delete_notes_requested = pyqtSignal(list)
    anki_review_session_requested = pyqtSignal()
    open_another_map_requested = pyqtSignal()
    window_closed = pyqtSignal()
    connection_label_updated = pyqtSignal(str, str, str)
    note_property_updated = pyqtSignal(str, str, object)
    search_requested = pyqtSignal(str)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(
        self,
        parent,
        mindmap_name: str,
        model: MindMap,
        log_buffer: list,
        buffer_handler: logging.Handler,
    ):
        super().__init__(parent)
        self.mindmap_name = mindmap_name
        self._app_event_filter_installed = False
        self._last_shortcut_override_signature: Optional[tuple[object, object]] = None

        self.setWindowTitle(f"AnkiMaps - {mindmap_name}")

        self.setGeometry(100, 100, 1280, 720)

        self._current_connection_color = ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value
        self._current_connection_width = ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_SIZE.value
        self._current_connection_type = CONNECTION_TYPES.FULL_DIRECTED.value

        self._fields_menu_note_id: Optional[NoteId] = None
        self._selection_order = []
        self._is_editing_connection = False
        self.peek_button: Optional[QPushButton] = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Left Panel ---
        menu_panel = QWidget()
        menu_panel.setFixedWidth(220)
        menu_layout = QVBoxLayout(menu_panel)
        menu_layout.setContentsMargins(10, 10, 10, 10)
        menu_layout.setSpacing(8)
        menu_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(menu_panel)

        LOGO_BLUE = "#4a90e2"
        button_style = f"""
        QPushButton {{
            background-color: white; border: 2px solid {LOGO_BLUE}; border-radius: 6px;
            padding: 6px; color: {LOGO_BLUE}; font-weight: bold; text-align: center;
        }}
        QPushButton:hover {{ background-color: #f0f8ff; }}
        QPushButton:pressed {{ background-color: #dbeaff; }}
        QPushButton:disabled {{ background-color: #f5f5f5; color: #a0a0a0; border-color: #c0c0c0; }}
        QPushButton:checked {{ background-color: {LOGO_BLUE}; color: white; }}
        """
        menu_panel.setStyleSheet(f"QWidget {{ background-color: white; }} {button_style}")

        logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(pixmap.scaledToWidth(150, Qt.TransformationMode.SmoothTransformation))
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            menu_layout.addWidget(logo_label)

        # --- Right Container (Map + Zoom) ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        main_layout.addWidget(right_container, 1)

        self.mindmap_view = MindMapView(model, self)
        right_layout.addWidget(self.mindmap_view, 1)

        # --- Add Controls to Panels ---
        self._add_search_bar(menu_layout)
        self._create_actions()
        self._add_main_buttons_grid(menu_layout)

        separator1 = self._create_separator()
        menu_layout.addWidget(separator1)

        self._add_linking_controls(menu_layout)
        separator2 = self._create_separator()
        menu_layout.addWidget(separator2)
        self._add_view_controls(menu_layout)
        menu_layout.addStretch(1)
        self._add_zoom_controls(right_layout)

        # --- Signal Connections ---
        self.mindmap_view.scene_loaded.connect(self._connect_to_scene_signals)
        self.mindmap_view.connection_label_updated.connect(self.connection_label_updated)
        self.type_selector.type_selection_changed.connect(self._on_connection_type_changed)
        self.size_selector.valueChanged.connect(self._on_connection_size_changed)
        self.mindmap_view.note_resized.connect(self._on_note_resized)
        self.mindmap_view.scale_changed.connect(self._update_zoom_slider)
        model.connection_added.connect(self._on_selection_changed)
        model.connection_removed.connect(self._on_selection_changed)
        self.mindmap_view.fields_menu_requested.connect(self._on_show_fields_menu)

        if LOGGING_ON:
            self.log_viewer = LogViewer(self, log_buffer=log_buffer, buffer_handler=buffer_handler)
            self.log_viewer.hide()
            right_layout.addWidget(self.log_viewer)

        if app := QApplication.instance():
            app.installEventFilter(self)
            self._app_event_filter_installed = True

    def _connect_to_scene_signals(self):
        """Connects signals to the scene. This is necessary because the scene object
        is replaced when a new map is loaded."""
        if scene := self.mindmap_view.scene():
            scene.selectionChanged.connect(self._on_selection_changed)
        else:
            showInfo("Could not connect selection handler: scene is not initialized.")

    def _add_search_bar(self, layout: QVBoxLayout):
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search notes in map...")
        self.search_bar.setClearButtonEnabled(True)
        layout.addWidget(self.search_bar)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)  # 300ms delay
        self.search_timer.timeout.connect(self._on_perform_search)
        self.search_bar.textChanged.connect(self.search_timer.start)

    def _on_perform_search(self):
        self.search_requested.emit(self.search_bar.text())

    def _create_separator(self):
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

    def _create_action(
        self,
        text: str,
        shortcut: str,
        slot,
        *,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        passes_checked: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.setEnabled(enabled)
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(checked)
        if passes_checked:
            action.triggered.connect(slot)
        else:
            action.triggered.connect(lambda _checked=False: slot())
        return action

    def _format_action_button_text(self, action: QAction, text: Optional[str] = None) -> str:
        label = text if text is not None else action.text()
        shortcut_text = action.shortcut().toString()
        if not shortcut_text:
            return label
        if len(shortcut_text) == 1:
            shortcut_text = shortcut_text.lower()
        return f"{label} ({shortcut_text})"

    def _sync_button_from_action(self, button: QPushButton, action: QAction):
        button.setEnabled(action.isEnabled())
        button.setText(self._format_action_button_text(action))
        if action.isCheckable():
            button.setCheckable(True)
            button.setChecked(action.isChecked())

    def _create_action_button(self, action: QAction) -> QPushButton:
        button = QPushButton()
        button.clicked.connect(action.trigger)
        action.changed.connect(
            lambda _=False, btn=button, act=action: self._sync_button_from_action(btn, act)
        )
        self._sync_button_from_action(button, action)
        return button

    def _create_actions(self):
        self.undo_action = self._create_action("Undo", "Ctrl+Z", self._emit_undo_requested)
        self.redo_action = self._create_action("Redo", "Ctrl+Y", self._emit_redo_requested)
        self.undo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

        self.add_action = self._create_action("Add Notes", "a", self.add_notes_requested.emit)
        self.delete_action = self._create_action("Delete", "d", self._on_delete_requested)
        self.edit_action = self._create_action("Edit Notes", "e", self._on_edit_button_clicked)
        self.open_action = self._create_action("Maps", "o", self.open_another_map_requested.emit)
        self.review_action = self._create_action("Review", "s", self.anki_review_session_requested.emit)
        self.link_action = self._create_action(
            "Link",
            "c",
            self._on_link_notes_button_clicked,
            enabled=False,
        )
        self.center_action = self._create_action(
            "Center",
            "z",
            self._on_center_on_selection_requested,
            enabled=False,
        )
        self.reset_action = self._create_action("Fit View", "h", self._on_reset_view_requested)
        self.export_action = self._create_action("Export", "x", self._on_export_requested)
        self.toggle_grid_action = self._create_action(
            "Center Logo",
            "g",
            self._on_toggle_center_and_grid,
            checkable=True,
            checked=True,
            passes_checked=True,
        )
        self.fields_action = self._create_action("Show Fields", "f", self._on_fields_shortcut)

        self.addActions(
            [
                self.undo_action,
                self.redo_action,
                self.add_action,
                self.delete_action,
                self.edit_action,
                self.open_action,
                self.review_action,
                self.link_action,
                self.center_action,
                self.toggle_grid_action,
                self.reset_action,
                self.export_action,
                self.fields_action,
            ]
        )

        # Extra fallback shortcuts to verify activation and avoid focus-related misses.
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.undo_shortcut.activated.connect(self._emit_undo_requested)

        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_shortcut.activated.connect(self._emit_redo_requested)

        self.redo_alt_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.redo_alt_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_alt_shortcut.activated.connect(self._emit_redo_requested)

        # Focused-view fallbacks: QGraphicsView can eat key events before they reach the window.
        self.undo_shortcut_view = QShortcut(QKeySequence("Ctrl+Z"), self.mindmap_view)
        self.undo_shortcut_view.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut_view.activated.connect(self._emit_undo_requested)

        self.redo_shortcut_view = QShortcut(QKeySequence("Ctrl+Y"), self.mindmap_view)
        self.redo_shortcut_view.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.redo_shortcut_view.activated.connect(self._emit_redo_requested)

        self.redo_alt_shortcut_view = QShortcut(QKeySequence("Ctrl+Shift+Z"), self.mindmap_view)
        self.redo_alt_shortcut_view.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.redo_alt_shortcut_view.activated.connect(self._emit_redo_requested)

        logger.info(
            "Undo/Redo shortcuts registered (window + view): undo=%s, redo=%s, redo_alt=%s",
            "Ctrl+Z",
            "Ctrl+Y",
            "Ctrl+Shift+Z",
        )

    def _emit_undo_requested(self):
        logger.info("Undo shortcut/action triggered")
        self.undo_requested.emit()

    def _emit_redo_requested(self):
        logger.info("Redo shortcut/action triggered")
        self.redo_requested.emit()

    def _handle_undo_redo_keypress(self, event, source: str) -> bool:
        if not hasattr(event, "matches"):
            return False

        key = event.key() if hasattr(event, "key") else None
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        ctrl_pressed = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift_pressed = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if event.matches(QKeySequence.StandardKey.Undo) or (
            ctrl_pressed and not shift_pressed and key == Qt.Key.Key_Z
        ):
            logger.info("Undo requested via %s", source)
            self._emit_undo_requested()
            return True
        if event.matches(QKeySequence.StandardKey.Redo) or (
            ctrl_pressed and not shift_pressed and key == Qt.Key.Key_Y
        ):
            logger.info("Redo requested via %s", source)
            self._emit_redo_requested()
            return True
        if ctrl_pressed and shift_pressed and key == Qt.Key.Key_Z:
            logger.info("Redo requested via %s (Ctrl+Shift+Z)", source)
            self._emit_redo_requested()
            return True
        return False

    @staticmethod
    def _get_qevent_type(name: str):
        if hasattr(QEvent, name):
            return getattr(QEvent, name)
        if hasattr(QEvent, "Type") and hasattr(QEvent.Type, name):
            return getattr(QEvent.Type, name)
        return None

    @staticmethod
    def _key_event_signature(event) -> Optional[tuple[object, object]]:
        if not hasattr(event, "key") or not hasattr(event, "modifiers"):
            return None
        return (event.key(), event.modifiers())

    def eventFilter(self, watched: QObject, event):
        if self.isVisible() and self.isActiveWindow():
            shortcut_override_type = self._get_qevent_type("ShortcutOverride")
            if (
                shortcut_override_type is not None
                and event.type() == shortcut_override_type
                and self._handle_undo_redo_keypress(event, "QApplication eventFilter ShortcutOverride")
            ):
                self._last_shortcut_override_signature = self._key_event_signature(event)
                event.accept()
                return True

            key_press_type = self._get_qevent_type("KeyPress")
            if key_press_type is not None and event.type() == key_press_type:
                signature = self._key_event_signature(event)
                if (
                    self._last_shortcut_override_signature is not None
                    and signature == self._last_shortcut_override_signature
                ):
                    self._last_shortcut_override_signature = None
                    event.accept()
                    return True
                self._last_shortcut_override_signature = None
                if self._handle_undo_redo_keypress(event, "QApplication eventFilter KeyPress"):
                    event.accept()
                    return True

        return super().eventFilter(watched, event)

    def _on_fields_shortcut(self):
        """Triggers the fields context menu via shortcut for the current selection."""
        if scene := self.mindmap_view.scene():
            selected_items = [item for item in scene.selectedItems() if isinstance(item, MindMapNoteView)]
        else:
            showInfo("Could not open fields menu: scene is not initialized.")
            return
        if selected_items:
            # Check if all selected notes are of the same type
            first_note_type = selected_items[0].mindmap_node.anki_note.note_type()
            if all(item.mindmap_node.anki_note.note_type() == first_note_type for item in selected_items):
                self._on_show_fields_menu(selected_items, QCursor.pos())

    def _on_show_fields_menu(self, selected_items: List[MindMapNoteView], global_pos: QPoint):
        """Rebuilds and shows the fields context menu."""
        self._rebuild_fields_menu(selected_items)
        self.fields_menu.exec(global_pos)

    def _add_main_buttons_grid(self, layout: QVBoxLayout):
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setVerticalSpacing(6)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)

        # Row 0
        add_btn = self._create_action_button(self.add_action)
        delete_btn = self._create_action_button(self.delete_action)
        grid_layout.addWidget(add_btn, 0, 0)
        grid_layout.addWidget(delete_btn, 0, 1)

        # Row 1
        edit_btn = self._create_action_button(self.edit_action)
        open_btn = self._create_action_button(self.open_action)
        grid_layout.addWidget(edit_btn, 1, 0)
        grid_layout.addWidget(open_btn, 1, 1)

        # Row 2
        self.reviews_button = self._create_action_button(self.review_action)
        self._on_review_state_changed(False)
        self.reviews_button.setCheckable(True)

        self.link_button = self._create_action_button(self.link_action)

        grid_layout.addWidget(self.reviews_button, 2, 0)
        grid_layout.addWidget(self.link_button, 2, 1)

        # Row 3
        self.center_button = self._create_action_button(self.center_action)

        reset_button = self._create_action_button(self.reset_action)
        grid_layout.addWidget(self.center_button, 3, 0)
        grid_layout.addWidget(reset_button, 3, 1)

        # Row 4
        export_button = self._create_action_button(self.export_action)
        grid_layout.addWidget(export_button, 4, 0, 1, 2)

        # Row 5
        grid_button = self._create_action_button(self.toggle_grid_action)
        grid_button.setToolTip("Show or hide the center logo marker")
        grid_layout.addWidget(grid_button, 5, 0, 1, 2)

        for button in [
            add_btn,
            delete_btn,
            edit_btn,
            open_btn,
            self.reviews_button,
            self.link_button,
            self.center_button,
            reset_button,
            export_button,
            grid_button,
        ]:
            button.setMinimumHeight(30)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout.addLayout(grid_layout)

    def _add_linking_controls(self, layout: QVBoxLayout):
        self.type_selector = LineTypeSelectorWidget()
        layout.addWidget(self.type_selector)
        self.color_button = QPushButton("Connection Color")
        self.color_button.clicked.connect(self._on_choose_color_clicked)
        self._update_color_button_style()
        layout.addWidget(self.color_button)

        size_layout = QHBoxLayout()
        size_label = QLabel("Line Width:")
        self.size_selector = QSpinBox()
        self.size_selector.setSuffix(" px")
        self.size_selector.setMinimum(1)
        self.size_selector.setMaximum(10)
        self.size_selector.setValue(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_SIZE.value)
        size_layout.addWidget(size_label)
        size_layout.addWidget(self.size_selector)
        layout.addLayout(size_layout)

        self.type_selector.setEnabled(False)
        self.color_button.setEnabled(False)
        self.size_selector.setEnabled(False)

    def _add_view_controls(self, layout: QVBoxLayout):
        self.fields_menu = QMenu(self)

        self.peek_button = QPushButton("Peek (P)")
        self.peek_button.setToolTip("Hold to temporarily unblur notes in the current view")
        self.peek_button.pressed.connect(lambda: self.mindmap_view.toggle_blur_for_visible_notes(True))
        self.peek_button.released.connect(lambda: self.mindmap_view.toggle_blur_for_visible_notes(False))
        self.peek_button.setVisible(False)  # Hidden by default
        layout.addWidget(self.peek_button)

        font_size_label = QLabel("Font Size:")
        layout.addWidget(font_size_label)
        self.font_size_selector = QSpinBox()
        self.font_size_selector.setMinimum(6)
        self.font_size_selector.setMaximum(48)
        self.font_size_selector.setSuffix(" pt")
        self.font_size_selector.setValue(ANKIMAPS_CONSTANTS.DEFAULT_NOTE_FONT_SIZE.value)
        self.font_size_selector.setEnabled(False)
        self.font_size_selector.valueChanged.connect(self._on_font_size_changed)
        layout.addWidget(self.font_size_selector)

        if LOGGING_ON:
            self.log_viewer_button = QPushButton("Toggle Log (`)")
            self.log_viewer_button.setShortcut(QKeySequence("`"))
            self.log_viewer_button.clicked.connect(self.toggle_log_viewer)
            layout.addWidget(self.log_viewer_button)

    def _add_zoom_controls(self, layout: QVBoxLayout):
        zoom_container = QWidget()
        zoom_layout = QHBoxLayout(zoom_container)
        zoom_layout.setContentsMargins(10, 2, 10, 2)
        zoom_layout.setSpacing(5)

        zoom_out_btn = QPushButton("-")
        zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.clicked.connect(self.zoom_in)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(self.zoom_label)

        layout.addWidget(zoom_container)
        self._update_zoom_slider(1.0)

    def _scale_to_slider_val(self, scale: float) -> int:
        return int(((scale - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM)) * 100)

    def _slider_val_to_scale(self, val: int) -> float:
        return MIN_ZOOM + (val / 100.0) * (MAX_ZOOM - MIN_ZOOM)

    def _on_zoom_slider_changed(self, value: int):
        target_scale = self._slider_val_to_scale(value)
        current_scale = self.mindmap_view.transform().m11()
        if abs(target_scale - current_scale) < 0.01:
            return

        factor = target_scale / current_scale
        self.mindmap_view.scale(factor, factor)
        self.mindmap_view.scale_changed.emit(target_scale)

    def _update_zoom_slider(self, scale: float):
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self._scale_to_slider_val(scale))
        self.zoom_slider.blockSignals(False)
        self._update_zoom_label(scale)

    def _update_zoom_label(self, scale: float):
        self.zoom_label.setText(f"{scale:.0%}")

    def zoom_in(self):
        self.mindmap_view.scale(1.1, 1.1)
        self.mindmap_view.scale_changed.emit(self.mindmap_view.transform().m11())

    def zoom_out(self):
        self.mindmap_view.scale(1 / 1.1, 1 / 1.1)
        self.mindmap_view.scale_changed.emit(self.mindmap_view.transform().m11())

    def _on_toggle_center_and_grid(self, checked):
        if self.mindmap_view and hasattr(self.mindmap_view, "_center_logo_item"):
            self.mindmap_view._center_logo_item.setVisible(checked)
            # self.mindmap_view._coordinate_grid.setVisible(checked)

    def _on_link_notes_button_clicked(self):
        if len(self._selection_order) != 2:
            return
        self.link_button_clicked.emit(
            str(self._selection_order[0].note_id),
            str(self._selection_order[1].note_id),
            self._current_connection_type,
            self._current_connection_color,
            self._current_connection_width,
            "",
            int(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_LABEL_FONT_SIZE.value),
        )

    def _on_delete_requested(self):
        selected = [
            item.note_id
            for item in self.mindmap_view.scene().selectedItems()
            if isinstance(item, MindMapNoteView)
        ]
        if selected:
            if (
                QMessageBox.question(
                    self,
                    "Confirm Deletion",
                    f"Remove {len(selected)} note(s) from this mind map?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.delete_notes_requested.emit(selected)
        else:
            showInfo("Please select one or more notes to delete.")

    def _on_edit_button_clicked(self):
        selected = [
            item.note_id
            for item in self.mindmap_view.scene().selectedItems()
            if isinstance(item, MindMapNoteView)
        ]
        if selected:
            self.edit_note_requested.emit(selected)
        else:
            showInfo("Please select one or more notes to edit.")

    def _on_choose_color_clicked(self):
        color = QColorDialog.getColor(QColor(self._current_connection_color), self, "Choose Connection Color")
        if color.isValid():
            self._current_connection_color = color.name()
            self._update_color_button_style()
            if self._is_editing_connection and len(self._selection_order) == 2:
                id1, id2 = self._selection_order[0].note_id, self._selection_order[1].note_id
                self.connection_property_updated.emit(
                    str(id1), str(id2), "color", self._current_connection_color
                )

    def _update_color_button_style(self):
        self.color_button.setStyleSheet(
            f"""
            background-color: {self._current_connection_color};
            color: black; font-weight: normal; border: 1px solid #777;
            """
        )

    def toggle_log_viewer(self):
        if hasattr(self, "log_viewer"):
            self.log_viewer.setVisible(not self.log_viewer.isVisible())

    def _on_connection_type_changed(self, type_id: int):
        self._current_connection_type = type_id  # Always remember the last selection
        if self._is_editing_connection and len(self._selection_order) == 2:
            id1, id2 = self._selection_order[0].note_id, self._selection_order[1].note_id
            self.connection_property_updated.emit(str(id1), str(id2), "connection_type", type_id)

    def _on_connection_size_changed(self, size: int):
        self._current_connection_width = size
        if self._is_editing_connection and len(self._selection_order) == 2:
            id1, id2 = self._selection_order[0].note_id, self._selection_order[1].note_id
            self.connection_property_updated.emit(str(id1), str(id2), "size", size)

    def _populate_connection_controls(self, connection: MindMapConnection):
        self.type_selector.blockSignals(True)
        self.size_selector.blockSignals(True)

        button_to_check = self.type_selector.button_group.button(connection.connection_type.value)
        if button_to_check:
            button_to_check.setChecked(True)

        self.size_selector.setValue(connection.size)
        self._current_connection_width = connection.size
        self._current_connection_color = connection.color
        self._current_connection_type = connection.connection_type.value
        self._update_color_button_style()

        self.type_selector.blockSignals(False)
        self.size_selector.blockSignals(False)

    def _reset_connection_controls(self):
        self.type_selector.blockSignals(True)
        self.size_selector.blockSignals(True)

        button_to_check = self.type_selector.button_group.button(self._current_connection_type)
        if button_to_check:
            button_to_check.setChecked(True)
        self.size_selector.setValue(self._current_connection_width)
        self._update_color_button_style()

        self.type_selector.blockSignals(False)
        self.size_selector.blockSignals(False)

    def _on_selection_changed(self):
        if self.mindmap_view:
            if scene := self.mindmap_view.scene():
                selected_items = [item for item in scene.selectedItems() if isinstance(item, MindMapNoteView)]
            else:
                showInfo("Scene is not initialized. Selection actions are unavailable.")
                return

        num_selected = len(selected_items)

        self._update_selection_order(selected_items)

        if num_selected == 1:
            self._update_single_selection_ui(selected_items[0])
        else:
            self._disable_single_selection_ui()

        self._update_connection_ui(selected_items)

    def _update_selection_order(self, selected_items: List[MindMapNoteView]):
        """Keeps track of the order notes were selected in, for small selections."""
        if len(selected_items) < 10:
            self._selection_order = [view for view in self._selection_order if view in selected_items]
            for item in selected_items:
                if item not in self._selection_order:
                    self._selection_order.append(item)
        else:
            self._selection_order.clear()

    def _update_single_selection_ui(self, view_item: MindMapNoteView):
        """Enables and configures UI controls that apply to a single selected note."""
        self.center_action.setEnabled(True)
        self.font_size_selector.setEnabled(True)

        self.font_size_selector.blockSignals(True)
        self.font_size_selector.setValue(int(view_item.mindmap_node.font_size))
        self.font_size_selector.blockSignals(False)

    def _disable_single_selection_ui(self):
        """Disables UI controls that only work with a single selected note."""
        self.center_action.setEnabled(False)
        self.font_size_selector.setEnabled(False)

    def _update_multi_selection_ui(self, selected_items: List[MindMapNoteView]):
        """Updates UI that can apply to one or more notes, like the fields menu."""
        # Check if all selected notes are of the same type
        first_note_type = selected_items[0].mindmap_node.anki_note.note_type()
        all_same_type = all(
            item.mindmap_node.anki_note.note_type() == first_note_type for item in selected_items
        )

        if all_same_type:
            self._rebuild_fields_menu(selected_items)
            self._fields_menu_note_id = selected_items[0].note_id  # Use as a reference
        else:
            self.fields_menu.clear()
            self._fields_menu_note_id = None

    def _update_connection_ui(self, selected_items: List[MindMapNoteView]):
        """Manages the state of all connection-related UI controls."""
        num_selected = len(selected_items)
        is_two_selected = num_selected == 2
        has_connection = False
        self._is_editing_connection = False

        if is_two_selected:
            id1, id2 = selected_items[0].note_id, selected_items[1].note_id
            if connection := self.mindmap_view.model.get_connection(id1, id2):
                self._is_editing_connection = True
                has_connection = True
                self._populate_connection_controls(connection)
            else:
                self._reset_connection_controls()
        else:
            self._reset_connection_controls()

        # Set state of connect button
        self.link_action.setEnabled(is_two_selected)
        self.link_action.setText("Unlink" if has_connection else "Link")

        # Set state of link styling panel
        is_link_panel_enabled = is_two_selected
        self.type_selector.setEnabled(is_link_panel_enabled)
        self.color_button.setEnabled(is_link_panel_enabled)
        self.size_selector.setEnabled(is_link_panel_enabled)

    def _on_font_size_changed(self, new_size: int):
        if view_item := self.mindmap_view.get_selected_view_item():
            self.note_property_updated.emit(str(view_item.note_id), "font_size", float(new_size))

    def _on_note_resized(self, note_id_str: str, new_width: float):
        """Unified handler for note resize events."""
        self.note_property_updated.emit(note_id_str, "width", new_width)

    def _rebuild_fields_menu(self, view_items: List[MindMapNoteView]):
        self.fields_menu.clear()
        if not view_items or not mw or not mw.col:
            return

        # Use the first item as a reference for field names, since they are all the same type
        ref_item = view_items[0]
        nt = ref_item.mindmap_node.anki_note.note_type()
        if not nt:
            return

        field_names = [f["name"] for f in nt["flds"]]

        # Determine shared checked state
        # A field is checked if it's shown in ALL selected notes.
        indices_in_all = set(ref_item.mindmap_node.shown_field_indices)
        for item in view_items[1:]:
            indices_in_all.intersection_update(item.mindmap_node.shown_field_indices)

        for i, name in enumerate(field_names):
            action = NonClosingCheckableAction(name, self.fields_menu)
            action.setChecked(i in indices_in_all)
            action.toggled.connect(
                lambda checked, index=i: self._on_field_toggled(view_items, index, checked)
            )
            self.fields_menu.addAction(action)

    def _on_field_toggled(self, view_items: List[MindMapNoteView], index: int, checked: bool):
        for view_item in view_items:
            indices = set(view_item.mindmap_node.shown_field_indices)
            if checked:
                indices.add(index)
            else:
                indices.discard(index)

            new_indices = sorted(list(indices))
            # Reuse existing signal to update the property
            self.note_property_updated.emit(str(view_item.note_id), "shown_field_indices", new_indices)

    def _on_review_state_changed(self, is_reviewing: bool):
        """Called when the review session starts or stops."""
        self.reviews_button.setChecked(is_reviewing)

        if self.peek_button:
            self.peek_button.setVisible(is_reviewing)
            if not is_reviewing:
                # If the button was held down when review ended, release it
                self.peek_button.setDown(False)

        if not is_reviewing:
            self.review_action.setText("Review")
            self.reviews_button.setToolTip("Start Review (S)")
        else:
            self.review_action.setText("Stop Review")
            self.reviews_button.setToolTip("Stop Review (S)\n(Loading cards...)")
        self.mindmap_view.update_review_visuals(is_reviewing)

    def _on_review_progress_updated(self, remaining: int, total: int):
        """Update the review button with the number of cards remaining."""
        if self.reviews_button.isChecked():
            self.reviews_button.setText(
                self._format_action_button_text(self.review_action, f"Stop ({remaining})")
            )
            self.reviews_button.setToolTip(f"Stop Review (S)\n({remaining} of {total} left)")

    def _on_review_focus_changed(self, active_nid: Optional[NoteId], answer_visible: bool):
        """Called when the question/answer is shown for a card."""
        self.mindmap_view.update_review_visuals(
            is_reviewing=True, active_nid=active_nid, answer_visible=answer_visible
        )

        if active_nid and (active_item := self.mindmap_view._all_view_items.get(active_nid)):
            if scene := self.mindmap_view.scene():
                scene.blockSignals(True)
                try:
                    scene.clearSelection()
                    active_item.setSelected(True)
                finally:
                    scene.blockSignals(False)

    def _on_center_on_selection_requested(self):
        selected_items = [
            item for item in self.mindmap_view.scene().selectedItems() if isinstance(item, MindMapNoteView)
        ]
        if selected_items:
            self._center_on_items(selected_items)

    def _center_on_items(self, items: List[MindMapNoteView]):
        if not items:
            return
        total_rect = QRectF()
        for i, item in enumerate(items):
            if i == 0:
                total_rect = item.sceneBoundingRect()
            else:
                total_rect = total_rect.united(item.sceneBoundingRect())
        padded_rect = total_rect.adjusted(-150, -150, 150, 150)
        self.mindmap_view.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.mindmap_view.scale_changed.emit(self.mindmap_view.transform().m11())

    def _on_reset_view_requested(self):
        self.initial_zoom_to_fit()

    def _on_export_requested(self):
        if not (scene := self.mindmap_view.scene()):
            showInfo("Could not export: scene is not initialized.")
            return

        source_rect = scene.itemsBoundingRect()
        if source_rect.isEmpty():
            showInfo("Could not export: this mindmap is empty.")
            return

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Mindmap",
            f"{self.mindmap_name}.png",
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;PDF Document (*.pdf)",
        )
        if not file_path:
            return

        export_path = self._resolve_export_path(file_path, selected_filter)
        extension = os.path.splitext(export_path)[1].lower()

        try:
            if extension == ".pdf":
                self._export_scene_to_pdf(scene, source_rect, export_path)
            elif extension in (".jpg", ".jpeg"):
                self._export_scene_to_image(scene, source_rect, export_path, "JPG")
            else:
                self._export_scene_to_image(scene, source_rect, export_path, "PNG")
            showInfo(f"Mindmap exported to:\n{export_path}")
        except Exception as exc:
            showInfo(f"Export failed: {exc}")

    def _resolve_export_path(self, file_path: str, selected_filter: str) -> str:
        extension = os.path.splitext(file_path)[1].lower()
        if extension in (".png", ".jpg", ".jpeg", ".pdf"):
            return file_path

        if "JPEG" in selected_filter:
            return f"{file_path}.jpg"
        if "PDF" in selected_filter:
            return f"{file_path}.pdf"
        return f"{file_path}.png"

    def _export_scene_to_image(self, scene, source_rect: QRectF, export_path: str, image_format: str):
        scale_factor = 2.0
        image_width = max(1, int(source_rect.width() * scale_factor))
        image_height = max(1, int(source_rect.height() * scale_factor))

        image = QImage(image_width, image_height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        target_rect = QRectF(0, 0, image_width, image_height)
        scene.render(painter, target_rect, source_rect)
        painter.end()

        if not image.save(export_path, image_format):
            raise RuntimeError(f"Could not write {image_format} file.")

    def _export_scene_to_pdf(self, scene, source_rect: QRectF, export_path: str):
        pdf_writer = QPdfWriter(export_path)
        pdf_writer.setResolution(300)

        painter = QPainter(pdf_writer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        target_rect = QRectF(0, 0, float(pdf_writer.width()), float(pdf_writer.height()))
        scene.render(painter, target_rect, source_rect)
        painter.end()

    def highlight_search_results(self, note_ids: List[NoteId]):
        self.mindmap_view.update_search_highlights(note_ids)

        found_items = []
        for nid in note_ids:
            if self.mindmap_view._all_view_items.get(nid):
                found_items.append(self.mindmap_view._all_view_items.get(nid))
        if found_items:
            self._center_on_items(found_items)
        else:
            if len(self.search_bar.text()) > 0:
                self.initial_zoom_to_fit()

    def closeEvent(self, event):
        if self._app_event_filter_installed and (app := QApplication.instance()):
            app.removeEventFilter(self)
            self._app_event_filter_installed = False
        self.window_closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Handle key press events for the main window."""
        if self._handle_undo_redo_keypress(event, "MindMapWindow keyPressEvent"):
            event.accept()
        elif event.matches(QKeySequence.StandardKey.SelectAll):
            scene = self.mindmap_view.scene()

            scene.blockSignals(True)
            try:
                for item in scene.items():
                    if isinstance(item, MindMapNoteView):
                        item.setSelected(True)
            finally:
                scene.blockSignals(False)

            self._on_selection_changed()

            event.accept()
        elif not event.isAutoRepeat() and event.key() == Qt.Key.Key_P:
            if self.peek_button and self.peek_button.isVisible():
                self.peek_button.setDown(True)
                self.mindmap_view.toggle_blur_for_visible_notes(True)
                event.accept()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Handle key release events for the main window."""
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_P:
            if self.peek_button and self.peek_button.isVisible():
                self.peek_button.setDown(False)
                self.mindmap_view.toggle_blur_for_visible_notes(False)
                event.accept()
            else:
                super().keyReleaseEvent(event)
        else:
            super().keyReleaseEvent(event)

    def initial_zoom_to_fit(self):
        """Calculates the bounding box of all items and zooms to fit them in the view."""
        if not self.mindmap_view.scene().items():
            return

        rect = self.mindmap_view.scene().itemsBoundingRect()

        if not rect.isEmpty():
            padded_rect = rect.adjusted(-100, -100, 100, 100)
            self.mindmap_view.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.mindmap_view.scale_changed.emit(self.mindmap_view.transform().m11())
