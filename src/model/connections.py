from dataclasses import dataclass
from enum import Enum

from anki.notes import NoteId


class CONNECTION_TYPES(Enum):
    FULL_DIRECTED = 0
    FULL_UNDIRECTED = 1
    DOTTED_DIRECTED = 2
    DOTTED_UNDIRECTED = 3
    FULL_BIDIRECTIONAL = 4
    DOTTED_BIDIRECTIONAL = 5


@dataclass
class MindMapConnection:
    connection_id: int
    from_note_id: NoteId
    to_note_id: NoteId
    connection_type: CONNECTION_TYPES
    color: str
    size: int
    label: str
    label_size: int
