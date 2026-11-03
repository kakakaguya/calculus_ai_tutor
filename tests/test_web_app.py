import os
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import json

from tutor.main_rag import TutorAnswer


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["CALCULUS_TUTOR_DB"] = str(Path(self.tempdir.name) / "test.db")
        # 匯入放在環境變數之後，測試不碰正式資料庫。
        import importlib
        import web_app

        self.app = importlib.reload(web_app)
        with self.app.connect_db() as conn:
            conn.executescript("""
                CREATE TABLE users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, email TEXT UNIQUE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE conversations (conversation_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE qa_records (record_id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL, material_id INTEGER, question TEXT NOT NULL, answer TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            """)
        self.app.initialize_database()
        user = self.app.login_or_register("測試學生")
        self.conv_id = self.app.get_conversations(user["user_id"])[0]["conversation_id"]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.AppHandler)
        self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        os.environ.pop("CALCULUS_TUTOR_DB", None)
        self.tempdir.cleanup()

    def test_ollama_answer_is_saved(self):
        with patch.object(self.app, "call_ollama", return_value=TutorAnswer("這是真實回答", ())):
            result = self.app.answer_question(self.conv_id, "什麼是極限？")
        self.assertEqual(result["source"], "ollama")
        self.assertEqual(self.app.get_history(self.conv_id)[0]["answer"], "這是真實回答")

    def test_unavailable_ollama_uses_marked_demo(self):
        from urllib.error import URLError
        with patch.object(self.app, "call_ollama", side_effect=URLError("refused")):
            result = self.app.answer_question(self.conv_id, "測試問題")
        self.assertEqual(result["source"], "demo")
        self.assertIn("無法連線", result["notice"])
        self.assertEqual(self.app.get_history(self.conv_id)[0]["answer_source"], "demo")

    def test_missing_vector_database_message_is_shown(self):
        error = RuntimeError("向量資料庫不存在，請先執行 python -m ingestion.build_vector_db")
        with patch.object(self.app, "call_ollama", side_effect=error):
            result = self.app.answer_question(self.conv_id, "測試問題")
        self.assertEqual(result["source"], "demo")
        self.assertIn("build_vector_db", result["notice"])

    def test_sources_are_returned_and_kept_in_history(self):
        sources = ({"number": 1, "type": "教材", "label": "6.8 L'Hospital's Rule", "chunk_id": "c1"},)
        with patch.object(self.app, "call_ollama", return_value=TutorAnswer("答［1］", sources)):
            result = self.app.answer_question(self.conv_id, "羅必達法則？")
        self.assertEqual(result["sources"], list(sources))
        self.assertEqual(self.app.get_history(self.conv_id)[0]["sources"], list(sources))

    def _get(self, path):
        from urllib.error import HTTPError
        try:
            with urlopen(f"http://127.0.0.1:{self.server.server_port}{path}") as response:
                return response.status, json.loads(response.read().decode())
        except HTTPError as error:
            return error.code, json.loads(error.read().decode())

    def test_clicking_a_source_returns_the_text_the_model_saw(self):
        sources = ({"number": 1, "section": "6.8", "title": "L'Hospital's Rule",
                    "label": "6.8 L'Hospital's Rule"},)
        passages = ({"number": 1, "chunk_id": "chunk-000001", "label": "6.8 L'Hospital's Rule | A",
                     "text": "Concept A."},
                    {"number": 1, "chunk_id": "chunk-000002", "label": "6.8 L'Hospital's Rule | B",
                     "text": "Concept B."})
        with patch.object(self.app, "call_ollama",
                          return_value=TutorAnswer("答［1］", sources, passages)):
            result = self.app.answer_question(self.conv_id, "羅必達法則？")
        record_id = result["record_id"]
        self.assertEqual(self.app.get_history(self.conv_id)[0]["record_id"], record_id)
        self.assertNotIn("passages", self.app.get_history(self.conv_id)[0])

        status, body = self._get(f"/api/passages?record={record_id}&number=1")

        self.assertEqual(status, 200)
        self.assertEqual([p["text"] for p in body["passages"]], ["Concept A.", "Concept B."])
        self.assertEqual(body["passages"][0]["label"], "6.8 L'Hospital's Rule | A")

    def test_record_without_saved_text_returns_an_empty_list(self):
        with patch.object(self.app, "call_ollama", return_value=TutorAnswer("答", ())):
            record_id = self.app.answer_question(self.conv_id, "舊格式？")["record_id"]

        status, body = self._get(f"/api/passages?record={record_id}&number=1")

        self.assertEqual((status, body["passages"]), (200, []))

    def test_passages_request_is_validated(self):
        for query in ("", "?record=abc&number=1", "?record=1", "?record=1;drop&number=1"):
            status, body = self._get("/api/passages" + query)
            self.assertEqual(status, 400, query)
            self.assertIn("error", body)
        status, _ = self._get("/api/passages?record=999999&number=1")
        self.assertEqual(status, 404)

    def test_demo_answer_has_no_sources(self):
        from urllib.error import URLError
        with patch.object(self.app, "call_ollama", side_effect=URLError("refused")):
            result = self.app.answer_question(self.conv_id, "測試問題")
        self.assertEqual(result["sources"], [])
        self.assertEqual(self.app.get_history(self.conv_id)[0]["sources"], [])

    def test_blank_question_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不可空白"):
            self.app.answer_question(self.conv_id, "   ")

    def test_http_chat_and_history_endpoints(self):
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        request = Request(
            base_url + "/api/chat",
            data=json.dumps({"question": "HTTP 測試", "conversation_id": self.conv_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with patch.object(self.app, "call_ollama", return_value=TutorAnswer("API 回答", ())):
            with urlopen(request) as response:
                chat = json.loads(response.read().decode())
        with urlopen(f"{base_url}/api/history?conversation_id={self.conv_id}") as response:
            history = json.loads(response.read().decode())
        self.assertEqual(chat["source"], "ollama")
        self.assertEqual(history[-1]["question"], "HTTP 測試")

    def test_latex_and_newlines_are_sent_and_saved_verbatim(self):
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        question = "請計算：\n\\int_{0}^{1} x^2 \\, dx\n結果為何？"
        request = Request(
            base_url + "/api/chat",
            data=json.dumps({"question": question, "conversation_id": self.conv_id},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with patch.object(self.app, "call_ollama", return_value=TutorAnswer("\\(1/3\\)", ())) as call:
            with urlopen(request) as response:
                chat = json.loads(response.read().decode("utf-8"))
        self.assertEqual(call.call_args.args[0], question)
        self.assertEqual(chat["question"], question)
        self.assertEqual(self.app.get_history(self.conv_id)[-1]["question"], question)

    def test_page_contains_mathlive_tabbed_keyboard_and_mathjax(self):
        page = self.app.PAGE
        self.assertIn('<math-field id="question"', page)
        self.assertIn('math-virtual-keyboard-policy="manual"', page)
        self.assertIn('https://unpkg.com/mathlive?module', page)
        self.assertIn('role="tablist"', page)
        self.assertIn('data-tab="calculus"', page)
        self.assertIn('key-panel', page)
        self.assertIn('CSS Grid', page.replace('grid-template-columns', 'CSS Grid'))
        self.assertIn(r'\\placeholder{?}', page)
        self.assertIn("selectionMode:'placeholder'", page)
        self.assertIn("input.getValue('latex')", page)
        self.assertIn('placeholder-box', page)
        self.assertIn('textContent=', page)
        self.assertIn('MathJax.typesetPromise', page)
        self.assertIn('renderSources', page)
        self.assertIn('/api/passages', page)

    def test_page_restores_markdown_and_math_block_rendering(self):
        page = self.app.PAGE
        self.assertIn("function renderInline(text)", page)
        self.assertIn("function renderMarkdown(markdown)", page)
        self.assertIn("line.match(/^(#{1,6})\\s+(.+)$/)", page)
        self.assertIn("<strong>", page)
        self.assertIn("<blockquote>", page)
        self.assertIn("<pre><code>", page)
        self.assertIn("if(line.trim()==='$$')", page)
        self.assertIn("math.push(line)", page)
        self.assertIn("escapeHtml(math.join('\\n'))", page)

    def test_all_keyboard_buttons_use_named_templates(self):
        page = self.app.PAGE
        self.assertNotIn("data-latex=", page)
        self.assertIn("button.dataset.template", page)
        for template in (
            "digit-0", "times", "power", "fraction", "function", "log",
            "sin", "integral", "limit", "indefinite-integral", "sum",
            "derivative", "partial-derivative", "infinity", "alpha",
        ):
            self.assertIn(f'data-template="{template}"', page)
        self.assertIn(
            "selectionMode:'placeholder'", page
        )
        self.assertIn(r"power:'x^{\\placeholder{?}}'", page)
        self.assertIn(r"fraction:'\\frac{\\placeholder{?}}{\\placeholder{?}}'", page)
        self.assertIn("background:#fff;color:#000", page)
        self.assertIn("math-field::part(virtual-keyboard-toggle)", page)
        self.assertIn("math-field::part(menu-toggle)", page)
        self.assertNotIn("background:linear-gradient", page)


if __name__ == "__main__":
    unittest.main()
