"""Container health check (no curl needed). Exit 0 when the API answers /health/live."""

from __future__ import annotations

import os
import sys
import urllib.request

url = os.environ.get("VOXORA_HEALTHCHECK_URL", "http://127.0.0.1:8000/health/live")
try:
    with urllib.request.urlopen(url, timeout=4) as r:  # noqa: S310 - fixed local URL
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
