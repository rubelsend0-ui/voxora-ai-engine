# Deployment

## Hardware (approximate - measure on your machine)
| Setup | Notes |
|---|---|
| **CPU only** | Everything works; XTTS-v2 synthesis is far slower than real time (minutes for a short paragraph) and dubbing is slow. Fine for development. 16 GB RAM recommended. |
| **NVIDIA GPU** | Recommended for XTTS-v2: ~6 GB VRAM or more, CUDA 12.x driver. Whisper `small` needs ~1-2 GB, `large-v3` ~5-10 GB. Run **one** job at a time per GPU (`VOXORA_LOCAL_WORKERS=1`, Celery `--concurrency=1`). |
| Disk | XTTS-v2 ~2 GB, Whisper small ~0.5 GB (large-v3 ~3 GB), each OPUS-MT pair ~0.3 GB, plus media. |
Without a GPU the engine falls back to CPU automatically (`VOXORA_DEVICE=auto`); `GET /engines` shows the device in use.

## 1. Local CPU
See README quick start.

## 2. Local NVIDIA GPU
```bash
nvidia-smi                                   # driver must support CUDA 12.x
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements-ai.txt
python -m scripts.doctor                     # CUDA: available
```
(If your driver is older, pick the matching index from pytorch.org.)

## 3. Docker
```bash
cp .env.example .env     # set POSTGRES_PASSWORD and VOXORA_API_KEY_PEPPER (python -c "import secrets;print(secrets.token_urlsafe(48))")
docker compose up -d --build                                     # API + Celery worker + Redis + PostgreSQL (CPU)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build   # NVIDIA (needs NVIDIA Container Toolkit)
docker compose -f docker-compose.local.yml up --build            # lightweight: 1 container, SQLite, no Redis
docker compose run --rm api python -m scripts.download_models --whisper small --translation en-es --xtts --accept-coqui-cpml
docker compose run --rm api python -m scripts.doctor
docker compose run --rm api python -m scripts.create_api_key --email you@example.com --name android
```
Build the slim API-only image with `--build-arg INSTALL_AI=false`. Health: `GET /health/live` (liveness, used by the image
HEALTHCHECK), `GET /health/ready` (database + storage; lists which engines are usable).

## 4. Linux server (systemd + nginx)
```bash
sudo apt install ffmpeg libsndfile1 python3.11 python3.11-venv redis-server postgresql
sudo useradd -r -m voxora && sudo -u voxora bash -c 'git clone <repo> /opt/voxora && cd /opt/voxora && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt'
# install torch + requirements-ai.txt as in sections 1-2, create /opt/voxora/.env (production values), then:
sudo -u voxora /opt/voxora/.venv/bin/alembic upgrade head
```
`/etc/systemd/system/voxora-api.service`
```ini
[Service]
User=voxora
WorkingDirectory=/opt/voxora
EnvironmentFile=/opt/voxora/.env
ExecStart=/opt/voxora/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --workers 2
Restart=always
```
`/etc/systemd/system/voxora-worker.service` (when `VOXORA_JOB_BACKEND=celery`)
```ini
[Service]
User=voxora
WorkingDirectory=/opt/voxora
EnvironmentFile=/opt/voxora/.env
ExecStart=/opt/voxora/.venv/bin/celery -A app.workers.celery_app.celery_app worker --concurrency=1 -Q voxora --loglevel=info
Restart=always
```
With `VOXORA_JOB_BACKEND=local` use a **single** uvicorn worker. nginx: terminate TLS, `client_max_body_size 600m;`,
`proxy_read_timeout 300s;`, proxy to 127.0.0.1:8000. Never expose Redis/PostgreSQL publicly.

## 5. Environment configuration
All settings are `VOXORA_*` variables - see `.env.example`. Production requires a >= 32-char `VOXORA_API_KEY_PEPPER`
(the app refuses to start otherwise). Put secrets in the environment/secret store, never in git or CI logs.

## 6. Models
`python -m scripts.download_models --whisper small --translation en-es,es-en --xtts --accept-coqui-cpml`
Stored in `VOXORA_MODELS_DIR` (default `./data/models`), separate from user media. Verify with `python -m scripts.doctor`.
Read docs/LICENSES.md first: XTTS-v2 is non-commercial.

## 7. Backups & operations
Back up the database and `VOXORA_DATA_DIR/storage` (voices contain biometric data - encrypt the disk, restrict access).
Models can be re-downloaded. Logs go to stdout. Migrations: `alembic upgrade head` (PostgreSQL) on every release.
