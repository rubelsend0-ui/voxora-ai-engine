import pytest

from app.ai_engine.base import EngineStatus, TranslationEngine
from app.ai_engine.registry import KINDS, EngineRegistry
from app.core.config import Settings
from app.core.errors import AIEngineNotConfigured


def _settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path, **kw)


def test_all_kinds_have_statuses_without_ai_packages(tmp_path):
    reg = EngineRegistry(_settings(tmp_path))
    statuses = reg.statuses()
    assert set(statuses) == set(KINDS)
    # Nothing is downloaded in a fresh data dir, so model-backed engines must say so honestly.
    for kind in ("voice_cloning", "text_to_speech", "speech_to_text", "translation"):
        assert statuses[kind].available is False
        assert statuses[kind].reason


def test_require_raises_ai_engine_not_configured(tmp_path):
    reg = EngineRegistry(_settings(tmp_path))
    with pytest.raises(AIEngineNotConfigured) as ei:
        reg.require("text_to_speech")
    assert ei.value.code == "AI_ENGINE_NOT_CONFIGURED"
    assert ei.value.status_code == 503
    assert ei.value.details["engine"] == "text_to_speech"
    assert "reason" in ei.value.details


def test_dubbing_unavailable_when_components_missing(tmp_path):
    reg = EngineRegistry(_settings(tmp_path))
    with pytest.raises(AIEngineNotConfigured):
        reg.require("dubbing")


def test_unknown_adapter_name_is_reported(tmp_path):
    reg = EngineRegistry(_settings(tmp_path, tts_adapter="does_not_exist"))
    with pytest.raises(AIEngineNotConfigured) as ei:
        reg.get("text_to_speech")
    assert "does_not_exist" in ei.value.details["reason"]


def test_custom_adapter_can_be_registered(tmp_path):
    class Dummy(TranslationEngine):
        adapter_name = "dummy"

        def status(self):
            return EngineStatus(available=True, adapter="dummy")

        def supports_pair(self, s, t):
            return True

        def available_pairs(self):
            return ["xx-yy"]

        def translate(self, texts, s, t):
            return list(texts)

    reg = EngineRegistry(_settings(tmp_path, translation_adapter="dummy"))
    reg.register_adapter("translation", "dummy", lambda r: Dummy())
    assert reg.require("translation").adapter_name == "dummy"
