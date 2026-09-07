#!/usr/bin/env python3
"""Забирает дневную статистику рекламы и раскладывает по вариантам обложки.
Результат — data/daily.csv (перезаписывается целиком каждый запуск).

  python collect.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta

from abtest import (block_order, current_block, effective_window, finish_dt,
                    load_state, switch_time_for_block)
from common import DATA_DIR, MSK, load_config, now_msk, require_ready
from ozon_performance import fetch_daily

DAILY_CSV = DATA_DIR / "daily.csv"
FIELDS = ["date", "block", "cycle", "variant_index", "variant_name",
          "views", "clicks", "spend", "orders", "counted", "reason"]


def _daterange(d1: datetime, d2: datetime):
    cur = d1
    while cur <= d2:
        yield cur
        cur += timedelta(days=1)


def collect(cfg: dict) -> list[dict]:
    require_ready(cfg)
    state = load_state()
    n_var = cfg["test"]["n_variants"]
    start = cfg["test"]["start_dt"]
    yesterday = (now_msk() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = min(yesterday, finish_dt(cfg))
    if end < start:
        print("Пока нет завершённых суток теста.")
        return []

    campaigns = [str(c) for c in cfg["test"]["campaign_ids"]]
    if not campaigns:
        raise SystemExit("В config.toml не заданы test.campaign_ids")

    daily = fetch_daily(campaigns, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    rows: list[dict] = []
    for day_dt in _daterange(start.replace(hour=0, minute=0), end):
        dstr = day_dt.strftime("%Y-%m-%d")
        metrics = daily.get(dstr, {"views": 0, "clicks": 0, "spend": 0, "orders": 0})

        noon = day_dt.replace(hour=12, tzinfo=MSK)
        block = current_block(cfg, noon)
        order = block_order(cfg)

        counted, reason, vi = False, "", -1
        if block < 0 or block >= len(order):
            reason = "вне периода теста"
        else:
            eff = effective_window(cfg, state, block)
            vi = eff.variant_index
            day_start = day_dt.replace(hour=0, tzinfo=MSK)
            if block > 0 and switch_time_for_block(state, block) is None:
                reason = "rotate.py не отработал в этом блоке"
            elif day_start < eff.measure_from:
                reason = "переходный период (settle)"
            else:
                counted, reason = True, "ok"

        rows.append({
            "date": dstr, "block": block if block >= 0 else "",
            "cycle": (block // n_var) if 0 <= block < len(order) else "",
            "variant_index": vi if vi >= 0 else "",
            "variant_name": cfg["variants"][vi]["name"] if vi >= 0 else "",
            "views": round(metrics["views"]), "clicks": round(metrics["clicks"]),
            "spend": round(metrics["spend"], 2), "orders": round(metrics["orders"]),
            "counted": int(counted), "reason": reason,
        })
    return rows


def main(argv: list[str]) -> int:
    cfg = load_config()
    rows = collect(cfg)
    if not rows:
        return 0
    DATA_DIR.mkdir(exist_ok=True)
    with DAILY_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    used = [r for r in rows if r["counted"]]
    print(f"Собрано суток: {len(rows)}, зачтено в тест: {len(used)}")
    print(f"  показов зачтено: {sum(r['views'] for r in used)}, "
          f"кликов: {sum(r['clicks'] for r in used)}")
    print(f"  -> {DAILY_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
