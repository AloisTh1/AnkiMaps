import sqlite3
from dataclasses import dataclass

from anki.notes import Note, NoteId

from ..model.connections import CONNECTION_TYPES, MindMapConnection
from ..model.mindmap import MindMap
from ..model.node import MindMapNode
from ..repository.db.sql_repository import SqlLiteRepository
from .history_manager import HistoryCommand


@dataclass(frozen=True)
class _ConnectionSnapshot:
    from_note_id: NoteId
    to_note_id: NoteId
    connection_type: int
    color: str
    size: int
    label: str
    label_size: int


@dataclass(frozen=True)
class _NodeSnapshot:
    note_id: NoteId
    anki_note: Note
    x: float
    y: float
    width: float
    shown_field_indices: tuple[int, ...]
    font_size: float

    @classmethod
    def from_node(cls, node: MindMapNode) -> "_NodeSnapshot":
        return cls(
            note_id=node.note_id,
            anki_note=node.anki_note,
            x=node.x,
            y=node.y,
            width=node.width,
            shown_field_indices=tuple(node.shown_field_indices),
            font_size=node.font_size,
        )

    def to_node(self) -> MindMapNode:
        return MindMapNode(
            note_id=self.note_id,
            anki_note=self.anki_note,
            x=self.x,
            y=self.y,
            width=self.width,
            shown_field_indices=list(self.shown_field_indices),
            font_size=self.font_size,
        )


def _snapshot_from_connection(connection: MindMapConnection) -> _ConnectionSnapshot:
    return _ConnectionSnapshot(
        from_note_id=connection.from_note_id,
        to_note_id=connection.to_note_id,
        connection_type=connection.connection_type.value,
        color=connection.color,
        size=connection.size,
        label=connection.label,
        label_size=connection.label_size,
    )


def _connection_from_snapshot(snapshot: _ConnectionSnapshot) -> MindMapConnection:
    return MindMapConnection(
        connection_id=-1,
        from_note_id=snapshot.from_note_id,
        to_note_id=snapshot.to_note_id,
        connection_type=CONNECTION_TYPES(snapshot.connection_type),
        color=snapshot.color,
        size=snapshot.size,
        label=snapshot.label,
        label_size=snapshot.label_size,
    )


class DeleteNodesCommand(HistoryCommand):
    def __init__(
        self,
        sql_repository: SqlLiteRepository,
        db_connection: sqlite3.Connection,
        model: MindMap,
        note_ids: list[NoteId],
    ):
        self.sql_repository = sql_repository
        self.db_connection = db_connection
        self.model = model

        seen: set[NoteId] = set()
        self.note_ids: list[NoteId] = []
        for note_id in note_ids:
            if note_id in seen:
                continue
            seen.add(note_id)
            if note_id in model.nodes:
                self.note_ids.append(note_id)

        self.node_snapshots: list[_NodeSnapshot] = []
        self.connection_snapshots: list[_ConnectionSnapshot] = []

    def _refresh_snapshots(self) -> None:
        self.node_snapshots = [
            _NodeSnapshot.from_node(self.model.nodes[note_id]) for note_id in self.note_ids
        ]

        selected_ids = {snapshot.note_id for snapshot in self.node_snapshots}
        self.connection_snapshots = [
            _snapshot_from_connection(connection)
            for connection in self.model.connections.values()
            if connection.from_note_id in selected_ids or connection.to_note_id in selected_ids
        ]

    def execute(self) -> bool:
        if not self.note_ids or any(note_id not in self.model.nodes for note_id in self.note_ids):
            return False

        # Redo may follow edits that are not themselves history commands. Capture
        # the current state each time so a later undo never resurrects stale data.
        self._refresh_snapshots()
        self.sql_repository.delete_nodes(self.db_connection, self.note_ids)
        self.model.remove_nodes_batch(self.note_ids)
        return True

    def undo(self) -> None:
        nodes = [snapshot.to_node() for snapshot in self.node_snapshots]
        connections = [_connection_from_snapshot(snapshot) for snapshot in self.connection_snapshots]
        connection_ids = self.sql_repository.restore_deleted_subgraph(
            self.db_connection,
            nodes,
            connections,
        )
        if len(connection_ids) != len(connections):
            raise RuntimeError("Database did not return an ID for every restored connection.")

        for connection, connection_id in zip(connections, connection_ids):
            connection.connection_id = connection_id

        self.model.add_nodes_batch(nodes)
        for connection in connections:
            self.model.add_connection(connection)


