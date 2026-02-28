import logging
import time
import weakref
from typing import List, Optional

from anki.notes import NoteId
from aqt.qt import (
    QApplication,
    QBrush,
    QColor,
    QCursor,
    QEvent,
    QGestureEvent,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsSceneContextMenuEvent,
    QGraphicsView,
    QInputDialog,
    QKeySequence,
    QPainter,
    QPen,
    QPinchGesture,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QWheelEvent,
    pyqtSignal,
)
from aqt.utils import showWarning

from ..common.constants import ANKIMAPS_CONSTANTS
from ..common.quadtree import Quadtree
from ..model.connections import MindMapConnection
from ..model.mindmap import MindMap
from ..model.node import MindMapNode
from .edges.edges import StickyLine
from .items.center_point import CenterLogoItem
from .nodes.notes import MindMapNoteView
from .nodes.states import NoteState

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class FastDragProxyItem(QGraphicsObject):
    """
    Visual proxy for dragging many items (without it the UI freezes).
    """

    def __init__(self, items_to_draw: List[MindMapNoteView]):
        super().__init__()
        self.setZValue(100)  # Draw on top of everything
        self.brush = QBrush(QColor(150, 150, 200, 100))
        self.pen = QPen(QColor(100, 100, 150), 1, Qt.PenStyle.DashLine)

        if not items_to_draw:
            self._bounding_rect = QRectF()
            return

        item_rects_scene = [item.sceneBoundingRect() for item in items_to_draw]

        total_bounds = QRectF()
        for r in item_rects_scene:
            total_bounds = total_bounds.united(r)

        self.setPos(total_bounds.topLeft())

        self._bounding_rect = total_bounds.translated(-total_bounds.topLeft())
        self.relative_rects = [r.translated(-total_bounds.topLeft()) for r in item_rects_scene]

    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def paint(self, painter: QPainter, option, widget=None):
        painter.setBrush(self.brush)
        painter.setPen(self.pen)
        # Draw a faint box for each item being dragged
        for r in self.relative_rects:
            painter.drawRect(r)


