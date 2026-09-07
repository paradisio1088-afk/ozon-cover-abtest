#!/usr/bin/env python3
"""Заливка картинок в GitHub-репозиторий и получение публичных ссылок (jsDelivr CDN).

Нужен Personal Access Token с правом Contents: write на выбранный репозиторий.
Файлы кладутся в папку photos/ и раздаются через
https://cdn.jsdelivr.net/gh/<owner>/<repo>@<commit>/photos/<file>
(коммит в ссылке -> мгновенно доступно, без задержки CDN-кеша).
"""

from __future__ import annotations

import base64
import hashlib

import requests

from common import load_secrets

API = "https://api.github.com"


def _repo_token() -> tuple[str, str]:
    s = load_secrets()
    repo, token = s.get("github_repo", "").strip(), s.get("github_token", "").strip()
    if not repo or "/" not in repo or not token:
        raise SystemExit("Не заданы GitHub-репозиторий (owner/repo) и токен (раздел «Подключение»)")
    return repo, token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def check_repo() -> dict:
    repo, token = _repo_token()
    r = requests.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=30)
    if r.status_code == 404:
        raise SystemExit(f"Репозиторий {repo} не найден или токен без доступа к нему")
    if r.status_code >= 400:
        raise SystemExit(f"GitHub {r.status_code}: {r.text[:300]}")
    data = r.json()
    return {"repo": repo, "private": data.get("private"),
            "default_branch": data.get("default_branch", "main")}


def _default_branch(repo: str, token: str) -> str:
    r = requests.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json().get("default_branch", "main")


def upload_image(data: bytes, filename: str, message: str = "add cover variant") -> dict:
    """Загружает/обновляет photos/<filename>. Возвращает {url, filename, sha, commit}."""
    repo, token = _repo_token()
    branch = _default_branch(repo, token)
    path = f"photos/{filename}"
    url = f"{API}/repos/{repo}/contents/{path}"

    existing = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=30)
    body = {"message": message, "content": base64.b64encode(data).decode(), "branch": branch}
    if existing.status_code == 200:
        body["sha"] = existing.json()["sha"]

    r = requests.put(url, headers=_headers(token), json=body, timeout=60)
    if r.status_code >= 400:
        raise SystemExit(f"GitHub upload {r.status_code}: {r.text[:300]}")
    res = r.json()
    commit_sha = res["commit"]["sha"]
    blob_sha = res["content"]["sha"]
    cdn = f"https://cdn.jsdelivr.net/gh/{repo}@{commit_sha}/photos/{filename}"
    return {"url": cdn, "filename": filename, "sha": blob_sha, "commit": commit_sha}


def guess_ext(filename: str, data: bytes) -> str:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if filename.lower().endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def make_filename(data: bytes, original: str) -> str:
    digest = hashlib.sha1(data).hexdigest()[:12]
    return f"{digest}{guess_ext(original, data)}"


def _main() -> None:
    print(check_repo())


if __name__ == "__main__":
    _main()
