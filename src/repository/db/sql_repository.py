import logging
import sqlite3
from typing import Any, Dict, List, Tuple

from anki.notes import NoteId

from ...common.constants import ANKIMAPS_CONSTANTS
from ...common.io import get_add_on_db_path
from ...model.connections import MindMapConnection
from ...model.node import MindMapNode
from .sql_code_generator import TABLES, create_sql_tables

logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


class SqlLiteRepository:
    """
    This repository's methods follow a strict contract:
    - They either succeed and return their result (or None if there is no result).
    - Or they fail and raise an exception, rolling back any transaction.

    They do not swallow errors or return True/False. This pushes error
    handling logic to the controller, where it belongs.
    """

    def get_connection(self, mindmap_name: str) -> sqlite3.Connection:
        """
        Establishes and prepares a new database connection.
        """
        try:
            db_path = get_add_on_db_path(mindmap_name=mindmap_name)
            if not db_path:
                raise sqlite3.OperationalError(f"Could not resolve database path for {mindmap_name}")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            cursor.executescript(create_sql_tables())
            conn.commit()
            return conn
        except sqlite3.Error as e:
            logger.error(f"SQLite error establishing connection to {mindmap_name}: {e}")
            raise

    def load_entire_map_data(
        self, conn: sqlite3.Connection
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Loads all raw node and connection data from the database.
        """
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT noteId, fieldsToShow, x, y, width, fontSize FROM {TABLES.NOTES_TABLE.value}"
            )
            nodes_data = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                f"SELECT connectionId, fromNoteId, toNoteId, connectionType, color, size, label, labelSize FROM {TABLES.CONNECTIONS_TABLE.value}"
            )
            connections_data = [dict(row) for row in cursor.fetchall()]

            logger.info(
                f"Loaded {len(nodes_data)} raw nodes and {len(connections_data)} raw connections from DB."
            )
            return nodes_data, connections_data
        except sqlite3.Error as e:
            logger.error(f"Failed to load map data: {e}")
            raise

    def add_nodes(self, conn: sqlite3.Connection, nodes: List[MindMapNode]) -> None:
        """Adds a list of nodes. Raises an exception on failure."""
        try:
            data = [
                (
                    node.note_id,
                    ",".join(map(str, node.shown_field_indices)),
                    node.x,
                    node.y,
                    node.width,
                    node.font_size,
                )
                for node in nodes
            ]
            conn.executemany(
                f"INSERT OR IGNORE INTO {TABLES.NOTES_TABLE.value} (noteId, fieldsToShow, x, y, width, fontSize) VALUES (?, ?, ?, ?, ?, ?)",
                data,
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error adding nodes: {e}")
            raise

    def update_note_positions(self, conn: sqlite3.Connection, position_data: list[dict]) -> None:
        """Updates positions for a list of notes. Raises an exception on failure."""
        if not position_data:
            return

        rows = [(p["x"], p["y"], int(p["id"])) for p in position_data]
        try:
            conn.execute("BEGIN")
            sql = f"UPDATE {TABLES.NOTES_TABLE.value} SET x = ?, y = ? WHERE noteId = ?"
            conn.executemany(sql, rows)
            conn.commit()
        except (sqlite3.Error, KeyError, ValueError) as e:
            conn.rollback()
            logger.error(f"Error updating positions: {e}")
            raise

    def update_node_property(
        self, conn: sqlite3.Connection, node_id: NoteId, column: str, value: Any
    ) -> None:
        """Updates a single property for a single note. Raises an exception on failure."""
        try:
            query = f"UPDATE {TABLES.NOTES_TABLE.value} SET {column}=? WHERE noteId=?"
            conn.execute(query, (value, node_id))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating node property {column}: {e}")
            raise

    def add_connection(self, conn: sqlite3.Connection, conn_data: MindMapConnection) -> int:
        """Adds a new connection to the database and returns its new row ID. Raises an exception on failure."""
        try:
            data = (
                conn_data.from_note_id,
                conn_data.to_note_id,
                conn_data.connection_type.value,
                conn_data.color,
                conn_data.size,
                conn_data.label,
                conn_data.label_size,
            )
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO {TABLES.CONNECTIONS_TABLE.value} (fromNoteId, toNoteId, connectionType, color, size, label, labelSize) VALUES (?, ?, ?, ?, ?, ?, ?)",
                data,
            )
            new_id = cursor.lastrowid
            conn.commit()
            if new_id is None:
                raise sqlite3.OperationalError("lastrowid was not set after insert.")
            return new_id
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error in add_connection: {e}")
            raise

    def update_connection_label(
        self, conn: sqlite3.Connection, id1: NoteId, id2: NoteId, new_label: str
    ) -> None:
        """Updates a connection's label. Raises an exception on failure."""
        try:
            query = f"UPDATE {TABLES.CONNECTIONS_TABLE.value} SET label=? WHERE (fromNoteId=? AND toNoteId=?) OR (fromNoteId=? AND toNoteId=?)"
            conn.execute(query, (new_label, id1, id2, id2, id1))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating connection label: {e}")
            raise

    def update_connection_property(
        self, conn: sqlite3.Connection, id1: NoteId, id2: NoteId, column: str, value: Any
    ) -> None:
        """Updates a single property for a connection. Raises an exception on failure."""
        try:
            query = f"UPDATE {TABLES.CONNECTIONS_TABLE.value} SET {column}=? WHERE (fromNoteId=? AND toNoteId=?) OR (fromNoteId=? AND toNoteId=?)"
            conn.execute(query, (value, id1, id2, id2, id1))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating connection property {column}: {e}")
            raise

    def delete_nodes(self, conn: sqlite3.Connection, node_ids: List[NoteId]) -> None:
        """Deletes a list of nodes and their associated connections (via foreign key cascade). Raises an exception on failure."""
        if not node_ids:
            return

        chunk_size = 900
        try:
            conn.execute("BEGIN")
            for i in range(0, len(node_ids), chunk_size):
                chunk = node_ids[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                sql = f"DELETE FROM {TABLES.NOTES_TABLE.value} WHERE noteId IN ({placeholders})"
                conn.execute(sql, chunk)
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error deleting nodes: {e}")
            raise

    def delete_connection(self, conn: sqlite3.Connection, id1: NoteId, id2: NoteId) -> None:
        """Deletes a connection between two nodes. Raises an exception on failure."""
        try:
            query = f"DELETE FROM {TABLES.CONNECTIONS_TABLE.value} WHERE (fromNoteId=? AND toNoteId=?) OR (fromNoteId=? AND toNoteId=?)"
            conn.execute(query, (id1, id2, id2, id1))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error deleting connection: {e}")
            raise

    def get_map_statistics(self, mindmap_name: str) -> dict:
        """
        Returns high-level statistics for a mindmap database.
        """
        conn = self.get_connection(mindmap_name)
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {TABLES.NOTES_TABLE.value}")
            nodes_count = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM {TABLES.CONNECTIONS_TABLE.value}")
            connections_count = cursor.fetchone()[0]

            return {
                "nodes_count": int(nodes_count),
                "connections_count": int(connections_count),
            }
        finally:
            conn.close()
