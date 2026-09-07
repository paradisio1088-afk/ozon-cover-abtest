#!/usr/bin/env python3
"""Запускается по расписанию (раз в час). Определяет, какой вариант обложки
должен быть активен сейчас, и переставляет обложку, если нужно.

  python rotate.py            # применить
  python rotate.py --dry-run  # показать, ничего не меняя
"""

from __future__ import annotations

import sys

from abtest import (block_order, current_block, finish_dt, load_state,
                    record_switch, target_variant)
from common import load_config, now_msk
from ozon_seller import _norm, get_images, set_cover


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    cfg = load_config()
    state = load_state()
    now = now_msk()
    pid = cfg["test"]["product_id"]

    b = current_block(cfg, now)
    total = len(block_order(cfg))

    if b < 0:
        print(f"Тест ещё не начался (старт {cfg['test']['start']} МСК).")
        return 0
    if b >= total:
        print(f"Тест завершён {finish_dt(cfg):%Y-%m-%d %H:%M} МСК. Ротация остановлена.")
        _maybe_apply_winner(cfg, state, dry)
        return 0

    vi = target_variant(cfg, now)
    variant = cfg["variants"][vi]
    _, primary = get_images(pid)

    already = _norm(primary) == _norm(variant["url"])
    print(f"Блок {b + 1}/{total} (цикл {b // cfg['test']['n_variants'] + 1}) — "
          f"нужен вариант «{variant['name']}»")
    print(f"  сейчас обложка: {primary}")

    if already:
        print("  уже стоит нужный вариант, ничего не делаю.")
        return 0
    if dry:
        print(f"  [dry-run] поставил бы: {variant['url']}")
        return 0

    res = set_cover(pid, variant["url"])
    record_switch(state, block=b, variant_index=vi, image_url=variant["url"],
                  changed=res["changed"])
    print(f"  обложка переключена на «{variant['name']}»: {variant['url']}")
    return 0


def _maybe_apply_winner(cfg: dict, state: dict, dry: bool) -> None:
    if not cfg["test"].get("apply_winner_on_finish"):
        return
    if state.get("winner_applied"):
        return
    try:
        from analyze import compute_results
    except Exception:
        return
    res = compute_results(cfg, state)
    winner = res.get("winner")
    if not winner or not res.get("significant"):
        print("  Победитель не определён однозначно — обложку не меняю.")
        return
    url = cfg["variants"][winner["variant_index"]]["url"]
    if dry:
        print(f"  [dry-run] поставил бы победителя: {winner['variant_name']}")
        return
    set_cover(cfg["test"]["product_id"], url)
    state["winner_applied"] = winner["variant_index"]
    from abtest import save_state
    save_state(state)
    print(f"  Установлена обложка-победитель: «{winner['variant_name']}»")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
