import logging
import math
import weakref
from typing import TYPE_CHECKING, Optional

from aqt import QPoint
from aqt.qt import (
    QBrush,
    QColor,
    QCursor,
    QGraphicsLineItem,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QLineF,
    QMenu,
    QObject,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPointF,
    QPolygonF,
    QRectF,
    Qt,
    pyqtSignal,
)

from ...common.constants import ANKIMAPS_CONSTANTS
from ...model.connections import CONNECTION_TYPES, MindMapConnection

if TYPE_CHECKING:
    from ..nodes.notes import MindMapNoteView

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class StickyLineSignals(QObject):
    label_edit_requested = pyqtSignal(QGraphicsLineItem)
    label_remove_requested = pyqtSignal(QGraphicsLineItem)
    connection_delete_requested = pyqtSignal(str, str)
    connection_left_clicked = pyqtSignal(object)  # self


class StickyLine(QGraphicsLineItem):
    def __init__(
        self,
        from_node: "MindMapNoteView",
        to_node: "MindMapNoteView",
        connection_type: int = CONNECTION_TYPES.FULL_UNDIRECTED.value,
        color: str = ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value,
        size: int = ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_SIZE.value,
        label: str = "",
        label_size: int = ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_LABEL_FONT_SIZE.value,
    ):
        super().__init__()
        self.signals = StickyLineSignals()

        self._from_node_ref = weakref.ref(from_node)
        self._to_node_ref = weakref.ref(to_node)

        self.connection_type: int = connection_type
        self._arrow_size = 10.0 + (size * 2.5)
        self.setZValue(-1)

        self._lod_mode_active = False

        self.label_item = QGraphicsTextItem(label, self)
        font = self.label_item.font()
        font.setPointSizeF(label_size)
        self.label_item.setFont(font)
        self.label_item.setDefaultTextColor(QColor("black"))
        self.label_item.setZValue(0)

        pen_color = QColor(color)
        if not pen_color.isValid():
            pen_color = QColor(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value)

        line_pen = QPen(pen_color, size)
        if (
            self.connection_type == CONNECTION_TYPES.DOTTED_DIRECTED.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_UNDIRECTED.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_BIDIRECTIONAL.value
        ):
            line_pen.setStyle(Qt.PenStyle.DotLine)

        self._original_pen = line_pen
        self.setPen(self._original_pen)
        self.setAcceptHoverEvents(True)

    def set_lod_mode(self, active: bool):
        if self._lod_mode_active == active:
            return
        self._lod_mode_active = active
        self.update()

    @property
    def from_node(self) -> Optional["MindMapNoteView"]:
        """The 'from' node. Can be None if the node has been deleted."""
        return self._from_node_ref()

    @property
    def to_node(self) -> Optional["MindMapNoteView"]:
        """The 'to' node. Can be None if the node has been deleted."""
        return self._to_node_ref()

    def _get_intersection_with_node_border(self, node: "MindMapNoteView", line: QLineF) -> QPointF:
        if not node:
            return line.p2()
        node_rect = node.sceneBoundingRect()
        p1, p2, p3, p4 = (
            node_rect.topLeft(),
            node_rect.topRight(),
            node_rect.bottomRight(),
            node_rect.bottomLeft(),
        )
        edges = [QLineF(p1, p2), QLineF(p2, p3), QLineF(p3, p4), QLineF(p4, p1)]
        for edge in edges:
            intersection_type, intersection_point = line.intersects(edge)
            if intersection_type == QLineF.IntersectionType.BoundedIntersection:
                if intersection_point is not None:
                    return intersection_point
        return node.sceneBoundingRect().center()

    def update_position(self):
        self.prepareGeometryChange()

        from_node, to_node = self.from_node, self.to_node
        if not from_node or not to_node:
            self.setLine(QLineF())
            return

        p1_center, p2_center = from_node.sceneBoundingRect().center(), to_node.sceneBoundingRect().center()
        if p1_center == p2_center:
            self.setLine(QLineF(p1_center, p2_center))
            return

        line_p1_to_p2, line_p2_to_p1 = QLineF(p1_center, p2_center), QLineF(p2_center, p1_center)
        p1_intersect = self._get_intersection_with_node_border(from_node, line_p2_to_p1)
        p2_intersect = self._get_intersection_with_node_border(to_node, line_p1_to_p2)
        line = QLineF(p1_intersect, p2_intersect)
        self.setLine(line)

        if self.label_item.toPlainText():
            center_point = line.pointAt(0.5)
            label_rect = self.label_item.boundingRect()
            self.label_item.setPos(
                center_point.x() - label_rect.width() / 2, center_point.y() - label_rect.height() / 2
            )
            angle = line.angle()
            if 90 < angle < 270:
                angle += 180
            self.label_item.setRotation(-angle)
        self.update()

    def boundingRect(self) -> QRectF:
        line_rect = QRectF(self.line().p1(), self.line().p2()).normalized()
        extra = (self.pen().width() + self._arrow_size) / 2.0
        return line_rect.adjusted(-extra, -extra, extra, extra)

    def paint(self, painter: QPainter, option, widget=None):
        if self._lod_mode_active:
            return

        if not (self.from_node and self.to_node) or self.line().isNull():
            return

        painter.setPen(self.pen())
        painter.drawLine(self.line())

        draw_arrow_at_p2 = (
            self.connection_type == CONNECTION_TYPES.FULL_DIRECTED.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_DIRECTED.value
            or self.connection_type == CONNECTION_TYPES.FULL_BIDIRECTIONAL.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_BIDIRECTIONAL.value
        )

        draw_arrow_at_p1 = (
            self.connection_type == CONNECTION_TYPES.FULL_BIDIRECTIONAL.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_BIDIRECTIONAL.value
        )

        arrow_head_poly = QPolygonF(
            [
                QPointF(0, 0),
                QPointF(-self._arrow_size, -self._arrow_size / 2),
                QPointF(-self._arrow_size, self._arrow_size / 2),
            ]
        )
        brush = QBrush(self.pen().color())
        pen = QPen()
        pen.setStyle(Qt.PenStyle.NoPen)

        if draw_arrow_at_p2:
            painter.save()
            painter.setBrush(brush)
            painter.setPen(pen)
            painter.translate(self.line().p2())
            angle_rad = math.atan2(self.line().dy(), self.line().dx())
            painter.rotate(math.degrees(angle_rad))
            painter.drawPolygon(arrow_head_poly)
            painter.restore()

        if draw_arrow_at_p1:
            painter.save()
            painter.setBrush(brush)
            painter.setPen(pen)
            painter.translate(self.line().p1())
            angle_rad = math.atan2(-self.line().dy(), -self.line().dx())  # Reversed direction
            painter.rotate(math.degrees(angle_rad))
            painter.drawPolygon(arrow_head_poly)
            painter.restore()

    def shape(self) -> QPainterPath:
        path = QPainterPath(self.line().p1())
        path.lineTo(self.line().p2())
        stroker = QPainterPathStroker()
        stroker.setWidth(10.0)
        return stroker.createStroke(path)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        if self._lod_mode_active:
            return
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        pen = self.pen()
        pen.setColor(QColor("blue"))
        pen.setWidth(self._original_pen.width() + 2)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.setPen(self._original_pen)
        super().hoverLeaveEvent(event)

    def _show_context_menu(self, screen_pos: QPoint):
        try:
            menu = QMenu()

            edit_action = menu.addAction("Add/Edit Label")
            edit_action.triggered.connect(lambda: self.signals.label_edit_requested.emit(self))

            if self.label_item.toPlainText():
                remove_action = menu.addAction("Remove Label")
                remove_action.triggered.connect(lambda: self.signals.label_remove_requested.emit(self))

            menu.addSeparator()

            delete_action = menu.addAction("Delete Connection")
            from_node = self.from_node
            to_node = self.to_node

            if from_node and to_node:
                delete_action.triggered.connect(
                    lambda: self.signals.connection_delete_requested.emit(
                        str(from_node.note_id), str(to_node.note_id)
                    )
                )
            else:
                delete_action.setEnabled(False)

            menu.exec(screen_pos)
        except Exception as e:
            import logging

            logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)
            logger.exception(f"Error showing connection context menu: {e}")

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):
        self._show_context_menu(event.screenPos())
        event.accept()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.signals.connection_left_clicked.emit(self)
            event.accept()
        else:
            super().mousePressEvent(event)

    def update_style(self, conn_data: MindMapConnection):
        """Updates the line's visual properties from a connection data object."""
        self.connection_type = conn_data.connection_type.value
        self._arrow_size = 10.0 + (conn_data.size * 2.5)

        self.label_item.setPlainText(conn_data.label)
        font = self.label_item.font()
        font.setPointSizeF(conn_data.label_size)
        self.label_item.setFont(font)

        pen_color = QColor(conn_data.color)
        if not pen_color.isValid():
            pen_color = QColor(ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value)
        line_pen = QPen(pen_color, conn_data.size)
        if (
            self.connection_type == CONNECTION_TYPES.DOTTED_DIRECTED.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_UNDIRECTED.value
            or self.connection_type == CONNECTION_TYPES.DOTTED_BIDIRECTIONAL.value
        ):
            line_pen.setStyle(Qt.PenStyle.DotLine)
        else:
            line_pen.setStyle(Qt.PenStyle.SolidLine)

        self._original_pen = line_pen
        self.setPen(self._original_pen)

        self.update_position()
