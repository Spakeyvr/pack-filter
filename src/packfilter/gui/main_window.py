"""Main application window."""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QSplitter, QStackedWidget, QStatusBar, QTabBar, QToolButton, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__
from ..engine import ApplyResult, Engine, Item, extract_zip, items_from_packs
from ..paths import data_dir, work_dir
from ..policy import Settings
from ..scanner import CATEGORIES
from . import theme
from .detail import DetailPanel
from .results import CardDelegate, ItemRole, ResultsModel, ResultsView, ThumbCache
from .settings_panel import SettingsPanel
from .tasks import Task, ThumbnailLoader

FILTERS = (("all", "All"), ("censor", "Will censor"), ("ok", "Not censored"), ("done", "Already censored"),
           ("problem", "Unreadable"))
ALL_PACKS = "__all__"


def etterna_song_folders() -> list[Path]:
    """Common Etterna install locations, so first-time users can start with one click."""
    home = Path.home()
    if sys.platform == "win32":
        drives = [Path(f"{d}:/") for d in "CDEFG"]
        cands = [d / sub / "Songs" for d in drives
                 for sub in ("Games/Etterna", "Etterna", "Program Files/Etterna", "Program Files (x86)/Etterna")]
        cands.append(home / "Etterna" / "Songs")
    elif sys.platform == "darwin":
        cands = [Path("/Applications/Etterna/Songs"), home / "Applications" / "Etterna" / "Songs",
                 home / "Library" / "Application Support" / "Etterna" / "Songs", home / "Etterna" / "Songs"]
    else:
        cands = [home / ".etterna" / "Songs", home / "Etterna" / "Songs", home / ".local/share/Etterna/Songs",
                 Path("/opt/etterna/Songs"), Path("/usr/share/etterna/Songs")]
    out = []
    for c in cands:
        try:
            if c.is_dir():
                out.append(c)
        except OSError:
            pass
    return out


def reveal_in_file_manager(path: Path) -> None:
    """Open the file manager with ``path`` selected (or its folder, where selecting isn't supported)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
            return
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def clean_stale_work_dirs() -> None:
    """Remove leftovers from a previous run that didn't exit cleanly."""
    for d in work_dir().glob("extract-*"):
        shutil.rmtree(d, ignore_errors=True)


