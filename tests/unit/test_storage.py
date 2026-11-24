import io

import pytest

from app.core.errors import PayloadTooLarge, ValidationFailed
from app.storage.local import LocalStorage


def test_save_stream_and_hash(tmp_path):
    st = LocalStorage(tmp_path)
    key = st.new_key("uploads", "usr_1", "wav")
    obj = st.save_stream(key, io.BytesIO(b"abc" * 100), max_bytes=1000)
    assert obj.size_bytes == 300 and len(obj.sha256) == 64
    assert st.exists(key)
    assert st.local_path(key).read_bytes() == b"abc" * 100


def test_size_limit_enforced_while_streaming_and_partial_removed(tmp_path):
    st = LocalStorage(tmp_path)
    key = st.new_key("uploads", "usr_1", "bin")
    with pytest.raises(PayloadTooLarge):
        st.save_stream(key, io.BytesIO(b"x" * 5000), max_bytes=1000)
    assert not st.exists(key)


def test_empty_upload_rejected(tmp_path):
    st = LocalStorage(tmp_path)
    with pytest.raises(ValidationFailed):
        st.save_stream(st.new_key("uploads", "u", "wav"), io.BytesIO(b""))


@pytest.mark.parametrize(
    "key",
    ["../etc/passwd", "uploads/../../x", "uploads/a/../../../x", "/etc/passwd", "nope/u/f.wav", "uploads", "uploads//x"],
)
def test_traversal_and_bad_keys_rejected(tmp_path, key):
    st = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        st.local_path(key)


def test_build_key_validation(tmp_path):
    st = LocalStorage(tmp_path)
    assert st.build_key("voices", "usr_1", "voc_2", "reference.wav") == "voices/usr_1/voc_2/reference.wav"
    with pytest.raises(ValueError):
        st.build_key("voices", "usr_1", "../x")
    with pytest.raises(ValueError):
        st.build_key("secrets", "a")


def test_move_and_delete_prefix(tmp_path):
    st = LocalStorage(tmp_path)
    src = st.new_key("tmp", "u", "wav")
    st.save_stream(src, io.BytesIO(b"1234"))
    dst = st.build_key("voices", "u", "v1", "reference.wav")
    st.move(src, dst)
    assert st.exists(dst) and not st.exists(src)
    st.delete_prefix("voices/u/v1")
    assert not st.exists(dst)
    with pytest.raises(ValueError):
        st.delete_prefix("voices/u")  # too broad


def test_healthy(tmp_path):
    assert LocalStorage(tmp_path).healthy()
