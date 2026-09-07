#!/usr/bin/env python3
"""Загрузка картинок на ImgBB и получение публичных ссылок (i.ibb.co).

Нужен бесплатный API-ключ: https://api.imgbb.com/ (после регистрации на imgbb.com).
Картинки по умолчанию не удаляются. Ozon скачивает их по ссылке при импорте.
"""

from __future__ import annotations

import hashlib

import requests

from common import load_secrets

ENDPOINT = "https://api.imgbb.com/1/upload"


def _key() -> str:
    k = load_secrets().get("imgbb_key", "").strip()
    if not k:
        raise SystemExit("Не задан ключ ImgBB (раздел «Подключение»)")
    return k


def check() -> dict:
    """Проверка ключа: пробная загрузка крошечного PNG."""
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    r = requests.post(ENDPOINT, data={"key": _key(), "image": tiny_png_b64,
                                      "name": "abtest-check", "expiration": 60}, timeout=30)
    if r.status_code == 400 and "Invalid API" in r.text:
        raise SystemExit("Неверный ключ ImgBB")
    if r.status_code >= 400:
        raise SystemExit(f"ImgBB {r.status_code}: {r.text[:200]}")
    return {"ok": True}


def _b64(data_or_b64) -> str:
    if isinstance(data_or_b64, bytes):
        import base64
        return base64.b64encode(data_or_b64).decode()
    return str(data_or_b64).split(",")[-1]  # убрать data:image/...;base64,


def make_filename(data: bytes, original: str) -> str:
    ext = ".jpg"
    for e in (".jpg", ".jpeg", ".png", ".webp"):
        if original.lower().endswith(e):
            ext = ".jpg" if e == ".jpeg" else e
    return f"{hashlib.sha1(data).hexdigest()[:12]}{ext}"


def upload_image(data, filename: str, message: str = "") -> dict:
    """data — bytes или base64-строка. Возвращает {url, filename}."""
    r = requests.post(ENDPOINT, data={
        "key": _key(),
        "image": _b64(data),
        "name": filename.rsplit(".", 1)[0],
    }, timeout=120)
    if r.status_code >= 400:
        raise SystemExit(f"ImgBB загрузка {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success"):
        raise SystemExit(f"ImgBB: {body.get('error', {}).get('message', 'ошибка')}")
    d = body["data"]
    return {"url": d.get("display_url") or d["url"], "filename": filename,
            "delete_url": d.get("delete_url", "")}


def _main() -> None:
    print(check())


if __name__ == "__main__":
    _main()
