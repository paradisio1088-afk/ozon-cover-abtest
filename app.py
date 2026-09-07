#!/usr/bin/env python3
"""Локальный веб-интерфейс A/B-теста обложки Ozon.

  python app.py            # http://127.0.0.1:8765

Ставит ключи, грузит фото в GitHub и в карточку, запускает тест, показывает отчёт.
Фоновая ротация — отдельно через launchd (см. install_service.sh).
"""

from __future__ import annotations

import base64
import json
import threading
import traceback
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from common import (DATA_DIR, ROOT, load_config, load_config_raw, load_secrets,
                    now_msk, save_config, save_secrets)

HOST, PORT = "127.0.0.1", 8765
STATIC = ROOT / "static"


# ─── сбор состояния для фронта ───────────────────────────────────────────────

def masked_secrets() -> dict:
    s = load_secrets()
    def show(v: str) -> str:
        v = str(v or "")
        return "" if not v else ("•" * max(len(v) - 4, 0) + v[-4:] if len(v) > 4 else "••••")
    return {
        "ozon_client_id": str(s.get("ozon_client_id", "")),
        "ozon_api_key": show(s.get("ozon_api_key", "")),
        "perf_client_id": s.get("perf_client_id", ""),
        "perf_client_secret": show(s.get("perf_client_secret", "")),
        "github_repo": s.get("github_repo", ""),
        "github_token": show(s.get("github_token", "")),
        "has": {k: bool(s.get(k)) for k in
                ("ozon_client_id", "ozon_api_key", "perf_client_id",
                 "perf_client_secret", "github_repo", "github_token")},
    }


def status_block() -> dict:
    cfg = load_config()
    t = cfg["test"]
    out = {"enabled": t.get("enabled"), "start": t.get("start"),
           "n_variants": len(cfg["variants"]), "phase": "idle"}
    if not t.get("start"):
        out["phase"] = "not_started"
        return out
    try:
        from abtest import (block_order, current_block, finish_dt, load_state,
                            schedule_table, switch_time_for_block, target_variant)
        now = now_msk()
        b = current_block(cfg, now)
        order = block_order(cfg)
        state = load_state()
        if b < 0:
            out["phase"] = "scheduled"
        elif b >= len(order):
            out["phase"] = "finished"
        else:
            out["phase"] = "running"
            vi = target_variant(cfg, now)
            out["block"] = b + 1
            out["total_blocks"] = len(order)
            out["cycle"] = b // t["n_variants"] + 1
            out["active_variant"] = cfg["variants"][vi]["name"] if vi is not None else None
            sw = switch_time_for_block(state, b)
            out["switch_confirmed"] = sw.isoformat(timespec="minutes") if sw else None
        out["finish"] = finish_dt(cfg).isoformat(timespec="minutes")
        out["schedule"] = schedule_table(cfg)
        out["switches"] = state.get("switches", [])[-20:]
    except Exception:
        out["error"] = traceback.format_exc().splitlines()[-1]
    return out


def full_state() -> dict:
    raw = load_config_raw()
    results = None
    rp = DATA_DIR / "results.json"
    if rp.exists():
        results = json.loads(rp.read_text())
    report = ""
    rmd = ROOT / "report.md"
    if rmd.exists():
        report = rmd.read_text()
    log_tail = ""
    lp = DATA_DIR / "worker.log"
    if lp.exists():
        log_tail = "\n".join(lp.read_text().splitlines()[-40:])
    return {
        "secrets": masked_secrets(),
        "config": raw,
        "status": status_block(),
        "results": results,
        "report_md": report,
        "worker_log": log_tail,
        "campaigns_cache": (DATA_DIR / "campaigns.json").exists()
        and json.loads((DATA_DIR / "campaigns.json").read_text()) or [],
    }


# ─── обработчики действий ────────────────────────────────────────────────────

def act_check(_: dict) -> dict:
    res = {}
    try:
        from ozon_seller import _post
        _post("/v3/product/list", {"filter": {}, "limit": 1})
        res["ozon"] = {"ok": True}
    except (SystemExit, Exception) as e:
        res["ozon"] = {"ok": False, "error": str(e)}
    try:
        from ozon_performance import list_campaigns
        c = list_campaigns()
        res["perf"] = {"ok": True, "campaigns": len(c)}
    except (SystemExit, Exception) as e:
        res["perf"] = {"ok": False, "error": str(e)}
    try:
        from image_host import check
        res["github"] = {"ok": True, **check()}
    except (SystemExit, Exception) as e:
        res["github"] = {"ok": False, "error": str(e)}
    return res


def act_product(body: dict) -> dict:
    from ozon_seller import get_images, resolve_product_id
    offer = str(body.get("offer_id", "")).strip()
    pid = int(body["product_id"]) if body.get("product_id") else resolve_product_id(offer)
    images, primary = get_images(pid)
    save_config({"product_id": pid, "offer_id": offer})
    return {"product_id": pid, "offer_id": offer, "current_cover": primary, "images": images}


