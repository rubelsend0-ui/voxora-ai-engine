"""Compute-device resolution that degrades gracefully when torch/CUDA are missing."""

from __future__ import annotations

import importlib.util
import logging

log = logging.getLogger("voxora.device")


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def cuda_available() -> bool:
    if not has_module("torch"):
        return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # broken CUDA install must not crash the API
        return False


def resolve_device(preference: str) -> str:
    """``auto`` -> cuda when usable, else cpu. An explicit ``cuda`` without a GPU falls back to cpu."""
    if preference == "cpu":
        return "cpu"
    if cuda_available():
        return "cuda"
    if preference == "cuda":
        log.warning("VOXORA_DEVICE=cuda requested but CUDA is unavailable; falling back to CPU")
    return "cpu"
