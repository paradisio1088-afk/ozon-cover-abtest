#!/usr/bin/env python3
"""Считает CTR по вариантам обложки, проверяет значимость, пишет report.md.

  python analyze.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

from abtest import block_order, current_block, finish_dt, load_state
from common import ROOT, load_config, now_msk, require_ready
from collect import DAILY_CSV
from stats import (chi_square_ctr, required_views_per_variant,
                   two_proportion_ztest)

REPORT_MD = ROOT / "report.md"


def _n(x) -> str:
    return f"{int(x):,}".replace(",", " ")


def _read_daily() -> list[dict]:
    if not DAILY_CSV.exists():
        raise SystemExit("Нет data/daily.csv — сначала запусти python collect.py")
    with DAILY_CSV.open(newline="") as fh:
        return list(csv.DictReader(fh))


def compute_results(cfg: dict, state: dict | None = None) -> dict:
    require_ready(cfg)
    rows = [r for r in _read_daily() if r["counted"] == "1"]
    n_var = cfg["test"]["n_variants"]

    agg = {i: {"views": 0, "clicks": 0, "spend": 0.0, "orders": 0, "days": 0}
           for i in range(n_var)}
    by_cycle: dict[tuple[int, int], dict] = defaultdict(lambda: {"views": 0, "clicks": 0})
    for r in rows:
        vi = int(r["variant_index"])
        a = agg[vi]
        a["views"] += int(r["views"]); a["clicks"] += int(r["clicks"])
        a["spend"] += float(r["spend"]); a["orders"] += int(r["orders"]); a["days"] += 1
        cy = int(r["cycle"])
        by_cycle[(vi, cy)]["views"] += int(r["views"])
        by_cycle[(vi, cy)]["clicks"] += int(r["clicks"])

    variants = []
    for i in range(n_var):
        a = agg[i]
        ctr = a["clicks"] / a["views"] if a["views"] else 0.0
        variants.append({
            "variant_index": i, "variant_name": cfg["variants"][i]["name"],
            "views": a["views"], "clicks": a["clicks"], "ctr": ctr,
            "spend": a["spend"], "orders": a["orders"], "days": a["days"],
        })
    ranked = sorted(variants, key=lambda v: v["ctr"], reverse=True)

    omnibus = chi_square_ctr([(v["clicks"], v["views"]) for v in variants])

    best = ranked[0]
    comparisons = []
    for v in ranked[1:]:
        t = two_proportion_ztest(best["clicks"], best["views"], v["clicks"], v["views"])
        comparisons.append({"vs": v["variant_name"], "vs_index": v["variant_index"],
                            "diff": t["diff"], "p_value": t["p_value"], "ci95": t["ci95"]})

    min_imp = int(cfg["test"]["min_impressions_per_variant"])
    runner_up = ranked[1] if len(ranked) > 1 else None
    enough_data = all(v["views"] >= min_imp for v in variants)
    beats_runner_up = bool(comparisons) and comparisons[0]["p_value"] < 0.05

    # стабильность лидера по циклам
    cycles = sorted({cy for (_, cy) in by_cycle})
    cycle_wins = 0
    for cy in cycles:
        best_cy, best_cy_ctr = None, -1.0
        for i in range(n_var):
            d = by_cycle.get((i, cy))
            if not d or not d["views"]:
                continue
            c = d["clicks"] / d["views"]
            if c > best_cy_ctr:
                best_cy_ctr, best_cy = c, i
        if best_cy == best["variant_index"]:
            cycle_wins += 1
    consistent = len(cycles) > 0 and cycle_wins >= (len(cycles) + 1) // 2

    significant = enough_data and beats_runner_up and consistent

    need = 0
    if runner_up and best["ctr"] > 0 and runner_up["ctr"] > 0 and not significant:
        gap_rel = (best["ctr"] - runner_up["ctr"]) / runner_up["ctr"]
        if gap_rel > 0:
            need = required_views_per_variant(runner_up["ctr"], gap_rel)

    return {
        "ranked": ranked, "omnibus": omnibus, "comparisons": comparisons,
        "by_cycle": {f"{i}|{cy}": v for (i, cy), v in by_cycle.items()},
        "cycles": cycles, "cycle_wins": cycle_wins, "consistent": consistent,
        "enough_data": enough_data, "min_impressions": min_imp,
        "significant": significant,
        "winner": best if significant else None,
        "needed_views_per_variant": need,
        "total_views": sum(v["views"] for v in variants),
        "total_clicks": sum(v["clicks"] for v in variants),
    }


def _verdict(cfg: dict, res: dict) -> str:
    now = now_msk()
    b = current_block(cfg, now)
    total = len(block_order(cfg))
    running = 0 <= b < total

    if res["significant"]:
        w = res["winner"]
        ru = res["ranked"][1]
        lift = 100 * (w["ctr"] - ru["ctr"]) / ru["ctr"] if ru["ctr"] else 0
        p = res["comparisons"][0]["p_value"]
        tail = "Тест ещё идёт, но лидер устойчив." if running else "Тест завершён."
        return (f"**Победитель: «{w['variant_name']}»** — CTR {w['ctr']*100:.2f}% против "
                f"{ru['ctr']*100:.2f}% у «{ru['variant_name']}» (+{lift:.0f}%, p={p:.3f}). "
                f"Лидировал в {res['cycle_wins']}/{len(res['cycles'])} циклах. {tail} "
                f"Рекомендация: поставить обложку «{w['variant_name']}».")

    reasons = []
    if not res["enough_data"]:
        reasons.append(f"на некоторые варианты пока < {res['min_impressions']} показов")
    if res["comparisons"] and res["comparisons"][0]["p_value"] >= 0.05:
        reasons.append(f"разрыв лидера и второго места незначим (p={res['comparisons'][0]['p_value']:.3f})")
    if not res["consistent"]:
        reasons.append("лидер меняется от цикла к циклу")
    msg = "**Вывод пока не однозначен**: " + "; ".join(reasons) + ". "
    if running:
        msg += "Тест продолжается. "
    if res["needed_views_per_variant"]:
        num = f"{res['needed_views_per_variant']:,}".replace(",", " ")
        msg += f"Ориентир: чтобы подтвердить текущий разрыв, нужно ~{num} показов на вариант."
    else:
        msg += "Если разрыв по CTR так и не появится — варианты равнозначны, бери любой (например, самый дешёвый по ставке)."
    return msg


def build_report(cfg: dict, res: dict) -> str:
    L = []
    L.append(f"# A/B-тест обложки — «{cfg['test']['name']}»\n")
    L.append(f"Товар: `{cfg['test'].get('offer_id') or cfg['test']['product_id']}`  ·  "
             f"обновлено {now_msk():%Y-%m-%d %H:%M} МСК  ·  "
             f"конец теста {finish_dt(cfg):%Y-%m-%d}\n")
    L.append(f"Зачтено показов: **{_n(res['total_views'])}**, кликов: **{_n(res['total_clicks'])}**\n")

    L.append("## Результаты по вариантам\n")
    L.append("| # | Вариант | Показы | Клики | CTR | Заказы | Расход ₽ | Дней |")
    L.append("|---|---------|-------:|------:|----:|-------:|---------:|-----:|")
    for pos, v in enumerate(res["ranked"], 1):
        mark = " 🏆" if res["winner"] and v["variant_index"] == res["winner"]["variant_index"] else ""
        L.append(f"| {pos} | {v['variant_name']}{mark} | {_n(v['views'])} | {_n(v['clicks'])} | "
                 f"{v['ctr']*100:.2f}% | {v['orders']} | {v['spend']:.0f} | {v['days']} |")
    L.append("")

    L.append("## Сравнение с лидером\n")
    L.append("| Вариант | Δ CTR (п.п.) | 95% ДИ | p-value | значимо |")
    L.append("|---------|-------------:|--------|--------:|:-------:|")
    for c in res["comparisons"]:
        lo, hi = c["ci95"]
        sig = "да" if c["p_value"] < 0.05 else "нет"
        L.append(f"| {c['vs']} | {c['diff']*100:+.2f} | "
                 f"[{lo*100:+.2f}; {hi*100:+.2f}] | {c['p_value']:.3f} | {sig} |")
    L.append("")
    L.append(f"Омнибус-тест (все варианты различны по CTR): "
             f"χ²={res['omnibus']['chi2']:.1f}, df={res['omnibus']['df']}, "
             f"p={res['omnibus']['p_value']:.3f}\n")

    if res["cycles"]:
        L.append("## CTR по циклам (проверка устойчивости)\n")
        head = "| Вариант | " + " | ".join(f"цикл {c+1}" for c in res["cycles"]) + " |"
        L.append(head)
        L.append("|" + "---|" * (len(res["cycles"]) + 1))
        for v in res["ranked"]:
            cells = []
            for cy in res["cycles"]:
                d = res["by_cycle"].get(f"{v['variant_index']}|{cy}")
                cells.append(f"{d['clicks']/d['views']*100:.2f}%" if d and d["views"] else "—")
            L.append(f"| {v['variant_name']} | " + " | ".join(cells) + " |")
        L.append("")

    L.append("## Вывод\n")
    L.append(_verdict(cfg, res) + "\n")

    L.append("---\n")
    L.append("_Метод: ротация вариантов блоками, сравнение рекламного CTR. "
             "Тест по времени чувствителен к дню недели и действиям конкурентов — "
             "поэтому смотрим и на устойчивость лидера по циклам, а не только на итоговый CTR._")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    cfg = load_config()
    res = compute_results(cfg)
    report = build_report(cfg, res)
    REPORT_MD.write_text(report)

    print(f"\n{'вариант':22} {'показы':>9} {'клики':>7} {'CTR':>7}")
    for v in res["ranked"]:
        print(f"{v['variant_name']:22} {v['views']:>9,} {v['clicks']:>7,} {v['ctr']*100:>6.2f}%"
              .replace(",", " "))
    print()
    print(_verdict(cfg, res))
    print(f"\n-> {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
