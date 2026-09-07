#!/usr/bin/env python3
"""Один прогон фоновой работы: переключить обложку по расписанию, собрать
статистику, пересчитать отчёт. Запускается по расписанию (launchd) и из
кнопки «Обновить сейчас» в интерфейсе.

  python worker.py            # полный прогон
  python worker.py --rotate-only
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime

from common import DATA_DIR, load_config, now_msk

LOG_PATH = DATA_DIR / "worker.log"
RESULTS_PATH = DATA_DIR / "results.json"


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    DATA_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as fh:
        fh.write(line + "\n")


def run(rotate_only: bool = False) -> dict:
    cfg = load_config()
    summary = {"ran_at": now_msk().isoformat(timespec="seconds"), "steps": {}}

    if not cfg["test"].get("enabled"):
        log("тест выключен — пропускаю")
        summary["steps"]["skipped"] = "тест выключен"
        return summary

    # 1. ротация обложки
    try:
        import rotate
        rc = rotate.main([])
        summary["steps"]["rotate"] = "ok" if rc == 0 else f"код {rc}"
    except SystemExit as e:
        summary["steps"]["rotate"] = f"ошибка: {e}"
        log(f"rotate: {e}")
    except Exception:
        summary["steps"]["rotate"] = "исключение"
        log("rotate ИСКЛЮЧЕНИЕ:\n" + traceback.format_exc())

    if rotate_only:
        return summary

    # 2. сбор статистики
    try:
        import collect
        collect.main([])
        summary["steps"]["collect"] = "ok"
    except SystemExit as e:
        summary["steps"]["collect"] = f"нет данных/ошибка: {e}"
        log(f"collect: {e}")
    except Exception:
        summary["steps"]["collect"] = "исключение"
        log("collect ИСКЛЮЧЕНИЕ:\n" + traceback.format_exc())

    # 3. анализ
    try:
        import analyze
        acfg = load_config()
        res = analyze.compute_results(acfg)
        analyze.REPORT_MD.write_text(analyze.build_report(acfg, res))
        RESULTS_PATH.write_text(json.dumps(_slim(res), ensure_ascii=False, indent=2, default=str))
        summary["steps"]["analyze"] = "ok"
        summary["winner"] = res["winner"]["variant_name"] if res.get("winner") else None
        summary["significant"] = res.get("significant")
    except SystemExit as e:
        summary["steps"]["analyze"] = f"мало данных: {e}"
    except Exception:
        summary["steps"]["analyze"] = "исключение"
        log("analyze ИСКЛЮЧЕНИЕ:\n" + traceback.format_exc())

    return summary


def _slim(res: dict) -> dict:
    return {
        "ranked": res["ranked"],
        "comparisons": [{**c, "ci95": list(c["ci95"])} for c in res["comparisons"]],
        "omnibus": res["omnibus"],
        "cycles": res["cycles"],
        "by_cycle": res["by_cycle"],
        "significant": res["significant"],
        "consistent": res["consistent"],
        "enough_data": res["enough_data"],
        "winner": res["winner"],
        "needed_views_per_variant": res["needed_views_per_variant"],
        "total_views": res["total_views"],
        "total_clicks": res["total_clicks"],
        "updated_at": now_msk().isoformat(timespec="seconds"),
    }


def main(argv: list[str]) -> int:
    summary = run(rotate_only="--rotate-only" in argv)
    log("итог: " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
