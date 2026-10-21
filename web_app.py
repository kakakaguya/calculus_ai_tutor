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
SYSTEM_PROMPT = "你是一位專業的微積分助教，請務必使用繁體中文並簡潔回答。"


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
        if "sources" not in columns:
            # 回答引用的教材，存成 JSON 陣列；舊紀錄沒有來源，預設為空陣列
            conn.execute("ALTER TABLE qa_records ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")

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
            "SELECT question, answer, answer_source, sources, created_at FROM qa_records "
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


def save_record(question: str, answer: str, source: str, sources: list[dict]) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO qa_records (conversation_id, question, answer, answer_source, sources) "
            "VALUES (?, ?, ?, ?, ?)",
            (guest_conversation_id(conn), question, answer, source,
             json.dumps(sources, ensure_ascii=False)),
        )



def friendly_ollama_error(error: Exception) -> str:
    if isinstance(error, (RuntimeError, FileNotFoundError)):
        return str(error)  # 向量資料庫或文字塊尚未建立，訊息裡有下一步該執行的指令
    if isinstance(error, HTTPError):
        return f"Ollama 回傳 HTTP {error.code}；請確認模型 {OLLAMA_MODEL} 已下載。"
    if isinstance(error, URLError):
        return "無法連線到 Ollama；請確認 Ollama 服務已啟動。"
    return "Ollama 回覆格式異常，請稍後再試。"


def call_ollama(question: str):
    """回傳 TutorAnswer：回答內容與引用的教材來源。"""
    # 從 Chroma 檢索教材後交給 Ollama 回答（第一次呼叫時才開啟向量資料庫）
    from tutor.main_rag import ask

    return ask(question)


def demo_answer(question: str) -> str:
    return f"目前 Ollama 尚未就緒，因此這是一則示範回覆。你剛才問的是：「{question}」"


def answer_question(question: str) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("問題不可空白")
    try:
        # 直接把使用者的問題傳給 call_ollama 處理
        result = call_ollama(question)
        answer, sources = result.answer, list(result.sources)
        source, notice = "ollama", None
    except Exception as error:  # 把攔截的範圍擴大，捕捉 LangChain 可能的錯誤
        answer, sources = demo_answer(question), []
        source, notice = "demo", friendly_ollama_error(error)

    save_record(question, answer, source, sources)
    return {"question": question, "answer": answer, "source": source, "sources": sources,
            "notice": notice}


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>微積分助教</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.6}#chat{min-height:280px;border:1px solid #ccc;padding:1rem;margin-bottom:1rem}.user{font-weight:700;color:#0056b3;margin-top:1rem;white-space:pre-wrap}.assistant{margin:0 0 1.5rem}.assistant h1,.assistant h2,.assistant h3{line-height:1.25;margin:1rem 0 .45rem}.assistant p{margin:.45rem 0}.assistant ul,.assistant ol{margin:.4rem 0;padding-left:1.6rem}.assistant blockquote{margin:.6rem 0;padding:.1rem .8rem;border-left:3px solid #bbb;color:#444}.assistant code{font-family:ui-monospace,Consolas,monospace;background:#f1f1f1;padding:.1rem .3rem;border-radius:3px}.assistant pre{overflow:auto;background:#f1f1f1;padding:.8rem;border-radius:4px}.assistant pre code{padding:0;background:none}.assistant a{color:#0655ad}.demo{color:#8a5500}.toolbar{display:flex;flex-wrap:wrap;gap:.35rem;margin:.5rem 0}.toolbar button{padding:.35rem .55rem}.composer{min-height:5.2rem;border:1px solid #999;border-radius:4px;padding:.65rem;white-space:pre-wrap;overflow-wrap:anywhere}.composer:empty:before{content:attr(data-placeholder);color:#777}.formula{display:inline-flex;align-items:center;gap:.2rem;vertical-align:middle;margin:.15rem;padding:.25rem;border:1px solid #7795bc;border-radius:4px;background:#f4f8ff;white-space:normal}.formula input{width:4.5rem;padding:.25rem;border:1px solid #9aa}.formula .integrand{width:7rem}.formula button{padding:.15rem .35rem}.composer-form{display:flex;gap:.5rem;align-items:flex-start}.composer-form .composer{flex:1}.composer-form>button{padding:.65rem 1rem}#status{min-height:1.5rem;color:#666}.sources{margin:.6rem 0 0;padding:.5rem .8rem;border-left:3px solid #7795bc;background:#f6f8fb;font-size:.9rem;color:#333}.sources ol{margin:.25rem 0 0;padding-left:0;list-style:none}@media(max-width:480px){body{margin:1rem auto}.composer-form{flex-direction:column}.composer-form>button{width:100%}.formula{flex-wrap:wrap}.formula input{min-width:3.5rem}.toolbar{max-height:8rem;overflow:auto}}</style>

