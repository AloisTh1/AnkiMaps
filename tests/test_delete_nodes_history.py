import importlib.util
import sqlite3
import sys
import types
import unittest
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from unittest.mock import patch

from src.controller.history_manager import HistoryManager


class _ConnectionTypes(Enum):
    FULL_DIRECTED = 0
    FULL_UNDIRECTED = 1
    DOTTED_DIRECTED = 2
    DOTTED_UNDIRECTED = 3
    FULL_BIDIRECTIONAL = 4
    DOTTED_BIDIRECTIONAL = 5


class _Tables(Enum):
    NOTES_TABLE = "mindmap_notes"
    CONNECTIONS_TABLE = "connections"


def _create_sql_tables() -> str:
    return """
        CREATE TABLE mindmap_notes (
            noteId INTEGER PRIMARY KEY,
            fieldsToShow TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            width REAL NOT NULL,
            fontSize REAL NOT NULL
        );
        CREATE TABLE connections (
            connectionId INTEGER PRIMARY KEY AUTOINCREMENT,
            fromNoteId INTEGER NOT NULL REFERENCES mindmap_notes(noteId) ON DELETE CASCADE,
            toNoteId INTEGER NOT NULL REFERENCES mindmap_notes(noteId) ON DELETE CASCADE,
            connectionType INT NOT NULL,
            color TEXT NOT NULL,
            size INTEGER NOT NULL,
            label TEXT NOT NULL,
            labelSize INT NOT NULL,
            UNIQUE(fromNoteId, toNoteId)
        );
    """


@dataclass
class _Node:
    note_id: int
    anki_note: object
    x: float
    y: float
    width: float
    shown_field_indices: list[int]
    font_size: float


@dataclass
class _Connection:
    connection_id: int
    from_note_id: int
    to_note_id: int
    connection_type: _ConnectionTypes
    color: str
    size: int
    label: str
    label_size: int


class _Model:
    def __init__(self, nodes: list[_Node], connections: list[_Connection]):
        self.nodes = {node.note_id: node for node in nodes}
        self.connections = {connection.connection_id: connection for connection in connections}
        self.remove_calls: list[list[int]] = []
        self.add_node_calls: list[list[_Node]] = []
        self.add_connection_calls: list[_Connection] = []
        self._reindex()

    def _reindex(self) -> None:
        self.out_edges = defaultdict(set)
        self.in_edges = defaultdict(set)
        self.edge_key_to_id = {}
        for connection_id, connection in self.connections.items():
            self.out_edges[connection.from_note_id].add(connection_id)
            self.in_edges[connection.to_note_id].add(connection_id)
            self.edge_key_to_id[frozenset((connection.from_note_id, connection.to_note_id))] = connection_id

    def get_connection(self, id1: int, id2: int):
        connection_id = self.edge_key_to_id.get(frozenset((id1, id2)))
        return self.connections.get(connection_id)

    def remove_nodes_batch(self, node_ids: list[int]) -> None:
        self.remove_calls.append(list(node_ids))
        deleted = set(node_ids)
        self.nodes = {note_id: node for note_id, node in self.nodes.items() if note_id not in deleted}
        self.connections = {
            connection_id: connection
            for connection_id, connection in self.connections.items()
            if connection.from_note_id not in deleted and connection.to_note_id not in deleted
        }
        self._reindex()

    def add_nodes_batch(self, nodes: list[_Node]) -> None:
        self.add_node_calls.append(list(nodes))
        for node in nodes:
            self.nodes.setdefault(node.note_id, node)

    def add_connection(self, connection: _Connection) -> None:
        self.add_connection_calls.append(connection)
        key = frozenset((connection.from_note_id, connection.to_note_id))
        if key not in self.edge_key_to_id:
            self.connections[connection.connection_id] = connection
        self._reindex()


class _Repository:
    def __init__(self):
        self.delete_calls: list[list[int]] = []
        self.restore_calls: list[tuple[list, list]] = []
        self.fail_delete = False
        self.fail_restore = False
        self._next_connection_id = 100

    def delete_nodes(self, _db_connection, node_ids: list[int]) -> None:
        if self.fail_delete:
            raise sqlite3.OperationalError("delete failed")
        self.delete_calls.append(list(node_ids))

    def restore_deleted_subgraph(self, _db_connection, nodes: list, connections: list):
        if self.fail_restore:
            raise sqlite3.OperationalError("restore failed")
        self.restore_calls.append((list(nodes), list(connections)))

        restored = []
        for _connection in connections:
            restored_connection_id = self._next_connection_id
            self._next_connection_id += 1
            restored.append(restored_connection_id)
        return restored


