#!/usr/bin/env python3
"""Заливка вариантов обложки в GitHub-репозиторий и получение постоянных
публичных ссылок через CDN jsDelivr.

ImgBB не подошёл — блокирует запросы из России. GitHub + jsDelivr работают,
ссылки постоянные (важно: Ozon может скачивать картинку не сразу, а из очереди
модерации).

Нужно (см. README):
  github_repo  — owner/repo (публичный репозиторий подойдёт, фото товара не секрет)
  github_token — classic token со scope public_repo (или repo для приватного)

Ссылка: https://cdn.jsdelivr.net/gh/<owner>/<repo>@<commit>/photos/<file>
Коммит в ссылке -> доступно сразу, без задержки CDN-кеша.
"""

from __future__ import annotations

import base64
import hashlib

import requests

from common import load_secrets

API = "https://api.github.com"


def _repo_token() -> tuple[str, str]:
    s = load_secrets()
    repo = s.get("github_repo", "").strip().removeprefix("https://github.com/").strip("/")
    token = s.get("github_token", "").strip()
    if not repo or repo.count("/") != 1 or not token:
        raise SystemExit("Не заданы GitHub-репозиторий (owner/repo) и токен (раздел «Подключение»)")
    return repo, token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _repo_info(repo: str, token: str) -> dict:
    r = requests.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=30)
    if r.status_code == 401:
        raise SystemExit("неверный или просроченный токен")
    if r.status_code == 404:
        raise SystemExit(f"репозиторий {repo} не найден или у токена нет доступа")
    if r.status_code >= 400:
        raise SystemExit(f"GitHub {r.status_code}: {r.text[:300]}")
    return r.json()


def check() -> dict:
    repo, token = _repo_token()
    info = _repo_info(repo, token)
    return {"repo": repo, "private": info.get("private"),
            "branch": info.get("default_branch", "main"),
            "empty": info.get("size", 1) == 0}


def upload_image(data: bytes, filename: str, message: str = "add cover variant") -> dict:
    """Кладёт photos/<filename> в репозиторий. Возвращает {url, filename, commit}."""
    repo, token = _repo_token()
    info = _repo_info(repo, token)
    branch = info.get("default_branch", "main")
    path = f"photos/{filename}"
    url = f"{API}/repos/{repo}/contents/{path}"

    body = {"message": message, "content": base64.b64encode(data).decode()}
    if info.get("size", 1) != 0:  # непустой репо -> указываем ветку и sha при перезаписи
        body["branch"] = branch
        cur = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=30)
        if cur.status_code == 200:
            body["sha"] = cur.json()["sha"]

    r = requests.put(url, headers=_headers(token), json=body, timeout=90)
    if r.status_code >= 400:
        hint = ""
        if "Repository is empty" in r.text or r.status_code == 409:
            hint = "\nОткрой репозиторий на GitHub и добавь любой файл (кнопка «Add a README»)."
        raise SystemExit(f"GitHub upload {r.status_code}: {r.text[:300]}{hint}")
    res = r.json()
    commit_sha = res["commit"]["sha"]
    return {"url": f"https://cdn.jsdelivr.net/gh/{repo}@{commit_sha}/photos/{filename}",
            "filename": filename, "commit": commit_sha}


def _ext(filename: str, data: bytes) -> str:
    for e in (".jpg", ".jpeg", ".png", ".webp"):
        if filename.lower().endswith(e):
            return ".jpg" if e == ".jpeg" else e
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def make_filename(data: bytes, original: str) -> str:
    return f"{hashlib.sha1(data).hexdigest()[:12]}{_ext(original, data)}"


def _main() -> None:
    print(check())


if __name__ == "__main__":
    _main()
