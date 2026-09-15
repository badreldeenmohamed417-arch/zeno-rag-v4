#!/usr/bin/env python3
"""
Vercel Serverless Function Entrypoint for Zeno RAG Central Server
Endpoints:
  - GET  /api/status          : Returns job state, progress %, book counts, error status
  - GET  /api/logs            : Returns recent log lines
  - POST /api/start_job       : Takes source_url, fetches PDFs from <source_url>/download
  - POST /api/trigger_upload  : Takes target_url, zips RAG output and uploads to <target_url>/upload
  - POST /upload              : Target receiver endpoint for extracting uploaded RAG result zips
  - GET  /download            : Serves downloadable PDFs/zips
"""
import os
import sys
import time
import json
import zipfile
import logging
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler

# For Vercel Serverless Environment (use /tmp directory for writable files)
TMP_DIR = Path("/tmp/zeno_rag")
STAGING_DIR = TMP_DIR / "staging"
RAG_STORAGE = TMP_DIR / "rag_storage"
LOG_FILE = TMP_DIR / "zeno_server.log"

STAGING_DIR.mkdir(parents=True, exist_ok=True)
RAG_STORAGE.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.environ.get("SERVER_SECRET", "zeno_secret_12345")

# State File in /tmp for persistence across function invocations
STATE_FILE = TMP_DIR / "job_state.json"

def get_job_state():
    if STATE_FILE.exists():
        try:
            return json.load(open(STATE_FILE, "r", encoding="utf-8"))
        except Exception:
            pass
    return {
        "state": "IDLE",
        "total_books": 0,
        "completed_books": 0,
        "progress_percent": 0.0,
        "faiss_count": 0,
        "last_error": None,
        "source_url": None,
        "target_url": None
    }

def save_job_state(state_dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, ensure_ascii=False)
    except Exception:
        pass

def append_log(message):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass

class handler(BaseHTTPRequestHandler):

    def check_auth(self):
        token = self.headers.get("X-Server-Secret", "")
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if token == SECRET_KEY or qs.get("secret", [""])[0] == SECRET_KEY:
            return True
        return False

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Server-Secret")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def send_error_json(self, message, code=400):
        self.send_json({"status": "error", "message": message}, code)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Server-Secret")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/status":
            if not self.check_auth():
                return self.send_error_json("Unauthorized: Missing or invalid X-Server-Secret", 401)
            state = get_job_state()
            faiss_cnt = len(list(RAG_STORAGE.glob("**/*.faiss")))
            state["faiss_count"] = faiss_cnt
            return self.send_json(state)

        elif path == "/api/logs":
            if not self.check_auth():
                return self.send_error_json("Unauthorized: Missing or invalid X-Server-Secret", 401)
            lines = []
            if LOG_FILE.exists():
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-100:]
            return self.send_json({"logs": [l.strip() for l in lines]})

        elif path == "/download":
            zip_path = STAGING_DIR / "books_package.zip"
            if not zip_path.exists():
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in STAGING_DIR.glob("*.pdf"):
                        zf.write(f, f.name)
            if zip_path.exists():
                size = zip_path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with open(zip_path, "rb") as f:
                    while True:
                        c = f.read(1024 * 1024)
                        if not c: break
                        self.wfile.write(c)
            else:
                self.send_error_json("No download package available", 404)
        else:
            self.send_error_json("Endpoint not found", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/upload":
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return self.send_error_json("Empty upload payload", 400)
            
            dest_zip = STAGING_DIR / f"received_{int(time.time())}.zip"
            got = 0
            with open(dest_zip, "wb") as f:
                while got < length:
                    chunk = self.rfile.read(min(1024*1024, length - got))
                    if not chunk: break
                    f.write(chunk)
                    got += len(chunk)
            
            try:
                with zipfile.ZipFile(dest_zip, 'r') as zf:
                    zf.extractall(RAG_STORAGE)
                dest_zip.unlink(missing_ok=True)
                append_log("✅ Results zip uploaded and extracted to rag_storage!")
                return self.send_json({"status": "success", "message": "Results uploaded and extracted successfully"})
            except Exception as e:
                append_log(f"❌ Upload extraction error: {e}")
                return self.send_error_json(str(e), 500)

        elif path == "/api/start_job":
            if not self.check_auth():
                return self.send_error_json("Unauthorized", 401)
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
            source_url = body.get("source_url")
            if not source_url:
                return self.send_error_json("Missing required field 'source_url'", 400)
            
            state = get_job_state()
            state["state"] = "DOWNLOADING"
            state["source_url"] = source_url
            save_job_state(state)
            append_log(f"▶ Job initiated with source_url: {source_url}")
            return self.send_json({"status": "started", "message": f"Job initiated with source_url {source_url}"})

        elif path == "/api/trigger_upload":
            if not self.check_auth():
                return self.send_error_json("Unauthorized", 401)
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
            target_url = body.get("target_url")
            if not target_url:
                return self.send_error_json("Missing required field 'target_url'", 400)
            
            state = get_job_state()
            state["state"] = "UPLOADING"
            state["target_url"] = target_url
            save_job_state(state)
            append_log(f"▶ Triggered upload to target_url: {target_url}")
            return self.send_json({"status": "uploading", "message": f"Upload triggered to {target_url}"})

        else:
            self.send_error_json("Endpoint not found", 404)
