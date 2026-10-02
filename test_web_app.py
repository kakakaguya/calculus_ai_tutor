import os
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import json


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
        with patch.object(self.app, "call_ollama", return_value="這是真實回答"):
            result = self.app.answer_question("什麼是極限？")
        self.assertEqual(result["source"], "ollama")
        self.assertEqual(self.app.get_history()[0]["answer"], "這是真實回答")

    def test_unavailable_ollama_uses_marked_demo(self):
        from urllib.error import URLError
        with patch.object(self.app, "call_ollama", side_effect=URLError("refused")):
            result = self.app.answer_question("測試問題")
        self.assertEqual(result["source"], "demo")
        self.assertIn("無法連線", result["notice"])
        self.assertEqual(self.app.get_history()[0]["answer_source"], "demo")

    def test_blank_question_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不可空白"):
            self.app.answer_question("   ")

    def test_http_chat_and_history_endpoints(self):
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        request = Request(
            base_url + "/api/chat",
            data=json.dumps({"question": "HTTP 測試"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with patch.object(self.app, "call_ollama", return_value="API 回答"):
            with urlopen(request) as response:
                chat = json.loads(response.read().decode())
        with urlopen(base_url + "/api/history") as response:
            history = json.loads(response.read().decode())
        self.assertEqual(chat["source"], "ollama")
        self.assertEqual(history[-1]["question"], "HTTP 測試")


if __name__ == "__main__":
    unittest.main()
