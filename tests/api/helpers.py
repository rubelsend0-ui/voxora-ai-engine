from __future__ import annotations

from tests.media import speechlike_wav

CONSENT = {
    "name": "Alice voice",
    "consent_confirmed": "true",
    "consent_type": "self",
    "consent_holder_name": "Alice Example",
    "language": "en",
}


def clone_voice(client, account, *, data=None, wav=None, filename="sample.wav"):
    payload = {**CONSENT, **(data or {})}
    return client.post(
        "/api/v1/voices/clone",
        headers=account.headers,
        data=payload,
        files={"file": (filename, wav if wav is not None else speechlike_wav(10), "audio/wav")},
    )


def ready_voice(client, account) -> str:
    r = clone_voice(client, account)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["voice"]["status"] == "ready", body
    return body["voice_id"]
