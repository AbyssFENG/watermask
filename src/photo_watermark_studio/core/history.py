# -*- coding: utf-8 -*-
"""编辑撤销/重做栈。只覆盖水印文档变更，不含导入/导出。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


class EditHistory:
    def __init__(self, limit: int = 40) -> None:
        self._limit = max(1, int(limit))
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def reset(self, snapshot: dict[str, Any]) -> None:
        self._undo.clear()
        self._redo.clear()
        self._current = deepcopy(snapshot)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, snapshot: dict[str, Any]) -> None:
        if self._current is None:
            self._current = deepcopy(snapshot)
            return
        if snapshot == self._current:
            return
        self._undo.append(self._current)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._current = deepcopy(snapshot)
        self._redo.clear()

    def undo(self) -> dict[str, Any] | None:
        if not self._undo or self._current is None:
            return None
        self._redo.append(self._current)
        self._current = self._undo.pop()
        return deepcopy(self._current)

    def redo(self) -> dict[str, Any] | None:
        if not self._redo or self._current is None:
            return None
        self._undo.append(self._current)
        self._current = self._redo.pop()
        return deepcopy(self._current)

    def current(self) -> dict[str, Any] | None:
        return deepcopy(self._current) if self._current is not None else None


class HistoryBridge:
    """把 push 与回调绑定，便于控制器使用。"""

    def __init__(self, on_restore: Callable[[dict[str, Any]], None]) -> None:
        self.history = EditHistory()
        self._on_restore = on_restore

    def seed(self, snapshot: dict[str, Any]) -> None:
        self.history.reset(snapshot)

    def record(self, snapshot: dict[str, Any]) -> None:
        self.history.push(snapshot)

    def undo(self) -> bool:
        data = self.history.undo()
        if data is None:
            return False
        self._on_restore(data)
        return True

    def redo(self) -> bool:
        data = self.history.redo()
        if data is None:
            return False
        self._on_restore(data)
        return True
