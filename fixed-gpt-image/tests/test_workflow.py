import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/image.py"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
KEY = "test-only-secret-never-real"
PROMPT = "private-test-prompt"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.calls.append((self.path, body, {k.lower(): v for k, v in self.headers.items()}))
        self.send_response(self.server.status)
        if self.server.status == 302:
            self.send_header("Location", self.server.endpoint + "/redirect-target")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.payload).encode())

    def do_GET(self):
        self.server.gets.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"should-not-download")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.endpoint = "http://127.0.0.1:%s/v1" % self.server.server_port
        self.server.calls, self.server.gets, self.server.status = [], [], 200
        self.server.payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = self.dir / "config.json"
        self.config.write_text(json.dumps({"version": 1, "endpoint": self.server.endpoint,
            "api_key": KEY, "model": "gpt-image-2.5", "timeout_seconds": 3, "allow_local_http": True}))
        self.out = self.dir / "out.png"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def invoke(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.config), *args],
                              text=True, capture_output=True, timeout=20, env=env)

    def image(self, *extra, env=None):
        return self.invoke("generate", "--prompt", PROMPT, "--output", str(self.out), *extra, env=env)

    def test_doctor_and_dry_run_no_requests(self):
        self.assertEqual(self.invoke("doctor").returncode, 0)
        r = self.image("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["dry_run"])
        self.assertEqual(self.server.calls, [])
        self.assertFalse(self.out.exists())
        self.assertNotIn(KEY, r.stdout + r.stderr)
        self.assertNotIn(PROMPT, r.stdout + r.stderr)

    def test_generate_fixed_model_and_metadata(self):
        r = self.image()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.out.read_bytes(), PNG)
        path, body, headers = self.server.calls[0]
        self.assertEqual(path, "/v1/images/generations")
        self.assertEqual(json.loads(body)["model"], "gpt-image-2.5")
        self.assertEqual(json.loads(body)["n"], 1)
        self.assertEqual(headers["authorization"], "Bearer " + KEY)
        meta = self.out.with_suffix(".png.json").read_text()
        self.assertNotIn(KEY, meta)
        self.assertNotIn(PROMPT, meta)
        self.assertEqual(len(self.server.calls), 1)

    def test_edit_local_multipart(self):
        image = self.dir / "input.png"
        image.write_bytes(PNG)
        r = self.invoke("edit", "--image", str(image), "--prompt", PROMPT, "--output", str(self.out))
        self.assertEqual(r.returncode, 0, r.stderr)
        path, body, _ = self.server.calls[0]
        self.assertEqual(path, "/v1/images/edits")
        self.assertIn(b"gpt-image-2.5", body)
        self.assertIn(PNG, body)

    def test_http_errors_no_retry_or_secret_echo(self):
        for status in (401, 429, 500):
            with self.subTest(status=status):
                self.server.calls.clear()
                self.server.status = status
                self.server.payload = {"error": {"message": KEY + PROMPT}}
                r = self.image()
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(len(self.server.calls), 1)
                self.assertNotIn(KEY, r.stdout + r.stderr)
                self.assertNotIn(PROMPT, r.stdout + r.stderr)

    def test_no_redirect(self):
        self.server.status = 302
        r = self.image()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.server.calls), 1)
        self.assertEqual(self.server.gets, [])

    def test_url_only_not_downloaded(self):
        self.server.payload = {"data": [{"url": self.server.endpoint + "/download.png"}]}
        r = self.image()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.server.gets, [])
        self.assertFalse(self.out.exists())

    def test_environment_does_not_change_provider(self):
        env = dict(os.environ, OPENAI_BASE_URL="https://wrong.invalid", GPT_IMAGE_PROFILE="wrong",
                   OPENAI_API_KEY="wrong-key", NODE_OPTIONS="--invalid-flag")
        r = self.image(env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.server.calls[0][2]["authorization"], "Bearer " + KEY)

    def test_output_not_overwritten(self):
        self.out.write_bytes(b"existing")
        r = self.image()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.out.read_bytes(), b"existing")
        self.assertEqual(self.server.calls, [])

    def test_configure_env_and_exclusive(self):
        target = self.dir / "new.json"
        cmd = [sys.executable, str(SCRIPT), "--config", str(target), "configure",
               "--endpoint", "https://example.invalid/v1"]
        env = dict(os.environ, OPENAI_API_KEY=KEY)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(target.read_text())["model"], "gpt-image-2.5")
        self.assertNotIn(KEY, r.stdout + r.stderr)
        self.assertNotEqual(subprocess.run(cmd, env=env, capture_output=True).returncode, 0)

    def test_remote_http_refused(self):
        c = json.loads(self.config.read_text())
        c["endpoint"] = "http://example.invalid/v1"
        self.config.write_text(json.dumps(c))
        self.assertNotEqual(self.image().returncode, 0)
        self.assertEqual(self.server.calls, [])

    def test_changed_bundle_rejected(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("fixed_image", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module, "BUNDLE_HASH", "invalid"):
            with self.assertRaisesRegex(ValueError, "differs from audited"):
                module.bundle()

    def test_invalid_image_rejected(self):
        self.server.payload = {"data": [{"b64_json": base64.b64encode(b"not PNG").decode()}]}
        self.assertNotEqual(self.image().returncode, 0)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
