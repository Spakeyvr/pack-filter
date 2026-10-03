"""Run engine work off the UI thread and report back through Qt signals."""

from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from PIL import Image, ImageFilter, ImageOps
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from ..engine import Cancelled
from ..model import load_rgb


class Task(QObject):
    """``fn(progress, cancel_event)`` runs in a background thread."""

    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: Callable[[Callable[[int, int, str], None], threading.Event], Any], parent=None):
        super().__init__(parent)
        self._fn = fn
        self.cancel_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _run(self) -> None:
        try:
            result = self._fn(lambda d, t, m: self.progress.emit(d, t, m), self.cancel_event)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.done.emit(result)


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    return QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()


def make_thumbnails(path: str, size: int) -> tuple[QImage, QImage]:
    """Return (thumbnail, heavily blurred thumbnail)."""
    with Image.open(path) as im:
        im.draft("RGB", (size * 2, size * 2))
        img = load_rgb(im)
        img = ImageOps.contain(img, (size, size), Image.LANCZOS)
    tiny = img.resize((max(1, img.width // 16), max(1, img.height // 16)), Image.BOX)
    blurred = tiny.resize(img.size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(max(img.size) / 24))
    return pil_to_qimage(img), pil_to_qimage(blurred)


class ThumbnailLoader(QObject):
    ready = Signal(object, QImage, QImage)   # key, thumb, blurred
    failed = Signal(object)

    def __init__(self, size: int = 360, parent=None):
        super().__init__(parent)
        self.size = size
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumbs")
        self._pending: set = set()

    def request(self, key, path: str) -> None:
        if key in self._pending:
            return
        self._pending.add(key)
        self._pool.submit(self._load, key, path)

    def _load(self, key, path: str) -> None:
        try:
            thumb, blurred = make_thumbnails(path, self.size)
        except Exception:
            self._pending.discard(key)
            self.failed.emit(key)
            return
        self._pending.discard(key)
        self.ready.emit(key, thumb, blurred)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
