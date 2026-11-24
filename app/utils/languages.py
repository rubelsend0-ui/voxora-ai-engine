"""Language-code helpers (ISO 639-1 style codes, e.g. ``en``, ``es``, ``zh-cn``)."""

from __future__ import annotations

import re

from app.core.errors import ValidationFailed

_CODE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")

_ALIASES = {"zh": "zh-cn", "zh-hans": "zh-cn", "iw": "he", "jw": "jv"}


def normalize_language(code: str | None, *, allow_auto: bool = False, field: str = "language") -> str | None:
    """Lower-case, validate and canonicalise a language code.

    ``"auto"`` (or an empty value) means *detect* and returns ``None`` when allowed.
    """
    if code is None or code.strip() == "" or code.strip().lower() == "auto":
        if allow_auto:
            return None
        raise ValidationFailed(f"'{field}' is required.", details={"field": field})
    c = code.strip().lower().replace("_", "-")
    c = _ALIASES.get(c, c)
    if not _CODE.match(c):
        raise ValidationFailed(f"'{field}' must be a language code such as 'en' or 'es'.", details={"field": field})
    return c


def base_language(code: str) -> str:
    """``zh-cn`` -> ``zh``."""
    return code.split("-", 1)[0]
