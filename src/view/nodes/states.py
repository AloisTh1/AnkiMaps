from enum import Flag, auto


class NoteState(Flag):
    """
    Represents the visual state of a note view.
    """

    NORMAL = 0
    SEARCH_HIGHLIGHTED = auto()
    REVIEW_ACTIVE = auto()
    REVIEW_BLURRED = auto()
    MASKED = auto()
