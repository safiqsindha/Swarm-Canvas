"""Grid color codes and the RGB values used only by the renderer."""

from __future__ import annotations

BASE_PALETTE = ["S", "W", "Y", "B", "w", "P", "G", "K"]
CATALOG = ["O", "R", "Gy", "L"]

RGB: dict[str, tuple[int, int, int]] = {
    "S": (126, 200, 227),
    "W": (18, 72, 140),
    "Y": (244, 208, 63),
    "B": (122, 78, 40),
    "w": (246, 244, 238),
    "P": (255, 45, 149),
    "G": (126, 217, 87),
    "K": (18, 18, 18),
    "O": (232, 122, 36),
    "R": (196, 40, 48),
    "Gy": (138, 138, 138),
    "L": (166, 214, 236),
}

BLANK_RGB = (232, 228, 218)
