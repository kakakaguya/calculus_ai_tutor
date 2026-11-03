#!/usr/bin/env python3
"""Fix systematic OCR mistakes in MinerU Markdown, in place, idempotently.

    python clean_markdown.py work/markdown --profile work/book_profile.json --dry-run
    python clean_markdown.py work/markdown --profile work/book_profile.json --backup work/backup

Generic rules (every book): base64 images -> placeholder, a gridded figure read as a big
empty table -> placeholder, a derivation wrapped in spurious |...| bars -> unwrapped,
runs of blank lines collapsed. Book rules come from the profile: whole lines to delete
(publisher footers) and regex replacements (a misread macro). Each rule reports how often
it fired per file, so a rule that hits correct text shows up in the dry run.
Files listed in protected_files (fixed by hand) are never rewritten.
"""

import argparse
from pathlib import Path
import re
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import IMAGE_PLACEHOLDER, OUTPUT_MARKER, load_profile, natural_key  # noqa: E402

MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
HTML_IMAGE = re.compile(r"<img\b[^>]*>")
MARKDOWN_TABLE = re.compile(r"(?:^\|.*\|[ \t]*$\n?)+", re.M)
SEPARATOR_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
HTML_TABLE = re.compile(r"<table>.*?</table>", re.S)
HTML_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
MIN_GRAPH_CELLS = 20
MIN_EMPTY_RATIO = 0.9
# A real determinant has no relation in its rows, so only all-relation arrays are unwrapped.
WRAPPED_ARRAY = re.compile(
    r"\\left\|\s*(\\begin\{array\}\{[^}]*\}((?:(?!\\begin\{array\}).)*?)\\end\{array\})"
    r"\s*\\right[|.]", re.S)
RELATION = re.compile(r"=|<|>|\\(?:approx|leq?|geq?|leqslant|geqslant|neq?|iff|Rightarrow|equiv)"
                      r"(?![A-Za-z])")
BLANK_RUN = re.compile(r"\n{3,}")


def _is_misread_graph(cells: list[str]) -> bool:
    empty = sum(1 for cell in cells if not cell.strip())
    return len(cells) >= MIN_GRAPH_CELLS and empty / len(cells) >= MIN_EMPTY_RATIO


def _markdown_table(match: re.Match) -> str:
    rows = [row for row in match.group(0).splitlines() if not SEPARATOR_ROW.match(row)]
    cells = [cell for row in rows for cell in row.strip().strip("|").split("|")]
    if not _is_misread_graph(cells):
        return match.group(0)
    return IMAGE_PLACEHOLDER + ("\n" if match.group(0).endswith("\n") else "")


def _html_table(match: re.Match) -> str:
    return IMAGE_PLACEHOLDER if _is_misread_graph(HTML_CELL.findall(match.group(0))) else match.group(0)


def _unwrap(match: re.Match) -> str:
    rows = [row for row in re.split(r"\\\\", match.group(2)) if row.strip()]
    return match.group(1) if rows and all(RELATION.search(row) for row in rows) else match.group(0)


def clean(body: str, profile: dict) -> tuple[str, dict[str, int]]:
    """Return the cleaned body and how many times each rule changed something."""
    counts: dict[str, int] = {}

    def apply(name: str, pattern: re.Pattern, replacement, text: str) -> str:
        hits = 0

        def replace(match: re.Match) -> str:
            nonlocal hits
            new = replacement(match) if callable(replacement) else match.expand(replacement)
            hits += new != match.group(0)  # a real table left alone is not a hit
            return new

        result = pattern.sub(replace, text)
        if hits:
            counts[name] = counts.get(name, 0) + hits
        return result

    text = apply("圖片", MARKDOWN_IMAGE, IMAGE_PLACEHOLDER, body)
    text = apply("圖片", HTML_IMAGE, IMAGE_PLACEHOLDER, text)
    for pattern in profile["compiled"]["delete_lines"]:
        line_pattern = re.compile(rf"^.*(?:{pattern.pattern}).*$\n?", pattern.flags)
        text = apply(f"刪行 {pattern.pattern[:30]}", line_pattern, "", text)
    text = apply("空表格→圖", MARKDOWN_TABLE, _markdown_table, text)
    text = apply("空表格→圖", HTML_TABLE, _html_table, text)
    text = apply("|array| 外框", WRAPPED_ARRAY, _unwrap, text)
    for pattern, replacement in profile["compiled"]["replacements"]:
        text = apply(f"取代 {pattern.pattern[:30]}", pattern, replacement, text)
    return BLANK_RUN.sub("\n\n", text).strip(), counts


def backup_once(paths: list[Path], backup_dir: Path) -> Path | None:
    archive = backup_dir / "markdown_before_cleanup.tar.gz"
    if archive.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        for path in paths:
            tar.add(path, arcname=path.name)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 MinerU Markdown 的系統性錯誤")
    parser.add_argument("markdown_dir", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="只列出會改的檔案與規則次數")
    parser.add_argument("--backup", type=Path, help="第一次寫入前把原檔打包備份到這裡")
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    paths = sorted(args.markdown_dir.glob("*.md"), key=lambda path: natural_key(path.name))
    if not paths:
        parser.error(f"找不到 Markdown：{args.markdown_dir}")
    if not args.dry_run:
        if args.backup is None:
            parser.error("正式寫入需要 --backup，清理規則出錯時才能還原")
        archive = backup_once(paths, args.backup)
        print(f"已備份到 {archive}" if archive else "備份已存在，略過備份")
    protected = set(profile["protected_files"])
    totals: dict[str, int] = {}
    changed = 0
    for path in paths:
        before = path.read_text(encoding="utf-8")
        if not before.startswith(OUTPUT_MARKER):
            print(f"略過（不是 MinerU 輸出）：{path.name}")
            continue
        body, counts = clean(before.removeprefix(OUTPUT_MARKER), profile)
        after = f"{OUTPUT_MARKER}\n\n{body}\n"
        if after == before:
            continue
        if path.name in protected:
            print(f"保護中（手動修正過，不改）：{path.name}  會觸發 {counts}")
            continue
        changed += 1
        for name, count in counts.items():
            totals[name] = totals.get(name, 0) + count
        print(f"{path.name}：{len(before):,} → {len(after):,} bytes  {counts}")
        if not args.dry_run:
            path.write_text(after, encoding="utf-8")
    verb = "會修改" if args.dry_run else "已修改"
    print(f"{verb} {changed} / {len(paths)} 個檔案；規則總次數：{totals}")


if __name__ == "__main__":
    main()
