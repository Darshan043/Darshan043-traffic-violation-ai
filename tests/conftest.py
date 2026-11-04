from __future__ import annotations

import sys

import pytest


@pytest.fixture(scope="session", autouse=True)
def default_suite_does_not_initialize_models(request):
    yield
    if "not integration" not in request.config.getoption("markexpr"):
        return

    torch = sys.modules.get("torch")
    assert torch is None or not torch.cuda.is_initialized()
    assert torch is None, "The default suite must not import Torch or load model weights"
    assert "ultralytics" not in sys.modules
