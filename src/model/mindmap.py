import logging
from collections import defaultdict
from typing import Dict, List, Optional

from anki.notes import NoteId
from aqt.qt import QObject, QRectF, pyqtSignal

from ..common.constants import ANKIMAPS_CONSTANTS
from .connections import MindMapConnection
from .node import MindMapNode

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class MindMap(QObject):
    """
    Represents the complete state of a single mind map.
    This is an observable object that emits signals when its state changes.
    """

    model_loaded = pyqtSignal()
    # Batch signals
    nodes_added = pyqtSignal(list)
    nodes_removed = pyqtSignal(list)
    connections_removed = pyqtSignal(list)  # Carries a list of frozensets

    # Single-item signals
    connection_added = pyqtSignal(MindMapConnection)
    connection_removed = pyqtSignal(frozenset)
    connection_updated = pyqtSignal(MindMapConnection)

    nodes_moved = pyqtSignal(list)
    node_properties_changed = pyqtSignal(list)

    editor_focus_changed = pyqtSignal(object, bool)  # nid, answer_visible

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.nodes: Dict[NoteId, MindMapNode] = {}

        # Efficient graph representation
        self.connections: Dict[int, MindMapConnection] = {}  # connection_id -> object
        self.out_edges: Dict[NoteId, set[int]] = defaultdict(set)  # from_note_id -> {connection_id, ...}
        self.in_edges: Dict[NoteId, set[int]] = defaultdict(set)  # to_note_id -> {connection_id, ...}
        self.edge_key_to_id: Dict[frozenset[NoteId], int] = {}  # For fast "does edge exist" checks

        self.active_editor_note_id: Optional[NoteId] = None
        self.editor_answer_visible: bool = False

    def get_connection(self, id1: NoteId, id2: NoteId) -> Optional[MindMapConnection]:
        key = frozenset([id1, id2])
        conn_id = self.edge_key_to_id.get(key)
        if conn_id is not None:
            return self.connections.get(conn_id)
        return None

    def add_node(self, node: MindMapNode):
        if node.note_id not in self.nodes:
            self.nodes[node.note_id] = node
            self.nodes_added.emit([node.note_id])

    def add_nodes_batch(self, nodes: list[MindMapNode]):
        new_node_ids = []
        for node in nodes:
            if node.note_id not in self.nodes:
                self.nodes[node.note_id] = node
                new_node_ids.append(node.note_id)
        if new_node_ids:
            self.nodes_added.emit(new_node_ids)

    def remove_node(self, node_id: NoteId):
        """Convenience method to remove a single node. Calls the batch version."""
        self.remove_nodes_batch([node_id])

    def remove_nodes_batch(self, node_ids: List[NoteId]):
        """
        Efficiently removes a batch of nodes and their connections,
        emitting signals in the correct order for the view to process.
        """
        removed_node_ids = []
        removed_connection_keys = []

        for node_id in node_ids:
            if node_id not in self.nodes:
                continue

            conn_ids_to_remove = self.out_edges.get(node_id, set()).union(self.in_edges.get(node_id, set()))

            for conn_id in conn_ids_to_remove:
                conn = self.connections.pop(conn_id, None)
                if not conn:
                    continue

                if conn.from_note_id != node_id:
                    self.out_edges[conn.from_note_id].discard(conn_id)
                if conn.to_note_id != node_id:
                    self.in_edges[conn.to_note_id].discard(conn_id)

                key = frozenset([conn.from_note_id, conn.to_note_id])
                if self.edge_key_to_id.pop(key, None):
                    removed_connection_keys.append(key)

            del self.nodes[node_id]
            self.out_edges.pop(node_id, None)
            self.in_edges.pop(node_id, None)
            removed_node_ids.append(node_id)

        if removed_connection_keys:
            self.connections_removed.emit(removed_connection_keys)
        if removed_node_ids:
            self.nodes_removed.emit(removed_node_ids)

    def add_connection(self, connection: MindMapConnection):
        key = frozenset([connection.from_note_id, connection.to_note_id])
        if key in self.edge_key_to_id:
            return

        conn_id = connection.connection_id
        self.connections[conn_id] = connection
        self.out_edges[connection.from_note_id].add(conn_id)
        self.in_edges[connection.to_note_id].add(conn_id)
        self.edge_key_to_id[key] = conn_id

        self.connection_added.emit(connection)

    def remove_connection(self, id1: NoteId, id2: NoteId) -> Optional[MindMapConnection]:
        key = frozenset([id1, id2])
        conn_id = self.edge_key_to_id.pop(key, None)
        if not conn_id:
            return None

        removed_conn = self.connections.pop(conn_id, None)
        if removed_conn:
            self.out_edges[removed_conn.from_note_id].discard(conn_id)
            if not self.out_edges[removed_conn.from_note_id]:
                del self.out_edges[removed_conn.from_note_id]

            self.in_edges[removed_conn.to_note_id].discard(conn_id)
            if not self.in_edges[removed_conn.to_note_id]:
                del self.in_edges[removed_conn.to_note_id]

            self.connection_removed.emit(key)

        return removed_conn

    def update_node_positions(self, position_data: list[dict]):
        updated_ids = []
        for p in position_data:
            node_id = NoteId(int(p["id"]))
            if node := self.nodes.get(node_id):
                node.x = p["x"]
                node.y = p["y"]
                updated_ids.append(node_id)
        if updated_ids:
            self.nodes_moved.emit(updated_ids)

    def update_node_property(self, node_id: NoteId, prop_name: str, value):
        if node := self.nodes.get(node_id):
            if hasattr(node, prop_name):
                setattr(node, prop_name, value)
                self.node_properties_changed.emit([node_id])

    def get_bounds(self) -> QRectF:
        if not self.nodes:
            return QRectF(-10000, -10000, 20000, 20000)
        min_x = min((n.x for n in self.nodes.values()), default=0)
        min_y = min((n.y for n in self.nodes.values()), default=0)
        max_x = max((n.x + n.width for n in self.nodes.values()), default=0)
        max_y = max((n.y + 1000 for n in self.nodes.values()), default=0)  # Estimate height
        width = max_x - min_x
        height = max_y - min_y
        return QRectF(min_x - 1000, min_y - 1000, width + 2000, height + 2000)
