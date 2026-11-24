# CPU image. For NVIDIA GPUs use docker/Dockerfile.gpu (see docs/DEPLOYMENT.md).
# Build without ML packages (fast, API only):  docker build --build-arg INSTALL_AI=false -t voxora-ai-engine .
FROM python:3.11-slim

ARG INSTALL_AI=true
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VOXORA_DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/voxora
COPY requirements.txt requirements-ai.txt ./
RUN pip install -r requirements.txt
RUN if [ "$INSTALL_AI" = "true" ]; then \
      pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
      && pip install -r requirements-ai.txt ; \
    fi

COPY . .
RUN useradd --create-home --uid 10001 voxora && mkdir -p /data && chown -R voxora:voxora /data /srv/voxora
USER voxora
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "scripts/healthcheck.py"]
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
