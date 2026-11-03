#!/usr/bin/env python3
"""Run every question through the tutor's retrieval and check the expected sections.

    .venv/bin/python .claude/skills/tutor-quality-check/scripts/check_retrieval.py \
        [--only trap,terminology] [--baseline data/quality_runs/<old>.json]

Run from the rag/ project root. Uses the real pipeline (tutor.main_rag: query
translation with qwen3, nomic-embed-text, Chroma), so Ollama must be running.
Only retrieval is checked here: a question passes when one of its expected sections is
among the retrieved sources. Results go to data/quality_runs/ (not in git); the newest
earlier run is used as the baseline unless --baseline is given.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

SKILL_DIR = Path(__file__).resolve().parents[1]
QUESTIONS = SKILL_DIR / "questions.jsonl"
RUNS_DIR = Path("data/quality_runs")


def load_questions(path: Path, only: set[str]) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if not only or row["category"] in only or row["id"] in only]


def check_one(retriever, item: dict) -> dict:
    from tutor.retrieval import source_list

    started = time.perf_counter()
    query = retriever._rewrite(item["question"])
    blocks = retriever.retrieve(item["question"])
    sources = [source["section"] for source in source_list(blocks)]
    expected = item["expect_sections"]
    if not expected:
        status = "info"  # out of scope: judged from the answer, not from retrieval
    elif sources and sources[0] in expected:
        status = "top1"
    elif any(section in expected for section in sources):
        status = "hit"
    else:
        status = "miss"
    return {"id": item["id"], "question": item["question"], "category": item["category"],
            "query": query, "sources": sources, "expected": expected, "status": status,
            "seconds": round(time.perf_counter() - started, 2)}


def latest_run(exclude: Path | None = None) -> Path | None:
    runs = sorted(RUNS_DIR.glob("*-retrieval.json"))
    runs = [run for run in runs if run != exclude]
    return runs[-1] if runs else None


def compare(current: list[dict], baseline_path: Path) -> list[str]:
    rank = {"miss": 0, "hit": 1, "top1": 2, "info": -1}
    before = {r["id"]: r for r in json.loads(baseline_path.read_text(encoding="utf-8"))["results"]}
    lines = []
    for result in current:
        old = before.get(result["id"])
        if old is None or old["status"] == result["status"] or result["status"] == "info":
            continue
        arrow = "改善" if rank[result["status"]] > rank[old["status"]] else "變差"
        lines.append(f"  {arrow}：{result['id']} {old['status']} → {result['status']}"
                     f"（{old['sources'][:3]} → {result['sources'][:3]}）")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="檢查助教系統的檢索是否命中正確章節")
    parser.add_argument("--only", default="", help="只跑這些類別或 id，逗號分隔")
    parser.add_argument("--baseline", type=Path, help="比較對象；預設為上一次的結果")
    parser.add_argument("--note", default="", help="這次改了什麼（寫進結果檔）")
    args = parser.parse_args()
    if not Path("tutor/retrieval.py").exists():
        sys.exit("請在 rag/ 專案根目錄執行")
    sys.path.insert(0, str(Path.cwd()))
    from tutor.main_rag import _tutor

    only = {part.strip() for part in args.only.split(",") if part.strip()}
    items = load_questions(QUESTIONS, only)
    try:
        retriever, _ = _tutor()
    except (RuntimeError, FileNotFoundError) as error:
        sys.exit(f"無法開啟檢索：{error}")
    results = []
    for item in items:
        result = check_one(retriever, item)
        results.append(result)
        mark = {"top1": "✓1", "hit": "✓ ", "miss": "✗ ", "info": "· "}[result["status"]]
        print(f"{mark} {result['id']:32s} 期望 {','.join(result['expected']) or '（教材外）':14s}"
              f" → {', '.join(result['sources'][:3]):24s} 檢索詞：{result['query'][:60]}", flush=True)

    scored = [r for r in results if r["status"] != "info"]
    summary = {status: sum(r["status"] == status for r in scored) for status in ("top1", "hit", "miss")}
    by_category: dict[str, list[int]] = {}
    for r in scored:
        counts = by_category.setdefault(r["category"], [0, 0])
        counts[0] += r["status"] != "miss"
        counts[1] += 1
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-retrieval.json"
    baseline = args.baseline or latest_run()
    out.write_text(json.dumps({"note": args.note, "summary": summary, "by_category": by_category,
                               "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    hits = summary["top1"] + summary["hit"]
    print(f"\n命中 {hits}/{len(scored)}（第一名就對 {summary['top1']}），"
          + "；".join(f"{c} {h}/{n}" for c, (h, n) in by_category.items()))
    if baseline and baseline.exists():
        changes = compare(results, baseline)
        print(f"與 {baseline.name} 比較：" + ("沒有變化" if not changes else ""))
        print("\n".join(changes))
    print(f"結果：{out}")


if __name__ == "__main__":
    main()
