from ...common.constants import ANKIMAPS_CONSTANTS
from .schema import TABLES


def create_sql_tables() -> str:
    """Defines the SQL for creating the addon's database tables."""
    return f"""
        CREATE TABLE IF NOT EXISTS {TABLES.NOTES_TABLE.value} (
            noteId INTEGER PRIMARY KEY,
            fieldsToShow TEXT NOT NULL DEFAULT "0",
            x REAL NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_NOTE_X.value},
            y REAL NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_NOTE_Y.value},
            width REAL NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_NOTE_WIDTH.value},
            fontSize REAL NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_NOTE_FONT_SIZE.value}
        );

        CREATE TABLE IF NOT EXISTS {TABLES.CONNECTIONS_TABLE.value} (
            connectionId INTEGER PRIMARY KEY AUTOINCREMENT,
            fromNoteId INTEGER NOT NULL,
            toNoteId INTEGER NOT NULL,
            connectionType INT NOT NULL DEFAULT 0,
            color TEXT NOT NULL DEFAULT '{ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_COLOR.value}',
            size INTEGER NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_SIZE.value},
            label TEXT NOT NULL DEFAULT '',
            labelSize INT NOT NULL DEFAULT {ANKIMAPS_CONSTANTS.DEFAULT_CONNECTION_LABEL_FONT_SIZE.value},
            FOREIGN KEY (fromNoteId) REFERENCES {TABLES.NOTES_TABLE.value} (noteId) ON DELETE CASCADE,
            FOREIGN KEY (toNoteId) REFERENCES {TABLES.NOTES_TABLE.value} (noteId) ON DELETE CASCADE,
            UNIQUE(fromNoteId, toNoteId)
        );

        CREATE INDEX IF NOT EXISTS idx_conn_from ON connections(fromNoteId);
        CREATE INDEX IF NOT EXISTS idx_conn_to   ON connections(toNoteId);  -- <<< new
    """
