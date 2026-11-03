#!/usr/bin/env python3
"""Check chunks.jsonl before it is embedded; every finding names the chunks involved.

    python validate_chunks.py work/chunks.jsonl --profile work/book_profile.json \
        [--expect-sections 1.1,1.2,...] [--json work/validation.json]

FAIL means the file is not usable as is (broken records, empty text, duplicate ids);
WARN means likely chunking or OCR mistakes worth a look. Exit code 1 on any FAIL.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import load_profile  # noqa: E402

REQUIRED = ("index", "id", "kind", "section", "text", "source_files")
CHARS_PER_TOKEN = 3.35  # nomic-embed-text on LaTeX-heavy English text
EMBED_LIMIT_TOKENS = 2048
MIN_SOLUTION_RATIO = 0.8
TINY_CHARS = 80


def section_tuple(section: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", section or ""))


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[int(fraction * (len(ordered) - 1))] if ordered else 0


def check(records: list[dict], profile: dict, expected: list[str]) -> list[dict]:
    findings: list[dict] = []

    def add(level: str, name: str, message: str, ids: list[str] = ()) -> None:
        findings.append({"level": level, "check": name, "message": message, "ids": list(ids)[:20]})

    broken = [str(r.get("id", f"#{n}")) for n, r in enumerate(records, 1)
              if any(key not in r for key in REQUIRED)]
    if broken:
        add("FAIL", "欄位完整", f"{len(broken)} 筆缺少必要欄位 {REQUIRED}", broken)
        return findings
    duplicates = [i for i, count in Counter(r["id"] for r in records).items() if count > 1]
    if duplicates:
        add("FAIL", "id 唯一", f"{len(duplicates)} 個重複 id", duplicates)
    empty = [r["id"] for r in records if not r["text"].strip()]
    if empty:
        add("FAIL", "內容非空", f"{len(empty)} 塊沒有文字", empty)

    examples = [r for r in records if r["kind"] == "example"]
    solution = profile["compiled"]["solution_marker"]
    if examples and solution:
        missing = [r["id"] for r in examples if not solution.search(r["text"])]
        ratio = 1 - len(missing) / len(examples)
        level = "WARN" if ratio < MIN_SOLUTION_RATIO else "PASS"
        add(level, "例題含解答", f"{ratio:.0%} 的例題有解答標記（{len(missing)} 題沒有）", missing)

    broken_math = [r["id"] for r in records if r["text"].count("$$") % 2]
    add("WARN" if broken_math else "PASS", "公式完整",
        f"{len(broken_math)} 塊的 $$ 不成對（公式可能被切斷）", broken_math)

    # Only within one part (body -> appendix "A" is not a step back), and starred sections
    # ("6.2*", an alternative track printed after 6.4) may legitimately go back.
    backwards = [b["id"] for a, b in zip(records, records[1:])
                 if a.get("part") == b.get("part") and not str(b["section"]).endswith("*")
                 and section_tuple(b["section"]) < section_tuple(a["section"])]
    add("WARN" if backwards else "PASS", "章節順序", f"{len(backwards)} 處章節編號倒退", backwards)

    if expected:
        found = {r["section"] for r in records}
        missing_sections = [s for s in expected if s not in found]
        add("WARN" if missing_sections else "PASS", "章節齊全",
            f"缺少 {len(missing_sections)} / {len(expected)} 個預期章節", missing_sections)

    tiny = [r["id"] for r in records if len(r["text"]) < TINY_CHARS]
    add("WARN" if len(tiny) > len(records) * 0.05 else "PASS", "過小的塊",
        f"{len(tiny)} 塊少於 {TINY_CHARS} 字元", tiny)
    over = [r["id"] for r in records
            if math.ceil(len(r["text"]) / CHARS_PER_TOKEN) > EMBED_LIMIT_TOKENS]
    add("PASS", "超過 embedding 上限",
        f"{len(over)} 塊估計超過 {EMBED_LIMIT_TOKENS} token（build_segments 會再切，僅供參考）", over)
    text_counts = Counter(r["text"] for r in records)
    duplicated_text = [r["id"] for r in records if text_counts[r["text"]] > 1]
    if duplicated_text:
        add("WARN", "重複內容", f"{len(duplicated_text)} 段文字重複出現", duplicated_text)
    return findings


def summary(records: list[dict]) -> list[str]:
    """Size overview; tolerant of broken records, which check() reports as FAIL."""
    lines = []
    for kind, count in Counter(r.get("kind", "?") for r in records).items():
        sizes = [len(r.get("text", "")) for r in records if r.get("kind", "?") == kind]
        lines.append(f"  {kind:13s} {count:5d} 塊  字元數 中位數 {percentile(sizes, .5)}"
                     f"  p90 {percentile(sizes, .9)}  最大 {max(sizes)}")
    lines.append(f"  章節數 {len({r.get('section') for r in records})}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="檢查 chunks.jsonl 的切塊品質")
    parser.add_argument("chunks", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--expect-sections", default="", help="逗號分隔的章節編號，例如目錄中的全部章節")
    parser.add_argument("--json", type=Path, help="同時輸出 JSON 報告")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    records = []
    for number, line in enumerate(args.chunks.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                sys.exit(f"FAIL 第 {number} 行不是合法 JSON：{error.msg}")
    expected = [s.strip() for s in args.expect_sections.split(",") if s.strip()]
    findings = check(records, profile, expected)
    print(f"{args.chunks}：{len(records)} 塊")
    print("\n".join(summary(records)))
    for finding in findings:
        ids = f"  例：{', '.join(finding['ids'][:5])}" if finding["ids"] and finding["level"] != "PASS" else ""
        print(f"[{finding['level']}] {finding['check']}：{finding['message']}{ids}")
    if args.json:
        args.json.write_text(json.dumps({"chunks": len(records), "findings": findings},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if any(finding["level"] == "FAIL" for finding in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
