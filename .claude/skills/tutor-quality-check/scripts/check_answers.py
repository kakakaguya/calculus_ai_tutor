#!/usr/bin/env python3
"""Ask the tutor selected questions and run the checks a program can decide.

    .venv/bin/python .claude/skills/tutor-quality-check/scripts/check_answers.py \
        --only trap,out_of_scope

Run from the rag/ project root; each answer takes about 40-60 s (qwen3:8b with thinking).
Automatic checks: simplified characters, sources listed, citation markers that point to
real sources, balanced LaTeX delimiters. Whether the mathematics is right is NOT decided
here: the answers are written next to each question's key_points into a Markdown file
for Claude to judge (see SKILL.md, step 3).
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time

SKILL_DIR = Path(__file__).resolve().parents[1]
QUESTIONS = SKILL_DIR / "questions.jsonl"
RUNS_DIR = Path("data/quality_runs")
# Characters that exist only in Simplified Chinese (their Traditional forms differ).
SIMPLIFIED = set("这们个为说时数导变积极线实点发应题门关现开过还进对会无于与从动种样经结级计认让"
                 "几义总图论设证达适间问么将边长连续简单复杂专业转换类别区阶层级处决断")
SIMPLIFIED -= set("于与")  # 於/于 and 與/与 also appear in Traditional usage; too noisy to flag
# The prompt asks for ［1］, but qwen3 also writes 【教材 1】 (copying the context labels).
CITATION = re.compile(r"(?:［\s*|【\s*(?:教材|例題)?\s*)(\d+)\s*[］】]")


def auto_checks(answer: str, sources: list[dict]) -> dict:
    simplified = sorted({char for char in answer if char in SIMPLIFIED})
    cited = sorted({int(n) for n in CITATION.findall(answer)})
    numbers = {source["number"] for source in sources}
    return {
        "simplified_chars": "".join(simplified),
        "has_sources": bool(sources),
        "citations": cited,
        "citations_out_of_range": [n for n in cited if n not in numbers],
        "latex_balanced": answer.count("$$") % 2 == 0 and answer.count("\\(") == answer.count("\\)")
        and answer.count("\\[") == answer.count("\\]"),
        "chars": len(answer),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="讓助教回答問題並做自動檢查")
    parser.add_argument("--only", default="trap,out_of_scope", help="類別或 id，逗號分隔")
    args = parser.parse_args()
    if not Path("tutor/main_rag.py").exists():
        sys.exit("請在 rag/ 專案根目錄執行")
    sys.path.insert(0, str(Path.cwd()))
    from tutor.main_rag import ask

    only = {part.strip() for part in args.only.split(",") if part.strip()}
    items = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = [item for item in items if not only or item["category"] in only or item["id"] in only]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    results, review = [], [f"# 助教回答檢查 {stamp}\n"]
    for item in items:
        started = time.perf_counter()
        try:
            result = ask(item["question"])
        except Exception as error:  # report and continue with the next question
            print(f"✗ {item['id']}：{error}", flush=True)
            results.append({"id": item["id"], "error": str(error)})
            continue
        seconds = round(time.perf_counter() - started, 1)
        sources = list(result.sources)
        checks = auto_checks(result.answer, sources)
        out_of_scope = not item["expect_sections"]
        flags = [name for name, bad in (("簡體字 " + checks["simplified_chars"], checks["simplified_chars"]),
                                        ("沒有來源", not checks["has_sources"] and not out_of_scope),
                                        ("引用編號不存在", checks["citations_out_of_range"]),
                                        ("教材外題目卻引用教材", out_of_scope and checks["citations"]),
                                        ("LaTeX 不成對", not checks["latex_balanced"])) if bad]
        print(f"{'✗' if flags else '✓'} {item['id']:32s} {seconds:5.1f}s  {'；'.join(flags)}", flush=True)
        results.append({"id": item["id"], "seconds": seconds, "checks": checks, "flags": flags,
                        "sources": [s["label"] for s in sources], "answer": result.answer})
        review += [f"## {item['id']}：{item['question']}",
                   f"- 類別：{item['category']}；期望章節：{', '.join(item['expect_sections']) or '教材外'}",
                   f"- 實際來源：{', '.join(s['label'] for s in sources) or '無'}",
                   f"- 自動檢查：{'；'.join(flags) or '通過'}（{seconds} 秒）",
                   "- 必須包含（Claude 判斷）：" + "；".join(item["key_points"]),
                   *([f"- 已知陷阱：{item['pitfall']}"] if item.get("pitfall") else []),
                   "", "<details><summary>回答全文</summary>", "", result.answer, "", "</details>", ""]
    (RUNS_DIR / f"{stamp}-answers.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
    review_path = RUNS_DIR / f"{stamp}-answers.md"
    review_path.write_text("\n".join(review), encoding="utf-8")
    flagged = sum(bool(r.get("flags") or r.get("error")) for r in results)
    print(f"\n自動檢查有問題 {flagged}/{len(results)}；逐題對照：{review_path}")


if __name__ == "__main__":
    main()