def act_campaigns(_: dict) -> dict:
    from ozon_performance import list_campaigns
    rows = [{"id": str(c.get("id")), "title": c.get("title", ""),
             "state": c.get("state", ""), "type": c.get("advObjectType", "")}
            for c in list_campaigns()]
    (DATA_DIR / "campaigns.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    return {"campaigns": rows}


def act_photos(body: dict) -> dict:
    from image_host import make_filename, upload_image
    raw = load_config_raw()
    variants = [] if body.get("replace") else list(raw.get("variants", []))
    for item in body.get("photos", []):
        data = base64.b64decode(item["data_b64"].split(",")[-1])
        fname = make_filename(data, item.get("filename", "cover.jpg"))
        up = upload_image(data, fname, message=f"cover variant {item.get('name','')}")
        variants.append({"name": item.get("name") or f"Вариант {len(variants)+1}",
                         "url": up["url"], "filename": fname})
    cfg = save_config({"variants": variants})
    return {"variants": cfg["variants"]}


def act_photos_delete(body: dict) -> dict:
    raw = load_config_raw()
    v = list(raw.get("variants", []))
    i = int(body["index"])
    if 0 <= i < len(v):
        v.pop(i)
    cfg = save_config({"variants": v})
    return {"variants": cfg["variants"]}


def act_photos_rename(body: dict) -> dict:
    raw = load_config_raw()
    v = list(raw.get("variants", []))
    i = int(body["index"])
    if 0 <= i < len(v):
        v[i]["name"] = str(body.get("name", "")).strip() or v[i]["name"]
    cfg = save_config({"variants": v})
    return {"variants": cfg["variants"]}


def act_config(body: dict) -> dict:
    allowed = ("name", "campaign_ids", "block_days", "cycles", "settle_hours",
               "shuffle_each_cycle", "min_impressions_per_variant", "apply_winner_on_finish")
    patch = {k: body[k] for k in allowed if k in body}
    if "campaign_ids" in patch:
        patch["campaign_ids"] = [str(x) for x in patch["campaign_ids"]]
    return {"config": save_config(patch)}


def act_init(_: dict) -> dict:
    from init import status as init_status, upload_missing
    cfg = load_config()
    if len(cfg["variants"]) < 2:
        raise SystemExit("Сначала загрузите минимум 2 варианта фото")
    upload_missing(cfg)
    present, missing = init_status(cfg)
    return {"present": present, "missing": missing,
            "ready": not missing, "total": len(cfg["variants"])}


def act_init_status(_: dict) -> dict:
    from init import status as init_status
    cfg = load_config()
    present, missing = init_status(cfg)
    return {"present": present, "missing": missing,
            "ready": not missing, "total": len(cfg["variants"])}


def _next_midnight_msk() -> str:
    d = (now_msk() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.strftime("%Y-%m-%dT%H:%M")


def act_test_start(body: dict) -> dict:
    from init import status as init_status
    cfg = load_config()
    if len(cfg["variants"]) < 2:
        raise SystemExit("Нужно минимум 2 варианта обложки")
    if not cfg["test"].get("product_id"):
        raise SystemExit("Не выбран товар")
    if not cfg["test"].get("campaign_ids"):
        raise SystemExit("Не выбраны рекламные кампании")
    _, missing = init_status(cfg)
    if missing:
        raise SystemExit(f"Не все фото прошли модерацию в карточке ({len(missing)} осталось). "
                         f"Нажмите «Проверить готовность» позже.")
    start = str(body.get("start", "")).strip() or _next_midnight_msk()
    from abtest import save_state
    save_state({"switches": [], "winner_applied": None})
    save_config({"start": start, "enabled": True})
    return {"start": start, "status": status_block()}


def act_test_stop(_: dict) -> dict:
    save_config({"enabled": False})
    return {"status": status_block()}


def act_test_reset(_: dict) -> dict:
    from abtest import save_state
    save_state({"switches": [], "winner_applied": None})
    save_config({"start": "", "enabled": False})
    for f in ("results.json", "daily.csv"):
        (DATA_DIR / f).unlink(missing_ok=True)
    (ROOT / "report.md").unlink(missing_ok=True)
    return {"status": status_block()}


def act_run_now(_: dict) -> dict:
    import worker
    summary = worker.run()
    return {"summary": summary, "state": full_state()}


def act_apply_winner(body: dict) -> dict:
    from ozon_seller import set_cover
    cfg = load_config()
    i = int(body["index"])
    v = cfg["variants"][i]
    res = set_cover(cfg["test"]["product_id"], v["url"])
    return {"applied": v["name"], "changed": res.get("changed")}


ACTIONS = {
    "/api/secrets": lambda b: (save_secrets(b), {"secrets": masked_secrets()})[1],
    "/api/check": act_check,
    "/api/product": act_product,
    "/api/campaigns": act_campaigns,
    "/api/photos": act_photos,
    "/api/photos/delete": act_photos_delete,
    "/api/photos/rename": act_photos_rename,
    "/api/config": act_config,
    "/api/init": act_init,
    "/api/init/status": act_init_status,
    "/api/test/start": act_test_start,
    "/api/test/stop": act_test_stop,
    "/api/test/reset": act_test_reset,
    "/api/run-now": act_run_now,
    "/api/apply-winner": act_apply_winner,
}


# ─── HTTP ────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # тише
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self._file(STATIC / "index.html")
        if path == "/api/state":
            return self._json(full_state())
        if path.startswith("/static/"):
            return self._file(STATIC / path[len("/static/"):])
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        fn = ACTIONS.get(path)
        if not fn:
            return self._json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._json({"ok": True, **(fn(body) or {})})
        except SystemExit as e:
            self._json({"ok": False, "error": str(e)}, 400)
        except Exception:
            tb = traceback.format_exc()
            print(tb)
            self._json({"ok": False, "error": tb.splitlines()[-1]}, 500)

    def _file(self, p: Path) -> None:
        p = p.resolve()
        if not str(p).startswith(str(STATIC.resolve())) and p != (STATIC / "index.html").resolve():
            return self._json({"error": "forbidden"}, 403)
        if not p.exists():
            return self._json({"error": "not found"}, 404)
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}.get(p.suffix, "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"A/B-тест обложки Ozon — интерфейс: {url}\nCtrl+C для остановки.")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
