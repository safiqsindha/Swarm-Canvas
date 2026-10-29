"""Repo-root paths. Prompts and the scoring plate live here, not in code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
TARGETS = ROOT / "targets"
CONFIGS = ROOT / "configs"
