#!/usr/bin/env python3
"""Раскладывает статистику рекламы по блокам ротации.

Показы/клики за блок = разница снимков (snapshots.csv) на границах окна учёта
блока. Окно = [конец переходного периода .. конец блока], но не позже
последнего снимка. Результат — data/blocks.csv (перезаписывается целиком).

  python collect.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta

from abtest import (block_bounds, block_order, effective_window, load_state,
                    switch_time_for_block)
from common import DATA_DIR, MSK, load_config, now_msk, require_ready
from snapshot import load_snapshots

BLOCKS_CSV = DATA_DIR / "blocks.csv"
FIELDS = ["block", "cycle", "variant_index", "variant_name",
          "views", "clicks", "spend", "orders", "window_from", "window_to",
          "partial", "counted", "reason"]
METRICS = ("views", "clicks", "spend", "orders")


def _day_key(dt: datetime) -> str:
    return dt.astimezone(MSK).strftime("%Y-%m-%d")


def _cumulative(snaps_by_day: dict[str, list[dict]], day: str, t: datetime) -> dict:
    """Накопленные метрики за дату day на момент t (последний снимок <= t)."""
    best = None
    for s in snaps_by_day.get(day, []):
        if datetime.fromisoformat(s["at_utc"]) <= t:
            best = s
        else:
            break
    if best is None:
        return {m: 0.0 for m in METRICS}
    return {m: float(best[m]) for m in METRICS}


def _traffic_between(snaps_by_day: dict, w0: datetime, w1: datetime) -> dict:
    """Суммарные метрики за интервал [w0, w1] (МСК), с учётом сброса счётчика в полночь."""
    total = {m: 0.0 for m in METRICS}
    if w1 <= w0:
        return total
    cur = w0
    while cur < w1:
        day = _day_key(cur)
        midnight_next = (cur.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
                         + timedelta(days=1))
        seg_end = min(w1, midnight_next)
        a = _cumulative(snaps_by_day, day, cur)
        b = _cumulative(snaps_by_day, day, seg_end)
        for m in METRICS:
            total[m] += max(b[m] - a[m], 0.0)
        cur = seg_end
    return total


def collect(cfg: dict) -> list[dict]:
    require_ready(cfg)
    state = load_state()
    n_var = max(cfg["test"]["n_variants"], 1)
    order = block_order(cfg)

    snaps = load_snapshots()
    if not snaps:
        print("Пока нет снимков статистики (snapshots.csv). Запусти worker.py позже.")
        return []
    snaps_by_day: dict[str, list[dict]] = {}
    for s in sorted(snaps, key=lambda r: r["at_utc"]):
        snaps_by_day.setdefault(s["date"], []).append(s)
    last_snap = max(datetime.fromisoformat(s["at_utc"]) for s in snaps).astimezone(MSK)

    now = now_msk()
    rows: list[dict] = []
    for b, vi in enumerate(order):
        b0, b1 = block_bounds(cfg, b)
        if b0 > now:
            break
        eff = effective_window(cfg, state, b)
        w0 = eff.measure_from
        w1 = min(b1, last_snap)
        partial = b1 > last_snap or b1 > now

        counted, reason = False, ""
        if b > 0 and switch_time_for_block(state, b) is None:
            reason = "ротация не отработала в этом блоке"
        elif w1 <= w0:
            reason = "переходный период ещё не кончился" if b1 > now else "нет данных за окно"
        else:
            counted, reason = True, "ok"

        t = _traffic_between(snaps_by_day, w0, w1) if counted else {m: 0.0 for m in METRICS}
        rows.append({
            "block": b, "cycle": b // n_var,
            "variant_index": vi, "variant_name": cfg["variants"][vi]["name"],
            "views": round(t["views"]), "clicks": round(t["clicks"]),
            "spend": round(t["spend"], 2), "orders": round(t["orders"]),
            "window_from": w0.strftime("%d.%m %H:%M"),
            "window_to": w1.strftime("%d.%m %H:%M") if counted else "—",
            "partial": int(partial), "counted": int(counted), "reason": reason,
        })
    return rows


def main(argv: list[str]) -> int:
    cfg = load_config()
    rows = collect(cfg)
    if not rows:
        return 0
    DATA_DIR.mkdir(exist_ok=True)
    with BLOCKS_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    used = [r for r in rows if r["counted"]]
    print(f"Блоков пройдено: {len(rows)}, зачтено: {len(used)}")
    print(f"  показов зачтено: {sum(r['views'] for r in used)}, "
          f"кликов: {sum(r['clicks'] for r in used)}")
    print(f"  -> {BLOCKS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