class DropZone(QFrame):
    def __init__(self, on_folder, on_zip, on_etterna, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)
        big = QLabel("Drop song packs here")
        big.setObjectName("Big")
        big.setAlignment(Qt.AlignCenter)
        lay.addWidget(big)
        sub = QLabel("Pack folders, your whole Songs folder, or downloaded .zip packs.\n"
                     "Works with Etterna and StepMania packs, and folders from other rhythm games.")
        sub.setObjectName("Hint")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        b1 = QPushButton("Add a folder...")
        b1.setObjectName("Primary")
        b1.clicked.connect(on_folder)
        b2 = QPushButton("Add .zip packs...")
        b2.clicked.connect(on_zip)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        self.etterna_btns = QVBoxLayout()
        self.etterna_btns.setAlignment(Qt.AlignCenter)
        lay.addLayout(self.etterna_btns)
        for folder in etterna_song_folders()[:3]:
            b = QPushButton(f"Use Etterna Songs folder: {folder}")
            b.setObjectName("Flat")
            b.clicked.connect(lambda _=False, f=folder: on_etterna(f))
            self.etterna_btns.addWidget(b)
        lay.addSpacing(10)
        note = QLabel("Your packs are never modified. Filtered copies are saved as .zip files "
                      "(to Downloads unless you pick another folder).")
        note.setObjectName("Hint")
        note.setAlignment(Qt.AlignCenter)
        lay.addWidget(note)

    def set_hover(self, on: bool) -> None:
        self.setProperty("hover", on)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setMinimumSize(QSize(980, 620))
        self.setAcceptDrops(True)

        self.settings_path = data_dir() / "settings.json"
        self.settings = Settings.load(self.settings_path)
        self.engine = Engine()
        self.items: list[Item] = []
        self.pack_roots: dict[Path, str] = {}
        self.task: Optional[Task] = None
        self._queue: list[Callable[[], None]] = []
        self._temp_dirs: list[Path] = []          # unpacked zip packs, deleted on exit
        self._sources: dict[Path, Path] = {}      # unpacked folder -> the .zip it came from
        clean_stale_work_dirs()
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_settings)
        self._refresh_timer = QTimer(self, singleShot=True, interval=60, timeout=self._refresh_view)

        self.loader = ThumbnailLoader()
        self.thumbs = ThumbCache(self.loader, self._thumbs_ready)

        self._build_ui()
        self._update_everything()

    # ================================================================== UI ==
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("Big")
        header.addWidget(title)
        tag = QLabel("Hide lewd song pack covers")
        tag.setObjectName("Hint")
        header.addWidget(tag)
        header.addSpacing(16)
        self.add_btn = QToolButton()
        self.add_btn.setText("+  Add packs")
        self.add_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.add_btn)
        menu.addAction("Add a folder (a pack, or a whole Songs folder)...", self.choose_folder)
        menu.addAction("Add .zip packs...", self.choose_zips)
        self.etterna_menu = menu.addMenu("Etterna Songs folder")
        found = etterna_song_folders()
        for f in found:
            self.etterna_menu.addAction(str(f), lambda f=f: self.add_paths([f]))
        self.etterna_menu.menuAction().setVisible(bool(found))
        menu.addSeparator()
        self.clear_action = menu.addAction("Remove all packs from the list", self.clear_packs)
        self.add_btn.setMenu(menu)
        header.addWidget(self.add_btn)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setToolTip("Check every image again (picks up changes made outside the app)")
        self.rescan_btn.clicked.connect(self.rescan)
        header.addWidget(self.rescan_btn)
        header.addStretch(1)
        self.restore_all_btn = QPushButton("Restore originals")
        self.restore_all_btn.setToolTip("Undo censoring done directly inside these packs (e.g. by the command line)")
        self.restore_all_btn.clicked.connect(self.restore_all)
        header.addWidget(self.restore_all_btn)
        self.dest_btn = QPushButton()
        self.dest_btn.setObjectName("Flat")
        self.dest_btn.setCursor(Qt.PointingHandCursor)
        self.dest_btn.setToolTip("Click to choose where filtered packs are saved")
        header.addWidget(self.dest_btn)
        self.apply_btn = QPushButton("Download")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.clicked.connect(self.download)
        header.addWidget(self.apply_btn)
        root.addLayout(header)

        # Body: packs | results | settings
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setMinimumWidth(200)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 12, 8, 8)
        lbl = QLabel("PACKS")
        lbl.setObjectName("SectionTitle")
        lbl.setContentsMargins(8, 0, 0, 4)
        sl.addWidget(lbl)
        self.pack_list = QListWidget()
        self.pack_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pack_list.setTextElideMode(Qt.ElideRight)
        self.pack_list.currentItemChanged.connect(lambda *_: self._refresh_view())
        self.pack_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pack_list.customContextMenuRequested.connect(self._pack_menu)
        sl.addWidget(self.pack_list, 1)
        self.remove_pack_btn = QPushButton("Remove from list")
        self.remove_pack_btn.clicked.connect(self.remove_selected_pack)
        sl.addWidget(self.remove_pack_btn)
        self.splitter.addWidget(side)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        self.stack = QStackedWidget()
        self.dropzone = DropZone(self.choose_folder, self.choose_zips, lambda f: self.add_paths([f]))
        self.stack.addWidget(self.dropzone)

        results_page = QWidget()
        rl = QVBoxLayout(results_page)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        bar = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        for _, name in FILTERS:
            self.tabs.addTab(name)
        self.tabs.currentChanged.connect(lambda *_: self._refresh_view())
        bar.addWidget(self.tabs)
        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search songs, packs, files...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(lambda *_: self._refresh_timer.start())
        bar.addWidget(self.search)
        rl.addLayout(bar)

        self.model = ResultsModel(self)
        self.view = ResultsView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(CardDelegate(self.thumbs, lambda: self.settings, self.view))
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._item_menu)
        self.empty_label = QLabel("No images match this filter.")
        self.empty_label.setObjectName("Hint")
        self.empty_label.setAlignment(Qt.AlignCenter)
        vstack = QStackedWidget()
        vstack.addWidget(self.view)
        vstack.addWidget(self.empty_label)
        self.view_stack = vstack
        rl.addWidget(vstack, 1)

        self.detail = DetailPanel(self.thumbs, lambda: self.settings)
        self.detail.override.connect(self.set_override)
        self.detail.restore.connect(self.restore_selected)
        rl.addWidget(self.detail)
        self.stack.addWidget(results_page)
        cl.addWidget(self.stack, 1)
        self.splitter.addWidget(center)

        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.changed.connect(self._settings_changed)
        self.dest_btn.clicked.connect(self.settings_panel._pick_dest)
        self.splitter.addWidget(self.settings_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([230, 760, 350])

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status = QLabel("Ready")
        sb.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(260)
        self.progress.setVisible(False)
        sb.addPermanentWidget(self.progress)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_task)
        sb.addPermanentWidget(self.cancel_btn)

        sel_all = QAction(self)
        sel_all.setShortcut(QKeySequence.SelectAll)
        sel_all.triggered.connect(self.view.selectAll)
        self.addAction(sel_all)

    # ============================================================ helpers ==
    def _busy(self) -> bool:
        return self.task is not None

    def _current_pack(self) -> Optional[str]:
        it = self.pack_list.currentItem()
        key = it.data(Qt.UserRole) if it else ALL_PACKS
        return None if key in (None, ALL_PACKS) else key

    def _visible_items(self) -> list[Item]:
        pack = self._current_pack()
        flt = FILTERS[max(0, self.tabs.currentIndex())][0]
        q = self.search.text().strip().lower()
        out = []
        for it in self.items:
            if pack is not None and str(it.pack_root) != pack:
                continue
            if not self._matches(it, flt):
                continue
            if q and q not in it.song.lower() and q not in it.pack.lower() and q not in it.path.name.lower():
                continue
            out.append(it)
        return out

    def _matches(self, it: Item, flt: str) -> bool:
        if flt == "censor":
            return it.will_censor(self.settings)
        if flt == "ok":
            return not it.censored and not it.error and not it.will_censor(self.settings)
        if flt == "done":
            return it.censored
        if flt == "problem":
            return bool(it.error)
        return True

    def _selected_items(self) -> list[Item]:
        return [idx.data(ItemRole) for idx in self.view.selectionModel().selectedIndexes()]

    # ============================================================ refresh ==
    def _thumbs_ready(self) -> None:
        self.view.viewport().update()
        if len(self.detail.items) == 1:
            self.detail.refresh()

    def _refresh_view(self) -> None:
        selected = {id(i) for i in self._selected_items()}
        visible = self._visible_items()
        if [id(i) for i in visible] != [id(i) for i in self.model.items()]:
            self.model.set_items(visible)
            sm = self.view.selectionModel()
            for row, it in enumerate(visible):
                if id(it) in selected:
                    sm.select(self.model.index(row), sm.SelectionFlag.Select)
        else:
            self.model.refresh()
        self.view_stack.setCurrentIndex(0 if visible else 1)
        if not visible:
            self.empty_label.setText("No images match this filter." if self.items else "")
        self._update_counts()
        self._selection_changed()

    def _update_counts(self) -> None:
        s = self.settings
        pack = self._current_pack()
        scope = [it for it in self.items if pack is None or str(it.pack_root) == pack]
        for i, (key, name) in enumerate(FILTERS):
            n = sum(self._matches(it, key) for it in scope)
            self.tabs.setTabText(i, f"{name}  {n}")
        n_censor = sum(it.will_censor(s) for it in self.items)
        n_done = sum(it.censored for it in self.items)
        busy = self._busy()
        n_packs = len(self._export_roots())
        self.apply_btn.setText(f"Download {n_packs} filtered pack{'s' if n_packs != 1 else ''}" if n_packs
                               else "Nothing to filter")
        self.apply_btn.setToolTip(f"{n_censor} image(s) will be censored. Saves one .zip per pack to "
                                  f"{s.output_path()}")
        self.apply_btn.setEnabled(n_packs > 0 and not busy)
        out = s.output_path()
        self.dest_btn.setText(f"Save to: {out.name or str(out)}")
        self.dest_btn.setToolTip(f"Filtered packs are saved to {out}. Click to change.")
        self.restore_all_btn.setVisible(n_done > 0)
        self.restore_all_btn.setEnabled(not busy)
        self.rescan_btn.setEnabled(bool(self.items) and not busy)
        self.add_btn.setEnabled(not busy)
        self.remove_pack_btn.setEnabled(self._current_pack() is not None and not busy)
        self.settings_panel.set_category_counts(
            {c: sum(c in it.categories for it in self.items) for c in CATEGORIES} if self.items else {})

        # Pack list labels
        for row in range(self.pack_list.count()):
            li = self.pack_list.item(row)
            key = li.data(Qt.UserRole)
            its = self.items if key == ALL_PACKS else [it for it in self.items if str(it.pack_root) == key]
            name = "All packs" if key == ALL_PACKS else self.pack_roots.get(Path(key), key)
            c = sum(it.will_censor(s) for it in its)
            d = sum(it.censored for it in its)
            extra = []
            if c:
                extra.append(f"{c} to censor")
            if d:
                extra.append(f"{d} censored")
            li.setText(f"{name}\n{len(its)} image{'s' if len(its) != 1 else ''}"
                       + (" · " + " · ".join(extra) if extra else ""))
            src = self._sources.get(Path(key)) if key != ALL_PACKS else None
            li.setToolTip(str(src) if src else (key if key != ALL_PACKS else ""))

    def _update_everything(self) -> None:
        self.stack.setCurrentIndex(1 if self.items or self._busy() else 0)
        self._rebuild_pack_list()
        self._refresh_view()

    def _rebuild_pack_list(self) -> None:
        current = self.pack_list.currentItem().data(Qt.UserRole) if self.pack_list.currentItem() else ALL_PACKS
        self.pack_list.blockSignals(True)
        self.pack_list.clear()
        keys = [ALL_PACKS] + [str(r) for r in sorted(self.pack_roots, key=lambda r: self.pack_roots[r].lower())]
        for key in keys:
            li = QListWidgetItem()
            li.setData(Qt.UserRole, key)
            self.pack_list.addItem(li)
            if key == current:
                self.pack_list.setCurrentItem(li)
        if self.pack_list.currentItem() is None and self.pack_list.count():
            self.pack_list.setCurrentRow(0)
        self.pack_list.blockSignals(False)

    def _selection_changed(self, *args) -> None:
        items = self._selected_items()
        self.detail.set_items(items)
        src = None
        if len(items) == 1 and not items[0].error and items[0].scores is not None:
            try:
                with Image.open(items[0].path) as im:
                    im.draft("RGB", (600, 600))
                    src = im.convert("RGB")
                    src.thumbnail((600, 600))
            except Exception:
                src = None
        self.settings_panel.set_preview_source(src)

    # ============================================================ tasks ==
    def _run(self, fn, on_done: Callable[[object], None], message: str) -> None:
        task = Task(fn, self)
        self.task = task
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.cancel_btn.setVisible(True)
        self.status.setText(message)
        task.progress.connect(self._task_progress)
        task.done.connect(lambda res: (self._task_finished(), on_done(res)))
        task.failed.connect(self._task_failed)
        task.cancelled.connect(self._task_cancelled)
        self._update_counts()
        task.start()

    def _task_progress(self, done: int, total: int, message: str) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.status.setText(message)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(250)

    def _task_finished(self) -> None:
        self.task = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.status.setText("Ready")
        self._update_counts()
        if self._queue:
            self._queue.pop(0)()

    def _task_failed(self, msg: str) -> None:
        self._task_finished()
        self._update_everything()
        QMessageBox.critical(self, APP_NAME, f"Something went wrong:\n\n{msg}")

    def _task_cancelled(self) -> None:
        self._task_finished()
        self._update_everything()
        self.status.setText("Cancelled")

    def cancel_task(self) -> None:
        if self.task:
            self.task.cancel()
            self.status.setText("Cancelling...")

    def _after_idle(self, fn: Callable[[], None]) -> None:
        if self._busy():
            self._queue.append(fn)
        else:
            fn()

    # ============================================================ adding ==
    def choose_folder(self) -> None:
        start = str(etterna_song_folders()[0]) if etterna_song_folders() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Choose a pack folder or your Songs folder", start)
        if path:
            self.add_paths([Path(path)])

    def choose_zips(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choose downloaded pack .zip files", str(Path.home()),
                                                "Zip archives (*.zip)")
        if files:
            self.add_zips([Path(f) for f in files])

    def add_zips(self, zips: list[Path]) -> None:
        """Unpack downloaded packs into a private scratch folder; they come back out as filtered zips."""
        tmp = Path(tempfile.mkdtemp(prefix="extract-", dir=work_dir()))
        self._temp_dirs.append(tmp)

        def work(progress, cancel):
            out = []
            for i, z in enumerate(zips):
                progress(i, len(zips), f"Unpacking {z.name}...")
                folder = extract_zip(z, tmp / str(i), cancel)
                self._sources[folder.resolve()] = z
                out.append(folder)
            return out

        self._after_idle(lambda: self._run(work, self.add_paths, "Unpacking zip packs..."))
        self.stack.setCurrentIndex(1)

    def add_paths(self, paths: list[Path]) -> None:
        if self._busy():
            self._queue.append(lambda: self.add_paths(paths))
            return

        def work(progress, cancel):
            progress(0, 0, "Looking for songs and images...")
            return Engine.collect(paths)

        def done(packs):
            known = {it.path for it in self.items}
            new_items = [it for it in items_from_packs(packs) if it.path not in known]
            for p in packs:
                self.pack_roots[p.root] = p.name
            self.items.extend(new_items)
            if not packs:
                QMessageBox.information(self, APP_NAME, "No images were found in that folder.")
            self._update_everything()
            if packs and len(packs) == 1 and self.pack_list.count() > 2:
                for row in range(self.pack_list.count()):
                    if self.pack_list.item(row).data(Qt.UserRole) == str(packs[0].root):
                        self.pack_list.setCurrentRow(row)
            self.classify([it for it in self.items if it.scores is None and not it.censored and not it.error])

        self._run(work, done, "Looking for songs and images...")
        self.stack.setCurrentIndex(1)

    def classify(self, items: list[Item]) -> None:
        if not items:
            return
        model = self.settings.model

        def work(progress, cancel):
            self.engine.classify(items, model, progress, cancel)
            return len(items)

        def done(n):
            self._update_everything()
            n_flag = sum(it.will_censor(self.settings) for it in self.items)
            self.status.setText(f"Checked {len(self.items)} images. {n_flag} would be censored with the "
                                "current settings.")

        self._after_idle(lambda: self._run(work, done, "Checking images..."))

    def rescan(self) -> None:
        for it in self.items:
            it.scores = None
        self._update_everything()
        self.classify(list(self.items))

    def clear_packs(self) -> None:
        if self._busy():
            return
        self.items.clear()
        self.pack_roots.clear()
        self._update_everything()

    def remove_selected_pack(self) -> None:
        key = self._current_pack()
        if key is None or self._busy():
            return
        self.items = [it for it in self.items if str(it.pack_root) != key]
        self.pack_roots.pop(Path(key), None)
        self._update_everything()

    def _pack_menu(self, pos) -> None:
        li = self.pack_list.itemAt(pos)
        if not li or li.data(Qt.UserRole) == ALL_PACKS:
            return
        menu = QMenu(self)
        src = self._sources.get(Path(li.data(Qt.UserRole)))
        if src:
            menu.addAction("Show the original .zip", lambda: reveal_in_file_manager(src))
        else:
            menu.addAction("Open folder",
                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(li.data(Qt.UserRole))))
        menu.addAction("Remove from list", self.remove_selected_pack)
        menu.exec(self.pack_list.mapToGlobal(pos))

    # ============================================================ editing ==
    def set_override(self, value) -> None:
        for it in self._selected_items():
            if not it.censored:
                it.override = value
        self._refresh_view()

    def _item_menu(self, pos) -> None:
        items = self._selected_items()
        if not items:
            return
        menu = QMenu(self)
        menu.addAction("Always censor", lambda: self.set_override(True))
        menu.addAction("Never censor", lambda: self.set_override(False))
        menu.addAction("Automatic", lambda: self.set_override(None))
        if any(i.censored for i in items):
            menu.addSeparator()
            menu.addAction("Restore original", self.restore_selected)
        if len(items) == 1:
            menu.addSeparator()
            menu.addAction("Open containing folder",
                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(items[0].path.parent))))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _settings_changed(self, what: str) -> None:
        self._save_timer.start()
        if what == "model":
            self.rescan()
        elif what in ("filter", "preview", "output"):
            self._refresh_view()
            self.detail.refresh()

    def _save_settings(self) -> None:
        try:
            self.settings.save(self.settings_path)
        except OSError:
            pass

    # ============================================================ apply ==
    def _export_roots(self) -> set[Path]:
        if self.settings.export_unchanged:
            return {it.pack_root for it in self.items}
        return {it.pack_root for it in self.items if it.will_censor(self.settings)}

    def download(self) -> None:
        s = dataclasses.replace(self.settings, categories=list(self.settings.categories))
        if not self._export_roots():
            return
        dest = s.output_path()
        items = list(self.items)

        def work(progress, cancel):
            return self.engine.export_zips(items, s, dest, progress, cancel)

        def done(res: ApplyResult):
            self._update_everything()
            n = len(res.output_roots)
            self.status.setText(f"Saved {n} filtered pack(s) to {dest}")
            names = "\n".join(f"  •  {z.name}" for z in res.output_roots[:12])
            if n > 12:
                names += f"\n  ... and {n - 12} more"
            text = (f"Saved {n} filtered pack{'s' if n != 1 else ''} to {dest} "
                    f"({res.censored} image{'s' if res.censored != 1 else ''} censored):\n\n{names}\n\n"
                    "To play them, extract each zip into your Etterna \"Songs\" folder (or add them the way "
                    "you normally add downloaded packs).")
            if res.errors:
                text += (f"\n\n{len(res.errors)} image(s) couldn't be processed and were left out:\n"
                         + "\n".join(res.errors[:6]))
            box = QMessageBox(QMessageBox.Warning if res.errors else QMessageBox.Information, APP_NAME, text,
                              parent=self)
            show_btn = box.addButton("Show in folder", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Ok)
            box.exec()
            if box.clickedButton() is show_btn and res.output_roots:
                reveal_in_file_manager(res.output_roots[0])

        self._run(work, done, "Creating filtered packs...")

    def _restore(self, items: list[Item], confirm: bool) -> None:
        items = [it for it in items if it.censored]
        if not items:
            return
        if confirm and QMessageBox.question(
                self, APP_NAME, f"Put the original image back for {len(items)} censored image(s)?") \
                != QMessageBox.Yes:
            return

        def work(progress, cancel):
            return self.engine.restore(items, progress, cancel)

        def done(res: ApplyResult):
            self._update_everything()
            self.status.setText(f"Restored {res.restored} image(s).")
            if res.errors:
                QMessageBox.warning(self, APP_NAME, "Some images could not be restored:\n\n"
                                    + "\n".join(res.errors[:8]))

        self._run(work, done, "Restoring originals...")

    def restore_all(self) -> None:
        self._restore(self.items, confirm=True)

    def restore_selected(self) -> None:
        self._restore(self._selected_items(), confirm=False)

    # ============================================================ events ==
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self._busy():
            e.acceptProposedAction()
            self.dropzone.set_hover(True)

    def dragLeaveEvent(self, e):
        self.dropzone.set_hover(False)

    def dropEvent(self, e):
        self.dropzone.set_hover(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        zips = [p for p in paths if p.is_file() and p.suffix.lower() == ".zip"]
        folders = [p for p in paths if p.is_dir()]
        if folders:
            self.add_paths(folders)
        if zips:
            self.add_zips(zips)

    def closeEvent(self, e):
        if self._busy():
            if QMessageBox.question(self, APP_NAME, "A job is still running. Stop it and quit?") != QMessageBox.Yes:
                e.ignore()
                return
        self.shutdown()
        e.accept()

    def shutdown(self) -> None:
        if self.task:
            self.task.cancel()
        for d in self._temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._save_settings()
        self.loader.shutdown()