class MoveNodesCommand(HistoryCommand):
    def __init__(
        self,
        sql_repository: SqlLiteRepository,
        db_connection: sqlite3.Connection,
        model: MindMap,
        previous_positions: list[dict],
        new_positions: list[dict],
    ):
        self.sql_repository = sql_repository
        self.db_connection = db_connection
        self.model = model
        self.previous_positions = previous_positions
        self.new_positions = new_positions

    def _apply_positions(self, positions: list[dict]) -> None:
        self.sql_repository.update_note_positions(self.db_connection, positions)
        self.model.update_node_positions(positions)

    def execute(self) -> bool:
        if not self.new_positions:
            return False
        self._apply_positions(self.new_positions)
        return True

    def undo(self) -> None:
        self._apply_positions(self.previous_positions)


class LinkConnectionCommand(HistoryCommand):
    def __init__(
        self,
        sql_repository: SqlLiteRepository,
        db_connection: sqlite3.Connection,
        model: MindMap,
        snapshot: _ConnectionSnapshot,
    ):
        self.sql_repository = sql_repository
        self.db_connection = db_connection
        self.model = model
        self.snapshot = snapshot

    def execute(self) -> bool:
        if self.model.get_connection(self.snapshot.from_note_id, self.snapshot.to_note_id):
            return False

        connection = MindMapConnection(
            connection_id=-1,
            from_note_id=self.snapshot.from_note_id,
            to_note_id=self.snapshot.to_note_id,
            connection_type=CONNECTION_TYPES(self.snapshot.connection_type),
            color=self.snapshot.color,
            size=self.snapshot.size,
            label=self.snapshot.label,
            label_size=self.snapshot.label_size,
        )
        new_id = self.sql_repository.add_connection(self.db_connection, connection)
        connection.connection_id = new_id
        self.model.add_connection(connection)
        return True

    def undo(self) -> None:
        self.sql_repository.delete_connection(
            self.db_connection,
            self.snapshot.from_note_id,
            self.snapshot.to_note_id,
        )
        self.model.remove_connection(self.snapshot.from_note_id, self.snapshot.to_note_id)


class UnlinkConnectionCommand(HistoryCommand):
    def __init__(
        self,
        sql_repository: SqlLiteRepository,
        db_connection: sqlite3.Connection,
        model: MindMap,
        snapshot: _ConnectionSnapshot,
    ):
        self.sql_repository = sql_repository
        self.db_connection = db_connection
        self.model = model
        self.snapshot = snapshot

    def execute(self) -> bool:
        if not self.model.get_connection(self.snapshot.from_note_id, self.snapshot.to_note_id):
            return False

        self.sql_repository.delete_connection(
            self.db_connection,
            self.snapshot.from_note_id,
            self.snapshot.to_note_id,
        )
        self.model.remove_connection(self.snapshot.from_note_id, self.snapshot.to_note_id)
        return True

    def undo(self) -> None:
        connection = MindMapConnection(
            connection_id=-1,
            from_note_id=self.snapshot.from_note_id,
            to_note_id=self.snapshot.to_note_id,
            connection_type=CONNECTION_TYPES(self.snapshot.connection_type),
            color=self.snapshot.color,
            size=self.snapshot.size,
            label=self.snapshot.label,
            label_size=self.snapshot.label_size,
        )
        new_id = self.sql_repository.add_connection(self.db_connection, connection)
        connection.connection_id = new_id
        self.model.add_connection(connection)


class UpdateConnectionColorCommand(HistoryCommand):
    def __init__(
        self,
        sql_repository: SqlLiteRepository,
        db_connection: sqlite3.Connection,
        model: MindMap,
        id1: NoteId,
        id2: NoteId,
        old_color: str,
        new_color: str,
    ):
        self.sql_repository = sql_repository
        self.db_connection = db_connection
        self.model = model
        self.id1 = id1
        self.id2 = id2
        self.old_color = old_color
        self.new_color = new_color

    def _apply_color(self, color: str) -> None:
        self.sql_repository.update_connection_property(self.db_connection, self.id1, self.id2, "color", color)
        if connection := self.model.get_connection(self.id1, self.id2):
            connection.color = color
            self.model.connection_updated.emit(connection)

    def execute(self) -> bool:
        if self.old_color == self.new_color:
            return False
        self._apply_color(self.new_color)
        return True

    def undo(self) -> None:
        self._apply_color(self.old_color)


def build_link_snapshot(
    from_note_id: NoteId,
    to_note_id: NoteId,
    connection_type: int,
    color: str,
    size: int,
    label: str,
    label_size: int,
) -> _ConnectionSnapshot:
    return _ConnectionSnapshot(
        from_note_id=from_note_id,
        to_note_id=to_note_id,
        connection_type=connection_type,
        color=color,
        size=size,
        label=label,
        label_size=label_size,
    )


def build_snapshot_from_existing(connection: MindMapConnection) -> _ConnectionSnapshot:
    return _snapshot_from_connection(connection)
