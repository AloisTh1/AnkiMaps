import os

from aqt.qt import QGraphicsItem, QGraphicsPixmapItem, QPixmap, Qt


class CenterLogoItem(QGraphicsPixmapItem):
    def __init__(self, width=1000, opacity=0.33):
        logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")

        pixmap = QPixmap()
        if os.path.exists(logo_path):
            pixmap.load(logo_path)
            pixmap = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = QPixmap(width, width)
            pixmap.fill(Qt.GlobalColor.transparent)

        super().__init__(pixmap)

        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)

        self.setOpacity(opacity)

        self.setZValue(-5)  # Draw it behind the nodes
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
