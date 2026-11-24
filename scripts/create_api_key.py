"""Create a user (if needed) and issue an API key. The key is printed ONCE and only its hash is stored.

    python -m scripts.create_api_key --email you@example.com --name "android-app"
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import generate_api_key, hash_api_key
from app.database.session import create_all_tables, session_scope
from app.models import ApiKey, User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="default", help="label for this key (e.g. 'android-app')")
    parser.add_argument("--display-name", default=None)
    args = parser.parse_args()

    settings = get_settings()
    if settings.auto_create_tables:
        create_all_tables()
    raw, prefix = generate_api_key()
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            user = User(email=args.email.lower(), display_name=args.display_name)
            db.add(user)
            db.flush()
        db.add(
            ApiKey(
                user_id=user.id,
                name=args.name,
                key_prefix=prefix,
                key_hash=hash_api_key(raw, settings.api_key_pepper),
            )
        )
        user_id = user.id
    print(f"user_id : {user_id}")
    print(f"api_key : {raw}")
    print("Store this key now - it cannot be shown again. Send it as the X-API-Key header.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
