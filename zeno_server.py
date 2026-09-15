#!/usr/bin/env python3
"""
Zeno RAG Central Server V4
Endpoints:
  - POST /api/start_job        : Takes source_url, fetches PDFs from <source_url>/download, packages & starts Colab/Kaggle GPU workers
  - POST /api/trigger_upload   : Takes target_url, zips RAG output and uploads to <target_url>/upload
  - POST /upload               : Target receiver endpoint for extracting uploaded RAG result zips
  - GET  /download             : Source endpoint for serving downloadable PDFs/zips
  - GET  /api/status           : Returns job state, progress %, book counts, error status
  - GET  /api/logs             : Returns recent log lines
  - Notification Webhook       : Dispatches alert payloads on ERROR and SUCCESS events
"""
import os
import sys
import time
import json
import zipfile
import logging
import threading
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Paths
BASE_DIR = Path("/home/badr-eldeen/Documents/zeno_rag")
STAGING_DIR = BASE_DIR / "staging"
RAG_STORAGE = BASE_DIR / "rag_storage"
LOG_FILE = BASE_DIR / "zeno_server.log"

STAGING_DIR.mkdir(parents=True, exist_ok=True)
RAG_STORAGE.mkdir(parents=True, exist_ok=True)

# Logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

SECRET_KEY = os.environ.get("SERVER_SECRET", "zeno_secret_12345")

# State
state_lock = threading.Lock()
job_state = {
    "state": "IDLE",            # IDLE, DOWNLOADING, PROCESSING, WAITING_FOR_UPLOAD, UPLOADING, COMPLETED, ERROR
    "total_books": 0,
    "completed_books": 0,
    "progress_percent": 0.0,
    "faiss_count": 0,
    "last_error": None,
    "source_url": None,
    "target_url": None,
    "notification_listeners": []  # App listener endpoints
}

