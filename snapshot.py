#!/usr/bin/env python3
"""Снимок накопленной статистики рекламы. Запускается вместе с worker.py
каждые ~15 минут. Из разницы двух снимков получаем показы/клики за короткий
интервал — это позволяет считать блоки короче суток (дневной отчёт Ozon
такого не даёт).

  python snapshot.py
"""

from __future__ import annotations

import csv
import sys
from datetime import timedelta

from common import DATA_DIR, load_config, now_msk, require_ready, utcnow_iso
from ozon_performance import fetch_daily

SNAP_CSV = DATA_DIR / "snapshots.csv"
FIELDS = ["at_utc", "date", "views", "clicks", "spend", "orders"]


def take_snapshot(cfg: dict | None = None) -> int:
    cfg = cfg or load_config()
    require_ready(cfg)
    campaigns = [str(c) for c in cfg["test"]["campaign_ids"]]

    today = now_msk()
    d_from = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    d_to = today.strftime("%Y-%m-%d")
    daily = fetch_daily(campaigns, d_from, d_to)   # {date: {views,clicks,spend,orders}}

    now = utcnow_iso()
    rows = []
    for date in (d_from, d_to):
        m = daily.get(date, {"views": 0, "clicks": 0, "spend": 0, "orders": 0})
        rows.append({"at_utc": now, "date": date,
                     "views": round(m["views"]), "clicks": round(m["clicks"]),
                     "spend": round(m["spend"], 2), "orders": round(m["orders"])})

    DATA_DIR.mkdir(exist_ok=True)
    new = not SNAP_CSV.exists()
    with SNAP_CSV.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def load_snapshots() -> list[dict]:
    if not SNAP_CSV.exists():
        return []
    with SNAP_CSV.open(newline="") as fh:
        out = []
        for r in csv.DictReader(fh):
            for k in ("views", "clicks", "orders"):
                r[k] = int(float(r[k]))
            r["spend"] = float(r["spend"])
            out.append(r)
    return out


if __name__ == "__main__":
    n = take_snapshot()
    print(f"снапшот записан ({n} строк) -> {SNAP_CSV}")
    sys.exit(0)
