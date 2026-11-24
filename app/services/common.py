from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound

T = TypeVar("T")


def get_owned(db: Session, model: type[T], object_id: str, user_id: str, what: str) -> T:
    """Fetch a row owned by ``user_id``. Foreign rows are indistinguishable from missing ones (404)."""
    obj = db.get(model, object_id)
    if obj is None or getattr(obj, "user_id", None) != user_id:
        raise NotFound(f"{what} not found.")
    return obj


def paginate(db: Session, stmt: Select[Any], order_by: Any, limit: int, offset: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(order_by).limit(limit).offset(offset)))
    return rows, int(total)
