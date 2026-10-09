"""簡易網頁問答介面。

啟動：python web_app.py
開啟：http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CALCULUS_TUTOR_DB", BASE_DIR / "database" / "calculus_tutor.db"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
SYSTEM_PROMPT = "你是一位專業的微積分助教，請使用繁體中文簡潔回答。"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    """保留既有資料，補上來源欄位並準備固定訪客對話。"""
    with connect_db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(qa_records)")}
        if "answer_source" not in columns:
            conn.execute(
                "ALTER TABLE qa_records ADD COLUMN answer_source TEXT NOT NULL DEFAULT 'ollama'"
            )

        guest = conn.execute(
            "SELECT user_id FROM users WHERE username = ? ORDER BY user_id LIMIT 1", ("Guest",)
        ).fetchone()
        if guest is None:
            cursor = conn.execute("INSERT INTO users (username) VALUES (?)", ("Guest",))
            user_id = cursor.lastrowid
        else:
            user_id = guest["user_id"]

        conversation = conn.execute(
            "SELECT conversation_id FROM conversations WHERE user_id = ? "
            "ORDER BY conversation_id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if conversation is None:
            conn.execute(
                "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
                (user_id, "訪客問答"),
            )


def guest_conversation_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT c.conversation_id FROM conversations c "
        "JOIN users u ON u.user_id = c.user_id "
        "WHERE u.username = ? ORDER BY c.conversation_id DESC LIMIT 1",
        ("Guest",),
    ).fetchone()
    if row is None:
        raise RuntimeError("Guest 對話尚未初始化")
    return int(row["conversation_id"])


def get_history(limit: int | None = None) -> list[dict]:
    with connect_db() as conn:
        conversation_id = guest_conversation_id(conn)
        sql = (
            "SELECT question, answer, answer_source, created_at FROM qa_records "
            "WHERE conversation_id = ? ORDER BY record_id DESC"
        )
        params: list[object] = [conversation_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = list(conn.execute(sql, params))
    rows.reverse()
    return [dict(row) for row in rows]


def save_record(question: str, answer: str, source: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO qa_records (conversation_id, question, answer, answer_source) "
            "VALUES (?, ?, ?, ?)",
            (guest_conversation_id(conn), question, answer, source),
        )



def friendly_ollama_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"Ollama 回傳 HTTP {error.code}；請確認模型 {OLLAMA_MODEL} 已下載。"
    if isinstance(error, URLError):
        return "無法連線到 Ollama；請確認 Ollama 服務已啟動。"
    return "Ollama 回覆格式異常，請稍後再試。"


def call_ollama(question: str) -> str:
    # 匯入main_rag.py 寫好的 LCEL 檢索鏈
    from tutor.main_rag import rag_chain

    answer = rag_chain.invoke(question)
    
    if not answer:
        raise ValueError("沒有收到 AI 的回覆")
    return answer


def demo_answer(question: str) -> str:
    return f"目前 Ollama 尚未就緒，因此這是一則示範回覆。你剛才問的是：「{question}」"


def answer_question(question: str) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("問題不可空白")
    try:
        # 直接把使用者的問題傳給 call_ollama 處理
        answer = call_ollama(question)
        source, notice = "ollama", None
    except Exception as error:  # 把攔截的範圍擴大，捕捉 LangChain 可能的錯誤
        answer = demo_answer(question)
        source, notice = "demo", friendly_ollama_error(error)
        
    save_record(question, answer, source)
    return {"question": question, "answer": answer, "source": source, "notice": notice}


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>微積分助教</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.6}#chat{min-height:280px;border:1px solid #ccc;padding:1rem;margin-bottom:1rem;white-space:pre-wrap}.user{font-weight:bold;color:#0056b3}.assistant{margin:0 0 1.5rem}.demo{color:#8a5500}form{display:flex;gap:.5rem}input{flex:1;padding:.65rem}button{padding:.65rem 1rem}#status{min-height:1.5rem;color:#666}</style>

<!-- 1. 引入 MathJax 來渲染數學公式 -->
<script>
  MathJax = {
    tex: { inlineMath: [['$', '$'], ['\\(', '\\)']], displayMath: [['$$', '$$'], ['\\[', '\\]']] }
  };
</script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>

<h1>微積分助教</h1><div id="chat" aria-live="polite">載入歷史紀錄中…</div>
<form id="form"><input id="question" required placeholder="輸入你的問題" aria-label="問題"><button>送出</button></form><p id="status"></p>
<script>
const chat=document.querySelector('#chat'), form=document.querySelector('#form'), input=document.querySelector('#question'), status=document.querySelector('#status');
function add(record){
    const q=document.createElement('div');q.className='user';q.textContent='你：'+record.question;
    const a=document.createElement('div');a.className='assistant '+(record.answer_source=== 'demo'||record.source==='demo'?'demo':'');
    a.textContent=(record.answer_source=== 'demo'||record.source==='demo'?'示範回覆：':'Ollama：')+record.answer;
    chat.append(q,a);
    chat.scrollTop=chat.scrollHeight;
    
    // 2. 每次有新訊息加入時，呼叫 MathJax 重新渲染該段落的數學公式
    if(window.MathJax) MathJax.typesetPromise([a]);
}
fetch('/api/history').then(r=>r.json()).then(rows=>{chat.textContent='';rows.forEach(add)}).catch(()=>chat.textContent='歷史紀錄載入失敗。');
form.addEventListener('submit',async e=>{e.preventDefault();const question=input.value.trim();if(!question)return;input.disabled=true;form.querySelector('button').disabled=true;status.textContent='正在送往 Ollama…';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});const data=await r.json();if(!r.ok)throw new Error(data.error||'送出失敗');add(data);input.value='';status.textContent=data.notice||'已收到 Ollama 回覆。'}catch(err){status.textContent=err.message}finally{input.disabled=false;form.querySelector('button').disabled=false;input.focus()}});
</script></html>"""


class AppHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/history":
            self.send_json(200, get_history())
        else:
            self.send_json(404, {"error": "找不到路徑"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self.send_json(404, {"error": "找不到路徑"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_json(200, answer_question(str(payload.get("question", ""))))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        print("[web]", format % args)


if __name__ == "__main__":
    initialize_database()
    print("請開啟 http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler).serve_forever()
