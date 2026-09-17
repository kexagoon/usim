"""Internationalization: DE default, RU second; cookie/localStorage bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "locales"

SUPPORTED = ("de", "ru")
DEFAULT_LANG = "de"

_cache: dict[str, dict[str, Any]] = {}


def load_locale(lang: str) -> dict[str, Any]:
    lang = (lang or DEFAULT_LANG).lower()
    if lang not in SUPPORTED:
        lang = DEFAULT_LANG
    if lang in _cache:
        return _cache[lang]
    path = LOCALES_DIR / f"{lang}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[lang] = data
    return data


def t(lang: str, key: str, **kwargs: Any) -> str:
    data = load_locale(lang)
    parts = key.split(".")
    cur: Any = data
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            # fallback to DE
            cur = load_locale(DEFAULT_LANG)
            for p2 in parts:
                if not isinstance(cur, dict) or p2 not in cur:
                    return key
                cur = cur[p2]
            break
        cur = cur[p]
    if not isinstance(cur, str):
        return key
    if kwargs:
        try:
            return cur.format(**kwargs)
        except (KeyError, ValueError):
            return cur
    return cur


def all_strings(lang: str) -> dict[str, Any]:
    return load_locale(lang)


def list_langs() -> list[dict[str, str]]:
    return [
        {"code": "de", "label": "DE"},
        {"code": "ru", "label": "RU"},
    ]
