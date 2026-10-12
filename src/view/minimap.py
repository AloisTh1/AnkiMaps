from typing import TYPE_CHECKING

from aqt.qt import QColor, QEvent, QPainter, QPen, QPointF, QRectF, Qt, QTimer, QTransform, QWidget

if TYPE_CHECKING:
    from .mindmap_view import MindMapView


class Minimap(QWidget):
    """Lightweight overview, including cards culled from the main viewport."""

    def __init__(self, view: "MindMapView", theme_mode: str = "Light"):
        # QGraphicsView scrolls viewport children with the canvas. Parent the
        # overlay to the fixed frame so navigation cannot move it off-screen.
        super().__init__(view)
        self._view = view
        self._dark = theme_mode.lower() == "dark"
        self._scene = None
        self._transform = QTransform()
        self._dragging = False
        self._has_nodes = False
        self.setObjectName("minimap")
        self.setAccessibleName("Minimap")
        self.setToolTip("Click or drag to navigate the map")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(33)
        self._refresh_timer.timeout.connect(self.update)
        view.viewport().installEventFilter(self)
        view.horizontalScrollBar().valueChanged.connect(self._schedule_refresh)
        view.verticalScrollBar().valueChanged.connect(self._schedule_refresh)
        view.scale_changed.connect(self._schedule_refresh)
        view.scene_loaded.connect(self._connect_scene)
        self._connect_scene()
        self._position_overlay()

    def _connect_scene(self):
        # Full map reloads replace and delete the old scene.
        scene = self._view.scene()
        if scene is not self._scene:
            self._scene = scene
            scene.changed.connect(self._schedule_refresh)
            scene.sceneRectChanged.connect(self._schedule_refresh)
        self._schedule_refresh()

    def _schedule_refresh(self, *_args):
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _position_overlay(self):
        viewport = self._view.viewport()
        self.resize(min(220, max(1, viewport.width() - 24)), min(150, max(1, viewport.height() - 24)))
        self.move(
            viewport.x() + max(0, viewport.width() - self.width() - 12),
            viewport.y() + max(0, viewport.height() - self.height() - 12),
        )
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move) and watched is self._view.viewport():
            self._position_overlay()
            self._schedule_refresh()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._position_overlay()
        self.update()

    def hideEvent(self, event):
        self._dragging = False
        self._refresh_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#232629" if self._dark else "#ffffff"))
        painter.setPen(QPen(QColor("#5b6470" if self._dark else "#aeb6bf"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        # Never render the full scene: hidden cards must still appear here, and
        # rendering card text/MathJax again would be expensive.
        nodes = {nid: item.sceneBoundingRect() for nid, item in self._view._all_view_items.items()}
        self._has_nodes = bool(nodes)
        if not nodes:
            painter.setPen(QColor("#aeb6bf" if self._dark else "#6b7280"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Empty map")
            return

        viewport_rect = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
        content = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        if content.isEmpty():
            return
        if not self._dragging:
            bounds = QRectF(viewport_rect)
            for rect in nodes.values():
                bounds = bounds.united(rect)
            bounds.adjust(-40, -40, 40, 40)
            scale = min(content.width() / bounds.width(), content.height() / bounds.height())
            self._transform = QTransform()
            self._transform.translate(content.center().x(), content.center().y())
            self._transform.scale(scale, scale)
            self._transform.translate(-bounds.center().x(), -bounds.center().y())

        painter.setClipRect(content)
        painter.setPen(QPen(QColor("#7f8790" if self._dark else "#aeb6bf"), 1))
        for key in self._view._all_lines:
            endpoints = list(key)
            if len(endpoints) == 2 and all(nid in nodes for nid in endpoints):
                painter.drawLine(
                    self._transform.map(nodes[endpoints[0]].center()),
                    self._transform.map(nodes[endpoints[1]].center()),
                )

        for nid, rect in nodes.items():
            selected = self._view._all_view_items[nid].isSelected()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#4a90e2" if selected else "#8ba8c7"))
            target = self._transform.mapRect(rect)
            # Keep tiny cards visible on very large maps.
            target.setSize(target.size().expandedTo(QRectF(0, 0, 2, 2).size()))
            painter.drawRect(target)

        painter.setPen(QPen(QColor("#4a90e2"), 2))
        painter.setBrush(QColor(74, 144, 226, 35))
        painter.drawRect(self._transform.mapRect(viewport_rect))

    def _navigate(self, position: QPointF):
        inverse, invertible = self._transform.inverted()
        if self._has_nodes and invertible:
            self._view.centerOn(inverse.map(position))
            self._schedule_refresh()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Freeze the coordinate mapping until release so dragging remains
            # stable even when the viewport moves beyond the map's bounds.
            self._dragging = True
            self._navigate(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._navigate(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._navigate(event.position())
            self._dragging = False
            self._schedule_refresh()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
