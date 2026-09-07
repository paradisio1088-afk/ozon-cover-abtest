#!/usr/bin/env python3
"""Где сейчас тест: расписание ротации и текущий блок.

  python status.py
"""

from __future__ import annotations

from abtest import (block_order, current_block, finish_dt, load_state,
                    switch_time_for_block, target_variant)
from common import load_config, now_msk


def main() -> int:
    cfg = load_config()
    state = load_state()
    now = now_msk()
    order = block_order(cfg)
    b = current_block(cfg, now)

    print(f"Тест «{cfg['test']['name']}»  ·  сейчас {now:%Y-%m-%d %H:%M} МСК")
    if not cfg["test"].get("start_dt"):
        print("Статус: не запущен (нет даты старта — задай в интерфейсе)")
        return 0
    print(f"Старт {cfg['test']['start']}  ·  конец {finish_dt(cfg):%Y-%m-%d %H:%M}  ·  "
          f"{len(order)} блоков × {cfg['test']['block_days']} дн.\n")

    if b < 0:
        print("Статус: ещё не начался")
    elif b >= len(order):
        print("Статус: завершён")
    else:
        vi = target_variant(cfg, now)
        sw = switch_time_for_block(state, b)
        print(f"Статус: идёт, блок {b + 1}/{len(order)} (цикл {b // cfg['test']['n_variants'] + 1})")
        print(f"Активный вариант: «{cfg['variants'][vi]['name']}»")
        print(f"Переключение зафиксировано: {sw:%Y-%m-%d %H:%M МСК}" if sw
              else "Переключение НЕ зафиксировано — проверь, что rotate.py работает!")

    print(f"\nВсего переключений в журнале: {len(state['switches'])}")
    print("\nРасписание:")
    print(f"  {'блок':>4} {'цикл':>4}  {'вариант':22} {'период':23} {'учёт с'}")
    from abtest import schedule_table
    for r in schedule_table(cfg):
        cur = " <--" if r["block"] == b else ""
        print(f"  {r['block']+1:>4} {r['cycle']+1:>4}  {r['variant_name']:22} "
              f"{r['from']} .. {r['to']}  {r['measure_from']}{cur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
