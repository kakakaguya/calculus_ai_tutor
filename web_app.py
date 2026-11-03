"""簡易網頁問答介面（含使用者登入與對話管理）。

啟動：python web_app.py
開啟：http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import inspect
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CALCULUS_TUTOR_DB", BASE_DIR / "database" / "calculus_tutor.db"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    with connect_db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(qa_records)")}
        if "answer_source" not in columns:
            conn.execute("ALTER TABLE qa_records ADD COLUMN answer_source TEXT NOT NULL DEFAULT 'ollama'")
        if "sources" not in columns:
            conn.execute("ALTER TABLE qa_records ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")
        if "passages" not in columns:
            # 回答當時送給模型的教材原文。重新切塊後 chunk id 會改變，所以存原文而不是 id
            conn.execute("ALTER TABLE qa_records ADD COLUMN passages TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_profiles ("
            "user_id INTEGER PRIMARY KEY, level TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', "
            "strengths TEXT NOT NULL DEFAULT '[]', weaknesses TEXT NOT NULL DEFAULT '[]', "
            "recommendations TEXT NOT NULL DEFAULT '[]', analyzed_count INTEGER NOT NULL DEFAULT 0, "
            "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )


# --- 資料庫操作：使用者與對話 ---

def login_or_register(username: str) -> dict:
    with connect_db() as conn:
        user = conn.execute("SELECT user_id, username FROM users WHERE username = ?", (username,)).fetchone()
        if user:
            return dict(user)
        # 不存在則註冊並建立第一筆對話
        cursor = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
        user_id = cursor.lastrowid
        conn.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, "新對話"))
        return {"user_id": user_id, "username": username}

def get_conversations(user_id: int) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT conversation_id, title FROM conversations WHERE user_id = ? ORDER BY conversation_id DESC",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]

def create_conversation(user_id: int, title: str) -> dict:
    with connect_db() as conn:
        cursor = conn.execute("INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title))
        return {"conversation_id": cursor.lastrowid, "title": title}

# --- 資料庫操作：問答紀錄 ---

def get_history(conversation_id: int, limit: int | None = None) -> list[dict]:
    with connect_db() as conn:
        sql = (
            "SELECT record_id, question, answer, answer_source, sources, created_at FROM qa_records "
            "WHERE conversation_id = ? ORDER BY record_id DESC"
        )
        params: list[object] = [conversation_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = list(conn.execute(sql, params))
    rows.reverse()
    return [{**dict(row), "sources": parse_sources(row["sources"])} for row in rows]

def parse_sources(raw: str | None) -> list[dict]:
    try:
        sources = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return sources if isinstance(sources, list) else []

def save_record(conversation_id: int, question: str, answer: str, source: str,
                sources: list[dict], passages: list[dict] | None = None) -> int:
    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO qa_records (conversation_id, question, answer, answer_source, sources, "
            "passages) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, question, answer, source,
             json.dumps(sources, ensure_ascii=False), json.dumps(passages or [], ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def get_passages(record_id: int, number: int) -> list[dict] | None:
    """某則回答第 number 個來源的教材原文；找不到這則回答時回傳 None。"""
    with connect_db() as conn:
        row = conn.execute(
            "SELECT passages FROM qa_records WHERE record_id = ?", (record_id,)
        ).fetchone()
    if row is None:
        return None
    return [{"label": p.get("label", ""), "text": p.get("text", "")}
            for p in parse_sources(row["passages"])
            if isinstance(p, dict) and p.get("number") == number]


# --- 學習程度判斷 ---

LEVELS = ("初學", "中級", "進階")
MIN_QUESTIONS = 3      # 至少問幾題才開始分析
REFRESH_EVERY = 5      # 每新增幾題自動重新分析
_analyzing: set[int] = set()
_analyzing_lock = threading.Lock()


def user_id_of(conversation_id: int) -> int | None:
    with connect_db() as conn:
        row = conn.execute("SELECT user_id FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
    return row["user_id"] if row else None


def count_questions(user_id: int) -> int:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM qa_records q JOIN conversations c ON c.conversation_id = q.conversation_id "
            "WHERE c.user_id = ?", (user_id,)
        ).fetchone()
    return row["n"]


def recent_questions(user_id: int, limit: int = 30) -> list[str]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT q.question FROM qa_records q JOIN conversations c ON c.conversation_id = q.conversation_id "
            "WHERE c.user_id = ? ORDER BY q.record_id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
    return [row["question"] for row in reversed(rows)]


def get_profile(user_id: int) -> dict | None:
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    profile = dict(row)
    for key in ("strengths", "weaknesses", "recommendations"):
        profile[key] = parse_sources(profile[key])
    return profile


def profile_status(user_id: int) -> dict:
    total = count_questions(user_id)
    profile = get_profile(user_id)
    if profile:
        profile["question_count"] = total
        return profile
    if total < MIN_QUESTIONS:
        return {"level": None, "message": f"目前累積 {total} 題，至少需要 {MIN_QUESTIONS} 題才能分析。"}
    return {"level": None, "message": "已有足夠提問，請按「重新分析」產生報告。"}


def ollama_json(system: str, prompt: str) -> dict:
    body = json.dumps({
        "model": OLLAMA_MODEL, "stream": False, "think": False, "format": "json",
        "options": {"temperature": 0.2},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=180) as response:
        text = json.loads(response.read().decode("utf-8"))["message"]["content"]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return json.loads(text)


def analyze_profile(user_id: int) -> dict | None:
    questions = recent_questions(user_id)
    if len(questions) < MIN_QUESTIONS:
        return None
    listing = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    prompt = (
        f"以下是一位學生依時間順序問過的微積分問題（可能含 LaTeX）：\n{listing}\n\n"
        "請輸出 JSON，欄位如下：\n"
        "- level：只能是「初學」「中級」「進階」其中之一\n"
        "- summary：50 字內的程度描述\n"
        "- strengths：學生看起來掌握較好的主題（陣列，最多 3 項）\n"
        "- weaknesses：學生看起來觀念不清或反覆發問的主題（陣列，最多 3 項）\n"
        "- recommendations：建議複習的微積分章節或主題（陣列，最多 3 項）\n"
        "判斷依據：問題的基礎程度、是否反覆問同類概念、是否涉及進階技巧。"
    )
    result = ollama_json("你是微積分教學評估專家，根據學生的提問紀錄判斷其學習程度。只輸出 JSON。", prompt)
    level = result.get("level")
    if level not in LEVELS:
        raise ValueError(f"模型回傳了無效的程度：{level}")

    def as_list(value: object) -> list[str]:
        return [str(item) for item in value][:3] if isinstance(value, list) else []

    with connect_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_profiles "
            "(user_id, level, summary, strengths, weaknesses, recommendations, analyzed_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, level, str(result.get("summary", "")),
             json.dumps(as_list(result.get("strengths")), ensure_ascii=False),
             json.dumps(as_list(result.get("weaknesses")), ensure_ascii=False),
             json.dumps(as_list(result.get("recommendations")), ensure_ascii=False),
             count_questions(user_id)),
        )
    return get_profile(user_id)


def maybe_refresh_profile(user_id: int) -> None:
    """提問數累積到門檻時，在背景重新分析（不拖慢回答）。"""
    total = count_questions(user_id)
    profile = get_profile(user_id)
    due = total >= MIN_QUESTIONS if profile is None else total - profile["analyzed_count"] >= REFRESH_EVERY
    if not due:
        return
    with _analyzing_lock:
        if user_id in _analyzing:
            return
        _analyzing.add(user_id)

    def worker() -> None:
        try:
            analyze_profile(user_id)
        except Exception as error:
            print("[profile] 分析失敗：", error)
        finally:
            with _analyzing_lock:
                _analyzing.discard(user_id)

    threading.Thread(target=worker, daemon=True).start()


def build_level_hint(profile: dict) -> str:
    tone = {
        "初學": "學生是初學者：用淺顯的語言，先講直觀概念再給公式，步驟拆細，避免跳步。",
        "中級": "學生是中級程度：簡要帶過基本概念，重點放在解題步驟與常見錯誤。",
        "進階": "學生是進階程度：直接切入重點，可使用嚴謹推導，並補充延伸或更一般化的觀點。",
    }[profile["level"]]
    if profile.get("weaknesses"):
        tone += "學生較弱的主題：" + "、".join(profile["weaknesses"]) + "，遇到相關內容請多加說明。"
    return tone


# --- 呼叫 LLM 邏輯 ---

def friendly_ollama_error(error: Exception) -> str:
    if isinstance(error, (RuntimeError, FileNotFoundError)):
        return str(error)
    if isinstance(error, HTTPError):
        return f"Ollama 回傳 HTTP {error.code}；請確認模型 {OLLAMA_MODEL} 已下載。"
    if isinstance(error, URLError):
        return "無法連線到 Ollama；請確認 Ollama 服務已啟動。"
    return "Ollama 回覆格式異常，請稍後再試。"

def call_ollama(question: str, profile: dict | None = None):
    from tutor.main_rag import ask
    # main_rag.ask 有支援 level_hint 參數時才帶入；沒有就維持原行為
    if profile and "level_hint" in inspect.signature(ask).parameters:
        return ask(question, level_hint=build_level_hint(profile))
    return ask(question)

def demo_answer(question: str) -> str:
    return f"目前 Ollama 尚未就緒，因此這是一則示範回覆。你剛才問的是：「{question}」"

def answer_question(conversation_id: int, question: str) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("問題不可空白")
    if not conversation_id:
        raise ValueError("無效的對話紀錄 ID")

    user_id = user_id_of(conversation_id)
    profile = get_profile(user_id) if user_id else None
    try:
        result = call_ollama(question, profile)
        answer, sources = result.answer, list(result.sources)
        passages = list(getattr(result, "passages", ()))
        source, notice = "ollama", None
    except Exception as error:  # 把攔截的範圍擴大，捕捉 LangChain 可能的錯誤
        answer, sources, passages = demo_answer(question), [], []
        source, notice = "demo", friendly_ollama_error(error)

    record_id = save_record(conversation_id, question, answer, source, sources, passages)
    if user_id:
        maybe_refresh_profile(user_id)

    with connect_db() as conn:
        conv = conn.execute("SELECT title FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
        if conv and (conv["title"] == "新對話" or conv["title"] == "訪客問答"):
            new_title = question[:15] + ("..." if len(question) > 15 else "")
            conn.execute("UPDATE conversations SET title = ? WHERE conversation_id = ?", (new_title, conversation_id))

    return {"record_id": record_id, "question": question, "answer": answer, "source": source,
            "sources": sources, "notice": notice}

# --- 前端網頁版型 ---

PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>微積分助教</title>
<style>
:root{font-family:system-ui,-apple-system,"Noto Sans TC",sans-serif;color:#172033;background:#f8fafc}
body{margin:0;padding:0;height:100vh;display:flex;flex-direction:column;line-height:1.6}

/* 登入介面 */
#login-view{position:fixed;inset:0;background:#f8fafc;display:flex;align-items:center;justify-content:center;z-index:100}
.login-card{background:#fff;padding:2.5rem;border-radius:14px;box-shadow:0 12px 30px #0f172a12;width:100%;max-width:350px;text-align:center}
.login-card input{width:100%;box-sizing:border-box;padding:.75rem;margin:1rem 0;border:1px solid #94a3b8;border-radius:8px;font-size:1rem}
.login-card button{width:100%;padding:.75rem;border-radius:8px;background:#1769c2;color:#fff;border:none;font-size:1rem;font-weight:700;cursor:pointer}
.login-card button:hover{background:#115196}

/* 主介面 */
#app-view{display:none;max-width:1000px;margin:2rem auto;padding:0 1rem;width:100%;box-sizing:border-box;flex-direction:row;gap:1.5rem}
.sidebar{width:260px;flex-shrink:0;display:flex;flex-direction:column;gap:1rem}
.main-content{flex:1;min-width:0;display:flex;flex-direction:column}
.panel{border:1px solid #d7deea;border-radius:14px;background:#fff;padding:1rem}

.user-profile{display:flex;justify-content:space-between;align-items:center;padding-bottom:.5rem;border-bottom:1px solid #e2e8f0;margin-bottom:.5rem}
.user-profile span{font-weight:700;color:#1e293b}
.logout-btn{background:none;border:none;color:#ef4444;cursor:pointer;font-size:.9rem}
.logout-btn:hover{text-decoration:underline}

.sidebar button.full-btn{width:100%;padding:0.5rem;border-radius:6px;border:1px solid #d7deea;background:#f1f5f9;cursor:pointer;font-weight:bold;color:#334155}
.sidebar button.full-btn:hover{background:#e2e8f0}
.item-list{list-style:none;padding:0;margin:0 0 0.5rem 0;max-height:400px;overflow-y:auto}
.item-list li{padding:0.6rem;cursor:pointer;border-radius:6px;color:#475569;font-size:0.95rem;margin-bottom:0.2rem}
.item-list li.active{background:#eff6ff;color:#1d4ed8;font-weight:700}
.item-list li:hover:not(.active){background:#f8fafc}

#chat{min-height:350px;max-height:55vh;border:1px solid #d7deea;border-radius:14px;background:#fff;padding:1rem;margin-bottom:1rem;overflow:auto}
.user{font-weight:700;color:#0759a0;margin-top:1rem;white-space:pre-wrap}
.assistant{margin:0 0 1.5rem}
.assistant h1,.assistant h2,.assistant h3,.assistant h4,.assistant h5,.assistant h6{line-height:1.25;margin:1rem 0 .45rem}
.assistant p{margin:.45rem 0}
.assistant ul,.assistant ol{margin:.4rem 0;padding-left:1.6rem}
.assistant blockquote{margin:.6rem 0;padding:.1rem .8rem;border-left:3px solid #bbb;color:#444}
.assistant code{font-family:ui-monospace,Consolas,monospace;background:#f1f5f9;padding:.1rem .3rem;border-radius:3px}
.assistant pre{overflow:auto;background:#f1f5f9;padding:.8rem;border-radius:6px}
.assistant pre code{padding:0;background:none}
.assistant a{color:#0655ad}
.demo{color:#8a5500}
.sources{margin:.6rem 0 0;padding:.5rem .8rem;border-left:3px solid #7795bc;background:#f6f8fb;font-size:.9rem}
.sources ol{margin:.25rem 0 0;padding-left:0;list-style:none}
.sources .hint{margin-left:.4rem;color:#667;font-size:.8rem}
.source-link{all:unset;cursor:pointer;color:#0655ad;border-radius:3px;padding:.05rem .2rem}
.source-link:hover,.source-link[aria-expanded="true"]{background:#e2e9f4}
.source-link:focus-visible{outline:2px solid #7795bc}
.passages{margin:.35rem 0 .6rem;padding:.4rem .7rem;border:1px solid #d5dde8;border-radius:4px;background:#fff;max-height:22rem;overflow:auto;font-size:.88rem}
.passage+.passage{border-top:1px dashed #ccd;margin-top:.5rem;padding-top:.5rem}
.passage-label{font-weight:600;color:#445;margin-bottom:.2rem}
.passage-empty{color:#777}

.math-composer{border:1px solid #d5dfed;border-radius:18px;padding:1rem;background:#fff;box-shadow:0 12px 30px #0f172a12}
.math-tabs{display:flex;gap:.4rem;overflow-x:auto;border-bottom:1px solid #e2e8f0;padding-bottom:.65rem;scrollbar-width:thin}
.math-tab{flex:0 0 auto;border:1px solid #000;border-radius:4px;padding:.5rem .75rem;background:#fff;color:#000;font-weight:650;cursor:pointer}
.math-tab:hover,.math-tab:focus-visible{background:#fff;outline:2px solid #000}
.math-tab[aria-selected="true"]{background:#fff;color:#000}
.key-panel{display:none;grid-template-columns:repeat(5,minmax(0,1fr));gap:.55rem;padding-top:.85rem}
.key-panel.is-active{display:grid}
.math-key{min-height:52px;border:1px solid #000;border-radius:4px;background:#fff;color:#000;font-size:1rem;font-weight:650;cursor:pointer}
.math-key:hover,.math-key:focus-visible{transform:translateY(-1px);border-color:#000;outline:2px solid #000}
.math-key:active{transform:translateY(1px)}
.math-key:disabled{opacity:.5;cursor:wait}
.template-key{font-size:.9rem}
.integral-icon,.limit-icon{display:inline-grid;grid-auto-flow:column;align-items:center;gap:.12rem;font-family:serif}
.integral-icon .limits{display:grid;gap:2px;font-size:.55em}
.placeholder-box{display:inline-block;min-width:1.05em;height:.82em;border:1.5px dashed #7192b8;border-radius:3px;vertical-align:middle}
.integral-icon .body{min-width:1.35em}
.limit-icon sub{font-size:.58em}.limit-icon .body{margin-left:.2rem}
math-field{display:block;width:100%;min-height:4.4rem;box-sizing:border-box;margin-top:.9rem;padding:.8rem;border:1px solid #94a3b8;border-radius:12px;background:#fbfdff;font-size:1.35rem;--caret-color:#1769c2;--selection-background-color:#bfdbfe}
math-field::part(virtual-keyboard-toggle),math-field::part(menu-toggle){display:none}
math-field:focus{outline:3px solid #bfdbfe;border-color:#1769c2}
#latex-preview{min-height:1.35rem;margin:.55rem .15rem 0;color:#526277;font:12px ui-monospace,Consolas,monospace;overflow-wrap:anywhere}
.composer-actions{display:flex;justify-content:flex-end;margin-top:.75rem}
.send-button{border:0;border-radius:10px;padding:.65rem 1rem;background:#1769c2;color:#fff;font-weight:700;cursor:pointer}
.send-button:disabled{opacity:.6}
#status{min-height:1.5rem;color:#64748b}

.profile-box{font-size:.9rem;color:#334155}
.level-badge{display:inline-block;padding:.1rem .6rem;border-radius:99px;background:#dbeafe;color:#1d4ed8;font-weight:700}
.p-summary{margin:.4rem 0}.p-title{font-weight:700;margin-top:.5rem}
.profile-box ul{margin:.2rem 0;padding-left:1.2rem}.p-meta{margin-top:.5rem;font-size:.8rem;color:#94a3b8}
@media(max-width:768px){ #app-view{flex-direction:column} .sidebar{width:100%} #chat{max-height:40vh} }
@media(max-width:520px){ .math-composer{padding:.75rem} .key-panel{grid-template-columns:repeat(4,minmax(0,1fr));gap:.4rem} .math-key{min-height:48px;font-size:.9rem} .template-key{font-size:.8rem} .send-button{width:100%} }
</style>
<script>MathJax={tex:{inlineMath:[['$','$'],['\\(','\\)']],displayMath:[['$$','$$'],['\\[','\\]']]}};</script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script><script type="module" src="https://unpkg.com/mathlive?module"></script></head>
<body>

<!-- 登入介面 -->
<div id="login-view">
    <div class="login-card">
        <h2 style="margin-top:0">微積分助教</h2>
        <p style="color:#64748b;font-size:0.9rem;margin-bottom:1.5rem">請輸入您的名稱以登入或註冊</p>
        <form id="login-form">
            <input type="text" id="username-input" placeholder="例如：王小明" required>
            <button type="submit">進入系統</button>
        </form>
    </div>
</div>

<!-- 主介面 -->
<div id="app-view">
    <div class="sidebar">
      <div class="panel">
        <div class="user-profile">
            <span id="display-username">👤 載入中</span>
            <button class="logout-btn" id="logout-btn">登出</button>
        </div>
        <h3 style="margin-top:0.5rem; margin-bottom:0.5rem; font-size:1rem;">我的歷史紀錄</h3>
        <ul id="conv-list" class="item-list" role="listbox"></ul>
        <button id="new-conv-btn" class="full-btn" type="button">＋ 建立新對話</button>
      </div>
      <div class="panel">
        <div class="user-profile"><span>📊 學習程度</span><button class="logout-btn" id="refresh-profile-btn" type="button" style="color:#1769c2">重新分析</button></div>
        <div id="profile-box" class="profile-box">尚未分析</div>
      </div>
    </div>

    <div class="main-content">
      <h1 style="margin-top:0; font-size:1.5rem">微積分助教</h1>
      <div id="chat" aria-live="polite">請從左側選擇對話或建立新對話。</div>

      <section class="math-composer" aria-label="數學公式輸入器">
        <div class="math-tabs" role="tablist">
          <button class="math-tab" type="button" role="tab" aria-selected="true" aria-controls="panel-basic" data-tab="basic">基本運算</button>
          <button class="math-tab" type="button" role="tab" aria-selected="false" aria-controls="panel-functions" data-tab="functions">函數與對數</button>
          <button class="math-tab" type="button" role="tab" aria-selected="false" aria-controls="panel-trig" data-tab="trig">三角函數</button>
          <button class="math-tab" type="button" role="tab" aria-selected="false" aria-controls="panel-calculus" data-tab="calculus">微積分與極限</button>
        </div>
        <div id="panel-basic" class="key-panel is-active" role="tabpanel" data-panel="basic">
          <button class="math-key" type="button" data-template="digit-7">7</button><button class="math-key" type="button" data-template="digit-8">8</button><button class="math-key" type="button" data-template="digit-9">9</button><button class="math-key" type="button" data-template="plus">+</button><button class="math-key" type="button" data-template="minus">−</button><button class="math-key" type="button" data-template="digit-4">4</button><button class="math-key" type="button" data-template="digit-5">5</button><button class="math-key" type="button" data-template="digit-6">6</button><button class="math-key" type="button" data-template="times">×</button><button class="math-key" type="button" data-template="divide">÷</button><button class="math-key" type="button" data-template="digit-1">1</button><button class="math-key" type="button" data-template="digit-2">2</button><button class="math-key" type="button" data-template="digit-3">3</button><button class="math-key" type="button" data-template="left-paren">(</button><button class="math-key" type="button" data-template="right-paren">)</button><button class="math-key" type="button" data-template="digit-0">0</button><button class="math-key" type="button" data-template="decimal">.</button><button class="math-key" type="button" data-template="equals">=</button><button class="math-key" type="button" data-template="power">xⁿ</button><button class="math-key" type="button" data-template="fraction">a⁄b</button>
        </div>
        <div id="panel-functions" class="key-panel" role="tabpanel" data-panel="functions" hidden>
          <button class="math-key" type="button" data-template="function">f(x)</button><button class="math-key" type="button" data-template="log">log</button><button class="math-key" type="button" data-template="ln">ln</button><button class="math-key" type="button" data-template="exp">exp</button><button class="math-key" type="button" data-template="sqrt">√</button>
        </div>
        <div id="panel-trig" class="key-panel" role="tabpanel" data-panel="trig" hidden>
          <button class="math-key" type="button" data-template="sin">sin</button><button class="math-key" type="button" data-template="cos">cos</button><button class="math-key" type="button" data-template="tan">tan</button><button class="math-key" type="button" data-template="arcsin">sin⁻¹</button><button class="math-key" type="button" data-template="pi">π</button>
        </div>
        <div id="panel-calculus" class="key-panel" role="tabpanel" data-panel="calculus" hidden>
          <button class="math-key template-key" type="button" data-template="integral" title="插入定積分並定位至第一個佔位符"><span class="integral-icon">∫<span class="limits"><span class="placeholder-box"></span><span class="placeholder-box"></span></span><span class="placeholder-box body"></span>dx</span></button><button class="math-key template-key" type="button" data-template="limit" title="插入極限並定位至第一個佔位符"><span class="limit-icon">lim<sub>x→<span class="placeholder-box"></span></sub><span class="placeholder-box body"></span></span></button><button class="math-key" type="button" data-template="indefinite-integral">∫ dx</button><button class="math-key" type="button" data-template="sum">Σ</button><button class="math-key" type="button" data-template="derivative">d/dx</button><button class="math-key" type="button" data-template="partial-derivative">∂/∂x</button><button class="math-key" type="button" data-template="differential">dx</button><button class="math-key" type="button" data-template="infinity">∞</button><button class="math-key" type="button" data-template="to">→</button><button class="math-key" type="button" data-template="alpha">α</button>
        </div>

        <math-field id="question" aria-label="數學問題" placeholder="請輸入數學式或使用上方快捷鍵" math-virtual-keyboard-policy="manual"></math-field>
        <div id="latex-preview" aria-live="polite"></div>
        <form id="form">
          <div class="composer-actions">
            <button class="send-button" id="send-btn" type="submit" disabled>送出問題</button>
          </div>
        </form>
      </section>
      <p id="status"></p>
    </div>
</div>

<script>
// --- UI Elements ---
const loginView = document.getElementById('login-view');
const appView = document.getElementById('app-view');
const loginForm = document.getElementById('login-form');
const usernameInput = document.getElementById('username-input');
const displayUsername = document.getElementById('display-username');
const logoutBtn = document.getElementById('logout-btn');

const chat = document.querySelector('#chat');
const form = document.querySelector('#form');
const input = document.querySelector('#question');
const status = document.querySelector('#status');
const preview = document.querySelector('#latex-preview');
const sendBtn = document.querySelector('#send-btn');
const convList = document.querySelector('#conv-list');
const btnNewConv = document.querySelector('#new-conv-btn');

// --- Global State ---
let currentUser = null; // {user_id, username}
let currentConvId = null;

// --- API Helpers ---
async function fetchApi(path, method='GET', body=null) {
    const opts = { method, headers: {} };
    if(body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const data = await res.json();
    if(!res.ok) throw new Error(data.error || '請求失敗');
    return data;
}

// --- Authentication Flow ---
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = usernameInput.value.trim();
    if(!username) return;
    try {
        const user = await fetchApi('/api/login', 'POST', { username });
        loginSuccess(user);
    } catch(err) { alert(err.message); }
});

logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('calculus_user');
    currentUser = null;
    currentConvId = null;
    appView.style.display = 'none';
    loginView.style.display = 'flex';
    usernameInput.value = '';
    chat.textContent = '';
    profileBox.textContent = '尚未分析';
});

function loginSuccess(user) {
    currentUser = user;
    localStorage.setItem('calculus_user', JSON.stringify(user));
    displayUsername.textContent = `👤 ${user.username}`;
    loginView.style.display = 'none';
    appView.style.display = 'flex';
    loadConversations();
    loadProfile();
}

function checkSession() {
    const saved = localStorage.getItem('calculus_user');
    if(saved) {
        try {
            const user = JSON.parse(saved);
            if(user.user_id && user.username) {
                loginSuccess(user);
            }
        } catch(e) { localStorage.removeItem('calculus_user'); }
    }
}

// --- Data Fetching & Rendering ---
async function loadConversations() {
    if(!currentUser) return;
    try {
        const convs = await fetchApi(`/api/conversations?user_id=${currentUser.user_id}`); convList.innerHTML = ''; if(convs.length > 0) { if(!convs.find(c => String(c.conversation_id) === String(currentConvId))) { currentConvId = convs[0].conversation_id; } convs.forEach(c => { const li = document.createElement('li'); li.textContent = c.title || '未命名對話'; li.setAttribute('role', 'option'); li.dataset.id = c.conversation_id; if(String(c.conversation_id) === String(currentConvId)) { li.classList.add('active'); li.setAttribute('aria-selected', 'true'); } li.addEventListener('click', () => switchConversation(c.conversation_id)); convList.append(li); }); sendBtn.disabled = false; await loadHistory(); } else { currentConvId = null; sendBtn.disabled = true; chat.textContent = '尚無對話紀錄，請點擊「建立新對話」。'; } } catch(err) { status.textContent = err.message; } }  async function switchConversation(id) { if(currentConvId === id) return; currentConvId = id; document.querySelectorAll('#conv-list li').forEach(li => { li.classList.toggle('active', li.dataset.id == id); li.setAttribute('aria-selected', String(li.dataset.id == id)); }); await loadHistory(); }  async function loadHistory() { if(!currentConvId) return; chat.textContent = '載入歷史紀錄中…'; try { const rows = await fetchApi(`/api/history?conversation_id=${currentConvId}`);
        chat.textContent = '';
        if(rows.length === 0) chat.textContent = '這是一個全新的對話，請開始發問。';
        rows.forEach(add);
    } catch(err) { chat.textContent = '歷史紀錄載入失敗。'; }
}

btnNewConv.addEventListener('click', async () => {
    if(!currentUser) return;
    try {
        const res = await fetchApi('/api/conversations', 'POST', {user_id: currentUser.user_id, title: "新對話"});
        currentConvId = res.conversation_id;
        await loadConversations();
    } catch(err) { alert(err.message); }
});

// --- Learning Profile ---
const profileBox = document.getElementById('profile-box');
const refreshProfileBtn = document.getElementById('refresh-profile-btn');
function listHtml(title, items){
    if(!Array.isArray(items) || !items.length) return '';
    return '<div class="p-title">'+title+'</div><ul>'+items.map(i=>'<li>'+escapeHtml(String(i))+'</li>').join('')+'</ul>';
}
function renderProfile(p){
    if(!p || !p.level){ profileBox.textContent = (p && p.message) || '尚未分析'; return; }
    profileBox.innerHTML = '<span class="level-badge">'+escapeHtml(p.level)+'</span>'
        + '<div class="p-summary">'+escapeHtml(p.summary||'')+'</div>'
        + listHtml('掌握較好', p.strengths) + listHtml('需要加強', p.weaknesses) + listHtml('建議複習', p.recommendations)
        + '<div class="p-meta">依據 '+p.analyzed_count+' 題提問分析（目前共 '+p.question_count+' 題）</div>';
}
async function loadProfile(){
    if(!currentUser) return;
    try{ renderProfile(await fetchApi('/api/profile?user_id='+currentUser.user_id)); }catch(e){}
}
refreshProfileBtn.addEventListener('click', async()=>{
    if(!currentUser) return;
    refreshProfileBtn.disabled = true; refreshProfileBtn.textContent = '分析中…';
    try{ renderProfile(await fetchApi('/api/profile/refresh','POST',{user_id: currentUser.user_id})); }
    catch(err){ profileBox.textContent = err.message; }
    finally{ refreshProfileBtn.disabled = false; refreshProfileBtn.textContent = '重新分析'; }
});

// --- Math Composer Logic ---
const templates={'+':'+','-':'-','.':'.','=':'=','(': '(',')':')','digit-0':'0','digit-1':'1','digit-2':'2','digit-3':'3','digit-4':'4','digit-5':'5','digit-6':'6','digit-7':'7','digit-8':'8','digit-9':'9',plus:'+',minus:'-',decimal:'.',equals:'=', 'left-paren':'(', 'right-paren':')',times:'\\times',divide:'\\div',power:'x^{\\placeholder{?}}',fraction:'\\frac{\\placeholder{?}}{\\placeholder{?}}',function:'f(\\placeholder{?})',log:'\\log_{\\placeholder{?}}(\\placeholder{?})',ln:'\\ln(\\placeholder{?})',exp:'\\exp(\\placeholder{?})',sqrt:'\\sqrt{\\placeholder{?}}',sin:'\\sin(\\placeholder{?})',cos:'\\cos(\\placeholder{?})',tan:'\\tan(\\placeholder{?})',arcsin:'\\arcsin(\\placeholder{?})',pi:'\\pi',integral:'\\int_{\\placeholder{?}}^{\\placeholder{?}} \\placeholder{?} \\, dx',limit:'\\lim_{x\\to\\placeholder{?}} \\placeholder{?}','indefinite-integral':'\\int \\placeholder{?} \\, dx',sum:'\\sum_{\\placeholder{?}}^{\\placeholder{?}}',derivative:'\\frac{d}{dx}', 'partial-derivative':'\\frac{\\partial}{\\partial x}',differential:'dx',infinity:'\\infty',to:'\\to',alpha:'\\alpha'};
function latexValue(){return input.getValue('latex').trim()}
function updatePreview(){const value=latexValue();preview.textContent=value?'LaTeX：'+value:''}
function insertLatex(latex){input.focus();input.executeCommand('insert',latex,{selectionMode:'placeholder'});updatePreview()}
function configureMathInput(){
    document.querySelectorAll('.math-key').forEach(button=>{
        button.disabled=false;
        button.addEventListener('click',()=>insertLatex(templates[button.dataset.template]));
    });
    input.addEventListener('input',updatePreview);
    updatePreview();
}
document.querySelectorAll('.math-key').forEach(button=>button.disabled=true);
document.querySelectorAll('.math-tab').forEach(tab=>tab.addEventListener('click',()=>{
    const name=tab.dataset.tab;
    document.querySelectorAll('.math-tab').forEach(item=>item.setAttribute('aria-selected',String(item===tab)));
    document.querySelectorAll('.key-panel').forEach(panel=>{
        const active=panel.dataset.panel===name;
        panel.classList.toggle('is-active',active);
        panel.hidden=!active;
    });
}));
customElements.whenDefined('math-field').then(configureMathInput);

function escapeHtml(text){const box=document.createElement('span');box.textContent=text;return box.innerHTML}
function renderInline(text){const codes=[];let html=escapeHtml(text).replace(/`([^`]+)`/g,(_,code)=>`\u0000${codes.push(code)-1}\u0000`);html=html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');html=html.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>');html=html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g,'<em>$1</em>').replace(/(?<!_)_([^_]+)_(?!_)/g,'<em>$1</em>');return html.replace(/\u0000(\d+)\u0000/g,(_,index)=>`<code>${codes[index]}</code>`)} function renderMarkdown(markdown){const lines=String(markdown||'').replace(/\r\n?/g,'\n').split('\n');let html='',list=null,code=null,math=null;const closeList=()=>{if(list){html+=`</${list}>`;list=null}};for(const line of lines){if(line.trim()==='$$'){closeList();if(math===null){math=[]}else{html+=`<p>$$${escapeHtml(math.join('\n'))}$$</p>`;math=null}continue}if(math!==null){math.push(line);continue}if(line.startsWith('```')){closeList();if(code===null){code=[]}else{html+=`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;code=null}continue}if(code!==null){code.push(line);continue}if(!line.trim()){closeList();continue}const heading=line.match(/^(#{1,6})\s+(.+)$/);const unordered=line.match(/^[-*+]\s+(.+)$/);const ordered=line.match(/^\d+[.)]\s+(.+)$/);if(heading){closeList();const level=heading[1].length;html+=`<h${level}>${renderInline(heading[2])}</h${level}>`;continue}if(/^[-*_]{3,}\s*$/.test(line)){closeList();html+='<hr>';continue}if(line.startsWith('> ')){closeList();html+=`<blockquote>${renderInline(line.slice(2))}</blockquote>`;continue}if(unordered||ordered){const tag=unordered?'ul':'ol';if(list!==tag){closeList();list=tag;html+=`<${tag}>`}html+=`<li>${renderInline((unordered||ordered)[1])}</li>`;continue}closeList();html+=`<p>${renderInline(line)}</p>`}closeList();if(code!==null)html+=`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;if(math!==null)html+=`<p>$$${escapeHtml(math.join('\n'))}$$</p>`;return html}
function renderSources(sources,recordId){
  if(!Array.isArray(sources)||!sources.length)return '';
  const items=sources.map(s=>{
    const text=`［${escapeHtml(String(s.number))}］${escapeHtml(s.label||'')}`;
    if(!recordId)return `<li>${text}</li>`;
    return `<li><button type="button" class="source-link" aria-expanded="false" data-record="${escapeHtml(String(recordId))}" data-number="${escapeHtml(String(s.number))}" title="顯示檢索到的教材原文">${text}</button><div class="passages" hidden></div></li>`;
  }).join('');
  return `<div class="sources"><strong>資料來源</strong>${recordId?'<span class="hint">（點章節可看檢索原文）</span>':''}<ol>${items}</ol></div>`;
}
async function togglePassages(button){
  const panel=button.nextElementSibling;const open=button.getAttribute('aria-expanded')==='true';
  button.setAttribute('aria-expanded',String(!open));panel.hidden=open;
  if(open||panel.dataset.loaded)return;
  panel.textContent='載入中…';
  try{
    const r=await fetch(`/api/passages?record=${encodeURIComponent(button.dataset.record)}&number=${encodeURIComponent(button.dataset.number)}`);
    const data=await r.json();if(!r.ok)throw new Error(data.error||'載入失敗');
    panel.innerHTML=data.passages.length?data.passages.map(p=>`<div class="passage"><div class="passage-label">${escapeHtml(p.label||'')}</div>${renderMarkdown(p.text)}</div>`).join(''):'<p class="passage-empty">這則回答沒有保存檢索原文（較早的紀錄）。</p>';
    panel.dataset.loaded='1';
    if(window.MathJax)MathJax.typesetPromise([panel]);
  }catch(err){panel.textContent='無法載入原文：'+err.message}
}
chat.addEventListener('click',e=>{const b=e.target.closest('.source-link');if(b)togglePassages(b)});

function add(record){
    if(chat.textContent === '這是一個全新的對話，請開始發問。' || chat.textContent === '載入歷史紀錄中…') chat.textContent = '';
    const q=document.createElement('div');q.className='user';q.textContent='你：'+record.question;
    const a=document.createElement('div');a.className='assistant '+(record.answer_source==='demo'||record.source==='demo'?'demo':'');
    a.innerHTML='<strong>'+(record.answer_source==='demo'||record.source==='demo'?'示範回覆':'Ollama 回覆')+'</strong>'+renderMarkdown(record.answer)+renderSources(record.sources,record.record_id);
    chat.append(q,a);
    chat.scrollTop=chat.scrollHeight;
    if(window.MathJax)MathJax.typesetPromise([a]);
}

// --- Submit Form ---
form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!currentConvId) return alert("請先選擇或建立對話");
    const question=latexValue();
    if(!question){status.textContent='問題不可空白';input.focus();return}
    input.readOnly=true;
    sendBtn.disabled=true;
    status.textContent='正在送往 Ollama…';
    try{
        const data = await fetchApi('/api/chat', 'POST', { question, conversation_id: currentConvId });
        add(data);
        input.setValue('');
        updatePreview();
        status.textContent=data.notice||'已收到 Ollama 回覆。';
        loadProfile(); setTimeout(loadProfile, 20000);

        // 若這是新對話的第一個問題，重新載入左側選單以更新標題
        const activeLi = document.querySelector('#conv-list li.active');
        if(activeLi && activeLi.textContent === '新對話') {
            await loadConversations();
        }
    }catch(error){
        status.textContent=error.message;
    }finally{
        input.readOnly=false;
        sendBtn.disabled=false;
        input.focus();
    }
});

// Boot up
window.addEventListener('DOMContentLoaded', checkSession);
</script></body></html>"""


class AppHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/api/conversations":
            qs = parse_qs(parsed.query)
            user_id = int(qs.get("user_id", [0])[0])
            self.send_json(200, get_conversations(user_id))

        elif parsed.path == "/api/profile":
            qs = parse_qs(parsed.query)
            self.send_json(200, profile_status(int(qs.get("user_id", [0])[0])))

        elif parsed.path == "/api/history":
            qs = parse_qs(parsed.query)
            conv_id = int(qs.get("conversation_id", [0])[0])
            self.send_json(200, get_history(conv_id))

        elif parsed.path == "/api/passages":
            self.send_passages(parse_qs(parsed.query))

        else:
            self.send_json(404, {"error": "找不到路徑"})

    def send_passages(self, query: dict[str, list[str]]) -> None:
        record, number = query.get("record", [""])[0], query.get("number", [""])[0]
        if not (record.isdigit() and number.isdigit()):
            self.send_json(400, {"error": "需要數字參數 record 與 number"})
            return
        passages = get_passages(int(record), int(number))
        if passages is None:
            self.send_json(404, {"error": "找不到這則回答"})
            return
        self.send_json(200, {"passages": passages})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

            if parsed.path == "/api/login":
                username = payload.get("username", "").strip()
                if not username:
                    self.send_json(400, {"error": "請輸入使用者名稱"})
                else:
                    self.send_json(200, login_or_register(username))

            elif parsed.path == "/api/conversations":
                self.send_json(200, create_conversation(payload.get("user_id"), payload.get("title", "新對話")))

            elif parsed.path == "/api/profile/refresh":
                user_id = int(payload.get("user_id") or 0)
                try:
                    analyze_profile(user_id)
                except Exception as error:
                    self.send_json(502, {"error": friendly_ollama_error(error)})
                else:
                    self.send_json(200, profile_status(user_id))

            elif parsed.path == "/api/chat":
                self.send_json(200, answer_question(payload.get("conversation_id"), str(payload.get("question", ""))))

            else:
                self.send_json(404, {"error": "找不到路徑"})

        except (ValueError, json.JSONDecodeError, KeyError) as error:
            self.send_json(400, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        print("[web]", format % args)


if __name__ == "__main__":
    initialize_database()
    print("請開啟 http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler).serve_forever()