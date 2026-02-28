from typing import List, Optional, Tuple

from anki.notes import NoteId
from aqt.qt import QRectF


class Quadtree:
    """
    A simple Quadtree implementation for fast spatial querying.
    """

    def __init__(self, boundary: QRectF, capacity: int = 4):
        self.boundary = boundary
        self.capacity = capacity
        self.points: List[Tuple[NoteId, QRectF]] = []
        self.divided = False
        self.northwest: Optional["Quadtree"] = None
        self.northeast: Optional["Quadtree"] = None
        self.southwest: Optional["Quadtree"] = None
        self.southeast: Optional["Quadtree"] = None

    def subdivide(self):
        x = self.boundary.x()
        y = self.boundary.y()
        w = self.boundary.width() / 2
        h = self.boundary.height() / 2

        ne = QRectF(x + w, y, w, h)
        nw = QRectF(x, y, w, h)
        se = QRectF(x + w, y + h, w, h)
        sw = QRectF(x, y + h, w, h)

        self.northeast = Quadtree(ne, self.capacity)
        self.northwest = Quadtree(nw, self.capacity)
        self.southeast = Quadtree(se, self.capacity)
        self.southwest = Quadtree(sw, self.capacity)
        self.divided = True

    def insert(self, point_data: Tuple[NoteId, QRectF]) -> bool:
        """
        Inserts a data point (with its bounding rectangle) into the quadtree.
        This implementation is type-safe and correctly handles rectangles.
        """
        _, rect = point_data

        if not self.boundary.intersects(rect):
            return False

        if self.divided:
            if self.northwest and self.northwest.insert(point_data):
                return True
            if self.northeast and self.northeast.insert(point_data):
                return True
            if self.southwest and self.southwest.insert(point_data):
                return True
            if self.southeast and self.southeast.insert(point_data):
                return True
            self.points.append(point_data)
            return True

        self.points.append(point_data)

        if len(self.points) > self.capacity:
            self.subdivide()

            remaining_points: List[Tuple[NoteId, QRectF]] = []
            for p in self.points:
                pushed_down = False
                if self.northwest and self.northwest.insert(p):
                    pushed_down = True
                elif self.northeast and self.northeast.insert(p):
                    pushed_down = True
                elif self.southwest and self.southwest.insert(p):
                    pushed_down = True
                elif self.southeast and self.southeast.insert(p):
                    pushed_down = True

                if not pushed_down:
                    remaining_points.append(p)

            self.points = remaining_points

        return True

    def query(self, range_rect: QRectF) -> list:
        found = []
        if not self.boundary.intersects(range_rect):
            return found

        for note_id, rect in self.points:
            if range_rect.intersects(rect):
                found.append(note_id)

        if self.divided:
            if self.northwest:
                found.extend(self.northwest.query(range_rect))
            if self.northeast:
                found.extend(self.northeast.query(range_rect))
            if self.southwest:
                found.extend(self.southwest.query(range_rect))
            if self.southeast:
                found.extend(self.southeast.query(range_rect))

        return found

    def clear(self):
        """Clears all points and subdivisions from the quadtree."""
        self.points = []
        if self.divided:
            if self.northwest:
                self.northwest.clear()
            if self.northeast:
                self.northeast.clear()
            if self.southwest:
                self.southwest.clear()
            if self.southeast:
                self.southeast.clear()

        self.divided = False
        self.northwest = None
        self.northeast = None
        self.southwest = None
        self.southeast = None
