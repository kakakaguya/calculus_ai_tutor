"""Chroma settings shared by the index builder and the tutor, so both always agree."""

import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DB_DIR = PROJECT_ROOT / "database" / "chroma_db"
COLLECTION_NAME = "calculus_sections"
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
# nomic-embed-text was trained with these task prefixes; leaving them out lowers recall.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class PrefixedEmbeddings(Embeddings):
    """Add the document/query task prefixes the embedding model expects."""

    def __init__(self, base: Embeddings, document_prefix: str, query_prefix: str) -> None:
        self._base = base
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._base.embed_documents([self._document_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._base.embed_query(self._query_prefix + text)


def make_embeddings() -> Embeddings:
    base = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)
    if EMBED_MODEL.startswith("nomic-embed-text"):
        return PrefixedEmbeddings(base, DOCUMENT_PREFIX, QUERY_PREFIX)
    return base


def open_vector_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=make_embeddings(),
        persist_directory=str(CHROMA_DB_DIR),
    )
