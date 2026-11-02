"""Split reference: each painter sees only its own fragment of the target.

A fragment is derived from the target by color and an optional inclusive row
and column range. Cells outside a fragment render as '?'.
"""

from __future__ import annotations

from dataclasses import dataclass

from swarm_canvas.engine import COL_LETTERS, cell_name

UNKNOWN = "?"
SPEC_KEYS = {"colors", "rows", "cols"}

# Ready-made regions for targets/sun_boat.txt.
NAMED_REGIONS: dict[str, dict] = {
    "sun": {"colors": ["Y"]},
    "cloud": {"colors": ["w"], "rows": [1, 4]},
    "hull": {"colors": ["B"]},
    "mast_sail": {"colors": ["K", "P", "w"], "rows": [7, 11]},
}


@dataclass(frozen=True)
class Fragment:
    spec: dict
    cells: frozenset  # of (col, row), zero-based
    lines: tuple  # the target with '?' outside the fragment

    @property
    def description(self) -> str:
        spec = self.spec
        text = "color " + " ".join(spec["colors"])
        if "rows" in spec:
            text += f", rows {spec['rows'][0]} to {spec['rows'][1]}"
        if "cols" in spec:
            text += f", columns {spec['cols'][0]} to {spec['cols'][1]}"
        return text

    def names(self) -> list[str]:
        return sorted(cell_name(c, r) for c, r in self.cells)


def parse_spec(value, where: str = "reference_split") -> dict:
    """Normalize a named region, a color list, or {colors, rows, cols}."""
    if isinstance(value, str):
        if value not in NAMED_REGIONS:
            raise ValueError(f"{where}: unknown region {value!r}; known: {sorted(NAMED_REGIONS)}")
        return parse_spec(NAMED_REGIONS[value], where)
    if isinstance(value, list):
        value = {"colors": value}
    if not isinstance(value, dict) or set(value) - SPEC_KEYS or not value.get("colors"):
        raise ValueError(f"{where}: a fragment is a region name, a color list, or colors with optional rows/cols")
    colors = value["colors"]
    if not isinstance(colors, list) or not all(isinstance(c, str) and c for c in colors):
        raise ValueError(f"{where}: colors must be a list of color codes")
    spec: dict = {"colors": list(dict.fromkeys(colors))}
    if "rows" in value:
        lo, hi = _pair(value["rows"], where, "rows")
        if not (isinstance(lo, int) and isinstance(hi, int)) or isinstance(lo, bool) or isinstance(hi, bool):
            raise ValueError(f"{where}: rows must be two integers")
        if not 1 <= lo <= hi <= 16:
            raise ValueError(f"{where}: rows must satisfy 1 <= low <= high <= 16")
        spec["rows"] = [lo, hi]
    if "cols" in value:
        lo, hi = _pair(value["cols"], where, "cols")
        if lo not in COL_LETTERS or hi not in COL_LETTERS or lo > hi:
            raise ValueError(f"{where}: cols must be two column letters A-X in order")
        spec["cols"] = [lo, hi]
    return spec


def _pair(value, where, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{where}: {name} must be a [low, high] pair")
    return value


def derive_fragment(plate: list[str], spec: dict) -> Fragment:
    """Cells of the target matching the spec's colors inside its row/column ranges."""
    spec = parse_spec(spec)
    colors = set(spec["colors"])
    row_lo, row_hi = spec.get("rows", [1, len(plate)])
    col_lo, col_hi = (COL_LETTERS.index(c) for c in spec.get("cols", [COL_LETTERS[0], COL_LETTERS[-1]]))
    cells = frozenset(
        (col, row)
        for row, line in enumerate(plate)
        for col, char in enumerate(line)
        if char in colors and row_lo - 1 <= row <= row_hi - 1 and col_lo <= col <= col_hi
    )
    return Fragment(spec=spec, cells=cells, lines=tuple(render_lines(plate, cells)))


def render_lines(plate: list[str], cells) -> list[str]:
    return [
        "".join(char if (col, row) in cells else UNKNOWN for col, char in enumerate(line))
        for row, line in enumerate(plate)
    ]


def resolve(split: dict, handles: list[str], plate: list[str], known: set[str]) -> dict[int, Fragment]:
    """Map every slot to its fragment. Keys are starting handles or `slot-N`.

    `known` are colors already visible on the canvas (prefilled); every other
    target cell must belong to some fragment or no painter could ever learn it.
    """
    if not isinstance(split, dict) or not split:
        raise ValueError("task.reference_split must be a nonempty mapping from slot or handle to a fragment")
    by_key = {}
    for index, handle in enumerate(handles):
        by_key[handle] = index
        by_key[f"slot-{index}"] = index
    fragments: dict[int, Fragment] = {}
    for key, value in split.items():
        if key not in by_key:
            raise ValueError(f"task.reference_split names an unknown slot or handle: {key!r}")
        index = by_key[str(key)]
        if index in fragments:
            raise ValueError(f"task.reference_split lists slot-{index} more than once")
        fragment = derive_fragment(plate, parse_spec(value, f"reference_split[{key}]"))
        if not fragment.cells:
            raise ValueError(f"task.reference_split fragment for {key!r} contains no target cells")
        fragments[index] = fragment
    missing = [h for i, h in enumerate(handles) if i not in fragments]
    if missing:
        raise ValueError(f"task.reference_split needs a fragment for every agent; missing {missing}")
    covered = set().union(*(f.cells for f in fragments.values()))
    needed = {(c, r) for r, line in enumerate(plate) for c, ch in enumerate(line) if ch not in known}
    uncovered = needed - covered
    if uncovered:
        raise ValueError(
            f"task.reference_split leaves {len(uncovered)} target cells unassigned "
            f"(for example {sorted(cell_name(c, r) for c, r in uncovered)[:3]})"
        )
    return fragments


def manifest(fragments: dict[int, Fragment]) -> dict:
    return {
        f"slot-{index}": {"spec": fragment.spec, "cells": len(fragment.cells)}
        for index, fragment in sorted(fragments.items())
    }
