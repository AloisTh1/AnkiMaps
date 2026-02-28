import typing

from aqt.qt import (
    QBrush,
    QButtonGroup,
    QHBoxLayout,
    QPainter,
    QPalette,
    QPen,
    QPointF,
    QPolygonF,
    QRadioButton,
    QSize,
    Qt,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from ..model.connections import CONNECTION_TYPES


class LinePreviewWidget(QWidget):
    """A custom widget that draws a single line preview, respecting Anki's theme."""

    def __init__(
        self,
        is_dotted: bool,
        is_directed: bool,
        is_bidirectional: bool,
        parent: typing.Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.is_dotted = is_dotted
        self.is_directed = is_directed
        self.is_bidirectional = is_bidirectional
        self.setMinimumSize(50, 20)

    def sizeHint(self) -> QSize:
        return QSize(50, 20)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        y_center = self.rect().height() // 2
        line_start_x, line_end_x = 8, 42

        # Use the widget's own palette, which is correctly set by Qt during paint events
        text_color = self.palette().color(QPalette.ColorRole.WindowText)

        line_pen = QPen(text_color, 2, Qt.PenStyle.SolidLine)
        if self.is_dotted:
            line_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(line_pen)
        painter.drawLine(line_start_x, y_center, line_end_x, y_center)

        arrow_brush = QBrush(text_color)
        arrow_pen = QPen(text_color)
        arrow_size = 6

        if self.is_directed:
            p1 = QPointF(line_end_x, y_center)
            p2 = QPointF(line_end_x - arrow_size, y_center - arrow_size * 0.5)
            p3 = QPointF(line_end_x - arrow_size, y_center + arrow_size * 0.5)
            arrow_head_end = QPolygonF([p1, p2, p3])
            painter.setBrush(arrow_brush)
            painter.setPen(arrow_pen)
            painter.drawPolygon(arrow_head_end)

        if self.is_bidirectional:
            p1 = QPointF(line_start_x, y_center)
            p2 = QPointF(line_start_x + arrow_size, y_center - arrow_size * 0.5)
            p3 = QPointF(line_start_x + arrow_size, y_center + arrow_size * 0.5)
            arrow_head_start = QPolygonF([p1, p2, p3])
            painter.setBrush(arrow_brush)
            painter.setPen(arrow_pen)
            painter.drawPolygon(arrow_head_start)


class LineTypeSelectorWidget(QWidget):
    """
    A widget that provides a visual selection of connection line types.
    """

    type_selection_changed = pyqtSignal(int)

    def __init__(self, parent: typing.Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._main_layout = QVBoxLayout()
        self._main_layout.setContentsMargins(2, 2, 2, 2)
        self._main_layout.setSpacing(4)
        self.setLayout(self._main_layout)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self._create_row(
            "Undirected", CONNECTION_TYPES.FULL_UNDIRECTED, CONNECTION_TYPES.DOTTED_UNDIRECTED, False, False
        )
        radio_directed, _ = self._create_row(
            "Directed", CONNECTION_TYPES.FULL_DIRECTED, CONNECTION_TYPES.DOTTED_DIRECTED, True, False
        )
        self._create_row(
            "Bidirectional",
            CONNECTION_TYPES.FULL_BIDIRECTIONAL,
            CONNECTION_TYPES.DOTTED_BIDIRECTIONAL,
            True,
            True,
        )

        radio_directed.setChecked(True)

        self.button_group.idClicked.connect(self.type_selection_changed.emit)

    def _create_row(
        self,
        base_name: str,
        type_full: CONNECTION_TYPES,
        type_dotted: CONNECTION_TYPES,
        is_directed: bool,
        is_bidirectional: bool,
    ):
        row_layout = QHBoxLayout()

        # Full version
        radio_full = QRadioButton("")
        radio_full.setToolTip(base_name)
        preview_full = LinePreviewWidget(
            is_dotted=False, is_directed=is_directed, is_bidirectional=is_bidirectional
        )
        row_layout.addWidget(radio_full)
        row_layout.addWidget(preview_full)
        self.button_group.addButton(radio_full, type_full.value)

        row_layout.addSpacing(20)

        # Dotted version
        radio_dotted = QRadioButton("")
        radio_dotted.setToolTip(f"Dotted {base_name}")
        preview_dotted = LinePreviewWidget(
            is_dotted=True, is_directed=is_directed, is_bidirectional=is_bidirectional
        )
        row_layout.addWidget(radio_dotted)
        row_layout.addWidget(preview_dotted)
        self.button_group.addButton(radio_dotted, type_dotted.value)

        row_layout.addStretch()
        self._main_layout.addLayout(row_layout)
        return radio_full, radio_dotted
