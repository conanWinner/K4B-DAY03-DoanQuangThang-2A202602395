import json
import os
from pathlib import Path
import sys
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_server import LabHandler, ThreadingHTTPServer


class WebUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, {"LLM_PROVIDER": "mock"})
        cls.env.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LabHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.env.stop()

    def test_page_and_safe_config(self):
        html = urlopen(self.base + "/", timeout=2).read().decode()
        self.assertIn("System prompt", html)
        self.assertIn("Agent trace", html)
        config = json.load(urlopen(self.base + "/api/config", timeout=2))
        self.assertEqual(config["provider"]["mode"], "mock")
        self.assertEqual(len(config["tools"]), 3)
        self.assertNotIn("API_KEY", json.dumps(config))

    def test_stream_shows_active_tool_and_result(self):
        body = json.dumps({"message": "Tra cứu CF001", "system_prompt": "Bạn là trợ lý.",
                           "session_id": "web-test-session", "allow_schedule": False}).encode()
        request = Request(self.base + "/api/chat", method="POST", data=body,
                          headers={"Content-Type": "application/json"})
        lines = [json.loads(line) for line in urlopen(request, timeout=3) if line.strip()]
        kinds = [line["data"]["action_type"] for line in lines if line["event"] == "trace"]
        self.assertIn("TOOL_STARTED", kinds)
        self.assertIn("TOOL_EXECUTION", kinds)
        self.assertEqual(lines[-1]["event"], "done")
        result = next(line["data"] for line in lines
                      if line["event"] == "trace" and line["data"]["action_type"] == "TOOL_EXECUTION")
        self.assertEqual(result["observation"]["status"], "SUCCESS")

    def test_rejects_empty_prompt(self):
        body = json.dumps({"message": "Xin chào", "system_prompt": ""}).encode()
        request = Request(self.base + "/api/chat", method="POST", data=body,
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(Exception) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
