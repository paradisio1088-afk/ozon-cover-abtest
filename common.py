"""Конфиг, секреты и работа со временем МСК.

Всё хранится в data/:
  secrets.json  — ключи Ozon и GitHub (права 0600, в .gitignore)
  config.json   — параметры теста и варианты обложек (можно коммитить)
  state.json    — журнал переключений
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SECRETS_PATH = DATA_DIR / "secrets.json"
CONFIG_PATH = DATA_DIR / "config.json"

MSK = timezone(timedelta(hours=3))  # Москва, без перехода на летнее время

SECRET_KEYS = [
    "ozon_client_id", "ozon_api_key",
    "perf_client_id", "perf_client_secret",
    "github_repo", "github_token",
]

DEFAULT_CONFIG = {
    "name": "cover-ctr",
    "product_id": 0,
    "offer_id": "",
    "campaign_ids": [],
    "start": "",                      # 'YYYY-MM-DDTHH:MM' МСК; пусто = тест не запущен
    "block_minutes": 360,             # длина блока показа варианта (360 = 6 часов)
    "cycles": 2,
    "settle_minutes": 60,             # сколько пропустить в начале блока (прогрев + подмена фото)
    "shuffle_each_cycle": True,
    "min_impressions_per_variant": 1000,
    "apply_winner_on_finish": False,
    "enabled": False,                # включает фоновую ротацию
    "variants": [],                  # [{name, url, filename, sha}]
}

# минимально допустимые значения (защита от совсем нерабочих настроек)
MIN_BLOCK_MINUTES = 30
MIN_IMPRESSIONS = 100


# ─── секреты ─────────────────────────────────────────────────────────────────

def load_secrets() -> dict:
    data = {}
    if SECRETS_PATH.exists():
        data = json.loads(SECRETS_PATH.read_text())
    # переменные окружения имеют приоритет (для CI/launchd)
    env_map = {
        "ozon_client_id": "OZON_CLIENT_ID", "ozon_api_key": "OZON_API_KEY",
        "perf_client_id": "OZON_PERF_CLIENT_ID", "perf_client_secret": "OZON_PERF_CLIENT_SECRET",
        "github_repo": "GITHUB_REPO", "github_token": "GITHUB_TOKEN",
    }
    for k, env in env_map.items():
        if os.environ.get(env):
            data[k] = os.environ[env]
    return data


def save_secrets(patch: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    cur = {}
    if SECRETS_PATH.exists():
        cur = json.loads(SECRETS_PATH.read_text())
    for k in SECRET_KEYS:
        if k in patch and patch[k] != "":
            cur[k] = patch[k].strip() if isinstance(patch[k], str) else patch[k]
    SECRETS_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2))
    os.chmod(SECRETS_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def secret(name: str) -> str:
    val = load_secrets().get(name, "")
    if not val:
        raise SystemExit(f"Не задан ключ «{name}» — впиши его в интерфейсе (раздел «Подключение»)")
    return val


def ozon_creds() -> dict:
    """Ключи Ozon: {client_id, api_key, perf_client_id, perf_client_secret}."""
    s = load_secrets()
    return {
        "client_id": s.get("ozon_client_id", ""),
        "api_key": s.get("ozon_api_key", ""),
        "perf_client_id": s.get("perf_client_id", ""),
        "perf_client_secret": s.get("perf_client_secret", ""),
    }


# ─── конфиг ──────────────────────────────────────────────────────────────────

def load_config_raw() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    return cfg


def save_config(patch: dict) -> dict:
    cfg = load_config_raw()
    for k, v in patch.items():
        if k in DEFAULT_CONFIG:
            cfg[k] = v
    cfg["block_minutes"] = max(int(cfg.get("block_minutes") or 0), MIN_BLOCK_MINUTES)
    cfg["settle_minutes"] = max(int(cfg.get("settle_minutes") or 0), 0)
    cfg["cycles"] = max(int(cfg.get("cycles") or 1), 1)
    cfg["min_impressions_per_variant"] = max(
        int(cfg.get("min_impressions_per_variant") or 0), MIN_IMPRESSIONS)
    DATA_DIR.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    return cfg


def load_config() -> dict:
    """Конфиг в форме, которую ждут abtest/collect/analyze:
    {"test": {..., start_dt, n_variants, total_blocks}, "variants": [...]}"""
    raw = load_config_raw()
    variants = raw.get("variants", [])
    test = {k: raw[k] for k in DEFAULT_CONFIG if k != "variants"}
    test["n_variants"] = len(variants)
    test["total_blocks"] = int(test["cycles"]) * max(len(variants), 1)
    test["start_dt"] = parse_msk(test["start"]) if test.get("start") else None
    return {"test": test, "variants": variants}


def require_ready(cfg: dict) -> None:
    t = cfg["test"]
    if len(cfg["variants"]) < 2:
        raise SystemExit("Нужно минимум 2 варианта обложки")
    if not t.get("product_id"):
        raise SystemExit("Не выбран товар")
    if not t.get("campaign_ids"):
        raise SystemExit("Не выбраны рекламные кампании")
    if not t.get("start_dt"):
        raise SystemExit("Тест не запущен (нет даты старта)")


# ─── время ───────────────────────────────────────────────────────────────────

def parse_msk(value: str) -> datetime:
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
