#!/usr/bin/env python3
"""Ozon Seller API: чтение и замена картинок карточки.

Обложка = первый элемент массива images. Меняем порядок уже загруженных
и одобренных картинок — повторной модерации при этом не происходит.

CLI:
  python ozon_seller.py resolve <offer_id>      -> product_id
  python ozon_seller.py pictures <product_id>   -> текущий список картинок
  python ozon_seller.py set-cover <product_id> <image_url>
"""

from __future__ import annotations

import sys
import time

import requests

from common import require_env

BASE = "https://api-seller.ozon.ru"


def _headers() -> dict:
    client_id, api_key = require_env("OZON_CLIENT_ID", "OZON_API_KEY")
    return {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}


def _post(path: str, body: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        resp = requests.post(f"{BASE}{path}", headers=_headers(), json=body, timeout=60)
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise SystemExit(f"Ozon Seller API {resp.status_code} на {path}: {resp.text[:500]}")
        return resp.json()
    raise SystemExit(f"Ozon Seller API: превышен лимит запросов на {path}")


def resolve_product_id(offer_id: str) -> int:
    data = _post("/v3/product/info/list", {"offer_id": [offer_id]})
    items = (data.get("items") or data.get("result", {}).get("items") or [])
    if not items:
        raise SystemExit(f"Товар с offer_id={offer_id} не найден")
    return int(items[0]["id"])


def get_product_info(product_id: int) -> dict:
    data = _post("/v3/product/info/list", {"product_id": [product_id]})
    items = (data.get("items") or data.get("result", {}).get("items") or [])
    if not items:
        raise SystemExit(f"Товар product_id={product_id} не найден")
    return items[0]


def get_images(product_id: int) -> tuple[list[str], str]:
    """Возвращает (все картинки по порядку, текущая обложка)."""
    info = get_product_info(product_id)
    images = list(info.get("images") or [])
    primary = info.get("primary_image") or ""
    if isinstance(primary, list):
        primary = primary[0] if primary else ""
    if primary and primary not in images:
        images = [primary] + images
    if not primary and images:
        primary = images[0]
    return images, primary


def _norm(url: str) -> str:
    """Для сравнения URL: без протокола и query, только путь/имя файла."""
    u = url.split("?", 1)[0].rstrip("/")
    u = u.split("://", 1)[-1]
    return u.lower()


def import_pictures(product_id: int, images: list[str], color_image: str = "") -> list[dict]:
    body = {"product_id": int(product_id), "images": images, "images360": [], "color_image": color_image}
    data = _post("/v1/product/pictures/import", body)
    return (data.get("result") or {}).get("pictures", [])


def set_cover(product_id: int, image_url: str) -> dict:
    """Ставит image_url первым в списке. Возвращает отчёт о действии."""
    images, primary = get_images(product_id)
    known = {_norm(u): u for u in images}
    match = known.get(_norm(image_url))
    if match is None:
        raise SystemExit(
            f"Картинки нет в карточке: {image_url}\n"
            f"Сначала залей все варианты и дождись модерации: python init.py"
        )
    if _norm(primary) == _norm(match):
        return {"changed": False, "primary": primary, "order": images}

    reordered = [match] + [u for u in images if _norm(u) != _norm(match)]
    pics = import_pictures(product_id, reordered)
    return {"changed": True, "from": primary, "to": match, "order": reordered, "pictures": pics}


def _main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "resolve":
        print(resolve_product_id(argv[1]))
    elif cmd == "pictures":
        images, primary = get_images(int(argv[1]))
        print(f"Обложка: {primary}\n")
        for i, u in enumerate(images):
            print(f"  [{i}]{' *' if u == primary else '  '} {u}")
    elif cmd == "set-cover":
        res = set_cover(int(argv[1]), argv[2])
        print("Без изменений (уже стоит)." if not res["changed"]
              else f"Обложка изменена:\n  было:  {res['from']}\n  стало: {res['to']}")
    else:
        raise SystemExit(f"Неизвестная команда: {cmd}")


if __name__ == "__main__":
    _main(sys.argv[1:])
