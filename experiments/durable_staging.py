"""Promote a closed attempt from temporary storage without dropping its evidence."""
from __future__ import annotations
import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4


def _hashes(directory: Path):
    result = {}
    for item in sorted(directory.rglob('*')):
        if item.is_symlink():
            raise ValueError('Symlinks are not permitted in staged evidence')
        if item.is_file():
            result[str(item.relative_to(directory))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def promote(source: Path, destination_parent: Path):
    source = Path(source).resolve(strict=True)
    destination_parent = Path(destination_parent).resolve(strict=True)
    if not source.is_dir() or destination_parent == source or source in destination_parent.parents:
        raise ValueError('Invalid staging source or destination')
    destination = destination_parent / source.name
    if destination.exists():
        raise FileExistsError(destination)
    expected = _hashes(source)
    stage = destination_parent / ('.promoting-' + uuid4().hex)
    try:
        shutil.copytree(source, stage, symlinks=False)
        if _hashes(stage) != expected or _hashes(source) != expected:
            raise ValueError('Staged files changed or failed hash verification')
        # Concurrent launchers must use distinct attempt IDs and a private destination parent.
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination
