#!/usr/bin/env python3
"""
File server that:
- Serves book zips via GET (Colab downloads from us)
- Receives result uploads via POST (Colab uploads to us)
"""
import os
import json
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock

STAGING_DIR = Path("/home/badr-eldeen/Documents/zeno_rag/staging")
FINAL_STORAGE = Path("/home/badr-eldeen/Documents/zeno_rag/rag_storage")
FINAL_STORAGE.mkdir(parents=True, exist_ok=True)
COMPLETED_FILE = FINAL_STORAGE / "completed_books.json"

# Track completions
lock = Lock()
completed_workers = set()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{self.command}] {args[0] if args else ''}")

    def do_HEAD(self):
        """Handle HEAD requests (used by curl -I or checks)"""
        path = self.path.lstrip("/").split("?")[0]
        filepath = STAGING_DIR / path
        if filepath.exists() and filepath.is_file():
            size = filepath.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        """Serve book zip files"""
        path = self.path.lstrip("/")
        if path.startswith("ngrok-skip-browser-warning"):
            path = ""
        
        # Remove query params
        path = path.split("?")[0]
        
        filepath = STAGING_DIR / path
        if filepath.exists() and filepath.is_file():
            size = filepath.stat().st_size
            print(f"  [DOWNLOAD] Serving {path} ({size/(1024*1024):.0f} MB)")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        elif path == "" or path == "status":
            # Status endpoint
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = {
                "completed_workers": list(completed_workers),
                "available_zips": [f.name for f in STAGING_DIR.glob("books_worker_*.zip")]
            }
            self.wfile.write(json.dumps(status).encode())
        else:
            print(f"  [404] {path}")
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Receive result uploads from workers"""
        path = self.path.lstrip("/").split("?")[0]
        
        if path.startswith("submit/"):
            worker_id = path.split("submit/")[1]
            length = int(self.headers.get('Content-Length', 0))
            
            if length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Empty upload")
                return
            
            print(f"\n  [UPLOAD] Receiving results from Worker #{worker_id} ({length/(1024*1024):.1f} MB)...")
            
            # Save zip
            result_zip = STAGING_DIR / f"results_worker_{worker_id}.zip"
            received = 0
            with open(result_zip, "wb") as f:
                while received < length:
                    chunk_size = min(1024 * 1024, length - received)
                    chunk = self.rfile.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
            
            print(f"  [UPLOAD] Received {received/(1024*1024):.1f} MB from Worker #{worker_id}")
            
            # Extract into final storage
            try:
                with zipfile.ZipFile(result_zip, 'r') as zf:
                    zf.extractall(FINAL_STORAGE)
                print(f"  [UPLOAD] ✅ Worker #{worker_id} results extracted to rag_storage!")
                
                with lock:
                    completed_workers.add(worker_id)
                    
                    # Update completed books
                    existing = set()
                    if COMPLETED_FILE.exists():
                        try:
                            existing = set(json.load(open(COMPLETED_FILE)))
                        except:
                            pass
                    
                    # Read completed IDs if sent
                    # We'll just track by worker for now
                    with open(COMPLETED_FILE, "w") as f:
                        json.dump(list(existing), f)
                
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
                
            except Exception as e:
                print(f"  [UPLOAD] ❌ Error extracting: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        
        elif path.startswith("complete/"):
            # Worker sends list of completed book IDs
            worker_id = path.split("complete/")[1]
            length = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(length).decode()
            
            try:
                new_ids = json.loads(data)
                with lock:
                    existing = set()
                    if COMPLETED_FILE.exists():
                        try:
                            existing = set(json.load(open(COMPLETED_FILE)))
                        except:
                            pass
                    existing.update(new_ids)
                    with open(COMPLETED_FILE, "w") as f:
                        json.dump(list(existing), f)
                
                print(f"  [COMPLETE] Worker #{worker_id} marked {len(new_ids)} books as done. Total: {len(existing)}")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(('0.0.0.0', 8000), Handler)
    print(f"Server running on port 8000")
    print(f"Serving zips from: {STAGING_DIR}")
    print(f"Saving results to: {FINAL_STORAGE}")
    zips = list(STAGING_DIR.glob("books_worker_*.zip"))
    for z in sorted(zips):
        print(f"  📦 {z.name} ({z.stat().st_size/(1024*1024):.0f} MB)")
    server.serve_forever()
