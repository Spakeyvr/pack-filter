"""Danbooru-style rating classifier (deepghs/anime_dbrating).

This mirrors ``imgutils.validate.anime_dbrating_score`` exactly (same model files,
same preprocessing) but only depends on onnxruntime, numpy and Pillow, which keeps
the packaged app small. ``tests/test_model_parity.py`` checks both agree.
"""

from __future__ import annotations

import json
import shutil
import ssl
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np
from PIL import Image, ImageFile

from .paths import bundled_assets_dir, models_dir

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 250_000_000

REPO_ID = "deepghs/anime_dbrating"
LABELS = ("general", "sensitive", "questionable", "explicit")
INPUT_SIZE = 384


@dataclass(frozen=True)
class ModelInfo:
    name: str
    title: str
    description: str
    approx_mb: int


MODELS = {
    "mobilenetv3_large_100_v0_ls0.2": ModelInfo(
        "mobilenetv3_large_100_v0_ls0.2", "Fast", "MobileNetV3 - quick, good for most packs", 17),
    "caformer_s36_v0_ls0.2": ModelInfo(
        "caformer_s36_v0_ls0.2", "Accurate", "CAFormer-S36 - slower, fewer mistakes", 150),
}
DEFAULT_MODEL = "mobilenetv3_large_100_v0_ls0.2"

ProgressFn = Callable[[int, int], None]  # (bytes_done, bytes_total)


class ModelDownloadError(RuntimeError):
    pass


def _model_url(model_name: str, filename: str) -> str:
    return f"https://huggingface.co/{REPO_ID}/resolve/main/{model_name}/{filename}"


def _candidate_dirs(model_name: str) -> list[Path]:
    return [bundled_assets_dir() / "models" / model_name, models_dir() / model_name]


def find_model(model_name: str) -> Optional[Path]:
    """Return the directory holding model.onnx + meta.json, if already available."""
    for d in _candidate_dirs(model_name):
        if (d / "model.onnx").is_file() and (d / "meta.json").is_file():
            return d
    return None


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover - certifi is a dependency, but be forgiving
        return ssl.create_default_context()


def _download(url: str, dest: Path, progress: Optional[ProgressFn], cancel: Optional[threading.Event]) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "packfilter"})
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp, open(tmp, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise ModelDownloadError("Download cancelled")
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except ModelDownloadError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise ModelDownloadError(f"Could not download {url}: {exc}") from exc
    shutil.move(str(tmp), dest)


def ensure_model(model_name: str = DEFAULT_MODEL, progress: Optional[ProgressFn] = None,
                 cancel: Optional[threading.Event] = None) -> Path:
    if model_name not in MODELS:
        raise ValueError(f"Unknown model {model_name!r}")
    found = find_model(model_name)
    if found:
        return found
    target = models_dir() / model_name
    target.mkdir(parents=True, exist_ok=True)
    _download(_model_url(model_name, "meta.json"), target / "meta.json", None, cancel)
    _download(_model_url(model_name, "model.onnx"), target / "model.onnx", progress, cancel)
    return target


def load_rgb(path_or_image) -> Image.Image:
    """Open an image the way imgutils does: first frame, alpha flattened onto white, RGB."""
    img = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    if getattr(img, "is_animated", False):
        img.seek(0)
    if img.format == "JPEG" and max(img.size) > INPUT_SIZE * 4:
        # Decode big JPEG backgrounds at reduced scale; it is much faster and the
        # model only sees 384x384 anyway.
        img.draft("RGB", (INPUT_SIZE * 2, INPUT_SIZE * 2))
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, "white")
        bg.alpha_composite(rgba)
        img = bg
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def preprocess(img: Image.Image) -> np.ndarray:
    img = load_rgb(img).resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    data = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
    return ((data - 0.5) / 0.5).astype(np.float32)


# GPU back-ends we try, best first. CoreML is deliberately absent: on Apple Silicon it was
# slower than the CPU for these models and gave wrong scores for the default one.
GPU_PROVIDERS = {
    "CUDAExecutionProvider": "NVIDIA CUDA",
    "DmlExecutionProvider": "DirectML",
}
# GPU results must match the CPU this closely (scores are probabilities).
GPU_TOLERANCE = 0.02


