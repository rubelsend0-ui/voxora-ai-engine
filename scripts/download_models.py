"""Download model weights into VOXORA_MODELS_DIR (kept separate from user media). Weights are never committed.

    python -m scripts.download_models --whisper small
    python -m scripts.download_models --translation en-es,es-en
    python -m scripts.download_models --xtts --accept-coqui-cpml

LICENSES (see docs/LICENSES.md): XTTS-v2 weights are under the Coqui Public Model License (CPML), which
allows NON-COMMERCIAL use only. You must pass --accept-coqui-cpml to confirm you have read it
(https://coqui.ai/cpml) and that your use is non-commercial.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings

WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def _snapshot(repo: str, target) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("huggingface_hub is not installed. Run: pip install -r requirements-ai.txt")
    target.mkdir(parents=True, exist_ok=True)
    print(f"-> downloading {repo} into {target}")
    snapshot_download(repo_id=repo, local_dir=str(target))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xtts", action="store_true", help="download coqui/XTTS-v2 (~2 GB)")
    p.add_argument("--accept-coqui-cpml", action="store_true", help="confirm you accept the CPML (non-commercial)")
    p.add_argument("--whisper", metavar="SIZE", help=f"one of: {', '.join(WHISPER_REPOS)}")
    p.add_argument("--translation", metavar="PAIRS", help="comma separated OPUS-MT pairs, e.g. en-es,es-en")
    args = p.parse_args()
    if not (args.xtts or args.whisper or args.translation):
        p.print_help()
        return 1

    root = get_settings().models_root
    if args.xtts:
        if not args.accept_coqui_cpml:
            sys.exit(
                "XTTS-v2 is licensed under the Coqui Public Model License (non-commercial use only).\n"
                "Read https://coqui.ai/cpml and re-run with --accept-coqui-cpml to proceed."
            )
        _snapshot("coqui/XTTS-v2", root / "xtts_v2")
    if args.whisper:
        if args.whisper not in WHISPER_REPOS:
            sys.exit(f"Unknown Whisper size '{args.whisper}'. Choose from: {', '.join(WHISPER_REPOS)}")
        _snapshot(WHISPER_REPOS[args.whisper], root / "whisper" / args.whisper)
    if args.translation:
        for pair in [x.strip() for x in args.translation.split(",") if x.strip()]:
            if pair.count("-") != 1:
                sys.exit(f"Bad pair '{pair}'. Use the form 'en-es'.")
            _snapshot(f"Helsinki-NLP/opus-mt-{pair}", root / "translation" / f"opus-mt-{pair}")
    print("Done. Check status with: python -m scripts.doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