def _load_history_commands():
    anki = types.ModuleType("anki")
    anki_notes = types.ModuleType("anki.notes")
    anki_notes.Note = object
    anki_notes.NoteId = int
    anki.notes = anki_notes

    connections = types.ModuleType("src.model.connections")
    connections.CONNECTION_TYPES = _ConnectionTypes
    connections.MindMapConnection = _Connection

    mindmap = types.ModuleType("src.model.mindmap")
    mindmap.MindMap = _Model

    node = types.ModuleType("src.model.node")
    node.MindMapNode = _Node

    repository = types.ModuleType("src.repository.db.sql_repository")
    repository.SqlLiteRepository = _Repository

    stubs = {
        "anki": anki,
        "anki.notes": anki_notes,
        "src.model.connections": connections,
        "src.model.mindmap": mindmap,
        "src.model.node": node,
        "src.repository.db.sql_repository": repository,
    }
    module_name = "src.controller._history_commands_delete_tests"
    source = Path(__file__).parents[1] / "src" / "controller" / "history_commands.py"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {source}")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


def _load_sql_repository():
    anki = types.ModuleType("anki")
    anki_notes = types.ModuleType("anki.notes")
    anki_notes.NoteId = int
    anki.notes = anki_notes

    common_io = types.ModuleType("src.common.io")
    common_io.get_add_on_db_path = lambda _name: None

    repository_package = types.ModuleType("src.repository")
    repository_package.__path__ = []
    db_package = types.ModuleType("src.repository.db")
    db_package.__path__ = []
    sql_generator = types.ModuleType("src.repository.db.sql_code_generator")
    sql_generator.TABLES = _Tables
    sql_generator.create_sql_tables = _create_sql_tables

    connections = types.ModuleType("src.model.connections")
    connections.MindMapConnection = _Connection

    node = types.ModuleType("src.model.node")
    node.MindMapNode = _Node

    stubs = {
        "anki": anki,
        "anki.notes": anki_notes,
        "src.common.io": common_io,
        "src.model.connections": connections,
        "src.model.node": node,
        "src.repository": repository_package,
        "src.repository.db": db_package,
        "src.repository.db.sql_code_generator": sql_generator,
    }
    module_name = "src.repository.db._sql_repository_delete_tests"
    source = Path(__file__).parents[1] / "src" / "repository" / "db" / "sql_repository.py"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {source}")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


HISTORY_COMMANDS = _load_history_commands()
DeleteNodesCommand = HISTORY_COMMANDS.DeleteNodesCommand
SQL_REPOSITORY = _load_sql_repository()


def _node(note_id: int, *, x: float = 0, y: float = 0) -> _Node:
    return _Node(
        note_id=note_id,
        anki_note=object(),
        x=x,
        y=y,
        width=320.5 + note_id,
        shown_field_indices=[0, note_id % 3],
        font_size=14.0 + note_id,
    )


def _connection(
    connection_id: int,
    from_note_id: int,
    to_note_id: int,
    *,
    connection_type: _ConnectionTypes = _ConnectionTypes.FULL_DIRECTED,
    color: str = "#123456",
    size: int = 4,
    label: str = "edge",
    label_size: int = 17,
) -> _Connection:
    return _Connection(
        connection_id=connection_id,
        from_note_id=from_note_id,
        to_note_id=to_note_id,
        connection_type=connection_type,
        color=color,
        size=size,
        label=label,
        label_size=label_size,
    )


def _node_state(node) -> tuple:
    return (
        node.note_id,
        node.anki_note,
        node.x,
        node.y,
        node.width,
        tuple(node.shown_field_indices),
        node.font_size,
    )


def _connection_state(connection) -> tuple:
    connection_type = connection.connection_type
    if isinstance(connection_type, Enum):
        connection_type = connection_type.value
    return (
        connection.from_note_id,
        connection.to_note_id,
        connection_type,
        connection.color,
        connection.size,
        connection.label,
        connection.label_size,
    )