class MindMapView(QGraphicsView):
    notes_moved = pyqtSignal(list)
    note_double_clicked = pyqtSignal(str)
    connection_delete_requested = pyqtSignal(str, str)
    connection_label_updated = pyqtSignal(str, str, str)
    note_resized = pyqtSignal(str, float)
    scene_loaded = pyqtSignal()
    scale_changed = pyqtSignal(float)
    fields_menu_requested = pyqtSignal(object, object)  # list of items, global pos

    DRAG_PROXY_THRESHOLD = 50

    def __init__(self, model: MindMap, parent=None):
        super().__init__(parent)
        self.model = model
        self.quadtree = Quadtree(QRectF())

        self._all_view_items: dict[NoteId, MindMapNoteView] = {}
        self._all_lines: dict[frozenset[NoteId], StickyLine] = {}
        self._currently_visible_ids: set[NoteId] = set()

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Enable pinch gestures
        self.grabGesture(Qt.GestureType.PinchGesture)

        self.horizontalScrollBar().valueChanged.connect(self._request_update)
        self.verticalScrollBar().valueChanged.connect(self._request_update)

        # State for panning and dragging
        self._panning = False
        self._last_mouse_pos = QPoint()
        self._drag_start_pos_scene: Optional[QPointF] = None
        self._item_pos_on_drag_start: dict[MindMapNoteView, QPointF] = {}
        self._proxy_initial_pos: Optional[QPointF] = None  # Position of proxy at drag start

        # Performance states
        self.is_in_fast_render_mode = False
        self._is_lod_mode = False
        self._fast_drag_proxy: Optional[FastDragProxyItem] = None
        self._search_highlighted_ids: set[NoteId] = set()
        self._review_active_nid: Optional[NoteId] = None

        self._center_logo_item = CenterLogoItem()

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(100)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._update_visibility)

        self.model.model_loaded.connect(self.on_full_model_load)
        self.model.nodes_added.connect(self.on_nodes_added)
        self.model.nodes_removed.connect(self.on_nodes_removed)
        self.model.nodes_moved.connect(self.on_nodes_moved)
        self.model.node_properties_changed.connect(self.on_node_properties_changed)
        self.model.connection_added.connect(self.on_connection_added)
        self.model.connection_removed.connect(self.on_connection_removed)
        self.model.connections_removed.connect(self.on_connections_removed)
        self.model.connection_updated.connect(self.on_connection_updated)
        self.scale_changed.connect(self._update_lod_status)

    def event(self, event: QEvent) -> bool:
        """Override to handle gesture events."""
        if isinstance(event, QGestureEvent):
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch and isinstance(pinch, QPinchGesture):
                self._handle_pinch(pinch)
                return True
        return super().event(event)

    def keyPressEvent(self, event):
        """
        Fallback shortcut handling when QGraphicsView focus prevents parent QAction/QShortcut capture.
        """
        key = event.key() if hasattr(event, "key") else None
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        ctrl_pressed = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift_pressed = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if event.matches(QKeySequence.StandardKey.Undo) or (
            ctrl_pressed and not shift_pressed and key == Qt.Key.Key_Z
        ):
            logger.info("Undo requested via MindMapView keyPressEvent fallback")
            emit_undo = getattr(self.window(), "_emit_undo_requested", None)
            if callable(emit_undo):
                emit_undo()
                event.accept()
                return
        elif event.matches(QKeySequence.StandardKey.Redo) or (
            ctrl_pressed and not shift_pressed and key == Qt.Key.Key_Y
        ):
            logger.info("Redo requested via MindMapView keyPressEvent fallback")
            emit_redo = getattr(self.window(), "_emit_redo_requested", None)
            if callable(emit_redo):
                emit_redo()
                event.accept()
                return
        elif ctrl_pressed and shift_pressed and key == Qt.Key.Key_Z:
            logger.info("Redo requested via MindMapView Ctrl+Shift+Z fallback")
            emit_redo = getattr(self.window(), "_emit_redo_requested", None)
            if callable(emit_redo):
                emit_redo()
                event.accept()
                return
        super().keyPressEvent(event)

    def _update_lod_status(self):
        scale = self.transform().m11()
        new_lod_mode = scale < ANKIMAPS_CONSTANTS.LOD_SCALE_THRESHOLD.value

        if new_lod_mode != self._is_lod_mode:
            self._is_lod_mode = new_lod_mode
            logger.info(f"LOD mode {'enabled' if self._is_lod_mode else 'disabled'}.")
            for item in self._all_view_items.values():
                item.set_lod_mode(self._is_lod_mode)
            for line in self._all_lines.values():
                line.set_lod_mode(self._is_lod_mode)

    def _handle_pinch(self, gesture: QPinchGesture):
        """Applies scaling based on a pinch gesture."""
        change_flags = gesture.changeFlags()
        if change_flags & QPinchGesture.ChangeFlag.ScaleFactorChanged:
            self.scale(gesture.scaleFactor(), gesture.scaleFactor())
            self._request_update()
            self.scale_changed.emit(self.transform().m11())

    def _enter_fast_drag_mode(self, selected_items: List[MindMapNoteView]):
        logger.info(f"Entering fast drag mode with {len(selected_items)} items.")
        self.is_in_fast_render_mode = True
        self._fast_drag_proxy = FastDragProxyItem(selected_items)
        self.scene().addItem(self._fast_drag_proxy)
        self.viewport().update()

    def _exit_fast_drag_mode(self):
        if not self._fast_drag_proxy:
            return
        logger.info("Exiting fast drag mode.")
        self.scene().removeItem(self._fast_drag_proxy)
        self._fast_drag_proxy = None
        self.is_in_fast_render_mode = False
        self.viewport().update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

        if event.button() == Qt.MouseButton.LeftButton:
            item_under_cursor = self.itemAt(event.pos())

            if isinstance(item_under_cursor, MindMapNoteView) and item_under_cursor.isSelected():
                self._drag_start_pos_scene = self.mapToScene(event.pos())
                selected = [
                    item for item in self.scene().selectedItems() if isinstance(item, MindMapNoteView)
                ]
                self._item_pos_on_drag_start = {item: item.pos() for item in selected}
                self._proxy_initial_pos = None
            else:
                self._drag_start_pos_scene = None
                self._item_pos_on_drag_start.clear()

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = self.mapToScene(self._last_mouse_pos) - self.mapToScene(event.pos())
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
            self.translate(delta.x(), delta.y())
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self._last_mouse_pos = event.pos()
            self._request_update()
            event.accept()
            return

        if not (event.buttons() & Qt.MouseButton.LeftButton and self._drag_start_pos_scene is not None):
            super().mouseMoveEvent(event)
            return

        distance = (self.mapToScene(event.pos()) - self._drag_start_pos_scene).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        if (
            not self.is_in_fast_render_mode
            and len(self._item_pos_on_drag_start) > ANKIMAPS_CONSTANTS.DRAG_PROXY_THRESHOLD.value
        ):
            self._enter_fast_drag_mode(list(self._item_pos_on_drag_start.keys()))
            if self._fast_drag_proxy:
                self._proxy_initial_pos = self._fast_drag_proxy.pos()

        if self.is_in_fast_render_mode:
            if self._fast_drag_proxy and self._proxy_initial_pos is not None:
                current_pos_scene = self.mapToScene(event.pos())
                delta = current_pos_scene - self._drag_start_pos_scene
                self._fast_drag_proxy.setPos(self._proxy_initial_pos + delta)
                event.accept()
                return

        super().mouseMoveEvent(event)
        for item in self.scene().selectedItems():
            if isinstance(item, MindMapNoteView):
                item.update_attached_lines()

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        moved_data = []
        items_to_reselect = list(self._item_pos_on_drag_start.keys())

        if bool(self._drag_start_pos_scene):
            current_pos_scene = self.mapToScene(event.pos())
            if self.is_in_fast_render_mode:
                delta = current_pos_scene - self._drag_start_pos_scene
                self._exit_fast_drag_mode()

                for item, start_pos in self._item_pos_on_drag_start.items():
                    final_pos = start_pos + delta
                    item.setPos(final_pos)
                    moved_data.append(
                        {"item": item, "id": str(item.note_id), "x": final_pos.x(), "y": final_pos.y()}
                    )
            else:
                for item, start_pos in self._item_pos_on_drag_start.items():
                    if item.pos() != start_pos:
                        moved_data.append(
                            {"item": item, "id": str(item.note_id), "x": item.pos().x(), "y": item.pos().y()}
                        )

        super().mouseReleaseEvent(event)

        if moved_data:
            for d in moved_data:
                d.pop("item", None)
            self.notes_moved.emit(moved_data)
            if items_to_reselect:
                self.scene().blockSignals(True)
                try:
                    for item in items_to_reselect:
                        item.setSelected(True)
                finally:
                    self.scene().blockSignals(False)
                from .mindmap_window import MindMapWindow

                p = self.parent()
                if isinstance(p, MindMapWindow):
                    p._on_selection_changed()

        self._drag_start_pos_scene = None
        self._item_pos_on_drag_start.clear()
        self._proxy_initial_pos = None
        if self.is_in_fast_render_mode:
            self._exit_fast_drag_mode()

    def on_full_model_load(self):
        start_time = time.time()
        logger.info("View: Full model reload requested. Swapping scene...")
        new_scene = QGraphicsScene(self)
        self._all_view_items.clear()
        self._all_lines.clear()
        new_scene.addItem(self._center_logo_item)
        for node_data in self.model.nodes.values():
            self._add_note_item_to_scene(node_data, new_scene)
        for conn_data in self.model.connections.values():
            self._add_connection_item_to_scene(conn_data, new_scene)
        old_scene = self.scene()
        self.setScene(new_scene)
        if old_scene:
            old_scene.deleteLater()
        QTimer.singleShot(0, self._finish_full_model_load)
        logger.info(
            f"View: Scene swap complete in {time.time() - start_time:.4f} seconds. Deferring quadtree build."
        )

    def _finish_full_model_load(self):
        """Finalizes setup after a full model load, once item geometries are stable."""
        self.scene().setSceneRect(self.model.get_bounds())
        self.rebuild_quadtree()
        self._request_update()
        self.scene_loaded.emit()
        self._update_lod_status()
        logger.info("View: Quadtree build and initial visibility update complete.")

    def on_nodes_added(self, node_ids: list[NoteId]):
        for nid in node_ids:
            if nid not in self._all_view_items and (node_data := self.model.nodes.get(nid)):
                self._add_note_item_to_scene(node_data, self.scene())
        self.rebuild_quadtree()
        self._request_update()

    def on_nodes_removed(self, node_ids: List[NoteId]):
        for nid in node_ids:
            if view_item := self._all_view_items.pop(nid, None):
                self.scene().removeItem(view_item)
                self._search_highlighted_ids.discard(nid)
                if self._review_active_nid == nid:
                    self._review_active_nid = None
        self.rebuild_quadtree()
        self._request_update()

    def on_connections_removed(self, keys: List[frozenset[NoteId]]):
        for key in keys:
            if line := self._all_lines.pop(key, None):
                self.scene().removeItem(line)

    def _request_update(self):
        self.update_timer.start()

    def _update_visibility(self):
        if self.is_in_fast_render_mode:
            return
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        visible_rect.adjust(-300, -300, 300, 300)
        if not self.quadtree:
            return
        visible_ids = set(self.quadtree.query(visible_rect))
        ids_to_hide = self._currently_visible_ids - visible_ids
        ids_to_show = visible_ids - self._currently_visible_ids
        for nid in ids_to_hide:
            if item := self._all_view_items.get(nid):
                item.setVisible(False)
        for nid in ids_to_show:
            if item := self._all_view_items.get(nid):
                item.setVisible(True)
        self._currently_visible_ids = visible_ids

    def _add_note_item_to_scene(self, node_data: MindMapNode, scene: QGraphicsScene):
        view_item = MindMapNoteView(node_data)
        view_item.setPos(node_data.x, node_data.y)
        scene.addItem(view_item)
        view_item.signals.note_double_clicked.connect(self.note_double_clicked)
        view_item.signals.note_resized.connect(self.note_resized)
        self._all_view_items[node_data.note_id] = view_item
        view_item.set_lod_mode(self._is_lod_mode)
        view_item.setVisible(False)

    def _add_connection_item_to_scene(self, conn_data: MindMapConnection, scene: QGraphicsScene):
        key = frozenset([conn_data.from_note_id, conn_data.to_note_id])
        if key in self._all_lines:
            return
        from_node, to_node = (
            self._all_view_items.get(conn_data.from_note_id),
            self._all_view_items.get(conn_data.to_note_id),
        )
        if from_node and to_node:
            line = StickyLine(
                from_node,
                to_node,
                conn_data.connection_type.value,
                conn_data.color,
                conn_data.size,
                conn_data.label,
                conn_data.label_size,
            )
            line.signals.connection_delete_requested.connect(
                lambda f, t: self.connection_delete_requested.emit(str(f), str(t))
            )
            line.signals.label_edit_requested.connect(self._on_connection_label_edit_requested)
            line.signals.label_remove_requested.connect(self._on_connection_label_remove_requested)
            line.signals.connection_left_clicked.connect(self._on_line_left_clicked)
            scene.addItem(line)
            line.update_position()
            self._all_lines[key] = line
            from_node.sticky_lines.add(weakref.ref(line))
            to_node.sticky_lines.add(weakref.ref(line))
            line.set_lod_mode(self._is_lod_mode)
            line.setVisible(True)

    def on_nodes_moved(self, node_ids: list[NoteId]):
        for nid in node_ids:
            if view_item := self._all_view_items.get(nid):
                node_data = self.model.nodes[nid]
                view_item.setPos(node_data.x, node_data.y)
        self.rebuild_quadtree()
        self._request_update()

    def on_node_properties_changed(self, node_ids: list[NoteId]):
        geometry_changed = False
        for nid in node_ids:
            if view_item := self._all_view_items.get(nid):
                old_rect = view_item.boundingRect()
                view_item.update_size()
                if old_rect != view_item.boundingRect():
                    geometry_changed = True
        if geometry_changed:
            self.rebuild_quadtree()
        self._request_update()

    def rebuild_quadtree(self):
        if not self.quadtree:
            return
        logger.info("Rebuilding quadtree")
        self.quadtree.clear()
        self.quadtree.boundary = self.model.get_bounds()
        if scene := self.scene():
            scene.setSceneRect(self.quadtree.boundary)
            for node_id, view_item in self._all_view_items.items():
                self.quadtree.insert((node_id, view_item.sceneBoundingRect()))

    def on_connection_added(self, conn_data: MindMapConnection):
        if scene := self.scene():
            self._add_connection_item_to_scene(conn_data, scene=scene)

    def on_connection_removed(self, key: frozenset[NoteId]):
        if scene := self.scene():
            if line := self._all_lines.pop(key, None):
                scene.removeItem(line)
        else:
            showWarning("Error getting scene in _on_line_left_clicked. Pls report to the dev")

    def on_connection_updated(self, conn_data: MindMapConnection):
        key = frozenset([conn_data.from_note_id, conn_data.to_note_id])
        if line := self._all_lines.get(key):
            line.update_style(conn_data)

    def _on_line_left_clicked(self, line_item: StickyLine):
        if scene := self.scene():
            from_node, to_node = line_item.from_node, line_item.to_node
            if from_node and to_node:
                scene.blockSignals(True)
                try:
                    scene.clearSelection()
                    from_node.setSelected(True)
                    to_node.setSelected(True)
                finally:
                    scene.blockSignals(False)

                from .mindmap_window import MindMapWindow

                w = self.window()

                if isinstance(w, MindMapWindow):
                    w._on_selection_changed()
        else:
            showWarning("Error getting scene in _on_line_left_clicked. Pls report to the dev")

    def _on_connection_label_edit_requested(self, line_item: StickyLine):
        node1, node2 = line_item.from_node, line_item.to_node
        if node1 and node2:
            current_label = line_item.label_item.toPlainText()
            text, ok = QInputDialog.getText(self, "Connection Label", "Enter label:", text=current_label)
            if ok:
                self.connection_label_updated.emit(str(node1.note_id), str(node2.note_id), text)

    def _on_connection_label_remove_requested(self, line_item: StickyLine):
        node1, node2 = line_item.from_node, line_item.to_node
        if node1 and node2:
            self.connection_label_updated.emit(str(node1.note_id), str(node2.note_id), "")

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            zoom_factor = 1.15 if angle > 0 else 1 / 1.15
            self.scale(zoom_factor, zoom_factor)
            self._request_update()
            self.scale_changed.emit(self.transform().m11())
            event.accept()
        else:
            super().wheelEvent(event)

    def get_selected_view_item(self) -> Optional[MindMapNoteView]:
        if scene := self.scene():
            selected = scene.selectedItems()
            if len(selected) == 1 and isinstance(selected[0], MindMapNoteView):
                return selected[0]
            return None
        else:
            showWarning("Error geting scene in get_selected_view_item")

    def update_search_highlights(self, new_ids: List[NoteId]):
        """Efficiently updates search highlights using set differences."""
        new_id_set = set(new_ids)
        ids_to_unhighlight = self._search_highlighted_ids - new_id_set
        ids_to_highlight = new_id_set - self._search_highlighted_ids

        for nid in ids_to_unhighlight:
            if item := self._all_view_items.get(nid):
                item.set_state(item.state & ~NoteState.SEARCH_HIGHLIGHTED)
        for nid in ids_to_highlight:
            if item := self._all_view_items.get(nid):
                item.set_state(item.state | NoteState.SEARCH_HIGHLIGHTED)
        self._search_highlighted_ids = new_id_set

    def update_review_visuals(
        self, is_reviewing: bool, active_nid: Optional[NoteId] = None, answer_visible: bool = False
    ):
        if not is_reviewing:
            for item in self._all_view_items.values():
                item.set_state(NoteState.NORMAL)
            self._review_active_nid = None
            return

        if self._review_active_nid and self._review_active_nid != active_nid:
            if prev_item := self._all_view_items.get(self._review_active_nid):
                prev_item.set_state(NoteState.REVIEW_BLURRED)

        self._review_active_nid = active_nid

        for nid, item in self._all_view_items.items():
            if nid == active_nid:
                new_state = NoteState.REVIEW_ACTIVE
                if not answer_visible:
                    new_state |= NoteState.MASKED
                item.set_state(new_state)
            else:
                item.set_state(NoteState.REVIEW_BLURRED)

        # Center on the new active note and flip if needed
        if active_nid and (active_item := self._all_view_items.get(active_nid)):
            padded_rect = active_item.sceneBoundingRect().adjusted(-400, -400, 400, 400)
            self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale_changed.emit(self.transform().m11())
            self._request_update()
            if answer_visible and NoteState.MASKED in active_item.state:
                active_item.fade_out_mask()

    def toggle_blur_for_visible_notes(self, unblurred: bool):
        """
        Temporarily toggles the blur effect for all visible notes except the active one.
        Called by the "Peek" button.
        """
        if not self._review_active_nid:
            return

        for nid in self._currently_visible_ids:
            if nid == self._review_active_nid:
                continue

            if item := self._all_view_items.get(nid):
                if unblurred:
                    item.set_state(item.state & ~NoteState.REVIEW_BLURRED)
                else:
                    item.set_state(item.state | NoteState.REVIEW_BLURRED)

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):
        """Shows a context menu for selected notes."""
        item_under_cursor = self.itemAt(event.pos())
        if scene := self.scene():
            if isinstance(item_under_cursor, MindMapNoteView) and not item_under_cursor.isSelected():
                scene.blockSignals(True)
                try:
                    scene.clearSelection()
                    item_under_cursor.setSelected(True)
                finally:
                    scene.blockSignals(False)

            selected_items = [item for item in scene.selectedItems() if isinstance(item, MindMapNoteView)]

            if not (isinstance(item_under_cursor, MindMapNoteView) and item_under_cursor.isSelected()):
                super().contextMenuEvent(event)
                return

            if selected_items:
                first_note_type = selected_items[0].mindmap_node.anki_note.note_type()
                if all(item.mindmap_node.anki_note.note_type() == first_note_type for item in selected_items):
                    self.fields_menu_requested.emit(selected_items, QCursor.pos())
                    event.accept()
                else:
                    showWarning("Please select notes of the same type.")
        else:
            showWarning("Error getting scene in contextMenuEvent. Pls report to the dev")
