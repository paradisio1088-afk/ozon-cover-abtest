"""Общие утилиты: загрузка .env и config.toml, работа со временем МСК."""

from __future__ import annotations

import os
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

MSK = timezone(timedelta(hours=3))  # Москва, без перехода на летнее время


def load_env(path: Path | None = None) -> None:
    """Подгружает пары KEY=VALUE из .env в os.environ (не перетирая уже заданные)."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def require_env(*names: str) -> list[str]:
    load_env()
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"Не заданы переменные окружения: {', '.join(missing)} (см. .env.example)")
    return [os.environ[n] for n in names]


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.toml"
    if not path.exists():
        raise SystemExit(f"Нет файла конфигурации: {path}")
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)

    test = cfg.get("test", {})
    variants = cfg.get("variants", [])
    if len(variants) < 2:
        raise SystemExit("В config.toml нужно минимум 2 варианта обложки ([[variants]])")
    if not test.get("product_id"):
        raise SystemExit("В config.toml не задан test.product_id")

    test["start_dt"] = parse_msk(test["start"])
    test["n_variants"] = len(variants)
    test["total_blocks"] = int(test["cycles"]) * len(variants)
    cfg["test"], cfg["variants"] = test, variants
    return cfg


def parse_msk(value: str) -> datetime:
    """'YYYY-MM-DDTHH:MM' (или с пробелом) -> aware datetime в МСК."""
    value = value.strip().replace(" ", "T")
    if len(value) == 16:
        value += ":00"
    return datetime.fromisoformat(value).replace(tzinfo=MSK)


def now_msk() -> datetime:
    return datetime.now(MSK)


def msk_date(dt: datetime) -> str:
    return dt.astimezone(MSK).strftime("%Y-%m-%d")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