def log_and_notify(msg, is_error=False, is_success=False):
    if is_error:
        logging.error(msg)
        with state_lock:
            job_state["state"] = "ERROR"
            job_state["last_error"] = msg
    else:
        logging.info(msg)
    
    # Notify registered mobile app listeners
    payload = {
        "event": "ERROR" if is_error else ("SUCCESS" if is_success else "INFO"),
        "message": msg,
        "state": job_state["state"],
        "timestamp": time.time()
    }
    listeners = list(job_state.get("notification_listeners", []))
    for listener_url in listeners:
        try:
            req = urllib.request.Request(
                listener_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

def update_progress_stats():
    with state_lock:
        comp_file = RAG_STORAGE / "completed_books.json"
        comp_count = 0
        if comp_file.exists():
            try:
                comp_count = len(json.load(open(comp_file)))
            except:
                pass
        faiss_cnt = len(list(RAG_STORAGE.glob("**/*.faiss")))
        total = job_state.get("total_books", 117)
        job_state["completed_books"] = comp_count
        job_state["faiss_count"] = faiss_cnt
        if total > 0:
            job_state["progress_percent"] = round(min(100.0, (comp_count / total) * 100), 1)

def run_download_and_process_task(source_url):
    try:
        log_and_notify(f"▶ Starting download task from {source_url}/download...")
        with state_lock:
            job_state["state"] = "DOWNLOADING"
            job_state["source_url"] = source_url

        dl_endpoint = f"{source_url.rstrip('/')}/download"
        req = urllib.request.Request(dl_endpoint, headers={'User-Agent': 'Mozilla/5.0', 'ngrok-skip-browser-warning': 'true'})
        
        target_zip = STAGING_DIR / "incoming_books.zip"
        with urllib.request.urlopen(req, timeout=600) as resp, open(target_zip, "wb") as out_f:
            shutil_copy = resp.read()
            out_f.write(shutil_copy)
        
        log_and_notify("✅ Books downloaded successfully. Extracting to staging...")
        
        # Extract PDFs
        with zipfile.ZipFile(target_zip, 'r') as zf:
            zf.extractall(STAGING_DIR)
        target_zip.unlink(missing_ok=True)
        
        pdfs = list(STAGING_DIR.glob("**/*.pdf"))
        with state_lock:
            job_state["total_books"] = len(pdfs)
            job_state["state"] = "PROCESSING"

        log_and_notify(f"📚 Total PDFs staged for GPU processing: {len(pdfs)}")

        # Launch workers
        log_and_notify("🚀 Launching GPU Workers...")
        res = subprocess.run([sys.executable, str(BASE_DIR / "launch_kaggle_workers.py")], capture_output=True, text=True)
        if res.returncode != 0:
            log_and_notify(f"Worker launch warning: {res.stderr[:200]}", is_error=False)

        # Wait for completion
        while True:
            time.sleep(10)
            update_progress_stats()
            with state_lock:
                if job_state["progress_percent"] >= 100.0:
                    job_state["state"] = "WAITING_FOR_UPLOAD"
                    log_and_notify("🎉 All books processed! Waiting for upload command...", is_success=True)
                    break
    except Exception as e:
        log_and_notify(f"❌ Error during download/processing: {e}", is_error=True)

def run_upload_task(target_url):
    try:
        log_and_notify(f"▶ Preparing RAG package export to {target_url}/upload...")
        with state_lock:
            job_state["state"] = "UPLOADING"
            job_state["target_url"] = target_url

        export_zip = STAGING_DIR / "results_export.zip"
        with zipfile.ZipFile(export_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(RAG_STORAGE):
                for file in files:
                    fp = os.path.join(root, file)
                    zf.write(fp, os.path.relpath(fp, RAG_STORAGE))
        
        sz_mb = export_zip.stat().st_size / (1024 * 1024)
        log_and_notify(f"📦 Package size: {sz_mb:.1f} MB. Posting to {target_url}/upload...")

        with open(export_zip, "rb") as f:
            data = f.read()

        dest_endpoint = f"{target_url.rstrip('/')}/upload"
        req = urllib.request.Request(
            dest_endpoint,
            data=data,
            headers={"Content-Type": "application/octet-stream", "X-Server-Secret": SECRET_KEY},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            resp_body = resp.read().decode()

        with state_lock:
            job_state["state"] = "COMPLETED"
        log_and_notify(f"✅ RAG results successfully uploaded to target server! Response: {resp_body}", is_success=True)
    except Exception as e:
        log_and_notify(f"❌ Error during upload: {e}", is_error=True)


class ZenoRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info(f"[{self.command}] {args[0] if args else ''}")

    def check_auth(self):
        token = self.headers.get("X-Server-Secret", "")
        # Allow open requests if query parameter has secret or header matches
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if token == SECRET_KEY or qs.get("secret", [""])[0] == SECRET_KEY:
            return True
        return False

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def send_error_json(self, message, code=400):
        self.send_json({"status": "error", "message": message}, code)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/status":
            if not self.check_auth():
                return self.send_error_json("Unauthorized: Missing or invalid X-Server-Secret", 401)
            update_progress_stats()
            with state_lock:
                return self.send_json(job_state)

        elif path == "/api/logs":
            if not self.check_auth():
                return self.send_error_json("Unauthorized: Missing or invalid X-Server-Secret", 401)
            lines = []
            if LOG_FILE.exists():
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-100:]
            return self.send_json({"logs": [l.strip() for l in lines]})

        elif path == "/download":
            # Serves books zip if available
            zip_path = STAGING_DIR / "books_package.zip"
            if not zip_path.exists():
                # Package current staging PDFs
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
                self.send_error_json("No download package found", 404)
        else:
            self.send_error_json("Endpoint not found", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/upload":
            # Target endpoint for receiving uploaded zip
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
            
            # Extract to rag_storage
            try:
                with zipfile.ZipFile(dest_zip, 'r') as zf:
                    zf.extractall(RAG_STORAGE)
                dest_zip.unlink(missing_ok=True)
                log_and_notify("✅ Results zip uploaded and extracted to rag_storage!", is_success=True)
                return self.send_json({"status": "success", "message": "Results uploaded and extracted successfully"})
            except Exception as e:
                log_and_notify(f"❌ Upload extraction error: {e}", is_error=True)
                return self.send_error_json(str(e), 500)

        elif path == "/api/start_job":
            if not self.check_auth():
                return self.send_error_json("Unauthorized", 401)
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
            source_url = body.get("source_url")
            if not source_url:
                return self.send_error_json("Missing required field 'source_url'", 400)
            
            threading.Thread(target=run_download_and_process_task, args=(source_url,), daemon=True).start()
            return self.send_json({"status": "started", "message": f"Download and processing job initiated from {source_url}"})

        elif path == "/api/trigger_upload":
            if not self.check_auth():
                return self.send_error_json("Unauthorized", 401)
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
            target_url = body.get("target_url")
            if not target_url:
                return self.send_error_json("Missing required field 'target_url'", 400)
            
            threading.Thread(target=run_upload_task, args=(target_url,), daemon=True).start()
            return self.send_json({"status": "uploading", "message": f"Upload job initiated to {target_url}"})

        elif path == "/api/register_listener":
            if not self.check_auth():
                return self.send_error_json("Unauthorized", 401)
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
            listener_url = body.get("listener_url")
            if listener_url:
                with state_lock:
                    if listener_url not in job_state["notification_listeners"]:
                        job_state["notification_listeners"].append(listener_url)
            return self.send_json({"status": "registered", "listeners": job_state["notification_listeners"]})
        else:
            self.send_error_json("Endpoint not found", 404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), ZenoRequestHandler)
    print(f"🚀 Zeno Server V4 listening on port {port}")
    print(f"🔑 Secret Key: {SECRET_KEY}")
    logging.info(f"Server started on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