<!-- 1. 引入 MathJax 來渲染數學公式 -->
<script>
  MathJax = {
    tex: { inlineMath: [['$', '$'], ['\\(', '\\)']], displayMath: [['$$', '$$'], ['\\[', '\\]']] }
  };
</script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>

<h1>微積分助教</h1><div id="chat" aria-live="polite">載入歷史紀錄中…</div>
<section aria-label="微積分特殊符號輸入器"><div class="toolbar" role="toolbar" aria-label="微積分符號">
<button type="button" data-integral title="插入含上下界的定積分">定積分</button>
<button type="button" data-latex="\int f(x) \, dx" title="插入不定積分">不定積分</button><button type="button" data-latex="\frac{ }{ }" title="插入分數">分數</button><button type="button" data-latex="\sqrt{ }" title="插入根號">根號</button><button type="button" data-latex="\lim_{x \to }" title="插入極限">極限</button><button type="button" data-latex="\sum_{i=1}^{n}" title="插入總和">總和</button><button type="button" data-latex="\frac{d}{dx}" title="插入導數">導數</button><button type="button" data-latex="\frac{\partial}{\partial x}" title="插入偏導數">偏導數</button><button type="button" data-latex="\alpha" title="插入 alpha">α</button><button type="button" data-latex="\beta" title="插入 beta">β</button><button type="button" data-latex="\gamma" title="插入 gamma">γ</button><button type="button" data-latex="+" title="加號">+</button><button type="button" data-latex="-" title="減號">−</button><button type="button" data-latex="=" title="等號">=</button><button type="button" data-latex="\infty" title="插入無限大">∞</button><button type="button" data-latex="\to" title="插入趨近">→</button></div>
<form id="form"><div class="composer-form"><div id="question" class="composer" contenteditable="true" role="textbox" aria-multiline="true" data-placeholder="輸入問題；可用上方按鈕插入 LaTeX" aria-label="問題"></div><button>送出</button></div></form></section><p id="status"></p>
<script>
const chat=document.querySelector('#chat'), form=document.querySelector('#form'), input=document.querySelector('#question'), status=document.querySelector('#status');
let savedRange=null;
function rememberCaret(){const s=getSelection();if(s.rangeCount&&input.contains(s.anchorNode))savedRange=s.getRangeAt(0).cloneRange()}
input.addEventListener('keyup',rememberCaret);input.addEventListener('mouseup',rememberCaret);input.addEventListener('focus',rememberCaret);
function activeRange(){if(savedRange&&input.contains(savedRange.startContainer))return savedRange;const r=document.createRange();r.selectNodeContents(input);r.collapse(false);return r}
function placeAfter(node){const r=document.createRange();r.setStartAfter(node);r.collapse(true);const s=getSelection();s.removeAllRanges();s.addRange(r);savedRange=r.cloneRange();input.focus()}
function insertText(text){const r=activeRange();r.deleteContents();const node=document.createTextNode(text);r.insertNode(node);placeAfter(node)}
function integralLatex(element){const value=selector=>element.querySelector(selector).value.trim();const lower=value('.lower'),upper=value('.upper'),fn=value('.integrand'),variable=value('.variable')||'x';return `\\int_{${lower}}^{${upper}} ${fn} \\, d${variable}`}
function insertIntegral(){const r=activeRange();r.deleteContents();const el=document.createElement('span');el.className='formula integral';el.contentEditable='false';el.setAttribute('aria-label','定積分公式元件');el.append('∫ ');for(const [klass,label,placeholder] of [['upper','上界','例如 1'],['lower','下界','例如 0'],['integrand','被積函數','例如 x^2'],['variable','微分變數','x']]){const field=document.createElement('input');field.className=klass;field.setAttribute('aria-label',label);field.placeholder=placeholder;if(klass==='variable')field.value='x';el.append(field)}const remove=document.createElement('button');remove.type='button';remove.textContent='移除';remove.title='移除此定積分';remove.addEventListener('click',()=>el.remove());el.append(remove);r.insertNode(el);placeAfter(el)}
function questionText(){let result='';for(const node of input.childNodes){if(node.nodeType===Node.TEXT_NODE)result+=node.textContent;else if(node.nodeType===Node.ELEMENT_NODE&&node.classList.contains('integral'))result+=integralLatex(node);else result+=node.innerText||node.textContent}return result.replace(/\u00a0/g,' ')}
document.querySelector('[data-integral]').addEventListener('click',insertIntegral);document.querySelectorAll('[data-latex]').forEach(button=>button.addEventListener('click',()=>insertText(button.dataset.latex)));
function escapeHtml(text){const box=document.createElement('span');box.textContent=text;return box.innerHTML}
function renderInline(text){
  const codes=[];let html=escapeHtml(text).replace(/`([^`]+)`/g,(_,code)=>`\u0000${codes.push(code)-1}\u0000`);
  html=html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  html=html.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>');
  html=html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g,'<em>$1</em>').replace(/(?<!_)_([^_]+)_(?!_)/g,'<em>$1</em>');
  return html.replace(/\u0000(\d+)\u0000/g,(_,index)=>`<code>${codes[index]}</code>`);
}
function renderMarkdown(markdown){
  const lines=String(markdown||'').replace(/\r\n?/g,'\n').split('\n');let html='',list=null,code=null,math=null;
  const closeList=()=>{if(list){html+=`</${list}>`;list=null}};
  for(const line of lines){
    // 新增：$$ 開頭的多行公式區塊，先整段收集起來，不要逐行拆成獨立段落，
    // 否則 MathJax 找不到成對的 $$ ... $$，公式就無法被渲染。
    if(line.trim()==='$$'){
      closeList();
      if(math===null){math=[]}
      else{html+=`<p>$$${escapeHtml(math.join('\n'))}$$</p>`;math=null}
      continue;
    }
    if(math!==null){math.push(line);continue}
    if(line.startsWith('```')){closeList();if(code===null){code=[]}else{html+=`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;code=null}continue}
    if(code!==null){code.push(line);continue}
    if(!line.trim()){closeList();continue}
    const heading=line.match(/^(#{1,6})\s+(.+)$/);const unordered=line.match(/^[-*+]\s+(.+)$/);const ordered=line.match(/^\d+[.)]\s+(.+)$/);
    if(heading){closeList();const level=heading[1].length;html+=`<h${level}>${renderInline(heading[2])}</h${level}>`;continue}
    if(/^[-*_]{3,}\s*$/.test(line)){closeList();html+='<hr>';continue}
    if(line.startsWith('> ')){closeList();html+=`<blockquote>${renderInline(line.slice(2))}</blockquote>`;continue}
    if(unordered||ordered){const tag=unordered?'ul':'ol';if(list!==tag){closeList();list=tag;html+=`<${tag}>`}html+=`<li>${renderInline((unordered||ordered)[1])}</li>`;continue}
    closeList();html+=`<p>${renderInline(line)}</p>`;
  }
  closeList();
  if(code!==null)html+=`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;
  // 新增：如果公式區塊到檔案結尾都還沒遇到結束的 $$，也要把收集到的內容印出來，避免整段消失。
  if(math!==null)html+=`<p>$$${escapeHtml(math.join('\n'))}$$</p>`;
  return html;
}
function renderSources(sources){
  if(!Array.isArray(sources)||!sources.length)return '';
  const items=sources.map(s=>`<li>［${escapeHtml(String(s.number))}］${escapeHtml(s.label||'')}</li>`).join('');
  return `<div class="sources"><strong>資料來源</strong><ol>${items}</ol></div>`;
}
function add(record){
    const q=document.createElement('div');q.className='user';q.textContent='你：'+record.question;
    const a=document.createElement('div');a.className='assistant '+(record.answer_source=== 'demo'||record.source==='demo'?'demo':'');
    const label=record.answer_source=== 'demo'||record.source==='demo'?'示範回覆':'Ollama 回覆';
    a.innerHTML=`<strong>${label}</strong>${renderMarkdown(record.answer)}${renderSources(record.sources)}`;
    chat.append(q,a);
    chat.scrollTop=chat.scrollHeight;
    
    // 2. 每次有新訊息加入時，呼叫 MathJax 重新渲染該段落的數學公式
    if(window.MathJax) MathJax.typesetPromise([a]);
}
fetch('/api/history').then(r=>r.json()).then(rows=>{chat.textContent='';rows.forEach(add)}).catch(()=>chat.textContent='歷史紀錄載入失敗。');
form.addEventListener('submit',async e=>{e.preventDefault();const question=questionText().trim();if(!question){status.textContent='問題不可空白';input.focus();return}input.contentEditable='false';const submit=form.querySelector('button[type="submit"],button:not([type])');submit.disabled=true;status.textContent='正在送往 Ollama…';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});const data=await r.json();if(!r.ok)throw new Error(data.error||'送出失敗');add(data);input.replaceChildren();status.textContent=data.notice||'已收到 Ollama 回覆。'}catch(err){status.textContent=err.message}finally{input.contentEditable='true';submit.disabled=false;input.focus()}});
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
