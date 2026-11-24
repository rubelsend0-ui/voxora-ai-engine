import pytest

from app.core.errors import ValidationFailed
from app.utils.files import content_type_for, extension_of, sanitize_filename
from app.utils.languages import normalize_language


def test_language_normalisation():
    assert normalize_language("EN") == "en"
    assert normalize_language("zh") == "zh-cn"
    assert normalize_language("pt_BR") == "pt-br"
    assert normalize_language("auto", allow_auto=True) is None
    assert normalize_language(None, allow_auto=True) is None


@pytest.mark.parametrize("bad", ["", "english", "e", "en;drop", "../x"])
def test_language_rejects_garbage(bad):
    with pytest.raises(ValidationFailed):
        normalize_language(bad)


def test_sanitize_filename_strips_paths():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\a\\voice sample.WAV") == "voice sample.WAV"
    assert sanitize_filename("") == "file"
    assert "/" not in sanitize_filename("a/b/c.mp3")


def test_extension_and_content_type():
    assert extension_of("clip.MP4") == "mp4"
    assert extension_of("noext") == ""
    assert content_type_for("mp3") == "audio/mpeg"
    assert content_type_for("exe") == "application/octet-stream"
