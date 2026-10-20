"""
讀取已切割好的 chunks.jsonl，透過 Ollama 建立向量並存入 ChromaDB。
執行方式（在專案根目錄）：python -m rag.ingestion.build_vector_db
"""

import json
from pathlib import Path
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

# 設定路徑
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_FILE = PROJECT_ROOT / "data" / "chunks.jsonl"
CHROMA_DB_DIR = PROJECT_ROOT / "database" / "chroma_db"


def load_documents() -> list[Document]:
    """讀取 chunks.jsonl，每一行轉成一個 Document，保留章節與類型等 metadata。"""
    docs = []
    if not CHUNKS_FILE.exists():
        print(f" 找不到檔案：{CHUNKS_FILE}")
        print(" 請先執行 chunk_markdown.py 產生 chunks.jsonl")
        return docs

    with CHUNKS_FILE.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                print(f" 第 {line_number} 行 JSON 解析失敗，已跳過：{error}")
                continue

            text = record.get("text", "").strip()
            if not text:
                continue

            # metadata 保留切割時標記好的資訊，之後可用來：
            # 1. 檢索時依 kind（例如只找 example）做篩選
            # 2. 回答時標示「這段資料來自第 X 節」
            # 3. 寫入資料庫 qa_records.material_id 時，用來對應教材來源
            doc = Document(
                page_content=text,
                metadata={
                    "chunk_id": record.get("id"),
                    "index": record.get("index"),
                    "kind": record.get("kind"),
                    "part": record.get("part"),
                    "section": record.get("section"),
                    "section_title": record.get("section_title"),
                    "source_files": ",".join(record.get("source_files", [])),
                },
            )
            docs.append(doc)

    return docs


def main():
    print("開始載入 chunks.jsonl...")
    documents = load_documents()

    if not documents:
        print("沒有找到任何文件，程式結束。")
        return

    print(f" 共載入 {len(documents)} 個文字區塊。")
    print(" 正在呼叫 Ollama (nomic-embed-text) 計算向量並寫入 ChromaDB，這可能需要幾分鐘...")

    # 指定使用 nomic-embed-text 作為 Embedding 模型
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    # 建立向量資料庫並持久化儲存
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=str(CHROMA_DB_DIR),
    )

    print(f" 向量資料庫建立完成！已儲存至：{CHROMA_DB_DIR}")


if __name__ == "__main__":
    main()