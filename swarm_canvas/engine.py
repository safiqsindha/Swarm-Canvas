"""Canvas state and last-write-wins paint resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

CELL_RE = re.compile(r"^([A-X])([1-9]|1[0-6])$")
COL_LETTERS = [chr(ord("A") + i) for i in range(24)]


@dataclass
class Paint:
    agent: str
    cell: str
    color: str


@dataclass
class CellState:
    color: str | None = None
    handle: str | None = None


def parse_cell(cell: str, cols: int = 24, rows: int = 16) -> tuple[int, int] | None:
    if not isinstance(cell, str):
        return None
    match = CELL_RE.match(cell)
    if not match:
        return None
    col = ord(match.group(1)) - ord("A")
    row = int(match.group(2)) - 1
    if col < 0 or col >= cols or row < 0 or row >= rows:
        return None
    return col, row


def cell_name(col: int, row: int) -> str:
    return f"{COL_LETTERS[col]}{row + 1}"


class Canvas:
    def __init__(self, cols: int = 24, rows: int = 16):
        self.cols = cols
        self.rows = rows
        self.cells: dict[tuple[int, int], CellState] = {}

    def apply(self, paints: list[Paint], order: list[str]) -> list[dict]:
        """Apply paints agent by agent in `order`. Last write wins.

        `order` is the shuffled painter sequence for this round. The event
        field `order` is that painter's 1-based place in the sequence.
        """
        grouped: dict[str, list[Paint]] = {}
        for paint in paints:
            grouped.setdefault(paint.agent, []).append(paint)

        events: list[dict] = []
        seen: set[str] = set()
        for index, agent in enumerate(order, start=1):
            if agent in seen:
                continue
            seen.add(agent)
            for paint in grouped.get(agent, []):
                pos = parse_cell(paint.cell, self.cols, self.rows)
                if pos is None:
                    continue
                prev = self.cells.get(pos)
                overwrote = None
                if prev and prev.handle and prev.handle != agent:
                    overwrote = prev.handle
                self.cells[pos] = CellState(color=paint.color, handle=agent)
                event = {
                    "type": "paint",
                    "agent": agent,
                    "cell": paint.cell,
                    "color": paint.color,
                    "applied": True,
                    "order": index,
                }
                if overwrote:
                    event["overwrote"] = overwrote
                events.append(event)
        return events

    def snapshot(self) -> dict:
        cells = []
        for row in range(self.rows):
            for col in range(self.cols):
                state = self.cells.get((col, row))
                if not state or not state.color:
                    continue
                cells.append(
                    {
                        "cell": cell_name(col, row),
                        "color": state.color,
                        "handle": state.handle,
                    }
                )
        return {"cols": self.cols, "rows": self.rows, "cells": cells}

    def to_text(self) -> str:
        """Column letters, row numbers, '.' for a blank cell."""
        header = "   " + " ".join(COL_LETTERS[: self.cols])
        lines = [header]
        for row in range(self.rows):
            shown = []
            for col in range(self.cols):
                state = self.cells.get((col, row))
                shown.append(state.color if state and state.color else ".")
            lines.append(f"{row + 1:2d} " + " ".join(shown))
        return "\n".join(lines)

    def board_check(self) -> str:
        """A free reading of the grid. Counts only, no advice and no target."""
        blank_by_column = []
        open_columns = []
        blanks = 0
        for col in range(self.cols):
            letter = COL_LETTERS[col]
            empty = 0
            for row in range(self.rows):
                state = self.cells.get((col, row))
                if not state or not state.color:
                    empty += 1
            blanks += empty
            blank_by_column.append(f"{letter} {empty}")
            if empty == self.rows:
                open_columns.append(letter)
        painted = self.cols * self.rows - blanks
        open_text = " ".join(open_columns) if open_columns else "none"
        return (
            f"CHECK {painted} painted, {blanks} blank. "
            f"Open columns: {open_text}. "
            f"Blank cells: {', '.join(blank_by_column)}."
        )
