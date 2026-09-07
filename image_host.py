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


def _branch_head(repo: str, token: str, branch: str) -> str | None:
    """SHA коммита в вершине ветки, либо None если репозиторий пустой."""
    r = requests.get(f"{API}/repos/{repo}/git/ref/heads/{branch}",
                     headers=_headers(token), timeout=30)
    return r.json()["object"]["sha"] if r.status_code == 200 else None


def _init_repo(repo: str, token: str, branch: str) -> None:
    """Создаёт первый коммит (README) в пустом репозитории через Git Data API."""
    h = _headers(token)
    blob = requests.post(f"{API}/repos/{repo}/git/blobs", headers=h,
                         json={"content": "# covers\n", "encoding": "utf-8"}, timeout=30).json()
    tree = requests.post(f"{API}/repos/{repo}/git/trees", headers=h, json={"tree": [
        {"path": "README.md", "mode": "100644", "type": "blob", "sha": blob["sha"]}]}, timeout=30).json()
    commit = requests.post(f"{API}/repos/{repo}/git/commits", headers=h,
                           json={"message": "init", "tree": tree["sha"], "parents": []}, timeout=30).json()
    requests.post(f"{API}/repos/{repo}/git/refs", headers=h,
                  json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]}, timeout=30)


def check() -> dict:
    repo, token = _repo_token()
    info = _repo_info(repo, token)
    branch = info.get("default_branch", "main")
    return {"repo": repo, "private": info.get("private"), "branch": branch,
            "empty": _branch_head(repo, token, branch) is None}


def upload_image(data: bytes, filename: str, message: str = "add cover variant") -> dict:
    """Кладёт photos/<filename> в репозиторий. Возвращает {url, filename, commit}."""
    repo, token = _repo_token()
    info = _repo_info(repo, token)
    branch = info.get("default_branch", "main")
    if _branch_head(repo, token, branch) is None:      # пустой репозиторий — инициализируем
        _init_repo(repo, token, branch)

    path = f"photos/{filename}"
    url = f"{API}/repos/{repo}/contents/{path}"
    body = {"message": message, "content": base64.b64encode(data).decode(), "branch": branch}
    cur = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=30)
    if cur.status_code == 200:                         # файл уже есть — перезаписываем
        body["sha"] = cur.json()["sha"]

    r = requests.put(url, headers=_headers(token), json=body, timeout=90)
    if r.status_code >= 400:
        raise SystemExit(f"GitHub upload {r.status_code}: {r.text[:300]}")
    commit_sha = r.json()["commit"]["sha"]
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
