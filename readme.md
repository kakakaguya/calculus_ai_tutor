# Calculus AI Tutor

使用 **LangChain + Ollama + Qwen3** 建立的簡易微積分 AI 助教。

目前可以透過自然語言向 AI 詢問微積分相關問題，並使用串流方式逐步顯示回答。

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

### 3. 下載 Qwen3 8B 模型

使用以下指令下載模型：

```bash
ollama pull qwen3:8b
```

確認模型是否成功下載：

```bash
ollama list
```

應該可以看到：

```text
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

如果專案中已經有 `requirements.txt`：

```bash
pip install -r requirements.txt
```

如果尚未建立 `requirements.txt`，也可以直接安裝：

```bash
pip install langchain langchain-ollama
```

安裝完成後，即可開始執行專案。

## 專案結構

```text
calculus_ai_tutor/
├── main.py
├── requirements.txt
├── README.md
└── .gitignore
```

### `main.py`

主要的 Python 程式，負責：

* 建立 Ollama 模型連線
* 設定 AI 助教的角色
* 接收使用者問題
* 將問題傳送給 Qwen3
* 使用串流方式顯示 AI 回答

### `requirements.txt`

記錄 Python 專案所需要的套件，例如：

```text
langchain
langchain-ollama
```

可以透過以下指令一次安裝：

```bash
pip install -r requirements.txt
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