class DeleteNodesCommandTests(unittest.TestCase):
    def test_batch_undo_restores_nodes_and_each_incident_connection_once(self):
        nodes = [_node(1, x=12.5, y=-8), _node(2, x=90, y=120), _node(3), _node(4)]
        connections = [
            _connection(
                10,
                1,
                2,
                connection_type=_ConnectionTypes.DOTTED_BIDIRECTIONAL,
                color="#abcdef",
                size=9,
                label="internal",
                label_size=22,
            ),
            _connection(
                11,
                2,
                3,
                connection_type=_ConnectionTypes.FULL_UNDIRECTED,
                color="#fedcba",
                size=2,
                label="external",
                label_size=13,
            ),
            _connection(12, 3, 4, label="unaffected"),
        ]
        expected_nodes = {node.note_id: _node_state(node) for node in nodes[:2]}
        expected_connections = {_connection_state(connection) for connection in connections[:2]}
        model = _Model(nodes, connections)
        repository = _Repository()
        history = HistoryManager()

        command = DeleteNodesCommand(repository, object(), model, [2, 1])

        self.assertTrue(history.execute(command))
        self.assertEqual(repository.delete_calls, [[2, 1]])
        self.assertEqual(set(model.nodes), {3, 4})
        self.assertEqual(
            {_connection_state(c) for c in model.connections.values()}, {_connection_state(connections[2])}
        )

        self.assertTrue(history.undo())
        self.assertEqual(set(model.nodes), {1, 2, 3, 4})
        self.assertEqual(
            {_node_state(model.nodes[note_id]) for note_id in (1, 2)}, set(expected_nodes.values())
        )
        restored_incident = {
            _connection_state(connection)
            for connection in model.connections.values()
            if connection.from_note_id in {1, 2} or connection.to_note_id in {1, 2}
        }
        self.assertEqual(restored_incident, expected_connections)
        self.assertEqual(len(repository.restore_calls), 1)
        self.assertEqual(len(repository.restore_calls[0][0]), 2)
        self.assertEqual(len(repository.restore_calls[0][1]), 2)

    def test_redo_deletes_the_restored_subgraph_and_can_be_undone_again(self):
        model = _Model([_node(1), _node(2)], [_connection(7, 1, 2)])
        repository = _Repository()
        history = HistoryManager()
        command = DeleteNodesCommand(repository, object(), model, [1])

        self.assertTrue(history.execute(command))
        self.assertTrue(history.undo())
        self.assertIn(1, model.nodes)
        self.assertIsNotNone(model.get_connection(1, 2))

        self.assertTrue(history.redo())
        self.assertNotIn(1, model.nodes)
        self.assertIsNone(model.get_connection(1, 2))
        self.assertEqual(repository.delete_calls, [[1], [1]])

        self.assertTrue(history.undo())
        self.assertIn(1, model.nodes)
        self.assertIsNotNone(model.get_connection(1, 2))

    def test_redo_refreshes_snapshots_after_non_history_edits(self):
        model = _Model([_node(1), _node(2)], [_connection(7, 1, 2, label="before")])
        repository = _Repository()
        history = HistoryManager()
        command = DeleteNodesCommand(repository, object(), model, [1])

        self.assertTrue(history.execute(command))
        self.assertTrue(history.undo())
        model.nodes[1].x = 432.5
        model.nodes[1].shown_field_indices = [2]
        model.get_connection(1, 2).label = "after"

        self.assertTrue(history.redo())
        self.assertTrue(history.undo())
        self.assertEqual(model.nodes[1].x, 432.5)
        self.assertEqual(model.nodes[1].shown_field_indices, [2])
        self.assertEqual(model.get_connection(1, 2).label, "after")

    def test_unknown_ids_are_ignored_and_duplicates_are_deleted_once(self):
        model = _Model([_node(1)], [])
        repository = _Repository()
        history = HistoryManager()

        unknown_only = DeleteNodesCommand(repository, object(), model, [999, 999])
        self.assertFalse(history.execute(unknown_only))
        self.assertFalse(history.can_undo())
        self.assertEqual(repository.delete_calls, [])
        self.assertEqual(model.remove_calls, [])

        duplicate_request = DeleteNodesCommand(repository, object(), model, [1, 1, 999, 1])
        self.assertTrue(history.execute(duplicate_request))
        self.assertEqual(repository.delete_calls, [[1]])
        self.assertEqual(model.remove_calls, [[1]])

    def test_snapshot_is_not_changed_when_removed_objects_are_mutated(self):
        deleted_node = _node(1, x=45.25, y=-19.5)
        incident_connection = _connection(
            9,
            1,
            2,
            connection_type=_ConnectionTypes.DOTTED_UNDIRECTED,
            color="#010203",
            size=8,
            label="original",
            label_size=19,
        )
        expected_node = _node_state(deleted_node)
        expected_connection = _connection_state(incident_connection)
        model = _Model([deleted_node, _node(2)], [incident_connection])
        repository = _Repository()
        history = HistoryManager()

        self.assertTrue(history.execute(DeleteNodesCommand(repository, object(), model, [1])))
        deleted_node.x = 999
        deleted_node.shown_field_indices.append(99)
        incident_connection.color = "#ffffff"
        incident_connection.label = "mutated"

        self.assertTrue(history.undo())
        self.assertEqual(_node_state(model.nodes[1]), expected_node)
        self.assertEqual(_connection_state(model.get_connection(1, 2)), expected_connection)

    def test_delete_failure_keeps_model_and_history_unchanged(self):
        model = _Model([_node(1), _node(2)], [_connection(5, 1, 2)])
        repository = _Repository()
        repository.fail_delete = True
        history = HistoryManager()

        with self.assertRaisesRegex(sqlite3.OperationalError, "delete failed"):
            history.execute(DeleteNodesCommand(repository, object(), model, [1]))

        self.assertEqual(set(model.nodes), {1, 2})
        self.assertIsNotNone(model.get_connection(1, 2))
        self.assertFalse(history.can_undo())
        self.assertFalse(history.can_redo())

    def test_restore_failure_retains_the_undo_entry(self):
        model = _Model([_node(1), _node(2)], [_connection(5, 1, 2)])
        repository = _Repository()
        history = HistoryManager()
        self.assertTrue(history.execute(DeleteNodesCommand(repository, object(), model, [1])))
        repository.fail_restore = True

        with self.assertRaisesRegex(sqlite3.OperationalError, "restore failed"):
            history.undo()

        self.assertNotIn(1, model.nodes)
        self.assertIsNone(model.get_connection(1, 2))
        self.assertTrue(history.can_undo())
        self.assertFalse(history.can_redo())

    def test_redo_failure_retains_the_redo_entry(self):
        model = _Model([_node(1), _node(2)], [_connection(5, 1, 2)])
        repository = _Repository()
        history = HistoryManager()
        self.assertTrue(history.execute(DeleteNodesCommand(repository, object(), model, [1])))
        self.assertTrue(history.undo())
        repository.fail_delete = True

        with self.assertRaisesRegex(sqlite3.OperationalError, "delete failed"):
            history.redo()

        self.assertIn(1, model.nodes)
        self.assertIsNotNone(model.get_connection(1, 2))
        self.assertFalse(history.can_undo())
        self.assertTrue(history.can_redo())


class RestoreDeletedSubgraphTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(_create_sql_tables())
        self.repository = SQL_REPOSITORY.SqlLiteRepository()

    def tearDown(self):
        self.connection.close()

    def test_restores_nodes_and_connections_in_one_transaction(self):
        survivor = _node(2)
        restored = _node(1, x=42.5, y=-7)
        edge = _connection(-1, 1, 2, label="restored")
        self.repository.add_nodes(self.connection, [survivor])

        connection_ids = self.repository.restore_deleted_subgraph(
            self.connection,
            [restored],
            [edge],
        )

        self.assertEqual(len(connection_ids), 1)
        self.assertEqual(
            self.connection.execute(
                "SELECT noteId, x, y, fieldsToShow FROM mindmap_notes WHERE noteId = 1"
            ).fetchone(),
            (1, 42.5, -7.0, "0,1"),
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT fromNoteId, toNoteId, label FROM connections WHERE connectionId = ?",
                (connection_ids[0],),
            ).fetchone(),
            (1, 2, "restored"),
        )
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_rolls_back_nodes_when_connection_restore_fails(self):
        self.repository.add_nodes(self.connection, [_node(2)])
        duplicate_edges = [_connection(-1, 1, 2), _connection(-1, 1, 2)]

        with self.assertLogs("AnkiMaps", level="ERROR"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.repository.restore_deleted_subgraph(self.connection, [_node(1)], duplicate_edges)

        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM mindmap_notes WHERE noteId = 1").fetchone()[0],
            0,
        )
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM connections").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
