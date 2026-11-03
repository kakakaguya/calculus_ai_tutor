#!/usr/bin/env python3
"""Embed segments.jsonl with Ollama and store them in a persistent Chroma collection.

    python build_vector_db.py work/segments.jsonl --persist database/chroma_db \
        --collection textbook_sections [--model nomic-embed-text] [--batch-size 64]

The collection is dropped and rebuilt every run, with segment ids as Chroma ids, so the
index always equals segments.jsonl (re-running never leaves duplicate copies).
nomic-embed-text needs task prefixes: documents are embedded as "search_document: ...";
the query side must embed "search_query: ..." or recall drops. Needs chromadb; Ollama
must be running with the model pulled.
"""

import argparse
import json
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_report import write_report  # noqa: E402

METADATA_FIELDS = ("chunk_id", "parent_id", "kind", "section", "section_title", "subheading",
                   "example_label", "position", "segment_count", "header")
NOMIC_DOCUMENT_PREFIX = "search_document: "


def embed(texts: list[str], model: str, base_url: str) -> list[list[float]]:
    body = json.dumps({"model": model, "input": texts, "truncate": True}).encode()
    request = Request(f"{base_url}/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=600) as response:
        return json.load(response)["embeddings"]


def metadata(segment: dict) -> dict:
    """Chroma accepts only non-empty scalar values."""
    return {key: segment[key] for key in METADATA_FIELDS
            if isinstance(segment.get(key), (str, int, float, bool)) and segment[key] != ""}


def main() -> None:
    parser = argparse.ArgumentParser(description="把 segments.jsonl 轉成向量寫入 ChromaDB")
    parser.add_argument("segments", type=Path)
    parser.add_argument("--persist", type=Path, required=True, help="Chroma 資料夾")
    parser.add_argument("--collection", default="textbook_sections")
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--json", type=Path, help="同時把寫入結果寫成 JSON")
    args = parser.parse_args()
    import chromadb

    segments = [json.loads(line) for line in args.segments.read_text(encoding="utf-8").splitlines() if line]
    if not segments:
        parser.error(f"{args.segments} 沒有片段")
    prefix = NOMIC_DOCUMENT_PREFIX if args.model.startswith("nomic-embed-text") else ""
    client = chromadb.PersistentClient(path=str(args.persist))
    if args.collection in [c.name for c in client.list_collections()]:
        client.delete_collection(args.collection)
    collection = client.create_collection(args.collection, metadata={"embed_model": args.model,
                                                                      "query_prefix": "search_query: " if prefix else ""})
    for start in range(0, len(segments), args.batch_size):
        batch = segments[start:start + args.batch_size]
        try:
            vectors = embed([prefix + s["embed_text"] for s in batch], args.model, args.base_url)
        except URLError as error:
            sys.exit(f"無法連線 Ollama（{args.base_url}）：{error}；請先啟動 ollama serve 並 pull {args.model}")
        collection.add(ids=[s["id"] for s in batch], embeddings=vectors,
                       documents=[s["embed_text"] for s in batch], metadatas=[metadata(s) for s in batch])
        print(f"已寫入 {start + len(batch)} / {len(segments)}", flush=True)
    print(f"完成：{args.persist} collection={args.collection}（查詢時記得加 search_query: 前綴）"
          if prefix else f"完成：{args.persist} collection={args.collection}")
    write_report(args.json, "vectors", ok=True, segments=len(segments), stored=collection.count(),
                 persist=str(args.persist), collection=args.collection, model=args.model,
                 query_prefix="search_query: " if prefix else "")


if __name__ == "__main__":
    main()
