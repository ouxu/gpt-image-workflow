#!/usr/bin/env python3
"""Fixed-profile wrapper for @zhoujinandrew/gpt-image-cli 1.3.0."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path.home() / ".config/fixed-gpt-image/config.json"
BUNDLE_HASH = "9f5941464c7160666831f5f95f557d402c432bab99d36d9a21b73f60dd6a74b0"


def fail(message):
    raise ValueError(message)


def endpoint(value, allow_local=False):
    p = urllib.parse.urlsplit(value)
    local = allow_local and p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")
    if (p.scheme != "https" and not local) or not p.hostname or p.username or p.password or p.query or p.fragment:
        fail("Endpoint must be HTTPS without credentials, query or fragment")
    return value.rstrip("/")


def load_config(path):
    c = json.loads(path.read_text())
    if c.get("version") != 1 or not isinstance(c.get("model"), str) or not c["model"].strip():
        fail("Invalid configuration or missing exact model ID")
    c["endpoint"] = endpoint(c["endpoint"], c.get("allow_local_http") is True)
    if not isinstance(c.get("api_key"), str) or not c["api_key"]:
        fail("Missing API key")
    if not isinstance(c.get("timeout_seconds"), int) or not 1 <= c["timeout_seconds"] <= 900:
        fail("timeout_seconds must be 1..900")
    return c


def configure(args, config):
    if config.exists():
        fail("Configuration exists; edit it explicitly to change the fixed provider/model")
    if args.workbuddy_provider:
        records = json.loads(Path(args.workbuddy_config).expanduser().read_text())
        matches = [x for x in records if x.get("id") == args.workbuddy_provider]
        if len(matches) != 1:
            fail("WorkBuddy selector must match exactly one record")
        url, key = matches[0].get("url", ""), matches[0].get("apiKey", "")
    else:
        url, key = args.endpoint, os.environ.get(args.key_env, "")
    if not key:
        fail("API key missing; pass via environment, never a command-line argument")
    c = {"version": 1, "endpoint": endpoint(url), "api_key": key,
         "model": args.model, "timeout_seconds": 240}
    if not args.model.strip():
        fail("Model must not be empty")
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(c, f, indent=2)
    return {"ok": True, "config": str(config), "endpoint": c["endpoint"], "model": c["model"]}


def bundle():
    p = ROOT / "node_modules/@zhoujinandrew/gpt-image-cli/dist/index.js"
    source = p.read_text()
    if hashlib.sha256(p.read_bytes()).hexdigest() != BUNDLE_HASH:
        fail("Upstream bundle differs from audited 1.3.0; refusing to run")
    old = "new OpenAI({ apiKey: profile.apiKey, baseURL: profile.endpoint })"
    if source.count(old) != 1:
        fail("Safety patch cannot be applied exactly once")
    patched = "new OpenAI({ apiKey: profile.apiKey, baseURL: profile.endpoint, maxRetries: 0, timeout: Number(process.env.FIXED_TIMEOUT_MS), fetch: fixedFetch })"
    prefix = '''import fixedNodeFetch from "node-fetch";
let fixedSubmitted = false;
async function fixedFetch(url, init) {
  const target = String(url);
  const allowed = [process.env.FIXED_ENDPOINT + "/images/generations", process.env.FIXED_ENDPOINT + "/images/edits"];
  if (fixedSubmitted || !allowed.includes(target) || init?.method?.toUpperCase() !== "POST") throw new Error("Network policy refused request");
  fixedSubmitted = true;
  const response = await fixedNodeFetch(url, {...init, redirect: "error", size: 67108864});
  return response;
}
globalThis.fetch = async () => { throw new Error("URL image downloads disabled; use base64 response and local input files"); };
'''
    return prefix + source.replace(old, patched)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def models(c):
    req = urllib.request.Request(c["endpoint"] + "/models", headers={"Authorization": "Bearer " + c["api_key"]})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as r:
        raw = r.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        fail("Model response too large")
    ids = [x.get("id") for x in json.loads(raw).get("data", [])]
    return {"ok": True, "configured_model": c["model"], "exact_model_listed": c["model"] in ids,
            "image_models": [x for x in ids if isinstance(x, str) and "image" in x.lower()],
            "note": "Listing does not prove successful generation or underlying model identity"}


def run_image(args, c):
    started = time.monotonic()
    source = bundle()
    if not shutil.which("node"):
        fail("Node.js required; install dependencies with npm ci --ignore-scripts")
    out = Path(args.output).expanduser().absolute()
    meta = out.with_suffix(out.suffix + ".json")
    if out.suffix.lower() != ".png" or not out.parent.is_dir():
        fail("Output must be a .png path with an existing parent directory")
    if out.exists() or out.is_symlink() or meta.exists() or meta.is_symlink():
        fail("Refusing to overwrite existing output or metadata")
    prompt = Path(args.prompt_file).read_text() if args.prompt_file else args.prompt
    if not prompt or not prompt.strip():
        fail("Prompt is empty")
    inputs = []
    if args.command == "edit":
        for name in args.image:
            p = Path(name).expanduser().resolve()
            if not p.is_file():
                fail("Image input must be an existing local file")
            inputs += ["--image", str(p)]
    plan = {"ok": True, "operation": args.command, "requested_model": c["model"],
            "endpoint": c["endpoint"], "count": 1, "retries": 0, "output": str(out)}
    with tempfile.TemporaryDirectory(prefix="fixed-image-") as temp:
        temp = Path(temp)
        image = temp / "result.png"
        fd, runtime = tempfile.mkstemp(prefix=".runtime-", suffix=".mjs", dir=ROOT)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(source)
            cmd = ["node", runtime, "--endpoint", c["endpoint"], "--model", c["model"], "--format", "json"]
            if args.dry_run:
                cmd += ["--dry-run"]
            cmd += [args.command, "--prompt", "-", "--count", "1", "--quality", args.quality,
                    "--size", args.size, "--output-format", "png", "--out", str(image)] + inputs
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TMPDIR") if k in os.environ}
            env.update({"HOME": str(temp), "OPENAI_API_KEY": c["api_key"], "FIXED_ENDPOINT": c["endpoint"],
                        "FIXED_TIMEOUT_MS": str(c["timeout_seconds"] * 1000)})
            result = subprocess.run(cmd, input=prompt, text=True, capture_output=True, env=env,
                                    timeout=c["timeout_seconds"] + 10)
            if result.returncode:
                # Never echo upstream errors: they can contain keys, prompts or response bodies.
                fail("Upstream request failed (exit %s); no retry. Server may still have processed/billed it" % result.returncode)
            data = json.loads(result.stdout)
            if not data.get("ok"):
                fail("Upstream returned failure; no retry")
            if args.dry_run:
                request = data["data"]["request"]
                if request.get("model") != c["model"] or request.get("n") != 1:
                    fail("Upstream dry-run differs from fixed request")
                return dict(plan, dry_run=True, network_requested=False)
            if data["data"].get("model") != c["model"] or data["data"].get("count") != 1:
                fail("Unexpected response model/count; refusing output")
            raw = image.read_bytes()
            # A signature check is not full image decoding; consumers must inspect the output.
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                fail("Response is not a PNG")
            record = dict(plan, elapsed_seconds=round(time.monotonic() - started, 3),
                          sha256=hashlib.sha256(raw).hexdigest(), upstream_version="1.3.0",
                          model_identity_verified=False)
            # Exclusive creation also protects against concurrent runs targeting the same name.
            with out.open("xb") as f:
                f.write(raw)
            with meta.open("x") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            return dict(record, metadata=str(meta))
        finally:
            Path(runtime).unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = p.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure")
    choose = setup.add_mutually_exclusive_group(required=True)
    choose.add_argument("--endpoint")
    choose.add_argument("--workbuddy-provider")
    setup.add_argument("--workbuddy-config", default=str(Path.home() / ".workbuddy/models.json"))
    setup.add_argument("--key-env", default="OPENAI_API_KEY")
    setup.add_argument("--model", default="gpt-image-2.5")
    sub.add_parser("doctor")
    sub.add_parser("models")
    for verb in ("generate", "edit"):
        op = sub.add_parser(verb)
        prompt = op.add_mutually_exclusive_group(required=True)
        prompt.add_argument("--prompt")
        prompt.add_argument("--prompt-file")
        op.add_argument("--output", required=True)
        op.add_argument("--size", default="1024x1024")
        op.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="low")
        op.add_argument("--dry-run", action="store_true")
        if verb == "edit":
            op.add_argument("--image", action="append", required=True)
    args = p.parse_args()
    try:
        if args.command == "configure":
            result = configure(args, args.config.expanduser())
        else:
            c = load_config(args.config.expanduser())
            if args.command == "doctor":
                bundle()
                result = {"ok": True, "endpoint": c["endpoint"], "model": c["model"],
                          "node_available": bool(shutil.which("node")), "retries": 0,
                          "config_permissions": oct(args.config.expanduser().stat().st_mode & 0o777),
                          "upstream": "@zhoujinandrew/gpt-image-cli@1.3.0", "paid_request_sent": False}
            elif args.command == "models":
                result = models(c)
            else:
                result = run_image(args, c)
        print(json.dumps(result, ensure_ascii=False))
    except ValueError as exc:
        # Only our fixed messages are safe. JSON parsing errors are not echoed.
        message = str(exc) if type(exc) is ValueError else "Invalid JSON configuration or upstream response"
        print(json.dumps({"ok": False, "error": message, "retry": False}), file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": "Timed out; server may still process/bill. No automatic retry"}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__ + ": operation failed; no retry"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
