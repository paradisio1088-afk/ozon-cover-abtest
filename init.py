#!/usr/bin/env python3
"""Разовая подготовка: залить ВСЕ варианты обложки в карточку и дождаться,
пока Ozon их обработает/отмодерирует. После этого ротация — только
перестановка (быстро, без повторной модерации).

  python init.py            # залить недостающие варианты
  python init.py --wait     # залить и ждать появления всех вариантов в карточке
  python init.py --check    # только проверить статус
"""

from __future__ import annotations

import sys
import time

from abtest import block_order
from common import load_config
from ozon_seller import get_images, import_pictures


def status(cfg: dict) -> tuple[list[str], list[str]]:
    from image_match import present as _present
    images, _ = get_images(cfg["test"]["product_id"])
    ok = set(_present([v["url"] for v in cfg["variants"]], images))
    present, missing = [], []
    for v in cfg["variants"]:
        (present if v["url"] in ok else missing).append(v["url"])
    return present, missing


def upload_missing(cfg: dict) -> None:
    from image_match import present as _present
    pid = cfg["test"]["product_id"]
    images, primary = get_images(pid)
    have = set(_present([v["url"] for v in cfg["variants"]], images))
    to_add = [v["url"] for v in cfg["variants"] if v["url"] not in have]
    if not to_add:
        print("Все варианты уже в карточке.")
        return
    # текущую обложку оставляем первой, чтобы не трогать живую карточку до модерации
    ordered = ([primary] if primary else []) + [u for u in images if u != primary] + to_add
    print(f"Догружаю {len(to_add)} вариант(ов) в карточку {pid}...")
    import_pictures(pid, ordered)
    print("Отправлено. Обработка фото у Ozon — от нескольких минут до суток.")


def wait_ready(cfg: dict, timeout_min: int = 180, interval_s: int = 60) -> bool:
    deadline = time.time() + timeout_min * 60
    while True:
        present, missing = status(cfg)
        print(f"  готово {len(present)}/{len(cfg['variants'])}"
              + (f", ждём: {', '.join(missing)}" if missing else ""))
        if not missing:
            return True
        if time.time() > deadline:
            return False
        time.sleep(interval_s)


def main(argv: list[str]) -> int:
    cfg = load_config()
    n = len(block_order(cfg))
    print(f"Тест «{cfg['test']['name']}»: {cfg['test']['n_variants']} вариантов, "
          f"{n} блоков по {cfg['test']['block_minutes']} мин.\n")

    if "--check" in argv:
        present, missing = status(cfg)
        print(f"В карточке: {len(present)}/{len(cfg['variants'])}")
        for u in missing:
            print(f"  нет: {u}")
        return 0 if not missing else 1

    upload_missing(cfg)
    if "--wait" in argv:
        ok = wait_ready(cfg)
        print("\nВсе варианты на месте — можно запускать ротацию." if ok
              else "\nНе дождались модерации всех фото. Запусти позже: python init.py --check")
        return 0 if ok else 1
    print("\nПроверить готовность позже: python init.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
