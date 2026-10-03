"""GPU back-end selection, with fake ONNX Runtime sessions (CI machines have no GPU)."""

import json
import time

import numpy as np
import onnxruntime
import pytest

from packfilter import model as model_mod


class FakeSession:
    def __init__(self, provider, offset=0.0, delay=0.0, fail=False):
        if fail:
            raise RuntimeError("driver exploded\nmore detail")
        self.provider, self.offset, self.delay = provider, offset, delay

    def get_providers(self):
        return [self.provider, "CPUExecutionProvider"]

    def get_inputs(self):
        return [type("I", (), {"name": "input"})()]

    def get_outputs(self):
        return [type("O", (), {"name": "output"})()]

    def run(self, names, feed):
        time.sleep(self.delay)
        x = feed["input"]
        base = np.tile([0.7, 0.1, 0.1, 0.1], (x.shape[0], 1)).astype(np.float32)
        return [base + self.offset]


@pytest.fixture
def model_dir(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"labels": ["general", "sensitive", "questionable", "explicit"]}))
    (tmp_path / "model.onnx").write_bytes(b"")
    return tmp_path


def use(monkeypatch, gpu: dict, available=("DmlExecutionProvider", "CPUExecutionProvider")):
    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: list(available))

    def fake_session(ort, path, provider):
        if provider == "CPUExecutionProvider":
            return FakeSession(provider, delay=0.01)
        return FakeSession(provider, **gpu)
    monkeypatch.setattr(model_mod, "_session", fake_session)


def test_fast_and_correct_gpu_is_used(monkeypatch, model_dir):
    use(monkeypatch, dict(delay=0.001))
    m = model_mod.RatingModel("x", model_dir, use_gpu=True)
    assert m.device == "GPU (DirectML)" and m.batch_size == 32 and m.speedup > 1


def test_gpu_with_wrong_results_is_rejected(monkeypatch, model_dir):
    use(monkeypatch, dict(delay=0.001, offset=0.3))
    m = model_mod.RatingModel("x", model_dir, use_gpu=True)
    assert m.device == "CPU" and "different results" in m.gpu_note


def test_slower_gpu_is_rejected(monkeypatch, model_dir):
    use(monkeypatch, dict(delay=0.05))  # e.g. DirectML on a software (WARP) adapter
    m = model_mod.RatingModel("x", model_dir, use_gpu=True)
    assert m.device == "CPU" and "not faster" in m.gpu_note


def test_broken_gpu_falls_back(monkeypatch, model_dir):
    use(monkeypatch, dict(fail=True))
    m = model_mod.RatingModel("x", model_dir, use_gpu=True)
    assert m.device == "CPU" and "driver exploded" in m.gpu_note and "\n" not in m.gpu_note


def test_cuda_preferred_over_directml(monkeypatch, model_dir):
    use(monkeypatch, dict(delay=0.001),
        available=("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"))
    assert model_mod.RatingModel("x", model_dir, use_gpu=True).device == "GPU (NVIDIA CUDA)"


def test_gpu_off_or_unavailable(monkeypatch, model_dir):
    use(monkeypatch, dict(delay=0.001))
    assert model_mod.RatingModel("x", model_dir, use_gpu=False).device == "CPU"
    use(monkeypatch, dict(delay=0.001), available=("CoreMLExecutionProvider", "CPUExecutionProvider"))
    m = model_mod.RatingModel("x", model_dir, use_gpu=True)
    assert m.device == "CPU" and "no GPU support" in m.gpu_note
