"""Local database: cached model scores, plus backups of every original we censor.

Backups are content-addressed (by SHA-256) and censored files are recorded by
their own hash. That means a censored cover is recognised and restorable even
after the pack has been moved or renamed.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .model import LABELS
from .paths import data_dir


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CensorRecord:
    censored_sha: str
    original_sha: str
    ext: str
    path: str
    created: float


class Store:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or data_dir()
        self.originals = self.root / "originals"
        self.originals.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.root / "packfilter.db", check_same_thread=False)
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS scores (sha TEXT, model TEXT, general REAL, sensitive REAL,"
                " questionable REAL, explicit REAL, PRIMARY KEY (sha, model))")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS censored (censored_sha TEXT PRIMARY KEY, original_sha TEXT,"
                " ext TEXT, path TEXT, created REAL)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- score cache ---------------------------------------------------------
    def get_scores(self, sha: str, model: str) -> Optional[dict[str, float]]:
        with self._lock:
            row = self._db.execute(
                "SELECT general, sensitive, questionable, explicit FROM scores WHERE sha=? AND model=?",
                (sha, model)).fetchone()
        return dict(zip(LABELS, row)) if row else None

    def put_scores(self, sha: str, model: str, scores: dict[str, float]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?)",
                             (sha, model, *(scores[label] for label in LABELS)))

    # --- backups -------------------------------------------------------------
    def backup_path(self, original_sha: str, ext: str) -> Path:
        return self.originals / original_sha[:2] / f"{original_sha}{ext.lower()}"

    def save_backup(self, original_sha: str, ext: str, data: bytes) -> Path:
        dest = self.backup_path(original_sha, ext)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(dest)
        return dest

    def record_censored(self, censored_sha: str, original_sha: str, ext: str, path: Path) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO censored VALUES (?,?,?,?,?)",
                             (censored_sha, original_sha, ext.lower(), str(path), time.time()))

    def lookup_censored(self, censored_sha: str) -> Optional[CensorRecord]:
        with self._lock:
            row = self._db.execute("SELECT * FROM censored WHERE censored_sha=?", (censored_sha,)).fetchone()
        return CensorRecord(*row) if row else None

    def restore(self, path: Path, current_sha: Optional[str] = None) -> bool:
        """Put the original image back if ``path`` is a file we censored."""
        rec = self.lookup_censored(current_sha or sha256_file(path))
        if rec is None:
            return False
        backup = self.backup_path(rec.original_sha, rec.ext)
        if not backup.is_file():
            return False
        tmp = path.with_name(path.name + ".pftmp")
        shutil.copyfile(backup, tmp)
        tmp.replace(path)
        return True

    def backup_size(self) -> int:
        return sum(f.stat().st_size for f in self.originals.rglob("*") if f.is_file())
