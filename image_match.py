"""Сопоставление вариантов обложки с фото в карточке по похожести.

Ozon при загрузке скачивает картинку и перевыкладывает на свой CDN (ir.ozone.ru),
исходная ссылка не сохраняется. Поэтому «какой из вариантов сейчас в карточке»
определяем перцептивным хэшем (average hash), а не сравнением URL.
"""

from __future__ import annotations

import io

import requests
from PIL import Image

_UA = {"User-Agent": "Mozilla/5.0"}
_cache: dict[str, int] = {}


def _fetch(url: str) -> bytes:
    return requests.get(url, headers=_UA, timeout=30).content


def ahash(data: bytes, n: int = 8) -> int:
    im = Image.open(io.BytesIO(data)).convert("L").resize((n, n))
    px = list(im.getdata())
    avg = sum(px) / len(px)
    bits = 0
    for i, p in enumerate(px):
        if p >= avg:
            bits |= 1 << i
    return bits


def _url_hash(url: str) -> int | None:
    if url in _cache:
        return _cache[url]
    try:
        h = ahash(_fetch(url))
    except Exception:
        return None
    _cache[url] = h
    return h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def match_url(target_url: str, candidates: list[str], threshold: int = 12) -> str | None:
    """URL из candidates, наиболее похожий на target_url (или None)."""
    th = _url_hash(target_url)
    if th is None:
        return None
    best_u, best_d = None, 999
    for u in candidates:
        ch = _url_hash(u)
        if ch is None:
            continue
        d = hamming(th, ch)
        if d < best_d:
            best_d, best_u = d, u
    return best_u if best_d <= threshold else None


def present(variant_urls: list[str], card_urls: list[str], threshold: int = 12) -> list[str]:
    """Какие variant_urls уже есть среди card_urls (по похожести)."""
    card_h = [h for h in (_url_hash(u) for u in card_urls) if h is not None]
    out = []
    for vu in variant_urls:
        vh = _url_hash(vu)
        if vh is not None and any(hamming(vh, ch) <= threshold for ch in card_h):
            out.append(vu)
    return out
