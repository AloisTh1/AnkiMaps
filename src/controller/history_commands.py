import sqlite3
from dataclasses import dataclass

from anki.notes import NoteId

from ..model.connections import CONNECTION_TYPES, MindMapConnection
from ..model.mindmap import MindMap
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
