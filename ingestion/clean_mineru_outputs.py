"""Re-apply mineru_cleanup.normalize_body to Markdown already written by ingest_mineru.py."""

import argparse
from pathlib import Path
import re
import sys

from ingestion.ingest_mineru import MARKDOWN_DIRECTORY, OUTPUT_MARKER, clean_markdown, natural_key
from ingestion.mineru_cleanup import PLACEHOLDER

WRAPPER = re.compile(r"\\left\|\s*\\begin\{array\}")
FOOTER = "Copyright 2021 Cengage Learning"


def change_summary(before: str, after: str) -> str:
    parts = [f"{len(before):,} → {len(after):,} bytes"]
    for label, count in (("圖片/圖形佔位", lambda t: t.count(PLACEHOLDER)),
                         ("版權頁尾", lambda t: t.count(FOOTER)),
                         ("|array| 外框", lambda t: len(WRAPPER.findall(t)))):
        if count(before) != count(after):
            parts.append(f"{label} {count(before)} → {count(after)}")
    return "，".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 data/markdown/ 內已轉換的 Markdown")
    parser.add_argument("--dry-run", action="store_true", help="只列出會修改的檔案，不寫入")
    args = parser.parse_args()
    paths = sorted(MARKDOWN_DIRECTORY.glob("*.md"), key=lambda p: natural_key(p.name))
    changed = 0
    for path in paths:
        before = path.read_text(encoding="utf-8")
        if not before.startswith(OUTPUT_MARKER):
            print(f"略過（不是 MinerU 輸出）：{path.name}", file=sys.stderr)
            continue
        after = clean_markdown(before.removeprefix(OUTPUT_MARKER))
        if after == before:
            continue
        changed += 1
        print(f"{path.name}：{change_summary(before, after)}")
        if not args.dry_run:
            path.write_text(after, encoding="utf-8")
    action = "會修改" if args.dry_run else "已修改"
    print(f"{action} {changed} / {len(paths)} 個檔案")


if __name__ == "__main__":
    main()
