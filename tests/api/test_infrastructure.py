from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.database.session import session_scope
from app.models import Base, Job, User, Voice
from app.workers.runner import recover_jobs
from tests.conftest import make_account


def test_alembic_migration_matches_models(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from tests.conftest import reset_caches, set_env

    set_env(tmp_path, monkeypatch, VOXORA_AUTO_CREATE_TABLES="false")
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    for table in Base.metadata.sorted_tables:
        assert table.name in insp.get_table_names(), table.name
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        assert db_cols == {c.name for c in table.columns}, table.name
    reset_caches()


def test_interrupted_jobs_are_failed_and_queued_jobs_resubmitted(client):
    acct = make_account("rec@example.com")
    with session_scope() as db:
        v = Voice(user_id=acct.id, name="v", status="processing", consent={})
        db.add(v)
        db.flush()
        running = Job(user_id=acct.id, type="voice_clone", status="processing", params={"voice_id": v.id})
        waiting = Job(user_id=acct.id, type="speech", status="queued", params={})
        db.add_all([running, waiting])
        db.flush()
        running_id, waiting_id, voice_id = running.id, waiting.id, v.id
    submitted: list[str] = []
    recover_jobs(submitted.append)
    assert submitted == [waiting_id]
    with session_scope() as db:
        assert db.get(Job, running_id).error_code == "JOB_INTERRUPTED"
        assert db.get(Voice, voice_id).status == "failed"
        assert db.get(Job, waiting_id).status == "queued"
    assert User  # keep import used


def test_progress_is_monotonic_and_persisted(client, alice, fakes):
    from tests.api.helpers import ready_voice

    vid = ready_voice(client, alice)
    job_id = client.post("/api/v1/speech/generate", headers=alice.headers,
                         json={"voice_id": vid, "text": "One. Two. Three.", "language": "en"}).json()["job_id"]
    job = client.get(f"/api/v1/jobs/{job_id}", headers=alice.headers).json()
    assert job["progress"] == 100 and job["stage"] == "Completed"
    assert job["started_at"] and job["finished_at"]
