from __future__ import annotations

from tests.api.helpers import ready_voice
from tests.media import speechlike_wav


def test_jobs_list_filter_and_isolation(client, alice, bob, fakes):
    vid = ready_voice(client, alice)
    client.post("/api/v1/speech/generate", headers=alice.headers,
                json={"voice_id": vid, "text": "Hi there.", "language": "en"})
    jobs = client.get("/api/v1/jobs", headers=alice.headers).json()
    assert jobs["total"] == 2
    assert client.get("/api/v1/jobs?type=speech", headers=alice.headers).json()["total"] == 1
    assert client.get("/api/v1/jobs?status=failed", headers=alice.headers).json()["total"] == 0
    assert client.get("/api/v1/jobs", headers=bob.headers).json()["total"] == 0
    assert client.get("/api/v1/jobs?type=bogus", headers=alice.headers).status_code == 422
    assert client.get("/api/v1/jobs?limit=1&offset=1", headers=alice.headers).json()["items"].__len__() == 1


def test_project_crud_and_job_association(client, alice, bob, fakes):
    p = client.post("/api/v1/projects", headers=alice.headers, json={"name": "Podcast", "description": "ep 1"})
    assert p.status_code == 201
    pid = p.json()["project_id"]
    vid = ready_voice(client, alice)
    r = client.post("/api/v1/speech/generate", headers=alice.headers,
                    json={"voice_id": vid, "text": "Hello.", "language": "en", "project_id": pid})
    assert r.status_code == 202
    jobs = client.get(f"/api/v1/projects/{pid}/jobs", headers=alice.headers).json()
    assert jobs["total"] == 1 and jobs["items"][0]["project_id"] == pid

    assert client.patch(f"/api/v1/projects/{pid}", headers=alice.headers, json={"name": "Podcast 2"}).json()["name"] == "Podcast 2"
    assert client.get(f"/api/v1/projects/{pid}", headers=bob.headers).status_code == 404
    # bob cannot attach his jobs to alice's project
    bv = ready_voice(client, bob)
    rb = client.post("/api/v1/speech/generate", headers=bob.headers,
                     json={"voice_id": bv, "text": "Hello.", "language": "en", "project_id": pid})
    assert rb.status_code == 404

    assert client.delete(f"/api/v1/projects/{pid}", headers=alice.headers).status_code == 204
    assert client.get(f"/api/v1/projects/{pid}", headers=alice.headers).status_code == 404
    assert client.get("/api/v1/jobs?type=speech", headers=alice.headers).json()["items"][0]["project_id"] is None


def test_file_management(client, alice, bob, fakes):
    up = client.post("/api/v1/files", headers=alice.headers,
                     files={"file": ("../../evil name.wav", speechlike_wav(4), "audio/wav")})
    assert up.status_code == 201, up.text
    f = up.json()
    assert f["filename"] == "evil name.wav" and f["kind"] == "upload" and f["duration_seconds"] > 3.9
    assert "storage" not in up.text and "uploads/" not in up.text

    assert client.get(f"/api/v1/files/{f['file_id']}", headers=alice.headers).json()["sha256"] == f["sha256"]
    dl = client.get(f"/api/v1/files/{f['file_id']}/download", headers=alice.headers)
    assert dl.status_code == 200 and len(dl.content) == f["size_bytes"]
    assert client.get(f"/api/v1/files/{f['file_id']}/download", headers=bob.headers).status_code == 404
    assert client.get("/api/v1/files?kind=upload", headers=alice.headers).json()["total"] == 1
    assert client.delete(f"/api/v1/files/{f['file_id']}", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/v1/files/{f['file_id']}", headers=alice.headers).status_code == 204
    assert client.get(f"/api/v1/files/{f['file_id']}", headers=alice.headers).status_code == 404


def test_generated_audio_is_listed_as_a_file(client, alice, fakes):
    vid = ready_voice(client, alice)
    job = client.post("/api/v1/speech/generate", headers=alice.headers,
                      json={"voice_id": vid, "text": "Hello.", "language": "en"}).json()["job_id"]
    fid = client.get(f"/api/v1/jobs/{job}", headers=alice.headers).json()["result"]["file_id"]
    meta = client.get(f"/api/v1/files/{fid}", headers=alice.headers).json()
    assert meta["kind"] == "generated" and meta["content_type"] == "audio/wav"
