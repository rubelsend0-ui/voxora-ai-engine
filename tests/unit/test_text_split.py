from app.utils.text import split_text


def test_empty():
    assert split_text("   ") == []


def test_short_text_single_chunk():
    assert split_text("Hello there.") == ["Hello there."]


def test_sentences_respect_limit_and_preserve_words():
    text = " ".join(f"This is sentence number {i}, with a clause, and more words to make it long." for i in range(12))
    chunks = split_text(text, 120)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_unbroken_run_is_hard_split():
    chunks = split_text("あ" * 500, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == "あ" * 500
