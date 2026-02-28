import logging
import os
import re
import weakref
from typing import TYPE_CHECKING, Set

from aqt import mw
from aqt.qt import (
    QBrush,
    QByteArray,
    QColor,
    QCursor,
    QEasingCurve,
    QGraphicsBlurEffect,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsOpacityEffect,
    QGraphicsRectItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QObject,
    QPainter,
    QPen,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTextDocument,
    QUrl,
    pyqtSignal,
)

from ...common.constants import ANKIMAPS_CONSTANTS
from ...model.node import MindMapNode
from .states import NoteState

if TYPE_CHECKING:
    from ..edges.edges import StickyLine
logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class NoteSignals(QObject):
    note_double_clicked = pyqtSignal(str)
    note_resized = pyqtSignal(str, float)


class MindMapNoteView(QGraphicsObject):
    """Graphics item that shows an Anki note inside the mind‑map."""

    def __init__(self, mindmap_node: MindMapNode):
        super().__init__()

        self.mindmap_node = mindmap_node
        self.note_id = mindmap_node.note_id
        self.signals = NoteSignals()
        self.state: NoteState = NoteState.NORMAL

        self.sticky_lines: Set[weakref.ReferenceType["StickyLine"]] = set()

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

        self._rect = QRectF()
        self.document = QTextDocument()
        self._resize_handle_size = ANKIMAPS_CONSTANTS.NOTE_RESIZE_HANDLE_SIZE.value
        self._min_width = ANKIMAPS_CONSTANTS.NOTE_MIN_WIDTH.value

        self._blur_effect = QGraphicsBlurEffect()
        self._blur_effect.setBlurRadius(ANKIMAPS_CONSTANTS.DEFAULT_NOTE_BLUR_RADIUS.value)
        self.setGraphicsEffect(self._blur_effect)
        self._blur_effect.setEnabled(False)

        self._mask_item = QGraphicsRectItem(self)
        no_pen = QPen()
        no_pen.setStyle(Qt.PenStyle.NoPen)
        self._mask_item.setPen(no_pen)
        self._mask_item.setVisible(False)

        self._mask_opacity_effect = QGraphicsOpacityEffect(self)
        self._mask_item.setGraphicsEffect(self._mask_opacity_effect)

        self._mask_reveal_anim = QPropertyAnimation(self._mask_opacity_effect, QByteArray(b"opacity"), self)
        self._mask_reveal_anim.setStartValue(1.0)
        self._mask_reveal_anim.setEndValue(0.0)
        self._mask_reveal_anim.setDuration(800)
        self._mask_reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._mask_reveal_anim.finished.connect(lambda: self._mask_item.setVisible(False))

        self._lod_mode_active = False
        self._is_resizing = False

        self.update_size()

    def set_state(self, new_state: NoteState):
        """Sets the note's state and triggers a repaint and effect changes."""
        if self.state == new_state:
            return

        self.state = new_state

        is_blurred = NoteState.REVIEW_BLURRED in self.state
        self._blur_effect.setEnabled(is_blurred)

        is_masked = NoteState.MASKED in self.state
        if is_masked:
            self._mask_opacity_effect.setOpacity(1.0)
            self._mask_item.setVisible(True)
        else:
            if self._mask_reveal_anim.state() != QPropertyAnimation.State.Running:
                self._mask_item.setVisible(False)

        self.update()

    def set_lod_mode(self, active: bool):
        if self._lod_mode_active == active:
            return
        self._lod_mode_active = active
        self.update()

    def rect(self) -> QRectF:
        return self._rect

    def setRect(self, *args):
        """Update the bounding rectangle."""
        self.prepareGeometryChange()
        if len(args) == 1 and isinstance(args[0], QRectF):
            self._rect = args[0]
        else:
            self._rect = QRectF(*args)

    def boundingRect(self) -> QRectF:
        return self._rect

    def fade_out_mask(self):
        """Reveals the answer by fading out the mask item."""
        if self._mask_item.isVisible() and self._mask_reveal_anim.state() != QPropertyAnimation.State.Running:
            self._mask_reveal_anim.start()

    def _get_resize_handle_rect(self) -> QRectF:
        r = self.rect()
        return QRectF(
            r.right() - self._resize_handle_size,
            r.bottom() - self._resize_handle_size,
            self._resize_handle_size,
            self._resize_handle_size,
        )

    def update_size(self):
        self.prepareGeometryChange()
        note, indices, width = (
            self.mindmap_node.anki_note,
            self.mindmap_node.shown_field_indices,
            self.mindmap_node.width,
        )
        inner_padding = 10
        font = self.document.defaultFont()
        font.setPointSizeF(self.mindmap_node.font_size)
        self.document.setDefaultFont(font)
        doc_width = width - (2 * inner_padding)
        self.document.setTextWidth(doc_width)
        note_type = note.note_type() or {}
        self.document.setDefaultStyleSheet(note_type.get("css", ""))
        if mw and mw.col and (media_dir := mw.col.media.dir()):
            base_url = QUrl.fromLocalFile(os.path.join(media_dir, ""))
            self.document.setMetaInformation(QTextDocument.MetaInformation.DocumentUrl, base_url.toString())
        content = [note.fields[i] for i in indices if 0 <= i < len(note.fields)]
        html_content = "<hr>".join(content) if content else "(Empty)"
        clean_html = re.sub(r'(<(table|img)[^>]*?)\s+width="[^"]*"', r"\1", html_content, flags=re.IGNORECASE)
        available_width = max(int(doc_width), 10)
        html_with_tables = re.sub(
            r"<table", f'<table width="{available_width}"', clean_html, flags=re.IGNORECASE
        )
        image_width = max(available_width - 10, 10)
        final_html = re.sub(r"<img", f'<img width="{image_width}"', html_with_tables, flags=re.IGNORECASE)
        self.document.setHtml(final_html)
        doc_height = self.document.size().height()
        self.setRect(0, 0, width, doc_height + (2 * inner_padding))

        content_rect = self._rect.adjusted(inner_padding, inner_padding, -inner_padding, -inner_padding)
        self._mask_item.setRect(content_rect)

        self.update_attached_lines()
        self.update()

    def update_attached_lines(self):
        for line_ref in list(self.sticky_lines):
            line = line_ref()
            if line:
                line.update_position()

    def paint(self, painter: QPainter, option, widget=None):
        if self._lod_mode_active:
            painter.setBrush(QColor(Qt.GlobalColor.darkGray))
            no_pen = QPen()
            no_pen.setStyle(Qt.PenStyle.NoPen)
            painter.setPen(no_pen)
            painter.drawRect(self.boundingRect())
            if NoteState.SEARCH_HIGHLIGHTED in self.state:
                painter.fillRect(self.boundingRect(), QColor(0, 255, 0, 120))
            if self.isSelected():
                painter.setBrush(Qt.GlobalColor.transparent)
                painter.setPen(QPen(QColor(30, 144, 255, 220), 2))
                painter.drawRect(self.boundingRect())
            return

        if NoteState.REVIEW_ACTIVE in self.state:
            base_brush = QBrush(QColor("#E0E8FF"))
            base_pen = QPen(Qt.GlobalColor.blue, 4)
            self.setZValue(1)
        else:
            base_brush = QBrush(Qt.GlobalColor.white)
            base_pen = QPen(Qt.GlobalColor.black, 1)
            self.setZValue(0)

        painter.setBrush(base_brush)
        painter.setPen(base_pen)
        painter.drawRect(self._rect)
        painter.save()
        inner_padding = 10
        painter.translate(self._rect.topLeft() + QPointF(inner_padding, inner_padding))
        self.document.drawContents(painter)
        painter.restore()

        self._mask_item.setBrush(base_brush.color().darker(110))

        if NoteState.SEARCH_HIGHLIGHTED in self.state:
            painter.fillRect(self.boundingRect(), QColor(0, 255, 0, 50))

        if self.isSelected():
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.setPen(QPen(QColor(30, 144, 255, 220), 3))
            painter.drawRect(self.boundingRect())

        handle_rect = self._get_resize_handle_rect()
        handle_pen = QPen(QColor("#888888"), 1.5)
        painter.setPen(handle_pen)
        painter.drawLine(handle_rect.bottomLeft() + QPointF(5, 0), handle_rect.topRight() + QPointF(0, 5))
        painter.drawLine(handle_rect.bottomLeft() + QPointF(10, 0), handle_rect.topRight() + QPointF(0, 10))
        painter.drawLine(handle_rect.bottomLeft() + QPointF(15, 0), handle_rect.topRight() + QPointF(0, 15))

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        if self._get_resize_handle_rect().contains(event.pos()):
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        if not self._is_resizing:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._get_resize_handle_rect().contains(
            event.pos()
        ):
            self._is_resizing = True
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._is_resizing:
            new_width = self.rect().width() + (event.pos().x() - event.lastPos().x())
            if new_width >= self._min_width:
                self.mindmap_node.width = new_width
                self.update_size()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._is_resizing:
            self._is_resizing = False
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            final_width = self.rect().width()
            self.signals.note_resized.emit(str(self.note_id), final_width)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if scene := self.scene():
                view = scene.views()[0] if self.scene() and scene.views() else None
                is_fast_mode = getattr(view, "is_in_fast_render_mode", False) if view else False
                if not is_fast_mode:
                    self.update_attached_lines()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        self.signals.note_double_clicked.emit(str(self.note_id))
        super().mouseDoubleClickEvent(event)
