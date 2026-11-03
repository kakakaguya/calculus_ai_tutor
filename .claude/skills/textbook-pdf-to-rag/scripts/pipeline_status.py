#!/usr/bin/env python3
"""Report which stage a work folder has reached and which outputs are out of date.

    python pipeline_status.py work [--markdown work/markdown] [--chroma database/chroma_db] \
        [--json work/reports/status.json]

Read-only: it looks at the files the stages leave behind and changes nothing. For each
stage it says 完成 / 部分 / 未做 / 過期 / 執行中 / 不需要, with the numbers behind that,
and names the next stage to run. "過期" means an input is newer than the output (for
example Markdown edited after chunking), so the output no longer reflects its inputs.
Cleanup is checked by dry-running the current rules: files they would still change mean
cleanup is not finished, even when a backup exists. Paths default to the layout in
SKILL.md; pass the options when a project keeps them elsewhere.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import OUTPUT_MARKER, load_profile, natural_key  # noqa: E402
from clean_markdown import clean  # noqa: E402
from run_mineru import LOCK_NAME, lock_owner  # noqa: E402
from stage_report import write_report  # noqa: E402
from validate_chunks import check  # noqa: E402

TODO_STATUSES = ("執行中", "未做", "部分", "過期")
REFERENCES = {"split": "references/00-split.md", "ocr": "references/01-ocr-mineru.md",
              "clean": "references/02-cleanup.md", "layout": "references/03-layout-hints.md",
              "chunk": "references/04-chunking.md", "segments": "references/05-segments-and-vectors.md",
              "vectors": "references/05-segments-and-vectors.md"}
SHOW = 5  # names listed per issue


def stage(key: str, name: str, status: str, detail: str, issues: list[str] | None = None) -> dict:
    return {"key": key, "stage": name, "status": status, "detail": detail, "issues": issues or []}


def files(folder: Path, pattern: str) -> list[Path]:
    return sorted(folder.glob(pattern), key=lambda path: natural_key(path.name)) if folder.is_dir() else []


def newer_inputs(output: Path, inputs: list[Path]) -> list[str]:
    """Names of inputs modified after output was written."""
    written = output.stat().st_mtime
    return [path.name for path in inputs if path.exists() and path.stat().st_mtime > written]


def stale_issue(names: list[str]) -> str:
    more = f" 等 {len(names)} 個" if len(names) > SHOW else ""
    return (f"這些輸入比輸出新：{'、'.join(names[:SHOW])}{more}"
            "（依修改時間判斷；只是複製或沒改到相關內容時可忽略）")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_stage(pdf_dir: Path, markdown: list[Path]) -> dict:
    pdfs = files(pdf_dir, "*.pdf")
    if not pdfs:
        if markdown:
            return stage("split", "0 切分", "不需要", "沒有切好的 PDF，但已有 Markdown（從 OCR 之後開始）")
        return stage("split", "0 切分", "未做", f"{pdf_dir} 沒有 PDF")
    manifest = pdf_dir / "split_manifest.json"
    if not manifest.exists():
        return stage("split", "0 切分", "完成", f"{len(pdfs)} 份 PDF",
                     ["沒有 split_manifest.json：切塊無法對回原書頁碼（使用者自己切的可忽略）"])
    listed = {part["file"] for part in json.loads(manifest.read_text(encoding="utf-8"))["parts"]}
    missing = sorted(listed - {pdf.name for pdf in pdfs}, key=natural_key)
    issues = [f"manifest 列了但檔案不見：{'、'.join(missing[:SHOW])}"] if missing else []
    return stage("split", "0 切分", "完成", f"{len(pdfs)} 份 PDF，有頁碼對照", issues)


def ocr_stage(pdf_dir: Path, markdown_dir: Path, markdown: list[Path]) -> dict:
    pdfs = files(pdf_dir, "*.pdf")
    owner = lock_owner(markdown_dir) if markdown_dir.is_dir() else None
    issues = []
    leftovers = files(markdown_dir, "*.part")
    if leftovers and owner is None:
        issues.append(f"有中斷留下的暫存檔（可刪）：{'、'.join(p.name for p in leftovers[:SHOW])}")
    if not pdfs:
        status = "完成" if markdown else "未做"
        return stage("ocr", "1 OCR", status, f"{len(markdown)} 份 Markdown（沒有 PDF 可對照）", issues)
    done = {path.stem for path in markdown}
    missing = [pdf.name for pdf in pdfs if pdf.stem not in done]
    detail = f"{len(pdfs) - len(missing)} / {len(pdfs)} 份已轉成 Markdown"
    if missing:
        issues.insert(0, f"還沒轉：{'、'.join(missing[:SHOW])}" + (" …" if len(missing) > SHOW else ""))
    if owner is not None:
        return stage("ocr", "1 OCR", "執行中", f"{detail}；run_mineru.py（PID {owner}）正在執行", issues)
    status = "完成" if not missing else ("未做" if len(missing) == len(pdfs) else "部分")
    return stage("ocr", "1 OCR", status, detail, issues)


def clean_stage(markdown: list[Path], profile: dict, backup_dir: Path) -> dict:
    if not markdown:
        return stage("clean", "2 清理", "未做", "還沒有 Markdown")
    protected = set(profile["protected_files"])
    pending, protected_hits = [], []
    for path in markdown:
        text = path.read_text(encoding="utf-8")
        if not text.startswith(OUTPUT_MARKER):
            continue
        body, _ = clean(text.removeprefix(OUTPUT_MARKER), profile)
        if f"{OUTPUT_MARKER}\n\n{body}\n" != text:
            (protected_hits if path.name in protected else pending).append(path.name)
    issues = [f"受保護、規則仍會改（需人工決定）：{'、'.join(protected_hits[:SHOW])}"] if protected_hits else []
    backed_up = (backup_dir / "markdown_before_cleanup.tar.gz").exists()
    if not pending:
        detail = "目前規則不會再改任何檔案" + ("，已有備份" if backed_up else "（沒有需要清理的內容）")
        return stage("clean", "2 清理", "完成", detail, issues)
    detail = f"目前規則還會改 {len(pending)} / {len(markdown)} 個檔案"
    if backed_up:
        return stage("clean", "2 清理", "部分", detail + "（已清理過，設定檔可能改過）", issues)
    return stage("clean", "2 清理", "未做", detail, issues)


def layout_stage(pdf_dir: Path, profile: dict, profile_path: Path, hints: Path) -> dict:
    if not profile["layout_markers"]:
        return stage("layout", "3 字型提示", "不需要", "設定檔沒有 layout_markers")
    if not files(pdf_dir, "*.pdf"):
        return stage("layout", "3 字型提示", "不需要", "沒有 PDF，無法讀字型")
    if not hints.exists():
        return stage("layout", "3 字型提示", "未做", f"還沒有 {hints.name}")
    found = json.loads(hints.read_text(encoding="utf-8"))
    totals: dict[str, int] = {}
    for per_file in found.values():
        for name, texts in per_file.items():
            totals[name] = totals.get(name, 0) + len(texts)
    newer = newer_inputs(hints, [profile_path])
    if newer:
        return stage("layout", "3 字型提示", "過期", f"{totals}",
                     ["設定檔在擷取之後改過；若改的是 layout_markers 要重跑"])
    return stage("layout", "3 字型提示", "完成", f"{len(found)} 份 PDF：{totals}")


def chunk_stage(chunks: Path, markdown: list[Path], profile: dict, extra_inputs: list[Path]) -> dict:
    if not chunks.exists():
        return stage("chunk", "4 切塊", "未做", f"還沒有 {chunks.name}")
    records = read_jsonl(chunks)
    kinds: dict[str, int] = {}
    for record in records:
        kinds[record.get("kind", "?")] = kinds.get(record.get("kind", "?"), 0) + 1
    findings = check(records, profile, [])
    fails = [f["check"] for f in findings if f["level"] == "FAIL"]
    warns = sum(f["level"] == "WARN" for f in findings)
    detail = f"{len(records)} 塊 {kinds}；validate：FAIL {len(fails)}、WARN {warns}"
    newer = newer_inputs(chunks, markdown + extra_inputs)
    if newer:
        return stage("chunk", "4 切塊", "過期", detail, [stale_issue(newer)])
    if fails:
        return stage("chunk", "4 切塊", "部分", detail, [f"FAIL：{'、'.join(fails)}"])
    issues = [f"有 {warns} 項 WARN，要逐項看過並在報告中解釋"] if warns else []
    return stage("chunk", "4 切塊", "完成", detail, issues)


def segments_stage(chunks: Path, tree: Path, segments: Path) -> dict:
    missing = [path.name for path in (tree, segments) if not path.exists()]
    if missing:
        return stage("segments", "5 片段", "未做", f"還沒有 {'、'.join(missing)}")
    nodes = read_jsonl(tree)
    examples = sum(node.get("kind") == "example" for node in nodes)
    linked = sum(1 for node in nodes if node.get("kind") == "example" and node.get("parent_id"))
    detail = f"{len(read_jsonl(segments))} 片段；例題掛到子主題 {linked} / {examples}"
    newer = [name for output in (tree, segments) for name in newer_inputs(output, [chunks])]
    if newer:
        return stage("segments", "5 片段", "過期", detail, [stale_issue(sorted(set(newer)))])
    issues = [f"{examples - linked} 個例題沒有掛到子主題"] if linked < examples else []
    return stage("segments", "5 片段", "完成", detail, issues)


def vectors_stage(segments: Path, chroma: Path) -> dict:
    store = chroma / "chroma.sqlite3"
    if not store.exists():
        return stage("vectors", "5 向量庫", "未做", f"{chroma} 沒有 Chroma 資料庫")
    if segments.exists() and newer_inputs(store, [segments]):
        return stage("vectors", "5 向量庫", "過期", f"{chroma}", [stale_issue([segments.name])])
    return stage("vectors", "5 向量庫", "完成", f"{chroma}")


def skip_superseded(stages: list[dict]) -> list[dict]:
    """An early stage with nothing on disk is not needed when a later stage already has output
    (intermediate files are often archived once the chunks exist)."""
    produced = [i for i, item in enumerate(stages) if item["status"] not in ("未做", "不需要")]
    last = max(produced, default=-1)
    return [{**item, "status": "不需要", "detail": f"{item['detail']}；後段已有產物，不必重做"}
            if i < last and item["status"] == "未做" else item
            for i, item in enumerate(stages)]


def next_step(stages: list[dict]) -> dict:
    for item in stages:
        if item["status"] in TODO_STATUSES:
            if item["status"] == "執行中":
                advice = "等它跑完；不要再啟動一次（會搶 GPU、互相覆蓋）。可看它的輸出記錄或過幾分鐘再查一次"
            else:
                advice = f"讀 {REFERENCES[item['key']]}，從這一段接著做"
            return {"key": item["key"], "stage": item["stage"], "status": item["status"], "advice": advice}
    return {"key": None, "stage": "全部完成", "status": "完成", "advice": "可以寫收尾報告"}


def inspect_work(work: Path, **paths: Path | None) -> dict:
    """Status of every stage; paths override the default layout (see SKILL.md)."""
    def path(name: str, default: str) -> Path:
        return paths.get(name) or work / default

    pdf_dir, markdown_dir = path("pdf_split", "pdf_split"), path("markdown", "markdown")
    profile_path, hints = path("profile", "book_profile.json"), path("hints", "layout_hints.json")
    chunks, tree, segments = path("chunks", "chunks.jsonl"), path("tree", "chunk_tree.jsonl"), \
        path("segments", "segments.jsonl")
    profile = load_profile(profile_path if profile_path.exists() else None)
    markdown = files(markdown_dir, "*.md")
    stages = skip_superseded([
        split_stage(pdf_dir, markdown),
        ocr_stage(pdf_dir, markdown_dir, markdown),
        clean_stage(markdown, profile, path("backup", "backup")),
        layout_stage(pdf_dir, profile, profile_path, hints),
        chunk_stage(chunks, markdown, profile, [profile_path, hints]),
        segments_stage(chunks, tree, segments),
        vectors_stage(segments, path("chroma", "chroma_db")),
    ])
    notes = [] if profile_path.exists() else [f"還沒有 {profile_path.name}：清理與切塊用預設規則估計"]
    return {"work": str(work), "stages": stages, "next": next_step(stages), "notes": notes}


def print_status(status: dict) -> None:
    print(f"工作目錄：{status['work']}")
    for note in status["notes"]:
        print(f"  註：{note}")
    for item in status["stages"]:
        print(f"{item['stage']:<8} {item['status']:<4} {item['detail']}")
        for issue in item["issues"]:
            print(f"           - {issue}")
    step = status["next"]
    print(f"下一步：{step['stage']}（{step['status']}）— {step['advice']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="檢查工作目錄做到哪一段、哪些產物過期（只讀不改）")
    parser.add_argument("work", type=Path)
    for name, help_text in (("pdf-split", "切好的 PDF 資料夾"), ("markdown", "Markdown 資料夾"),
                            ("profile", "book_profile.json"), ("hints", "layout_hints.json"),
                            ("chunks", "chunks.jsonl"), ("tree", "chunk_tree.jsonl"),
                            ("segments", "segments.jsonl"), ("backup", "清理備份資料夾"),
                            ("chroma", "Chroma 資料夾")):
        parser.add_argument(f"--{name}", type=Path, help=f"{help_text}（預設在工作目錄下）")
    parser.add_argument("--json", type=Path, help="同時寫成 JSON")
    args = parser.parse_args()
    overrides = {key: value for key, value in vars(args).items() if key not in ("work", "json")}
    try:
        status = inspect_work(args.work, **overrides)
    except (OSError, ValueError) as error:
        sys.exit(f"無法檢查：{error}")
    print_status(status)
    write_report(args.json, "status", ok=True, **{k: v for k, v in status.items()})


if __name__ == "__main__":
    main()
