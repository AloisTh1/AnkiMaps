from dataclasses import dataclass

from anki.notes import Note, NoteId

from ..common.constants import ANKIMAPS_CONSTANTS


@dataclass
class MindMapNode:
    """
    Represents a complete, valid node within the mind map.
    This is the primary business object for the Controller. It is guaranteed
    to have all the necessary information for application logic and display.
    """

    note_id: NoteId
    anki_note: Note
    x: float
    y: float
    width: float
    shown_field_indices: list[int]
    font_size: float = ANKIMAPS_CONSTANTS.DEFAULT_NOTE_FONT_SIZE.value
