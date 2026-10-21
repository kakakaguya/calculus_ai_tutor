import json

import pytest

from ingestion.build_vector_db import build_index, load_segments, to_document, to_metadata
from tutor.vector_store import PrefixedEmbeddings


def _segment(number: int, chunk: str = "chunk-000001", **overrides) -> dict:
    segment = {
        "id": f"{chunk}-s{number:02d}",
        "chunk_id": chunk,
        "parent_id": None,
        "kind": "section_text",
        "part": "body",
        "section": "3.4",
        "section_title": "Limits at Infinity",
        "subheading": "Evaluating Limits",
        "example_label": None,
        "position": number,
        "segment_count": 2,
        "header": "3.4 Limits at Infinity | Evaluating Limits",
        "text": f"Body {number}.",
        "embed_text": f"3.4 Limits at Infinity | Evaluating Limits\n\nBody {number}.",
        "estimated_tokens": 20,
    }
    return {**segment, **overrides}


class FakeStore:
    def __init__(self):
        self.reset_calls = 0
        self.batches = []

    def reset_collection(self):
        self.reset_calls += 1

    def add_documents(self, documents, ids):
        self.batches.append((documents, ids))


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[float(len(text))] for text in texts]

    def embed_query(self, text):
        return [float(len(text))]


def test_load_segments_reports_missing_fields(tmp_path):
    path = tmp_path / "segments.jsonl"
    path.write_text(json.dumps({"id": "x"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="第 1 行缺少欄位"):
        load_segments(path)


def test_load_segments_reports_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_segments"):
        load_segments(tmp_path / "missing.jsonl")


def test_metadata_keeps_scalars_and_drops_empty_values():
    metadata = to_metadata(_segment(1))

    assert metadata["chunk_id"] == "chunk-000001"
    assert metadata["subheading"] == "Evaluating Limits"
    assert metadata["position"] == 1
    assert "parent_id" not in metadata
    assert "example_label" not in metadata
    assert "embed_text" not in metadata
    assert all(isinstance(value, (str, int, float, bool)) for value in metadata.values())


def test_document_embeds_the_headed_text():
    document = to_document(_segment(2))

    assert document.page_content.startswith("3.4 Limits at Infinity | Evaluating Limits\n\n")
    assert document.page_content.endswith("Body 2.")


def test_build_index_resets_then_adds_in_batches_with_stable_ids():
    store = FakeStore()
    segments = [_segment(number) for number in range(1, 6)]

    build_index(store, segments, batch_size=2)

    assert store.reset_calls == 1
    assert [ids for _, ids in store.batches] == [
        ["chunk-000001-s01", "chunk-000001-s02"],
        ["chunk-000001-s03", "chunk-000001-s04"],
        ["chunk-000001-s05"],
    ]


def test_prefixed_embeddings_mark_documents_and_queries():
    embeddings = PrefixedEmbeddings(FakeEmbeddings(), "doc: ", "query: ")

    assert embeddings.embed_documents(["ab"]) == [[float(len("doc: ab"))]]
    assert embeddings.embed_query("ab") == [float(len("query: ab"))]
