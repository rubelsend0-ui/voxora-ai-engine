"""Print a setup report: device, FFmpeg and the status/hint of every AI engine.

    python -m scripts.doctor
"""

from __future__ import annotations

from app.ai_engine.device import cuda_available, has_module
from app.ai_engine.registry import get_registry
from app.core.config import get_settings


def main() -> int:
    s = get_settings()
    print(f"models dir : {s.models_root}")
    print(f"storage dir: {s.storage_root}")
    print(f"torch      : {'installed' if has_module('torch') else 'NOT installed'}")
    print(f"CUDA       : {'available' if cuda_available() else 'not available (CPU will be used)'}")
    print()
    all_ok = True
    for kind, st in get_registry().statuses().items():
        mark = "OK " if st.available else "-- "
        all_ok &= st.available
        print(f"[{mark}] {kind:17s} adapter={st.adapter} device={st.device or '-'}")
        if not st.available:
            print(f"        reason: {st.reason}")
            if st.hint:
                print(f"        hint  : {st.hint}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
