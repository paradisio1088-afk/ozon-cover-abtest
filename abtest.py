"""Логика ротации: какой вариант обложки должен быть активен в каждый момент,
плюс состояние теста (журнал переключений) в data/state.json."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from common import DATA_DIR, MSK, utcnow_iso

STATE_PATH = DATA_DIR / "state.json"


# ─── расписание ──────────────────────────────────────────────────────────────

def block_order(cfg: dict) -> list[int]:
    """Список индексов вариантов по блокам за все циклы.
    Пример 5 вариантов, 2 цикла: [0,1,2,3,4, ...перемешанный второй цикл...]."""
    n = cfg["test"]["n_variants"]
    cycles = int(cfg["test"]["cycles"])
    shuffle = bool(cfg["test"].get("shuffle_each_cycle"))
    order: list[int] = []
    for c in range(cycles):
        idx = list(range(n))
        if shuffle and c > 0:  # цикл 1 идёт в порядке из config (старт с текущей обложки)
            random.Random(f"{cfg['test']['name']}::{c}").shuffle(idx)
        order += idx
    return order


def block_len(cfg: dict) -> timedelta:
    return timedelta(minutes=int(cfg["test"]["block_minutes"]))


def block_bounds(cfg: dict, block: int) -> tuple[datetime, datetime]:
    start = cfg["test"]["start_dt"]
    d = block_len(cfg)
    return start + d * block, start + d * (block + 1)


def current_block(cfg: dict, now: datetime) -> int:
    """Номер блока для момента now. <0 — тест ещё не начался,
    >= total_blocks — уже закончился."""
    start = cfg["test"]["start_dt"]
    if start is None or now < start:
        return -1
    return int((now - start) / block_len(cfg))


def target_variant(cfg: dict, now: datetime) -> int | None:
    b = current_block(cfg, now)
    order = block_order(cfg)
    if b < 0 or b >= len(order):
        return None
    return order[b]


def measurement_start(cfg: dict, block: int) -> datetime:
    """С какого момента блок можно засчитывать в статистику."""
    b0, _ = block_bounds(cfg, block)
    return b0 + timedelta(minutes=float(cfg["test"]["settle_minutes"]))


def finish_dt(cfg: dict) -> datetime:
    _, end = block_bounds(cfg, cfg["test"]["total_blocks"] - 1)
    return end


def _fmt(dt: datetime) -> str:
    return dt.astimezone(MSK).strftime("%d.%m %H:%M")


def schedule_table(cfg: dict) -> list[dict]:
    order = block_order(cfg)
    rows = []
    for b, vi in enumerate(order):
        b0, b1 = block_bounds(cfg, b)
        rows.append({
            "block": b, "cycle": b // max(cfg["test"]["n_variants"], 1),
            "variant_index": vi, "variant_name": cfg["variants"][vi]["name"],
            "from": _fmt(b0), "to": _fmt(b1),
            "measure_from": _fmt(measurement_start(cfg, b)),
        })
    return rows


# ─── состояние ───────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"switches": [], "winner_applied": None}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def record_switch(state: dict, *, block: int, variant_index: int, image_url: str,
                  changed: bool) -> None:
    state["switches"].append({
        "at_utc": utcnow_iso(), "block": block,
        "variant_index": variant_index, "image_url": image_url, "changed": changed,
    })
    save_state(state)


def switch_time_for_block(state: dict, block: int) -> datetime | None:
    """Когда фактически включили нужный вариант в этом блоке (по журналу)."""
    best = None
    for s in state["switches"]:
        if s["block"] == block:
            t = datetime.fromisoformat(s["at_utc"]).astimezone(MSK)
            if best is None or t < best:
                best = t
    return best


@dataclass
class Effective:
    """Фактическое окно, которое можно засчитать для блока."""
    block: int
    variant_index: int
    measure_from: datetime  # МСК


def effective_window(cfg: dict, state: dict, block: int) -> Effective:
    order = block_order(cfg)
    planned = measurement_start(cfg, block)
    actual_switch = switch_time_for_block(state, block)
    mf = planned
    if actual_switch is not None:
        settle = timedelta(minutes=float(cfg["test"]["settle_minutes"]))
        mf = max(planned, actual_switch + settle)
    return Effective(block=block, variant_index=order[block], measure_from=mf)
