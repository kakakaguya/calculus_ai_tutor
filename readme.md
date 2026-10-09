# Calculus AI Tutor

使用 **LangChain + Ollama + Qwen3** 建立的簡易微積分 AI 助教。

目前可以透過自然語言向 AI 詢問微積分相關問題，並使用串流方式逐步顯示回答。

## 簡易網頁介面

不需要安裝 Flask 或 FastAPI。進入專案資料夾後執行：

```powershell
python web_app.py
```

再以瀏覽器開啟 `http://127.0.0.1:8000`。網頁會把問題傳給本機 Ollama 的

## 使用技術

* Python
* LangChain
* LangChain-Ollama
* Ollama
* Qwen3 8B

## 環境需求

* Python 3.10+
* Ollama
* Qwen3 8B 模型

## 安裝與設定

### 1. 安裝 Python

確認 Python 已安裝：

```bash
python3 --version
```

如果有顯示 Python 版本，例如：

```text
Python 3.12.3
```

即可繼續。

### 2. 安裝 Ollama

確認 Ollama 是否已安裝：

```bash
ollama --version
```

### 3. 下載 Qwen3 8B 與 Embedding 模型

使用以下指令下載模型：

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

確認模型是否成功下載：

```bash
ollama list
```

應該可以看到：

```text
nomic-embed-text
qwen3:8b
```

### 4. 建立 Python 虛擬環境

進入專案資料夾：

```bash
cd calculus_ai_tutor
```

建立虛擬環境：

```bash
python3 -m venv .venv
```

啟用虛擬環境：

**Linux / WSL：**

```bash
source .venv/bin/activate
```

**Windows：**

```powershell
.venv\Scripts\activate
```

啟用成功後，終端機前方通常會出現：

```text
(.venv)
```

### 5. 安裝 Python 套件

安裝專案依賴：

```bash
pip install -r requirement.txt
```

如果尚未建立 `requirement.txt`，也可以直接安裝：

```bash
pip install langchain langchain-ollama
```
### 6. 建立向量資料庫
開始問答前，需要先將微積分教材轉換為向量儲存。請在虛擬環境下執行：

```bash
python -m ingestion.build_vector_db
```
安裝完成後，即可開始執行專案。

## 專案結構

```text
rag/
├── ingestion/                  PDF → Markdown 讀取流程
│   ├── ingest_mineru.py        用 MinerU 轉換 PDF
│   ├── mineru_cleanup.py       修正 MinerU 輸出的固定錯誤
│   └── clean_mineru_outputs.py 對已轉換的檔案重新套用清理規則
├── tutor/
│   └── main_rag.py             助教問答
├── database/
│   ├── create_database.py      建立系統資料庫
│   └── calculus_tutor.db
├── web_app.py                  簡易網頁介面（python web_app.py）
├── test_web_app.py             網頁介面測試
├── tests/                      單元測試
├── data/                       資料（不進 git）
│   ├── raw/                    原始教材
│   ├── pdf_split/              切好的 192 份課本 PDF
│   ├── markdown/               轉換後的 Markdown
│   └── backup/                 清理前的備份
├── requirement.txt
├── README.md
└── .gitignore
```

程式請在專案根目錄用 `python -m` 執行，例如 `python -m ingestion.ingest_mineru`，檔案間的 import 才找得到。

### `tutor/main_rag.py`

助教問答程式，負責：

* 建立 Ollama 模型連線
* 設定 AI 助教的角色
* 接收使用者問題
* 將問題傳送給 Qwen3
* 使用串流方式顯示 AI 回答

### `requirement.txt`

記錄 Python 專案所需要的套件，例如：

```text
langchain
langchain-ollama
```

可以透過以下指令一次安裝：

```bash
pip install -r requirement.txt
```

### `README.md`

專案說明文件，包含安裝方式、使用方法與專案介紹。

### `.gitignore`

告訴 Git 哪些檔案不需要加入版本控制，例如：

```text
.venv/
__pycache__/
*.pyc
.env
```

這可以避免把虛擬環境、Python 快取或敏感設定檔上傳到 GitHub。

## PDF 轉 Markdown（MinerU）

[ingestion/ingest_mineru.py](ingestion/ingest_mineru.py) 用 MinerU 的本地模型讀取課本 PDF，正文、行內式和獨立公式都會輸出成 Markdown + LaTeX（曾試過 Docling、EasyOCR + Pix2Text，公式與正文的正確率都明顯較差）。MinerU 裝在獨立的虛擬環境 `.venv-mineru`，避免和專案其他套件的依賴衝突；程式從專案原本的 `.venv` 執行，透過子程序呼叫 MinerU。

安裝（只需一次，模型約 2 GB，存在 `~/.mineru/models`）：

```bash
python3 -m venv .venv-mineru
.venv-mineru/bin/pip install "mineru>=4.0,<5"
.venv-mineru/bin/mineru-kit models download --tier standard
.venv-mineru/bin/mineru-kit models verify --tier standard
```

執行：

```bash
python -m ingestion.ingest_mineru               # 轉換 data/pdf_split/ 全部 PDF 到 data/markdown/
python -m ingestion.ingest_mineru --limit 2     # 只試跑前 2 份
python -m ingestion.ingest_mineru --resume      # 中斷後接續：略過已轉換的 PDF
python -m ingestion.clean_mineru_outputs --dry-run  # 只列出清理規則會修改的檔案
python -m ingestion.clean_mineru_outputs        # 對已轉換的 Markdown 重新套用清理規則
python -m pytest tests                # 執行單元測試
```

- 只在本機解析，程式不會傳 `--remote`，PDF 不會上傳。
- 使用 `standard` 等級（ONNX 版面/OCR 模型 + MinerU2.5-Pro 1.2B VLM 公式模型，llama.cpp 會用到 GPU，約 2 GB 顯存）。
- 強制 OCR（`--ocr-mode ocr`）：這本書的 PDF 文字層數學字型對應錯誤，用預設的 auto 模式時 δ 會消失、`>` 變 `≥`。強制 OCR 每份 5 頁約 3 分鐘，記憶體峰值約 3.4 GB。
- 後處理（[ingestion/mineru_cleanup.py](ingestion/mineru_cleanup.py)）：嵌入的 base64 圖片（含表格內的 `<img>`）換成 `<!-- image -->`；被誤讀成大片空白表格的圖形換成 `<!-- image -->`；刪除出版社版權頁尾；多行推導外被誤加的 `\left| … \right|` 拆掉（每列都含 `=`、`≈`、`≤` 等關係才拆，真正的行列式保留）；`\varliminf` 改回 `\lim`。
- 清理前的完整輸出備份在 `data/backup/data_markdown_mineru_before_cleanup.tar.gz`（資料夾整理前打包，解壓後的資料夾名稱是舊的 `data_markdown_mineru/`）。
