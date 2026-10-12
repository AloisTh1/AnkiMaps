"""Exercise minimap rendering/navigation with real Qt, without an Anki collection."""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402


def _load_minimap():
    # Anki's native backend is unnecessary for this standalone Qt widget.
    qt = types.ModuleType("aqt.qt")
    for module in (QtCore, QtGui, QtWidgets):
        qt.__dict__.update({name: getattr(module, name) for name in dir(module) if not name.startswith("_")})
    spec = importlib.util.spec_from_file_location(
        "minimap_under_test", Path(__file__).resolve().parents[1] / "src/view/minimap.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"aqt.qt": qt}):
        spec.loader.exec_module(module)
    return module.Minimap


Minimap = _load_minimap()


class MapView(QtWidgets.QGraphicsView):
    scale_changed = QtCore.pyqtSignal(float)
    scene_loaded = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setSceneRect(-2000, -1500, 4000, 3000)
        self._all_view_items = {}
        self._all_lines = {}

    def add_node(self, nid, x, y):
        item = self.scene().addRect(x, y, 200, 100)
        item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self._all_view_items[nid] = item
        return item


class MinimapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.view = MapView()
        self.view.resize(900, 600)
        self.view.add_node(1, -1000, -500)
        self.view.add_node(2, 1000, 500).hide()
        self.view._all_lines[frozenset((1, 2))] = object()
        self.minimap = Minimap(self.view)
        self.view.show()
        self.view.centerOn(0, 0)
        self.refresh()

    def refresh(self):
        self.app.processEvents()
        QTest.qWait(80)
        self.app.processEvents()
        # Offscreen Qt may defer exposing a child until it is explicitly rendered.
        self.minimap.grab()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def test_hidden_cards_are_drawn_and_click_navigates_without_zooming(self):
        target = self.view._all_view_items[2].sceneBoundingRect().center()
        point = self.minimap._transform.map(target).toPoint()
        pixel = self.minimap.grab().toImage().pixelColor(point)
        self.assertEqual(pixel.name(), "#8ba8c7")
        zoom = self.view.transform().m11()
        QTest.mouseClick(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=point)
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.assertLess((center - target).manhattanLength(), 30)
        self.assertEqual(self.view.transform().m11(), zoom)
        self.assertFalse(self.view._all_view_items[2].isVisible())

    def test_drag_mapping_stays_stable_while_panning(self):
        transform = QtGui.QTransform(self.minimap._transform)
        QTest.mousePress(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(100, 70))
        QTest.mouseMove(self.minimap, QtCore.QPoint(195, 115))
        self.refresh()
        self.assertEqual(self.minimap._transform, transform)
        QTest.mouseRelease(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(195, 115))
        self.assertFalse(self.minimap._dragging)

    def test_overlay_stays_anchored_during_navigation(self):
        def screen_position():
            return self.minimap.mapTo(self.view, QtCore.QPoint())

        initial_position = screen_position()
        for offset in (20, 60, -40, 0):
            self.view.centerOn(offset, offset)
            self.refresh()
            self.assertEqual(screen_position(), initial_position)
            self.assertTrue(self.minimap.visibleRegion().contains(self.minimap.rect().center()))

        point = self.minimap._transform.map(
            self.view._all_view_items[2].sceneBoundingRect().center()
        ).toPoint()
        QTest.mouseClick(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.refresh()
        self.assertEqual(screen_position(), initial_position)
        self.assertTrue(self.minimap.visibleRegion().contains(self.minimap.rect().center()))

        QTest.mousePress(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(110, 75))
        QTest.mouseMove(self.minimap, QtCore.QPoint(130, 90))
        self.refresh()
        self.assertEqual(screen_position(), initial_position)
        QTest.mouseRelease(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(130, 90))
        self.view.scale(1.2, 1.2)
        self.view.scale_changed.emit(1.2)
        self.refresh()
        self.assertEqual(screen_position(), initial_position)

    def test_pan_zoom_resize_and_hide(self):
        old_transform = QtGui.QTransform(self.minimap._transform)
        self.view.scale(0.2, 0.2)
        self.view.scale_changed.emit(0.2)
        self.view.centerOn(1200, 800)
        self.refresh()
        self.assertNotEqual(self.minimap._transform, old_transform)
        self.view.resize(600, 400)
        self.app.processEvents()
        self.assertEqual(
            self.minimap.x() + self.minimap.width(), self.view.viewport().geometry().right() + 1 - 12
        )
        self.assertEqual(
            self.minimap.y() + self.minimap.height(), self.view.viewport().geometry().bottom() + 1 - 12
        )
        self.minimap.hide()
        self.view.horizontalScrollBar().setValue(0)
        self.assertFalse(self.minimap._refresh_timer.isActive())
        self.minimap.show()
        self.assertTrue(self.minimap.isVisible())

    def test_reload_empty_map_then_add_move_remove_card(self):
        old_scene = self.view.scene()
        self.view.setScene(QtWidgets.QGraphicsScene(self.view))
        self.view._all_view_items.clear()
        self.view._all_lines.clear()
        self.view.scene_loaded.emit()
        old_scene.deleteLater()
        self.refresh()
        self.assertFalse(self.minimap._has_nodes)
        before = self.view.mapToScene(self.view.viewport().rect().center())
        QTest.mouseClick(self.minimap, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(50, 50))
        self.assertEqual(self.view.mapToScene(self.view.viewport().rect().center()), before)
        item = self.view.add_node(3, 0, 0)
        self.refresh()
        self.assertTrue(self.minimap._has_nodes)
        transform = QtGui.QTransform(self.minimap._transform)
        item.setPos(5000, 3000)
        self.refresh()
        self.assertNotEqual(self.minimap._transform, transform)
        self.view._all_view_items.clear()
        self.view.scene().removeItem(item)
        self.refresh()
        self.assertFalse(self.minimap._has_nodes)


if __name__ == "__main__":
    unittest.main()
