Calculus AI Tutor

一個使用 LangChain + Ollama + Qwen3 8B 建立的本地端微積分 AI 助教。

本專案目前提供基本的自然語言問答功能，使用者可以輸入微積分相關問題，由本地部署的 Qwen3 8B 模型進行回答，並透過串流（Streaming）方式逐步顯示模型輸出的內容。

本專案後續預計整合 RAG、向量資料庫、SymPy 數學計算、問題分類與 Router、數學圖片辨識以及前端介面，逐步發展成完整的學習課程助教系統。

📌 專案特色
使用本地端 LLM 進行問答
使用 Qwen3 8B 作為語言模型
使用 Ollama 管理與執行本地模型
使用 LangChain 建立模型呼叫流程
支援 Streaming 串流輸出
使用繁體中文回答
目前以微積分教學與問題解答為主要用途
不需要將問題直接傳送到 OpenAI 等雲端 API
後續可擴充 RAG、數學計算與圖片辨識等功能
🛠️ 使用技術
技術	用途
Python	主要開發語言
LangChain	建立 LLM 應用程式流程
LangChain-Ollama	連接 LangChain 與 Ollama
Ollama	本地端 LLM 執行環境
Qwen3 8B	AI 語言模型
Git / GitHub	程式版本控制與專案管理
📋 環境需求

開始使用本專案前，請確認電腦已安裝以下環境。

Python

需要：

Python 3.10+

建議使用 Python 3.11 或 3.12。

確認 Python 版本：

python --version

如果你的系統使用 python3：

python3 --version
Ollama

本專案使用 Ollama 在本機執行 Qwen3 8B。

請先安裝 Ollama。

安裝完成後，可以使用以下指令確認：

ollama --version

如果可以正常顯示版本號，代表 Ollama 已經安裝完成。

🤖 安裝 Qwen3 8B

安裝 Ollama 後，需要下載本專案使用的模型：

ollama pull qwen3:8b

下載完成後，可以使用：

ollama list

確認模型是否存在。

應該可以看到類似：

NAME       ID       SIZE
qwen3:8b   ...      ...

也可以直接測試：

ollama run qwen3:8b

如果可以輸入問題並得到回答，代表模型已經可以正常運作。

離開模型：

/bye
📥 安裝專案
1. Clone Repository

首先將 GitHub 專案下載到本機：

git clone https://github.com/kakakaguya/calculus_ai_tutor.git

進入專案資料夾：

cd calculus_ai_tutor
🐍 建立 Python 虛擬環境

建議使用虛擬環境，以避免不同 Python 專案之間的套件互相影響。

Linux / WSL

建立虛擬環境：

python3 -m venv .venv

啟用：

source .venv/bin/activate

啟用後，終端機通常會看到：

(.venv) user@computer:~/calculus_ai_tutor$
Windows

建立虛擬環境：

python -m venv .venv

啟用：

.venv\Scripts\activate
📦 安裝 Python 套件

啟用虛擬環境後：

pip install -r requirements.txt

如果尚未建立 requirements.txt，目前至少需要：

langchain
langchain-core
langchain-ollama

也可以直接安裝：

pip install langchain langchain-core langchain-ollama
