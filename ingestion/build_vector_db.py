"""data/segments.jsonl → Chroma vectors (database/chroma_db) via Ollama embeddings.

Each run rebuilds the collection from scratch, with segment ids as Chroma ids, so the
index always matches segments.jsonl. Run from the project root:
    python -m ingestion.build_vector_db
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Protocol

from langchain_core.documents import Document

from tutor.vector_store import CHROMA_DB_DIR, COLLECTION_NAME, EMBED_MODEL, open_vector_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEGMENTS = PROJECT_ROOT / "data" / "segments.jsonl"
BATCH_SIZE = 64
REQUIRED_FIELDS = ("id", "chunk_id", "kind", "embed_text")
METADATA_FIELDS = (
    "chunk_id", "parent_id", "kind", "part", "section", "section_title", "subheading",
    "example_label", "position", "segment_count", "header",
)

logger = logging.getLogger(__name__)


class VectorStore(Protocol):
    def reset_collection(self) -> None: ...

    def add_documents(self, documents: list[Document], ids: list[str]) -> object: ...


def load_segments(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請先執行 python -m ingestion.build_segments")
    segments: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            segment = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON：{error.msg}") from error
        missing = [field for field in REQUIRED_FIELDS if field not in segment]
        if missing:
            raise ValueError(f"{path} 第 {line_number} 行缺少欄位：{', '.join(missing)}")
        segments.append(segment)
    return segments


def to_metadata(segment: dict) -> dict:
    """Chroma accepts only non-empty scalar metadata values."""
    return {
        field: segment[field]
        for field in METADATA_FIELDS
        if isinstance(segment.get(field), (str, int, float, bool)) and segment[field] != ""
    }


def to_document(segment: dict) -> Document:
    return Document(page_content=segment["embed_text"], metadata=to_metadata(segment))


def build_index(store: VectorStore, segments: list[dict], batch_size: int = BATCH_SIZE) -> None:
    store.reset_collection()
    for start in range(0, len(segments), batch_size):
        batch = segments[start:start + batch_size]
        store.add_documents([to_document(segment) for segment in batch],
                            ids=[segment["id"] for segment in batch])
        logger.info("已寫入 %s / %s 個片段", start + len(batch), len(segments))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="把 segments.jsonl 轉成向量寫入 ChromaDB")
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size 必須大於 0")

    try:
        segments = load_segments(args.segments)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not segments:
        parser.error(f"{args.segments} 沒有任何片段")

    logger.info("用 %s 計算 %s 個片段的向量，寫入 %s（collection：%s）",
                EMBED_MODEL, len(segments), CHROMA_DB_DIR, COLLECTION_NAME)
    build_index(open_vector_store(), segments, args.batch_size)
    logger.info("向量資料庫建立完成")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