def _session(ort, path: Path, provider: str):
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    if provider == "DmlExecutionProvider":
        # Required by DirectML: no memory pattern, sequential execution.
        opts.enable_mem_pattern = False
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = [provider] if provider == "CPUExecutionProvider" else [provider, "CPUExecutionProvider"]
    sess = ort.InferenceSession(str(path), sess_options=opts, providers=providers)
    if sess.get_providers()[0] != provider:
        raise RuntimeError(f"{provider} could not be initialised")
    return sess


def _timed(sess, name: str, x: np.ndarray, repeats: int = 2) -> tuple[np.ndarray, float]:
    out = sess.run(None, {name: x})[0]  # warm-up (GPU kernels compile on first run)
    t = time.perf_counter()
    for _ in range(repeats):
        out = sess.run(None, {name: x})[0]
    return out, (time.perf_counter() - t) / repeats


class RatingModel:
    """Thread-safe wrapper around the ONNX session.

    With ``use_gpu`` it tries CUDA, then DirectML (any DirectX 12 GPU on Windows). A GPU is
    only kept if it reproduces the CPU's scores and is actually faster; otherwise the CPU
    is used. ``device`` describes what was picked, ``gpu_note`` why a GPU wasn't.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, model_dir: Optional[Path] = None,
                 use_gpu: bool = False):
        import onnxruntime as ort

        self.model_name = model_name
        model_dir = model_dir or find_model(model_name)
        if model_dir is None:
            raise FileNotFoundError(f"Model {model_name} is not downloaded yet; call ensure_model() first")
        with open(model_dir / "meta.json", "r", encoding="utf-8") as fh:
            self.labels = tuple(json.load(fh)["labels"])
        path = model_dir / "model.onnx"
        self._session = _session(ort, path, "CPUExecutionProvider")
        self._input = self._session.get_inputs()[0].name
        self._output = self._session.get_outputs()[0].name
        self.device = "CPU"
        self.provider = "CPUExecutionProvider"
        self.gpu_note = ""
        self.batch_size = 16
        self._lock = threading.Lock()
        if use_gpu:
            self._try_gpu(ort, path)

    def _try_gpu(self, ort, path: Path) -> None:
        available = set(ort.get_available_providers())
        candidates = [p for p in GPU_PROVIDERS if p in available]
        if not candidates:
            self.gpu_note = "no GPU support in this build of ONNX Runtime"
            return
        x = np.random.RandomState(0).uniform(-1, 1, (8, 3, INPUT_SIZE, INPUT_SIZE)).astype(np.float32)
        cpu_out, cpu_time = _timed(self._session, self._input, x)
        notes = []
        for provider in candidates:
            name = GPU_PROVIDERS[provider]
            try:
                sess = _session(ort, path, provider)
                gpu_out, gpu_time = _timed(sess, self._input, x)
            except Exception as exc:  # driver problems, missing CUDA libraries, ...
                notes.append(f"{name} unavailable ({str(exc).splitlines()[0][:120]})")
                continue
            diff = float(np.abs(gpu_out - cpu_out).max())
            if diff > GPU_TOLERANCE:
                notes.append(f"{name} gave different results (off by {diff:.2f})")
                continue
            if gpu_time >= cpu_time:
                notes.append(f"{name} was not faster than the CPU")
                continue
            self._session, self.provider = sess, provider
            self.device = f"GPU ({name})"
            self.batch_size = 32
            self.speedup = cpu_time / gpu_time
            return
        self.gpu_note = "; ".join(notes)

    def predict_batch(self, arrays: Sequence[np.ndarray]) -> list[dict[str, float]]:
        if not arrays:
            return []
        batch = np.stack(arrays)
        with self._lock:
            out = self._session.run([self._output], {self._input: batch})[0]
        return [{label: float(score) for label, score in zip(self.labels, row)} for row in out]

    def predict(self, image) -> dict[str, float]:
        return self.predict_batch([preprocess(image if isinstance(image, Image.Image) else Image.open(image))])[0]
