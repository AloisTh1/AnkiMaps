from abc import ABC, abstractmethod


class HistoryCommand(ABC):
    @abstractmethod
    def execute(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def undo(self) -> None:
        raise NotImplementedError


class HistoryManager:
    def __init__(self, max_size: int = 100):
        self._undo_stack: list[HistoryCommand] = []
        self._redo_stack: list[HistoryCommand] = []
        self._max_size = max_size

    def execute(self, command: HistoryCommand) -> bool:
        if not command.execute():
            return False

        self._undo_stack.append(command)
        if len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False

        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False

        command = self._redo_stack.pop()
        if not command.execute():
            self._redo_stack.append(command)
            return False

        self._undo_stack.append(command)
        return True

    def undo_size(self) -> int:
        return len(self._undo_stack)

    def redo_size(self) -> int:
        return len(self._redo_stack)

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
