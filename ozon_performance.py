#!/usr/bin/env python3
"""Ozon Performance API: токен, список кампаний, дневная статистика показов/кликов.

Хост: https://api-performance.ozon.ru

CLI:
  python ozon_performance.py campaigns
  python ozon_performance.py stats <campaign_id[,campaign_id...]> <YYYY-MM-DD> <YYYY-MM-DD>
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

import requests

from common import ozon_creds

BASE = "https://api-performance.ozon.ru"

_token_cache: dict = {"value": None, "exp": 0.0}


def get_token() -> str:
    if _token_cache["value"] and time.time() < _token_cache["exp"] - 60:
        return _token_cache["value"]
    c = ozon_creds()
    if not c["perf_client_id"] or not c["perf_client_secret"]:
        raise SystemExit("Не заданы ключи Performance API (раздел «Подключение»)")
    resp = requests.post(
        f"{BASE}/api/client/token",
        json={"client_id": c["perf_client_id"], "client_secret": c["perf_client_secret"],
              "grant_type": "client_credentials"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise SystemExit(f"Performance API токен {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    _token_cache["value"] = data["access_token"]
    _token_cache["exp"] = time.time() + float(data.get("expires_in", 1800))
    return _token_cache["value"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}


def list_campaigns(only_running: bool = False) -> list[dict]:
    resp = requests.get(f"{BASE}/api/client/campaign", headers=_auth(), timeout=60)
    if resp.status_code >= 400:
        raise SystemExit(f"Performance API campaign {resp.status_code}: {resp.text[:400]}")
    rows = resp.json().get("list", [])
    if only_running:
        rows = [c for c in rows if c.get("state") == "CAMPAIGN_STATE_RUNNING"]
    return rows


def _to_float(x) -> float:
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    return float(str(x).replace("\xa0", "").replace(" ", "").replace(",", "."))


def fetch_daily(campaign_ids: list[str], date_from: str, date_to: str) -> dict[str, dict]:
    """Синхронный дневной отчёт. Возвращает {дата: {views, clicks, spend, orders}} —
    сумма по всем переданным кампаниям."""
    body = {"campaigns": [str(c) for c in campaign_ids], "dateFrom": date_from, "dateTo": date_to}
    resp = requests.post(f"{BASE}/api/client/statistics/daily/json", headers=_auth(),
                         json=body, timeout=120)
    if resp.status_code >= 400:
        raise SystemExit(f"Performance API daily {resp.status_code}: {resp.text[:400]}")

    rows = resp.json()
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("result") or []

    out: dict[str, dict] = {}
    for r in rows:
        day = (r.get("date") or r.get("day") or "")[:10]
        if not day:
            continue
        acc = out.setdefault(day, {"views": 0.0, "clicks": 0.0, "spend": 0.0, "orders": 0.0})
        acc["views"] += _to_float(r.get("views") or r.get("viewsCount"))
        acc["clicks"] += _to_float(r.get("clicks") or r.get("clicksCount"))
        acc["spend"] += _to_float(r.get("moneySpent") or r.get("expense") or r.get("spent"))
        acc["orders"] += _to_float(r.get("orders") or r.get("ordersCount"))
    return out


def _main(argv: list[str]) -> None:
    if not argv or argv[0] not in {"campaigns", "stats"}:
        print(__doc__)
        return
    if argv[0] == "campaigns":
        for c in list_campaigns():
            print(f"{c.get('id'):>12}  {c.get('state','?'):26}  "
                  f"{c.get('advObjectType','?'):10}  {c.get('title','')}")
        return
    ids = argv[1].split(",")
    d1, d2 = argv[2], argv[3]
    datetime.strptime(d1, "%Y-%m-%d"); datetime.strptime(d2, "%Y-%m-%d")
    daily = fetch_daily(ids, d1, d2)
    print(f"{'дата':12} {'показы':>10} {'клики':>8} {'CTR%':>7} {'расход':>10}")
    for day in sorted(daily):
        v = daily[day]
        ctr = 100 * v["clicks"] / v["views"] if v["views"] else 0
        print(f"{day:12} {v['views']:>10.0f} {v['clicks']:>8.0f} {ctr:>7.2f} {v['spend']:>10.2f}")


if __name__ == "__main__":
    _main(sys.argv[1:])
