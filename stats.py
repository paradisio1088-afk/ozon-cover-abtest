"""Статистика для сравнения CTR вариантов. Только stdlib (math)."""

from __future__ import annotations

import math


def _phi(z: float) -> float:
    """Функция распределения стандартного нормального N(0,1)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion_ztest(clicks_a: int, views_a: int,
                         clicks_b: int, views_b: int) -> dict:
    """Двусторонний z-тест разности двух долей (CTR_a vs CTR_b).

    Возвращает: p_a, p_b, diff (a-b), z, p_value (двусторонний),
    ci95 — 95% доверительный интервал разности.
    """
    if views_a == 0 or views_b == 0:
        return {"p_a": 0.0, "p_b": 0.0, "diff": 0.0, "z": 0.0,
                "p_value": 1.0, "ci95": (0.0, 0.0), "enough": False}

    p_a, p_b = clicks_a / views_a, clicks_b / views_b
    p_pool = (clicks_a + clicks_b) / (views_a + views_b)
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / views_a + 1 / views_b))
    z = (p_a - p_b) / se_pool if se_pool > 0 else 0.0
    p_value = 2 * (1 - _phi(abs(z)))

    se_unpool = math.sqrt(p_a * (1 - p_a) / views_a + p_b * (1 - p_b) / views_b)
    diff = p_a - p_b
    ci = (diff - 1.96 * se_unpool, diff + 1.96 * se_unpool)
    return {"p_a": p_a, "p_b": p_b, "diff": diff, "z": z, "p_value": p_value,
            "ci95": ci, "enough": True}


def chi_square_ctr(rows: list[tuple[int, int]]) -> dict:
    """Омнибус-тест: отличаются ли CTR между всеми вариантами.
    rows = [(clicks, views), ...]. p-value через аппроксимацию Уилсона–Хилферти."""
    total_clicks = sum(c for c, _ in rows)
    total_views = sum(v for _, v in rows)
    k = len(rows)
    if k < 2 or total_views == 0 or total_clicks == 0 or total_clicks == total_views:
        return {"chi2": 0.0, "df": max(k - 1, 0), "p_value": 1.0}

    p = total_clicks / total_views
    chi2 = 0.0
    for clicks, views in rows:
        for obs, exp in ((clicks, views * p), (views - clicks, views * (1 - p))):
            if exp > 0:
                chi2 += (obs - exp) ** 2 / exp
    df = k - 1
    # Уилсон–Хилферти: (chi2/df)^(1/3) ~ N(1 - 2/(9df), 2/(9df))
    t = (chi2 / df) ** (1 / 3)
    mu = 1 - 2 / (9 * df)
    sigma = math.sqrt(2 / (9 * df))
    z = (t - mu) / sigma
    p_value = 1 - _phi(z)
    return {"chi2": chi2, "df": df, "p_value": max(min(p_value, 1.0), 0.0)}


def required_views_per_variant(baseline_ctr: float, mde_rel: float,
                               alpha: float = 0.05, power: float = 0.8) -> int:
    """Грубая оценка нужных показов на вариант, чтобы поймать
    относительный прирост CTR mde_rel (напр. 0.15 = +15%)."""
    if baseline_ctr <= 0 or baseline_ctr >= 1 or mde_rel <= 0:
        return 0
    z_a = 1.959963  # two-sided 0.05
    z_b = 0.841621  # power 0.8
    p1 = baseline_ctr
    p2 = baseline_ctr * (1 + mde_rel)
    p_bar = (p1 + p2) / 2
    num = (z_a * math.sqrt(2 * p_bar * (1 - p_bar))
           + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p1) ** 2)
