# Calculus AI Tutor

以 Ollama + Qwen3 建立的微積分 AI 助教，教材來自 Thomas' Calculus 課本（PDF → Markdown → 文字塊）。

## 環境需求

- Python 3.10+
- [Ollama](https://ollama.com)，並下載模型：

  ```bash
  ollama pull qwen3:8b
  ollama pull nomic-embed-text
  ```

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -r requirement.txt
```

## 使用

第一次使用前，先建立向量資料庫（存到 `database/chroma_db/`）：

```bash
python -m ingestion.build_vector_db
```

```bash
python web_app.py                  # 網頁介面，開啟 http://127.0.0.1:8000
python -m tutor.main_rag           # 命令列問答
python -m pytest tests             # 執行測試
```

可用環境變數：

| 變數 | 預設值 |
|------|--------|
| `OLLAMA_MODEL` | `qwen3:8b` |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/chat` |
| `CALCULUS_TUTOR_DB` | `database/calculus_tutor.db` |

## 教材處理（PDF → 文字塊）

PDF 轉換使用 [MinerU](https://github.com/opendatalab/MinerU)，需裝在獨立的虛擬環境（模型約 2 GB，需 GPU）：

```bash
python3 -m venv .venv-mineru
.venv-mineru/bin/pip install "mineru>=4.0,<5"
.venv-mineru/bin/mineru-kit models download --tier standard
```

處理流程（在專案根目錄執行）：

```bash
python -m ingestion.ingest_mineru --resume          # data/pdf_split/*.pdf → data/markdown/
python -m ingestion.clean_mineru_outputs            # 清理 Markdown
.venv-mineru/bin/python -m ingestion.pdf_layout     # 產生小標題與習題對照檔
python -m ingestion.chunk_markdown                  # data/markdown/ → data/chunks.jsonl
```

> **注意：** `data/markdown/` 中有幾份檔案經過手動修正（`merged-15`、`43`、`64`、`88`、`183`、`192`），重新轉換整份 PDF 會覆蓋這些修改。

## 專案結構

```text
rag/
├── web_app.py          網頁介面
├── tutor/              助教問答
├── ingestion/          PDF 轉換、清理、切塊
├── database/           SQLite 資料庫與 ChromaDB 向量資料庫
├── tests/              測試
└── data/               教材資料（不進 git）
    ├── raw/            原始課本 PDF
    ├── pdf_split/      切分後的 PDF
    ├── markdown/       轉換後的 Markdown
    ├── chunks.jsonl    切好的文字塊
    └── backup/         清理前的備份
```
