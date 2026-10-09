"""
讀取已 Chunking 的 Markdown 檔案，透過 Ollama 建立向量並存入 ChromaDB。
執行方式（在專案根目錄）：python -m rag.ingestion.build_vector_db
"""

from pathlib import Path
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

# 設定路徑
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKED_DIR = PROJECT_ROOT / "data" / "markdown"
CHROMA_DB_DIR = PROJECT_ROOT / "database" / "chroma_db"

def load_documents() -> list[Document]:
    docs = []
    if not CHUNKED_DIR.exists():
        print(f" 找不到目錄：{CHUNKED_DIR}")
        return docs

    # 讀取所有 .md 檔案
    # 假設每一個 chunk 已經是一個獨立的 .md 檔，或者長度已經適合檢索
    for filepath in CHUNKED_DIR.rglob("*.md"):
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            continue
            
        # 建立 Document 並放入 metadata，這在之後回答標示「資料來源」時用
        doc = Document(
            page_content=content,
            metadata={"source": filepath.name}
        )
        docs.append(doc)
    
    return docs

def main():
    print("開始載入 Markdown 檔案...")
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
        persist_directory=str(CHROMA_DB_DIR)
    )

    print(f"🎉 向量資料庫建立完成！已儲存至：{CHROMA_DB_DIR}")

if __name__ == "__main__":
    main()