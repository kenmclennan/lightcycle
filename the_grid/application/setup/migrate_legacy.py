import gzip
import os
import shutil
from dataclasses import dataclass, field
from typing import List

_DB = ".grid.db"
_STORE_SUFFIXES = ("", "-wal", "-shm")


@dataclass(frozen=True)
class MigrateResponse:
    moved: List[str] = field(default_factory=list)
    already: bool = False
    nothing: bool = False
    backup: str = None


def _backup_store(store, data_root):
    backups = os.path.join(data_root, "backups")
    os.makedirs(backups, exist_ok=True)
    dst = os.path.join(backups, _DB + ".gz")
    with open(store, "rb") as src, gzip.open(dst, "wb") as out:
        shutil.copyfileobj(src, out)
    return dst


def migrate_legacy(config):
    data_root = config.data_root()
    new_store = os.path.join(data_root, _DB)
    if os.path.exists(new_store):
        return MigrateResponse(already=True)

    legacy_root = config.legacy_data_root()
    legacy_store = os.path.join(legacy_root, _DB)
    legacy_config = config.legacy_config_path()
    if not os.path.exists(legacy_store) and not os.path.exists(legacy_config):
        return MigrateResponse(nothing=True)

    os.makedirs(data_root, exist_ok=True)
    moved = []
    backup = None
    if os.path.exists(legacy_store):
        backup = _backup_store(legacy_store, data_root)
        for suffix in _STORE_SUFFIXES:
            src = legacy_store + suffix
            if os.path.exists(src):
                shutil.move(src, new_store + suffix)
        moved.append("store")

    new_config = os.path.join(data_root, "config")
    if os.path.exists(legacy_config) and not os.path.exists(new_config):
        shutil.move(legacy_config, new_config)
        moved.append("config")

    for name in ("logs", ".worktrees"):
        src = os.path.join(legacy_root, name)
        dst = os.path.join(data_root, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            moved.append(name)

    return MigrateResponse(moved=moved, backup=backup)
