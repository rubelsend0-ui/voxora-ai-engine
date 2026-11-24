#!/bin/sh
set -e
mkdir -p "${VOXORA_DATA_DIR:-/data}/storage" "${VOXORA_DATA_DIR:-/data}/models" "${VOXORA_DATA_DIR:-/data}/tmp"
if [ "${VOXORA_RUN_MIGRATIONS:-true}" = "true" ] && [ "${VOXORA_AUTO_CREATE_TABLES:-false}" != "true" ]; then
  alembic upgrade head
fi
exec "$@"
