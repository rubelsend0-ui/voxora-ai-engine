"""Text translation with Helsinki-NLP OPUS-MT (MarianMT) models, one model per language pair.

Pairs are downloaded explicitly (``scripts.download_models --translation en-es``) into
``<models_dir>/translation/opus-mt-<src>-<tgt>``. If no direct model exists but both
``src->en`` and ``en->tgt`` do, translation is pivoted through English (lower quality).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

from app.ai_engine.base import EngineStatus, TranslationEngine
from app.ai_engine.device import has_module, resolve_device
from app.core.config import Settings
from app.core.errors import AIEngineError, AIEngineNotConfigured
from app.utils.languages import base_language

log = logging.getLogger("voxora.translation")

_BATCH = 16
_MAX_CACHED = 3


class MarianTranslationAdapter(TranslationEngine):
    adapter_name = "marian"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._root = settings.models_root / "translation"
        self._lock = threading.RLock()
        self._loaded: dict[str, tuple[Any, Any]] = {}  # pair -> (tokenizer, model)

    # ---------------------------------------------------------------- pairs
    def _pair_dir(self, src: str, tgt: str):
        return self._root / f"opus-mt-{base_language(src)}-{base_language(tgt)}"

    def _has_model(self, src: str, tgt: str) -> bool:
        d = self._pair_dir(src, tgt)
        return d.is_dir() and (d / "config.json").is_file()

    def available_pairs(self) -> list[str]:
        if not self._root.is_dir():
            return []
        pairs = []
        for d in sorted(self._root.iterdir()):
            if d.is_dir() and d.name.startswith("opus-mt-") and (d / "config.json").is_file():
                pairs.append(d.name.removeprefix("opus-mt-"))
        return pairs

    def _route(self, src: str, tgt: str) -> list[tuple[str, str]] | None:
        if base_language(src) == base_language(tgt):
            return []
        if self._has_model(src, tgt):
            return [(src, tgt)]
        if base_language(src) != "en" and base_language(tgt) != "en":
            if self._has_model(src, "en") and self._has_model("en", tgt):
                return [(src, "en"), ("en", tgt)]
        return None

    def supports_pair(self, source: str, target: str) -> bool:
        return self._route(source, target) is not None

    # --------------------------------------------------------------- status
    def status(self) -> EngineStatus:
        deps = [m for m in ("torch", "transformers", "sentencepiece") if not has_module(m)]
        if deps:
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                reason=f"Python packages not installed: {', '.join(deps)}.",
                hint="pip install -r requirements-ai.txt",
            )
        pairs = self.available_pairs()
        if not pairs:
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                reason="No translation models have been downloaded.",
                hint="Run: python -m scripts.download_models --translation en-es,es-en",
            )
        return EngineStatus(
            available=True,
            adapter=self.adapter_name,
            model="Helsinki-NLP/opus-mt",
            device=resolve_device(self._settings.device),
            details={"pairs": pairs},
        )

    # ------------------------------------------------------------- inference
    def _load(self, src: str, tgt: str) -> tuple[Any, Any]:
        key = f"{base_language(src)}-{base_language(tgt)}"
        with self._lock:
            if key in self._loaded:
                return self._loaded[key]
            try:
                from transformers import MarianMTModel, MarianTokenizer

                path = str(self._pair_dir(src, tgt))
                tok = MarianTokenizer.from_pretrained(path)
                model = MarianMTModel.from_pretrained(path).to(resolve_device(self._settings.device))
                model.eval()
            except Exception as exc:
                log.exception("Failed to load translation model %s", key)
                raise AIEngineError("A translation model failed to load. See server logs.") from exc
            if len(self._loaded) >= _MAX_CACHED:
                self._loaded.pop(next(iter(self._loaded)))
            self._loaded[key] = (tok, model)
            return tok, model

    def _translate_direct(self, texts: list[str], src: str, tgt: str) -> list[str]:
        import torch

        tok, model = self._load(src, tgt)
        device = next(model.parameters()).device
        out: list[str] = []
        for i in range(0, len(texts), _BATCH):
            batch = texts[i : i + _BATCH]
            enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
            with torch.no_grad():
                gen = model.generate(**enc, num_beams=4, max_new_tokens=512)
            out.extend(tok.batch_decode(gen, skip_special_tokens=True))
        return out

    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]:
        st = self.status()
        if not st.available:
            raise AIEngineNotConfigured("translation", st.reason or "unavailable", hint=st.hint)
        route = self._route(source, target)
        if route is None:
            raise AIEngineNotConfigured(
                "translation",
                f"No translation model for {source}->{target}.",
                hint=f"Run: python -m scripts.download_models --translation {base_language(source)}-{base_language(target)}",
            )
        items = list(texts)
        idx = [i for i, t in enumerate(items) if t and t.strip()]
        current = [items[i] for i in idx]
        with self._lock:
            for s, t in route:
                current = self._translate_direct(current, s, t)
        result = list(items)
        for i, tr in zip(idx, current, strict=True):
            result[i] = tr
        return result
