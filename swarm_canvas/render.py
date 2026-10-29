"""Text is on the canvas. This module writes PNG, xlsx, and the timelapse GIF."""

from __future__ import annotations

from pathlib import Path

import imageio.v2 as imageio
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image

from swarm_canvas.colors import BLANK_RGB, RGB
from swarm_canvas.engine import Canvas, parse_cell


def to_png(snapshot: dict, path: str | Path, scale: int = 20) -> None:
    cols = snapshot["cols"]
    rows = snapshot["rows"]
    image = Image.new("RGB", (cols * scale, rows * scale), BLANK_RGB)
    pixels = image.load()
    for cell in snapshot["cells"]:
        pos = parse_cell(cell["cell"], cols, rows)
        if pos is None:
            continue
        color = RGB.get(cell["color"], BLANK_RGB)
        col, row = pos
        for y in range(row * scale, (row + 1) * scale):
            for x in range(col * scale, (col + 1) * scale):
                pixels[x, y] = color
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def to_xlsx(snapshot: dict, path: str | Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "canvas"
    blank = PatternFill("solid", fgColor=_hex(BLANK_RGB))
    center = Alignment(horizontal="center", vertical="center")
    for row in range(1, snapshot["rows"] + 1):
        for col in range(1, snapshot["cols"] + 1):
            cell = sheet.cell(row=row, column=col, value="")
            cell.fill = blank
            cell.alignment = center
    for item in snapshot["cells"]:
        pos = parse_cell(item["cell"], snapshot["cols"], snapshot["rows"])
        if pos is None:
            continue
        col, row = pos
        rgb = RGB.get(item["color"], BLANK_RGB)
        cell = sheet.cell(row=row + 1, column=col + 1, value=item["color"])
        cell.fill = PatternFill("solid", fgColor=_hex(rgb))
        luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        cell.font = Font(color="111111" if luminance > 150 else "F4F1EA", size=9)
        cell.alignment = center
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def to_gif(png_paths: list[str | Path], path: str | Path, fps: int = 4) -> None:
    frames = [imageio.imread(Path(item)) for item in png_paths]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = max(1, int(1000 / fps))
    imageio.mimsave(path, frames, duration=duration_ms, loop=0)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def write_canvas_files(canvas: Canvas, directory: Path, stem: str) -> Path:
    snapshot = canvas.snapshot()
    json_path = directory / f"{stem}.json"
    png_path = directory / f"{stem}.png"
    xlsx_path = directory / f"{stem}.xlsx"
    import json

    json_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    to_png(snapshot, png_path)
    to_xlsx(snapshot, xlsx_path)
    return png_path
