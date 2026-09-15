#!/usr/bin/env python3
"""
Zeno RAG Master Server & Tunnel Launcher
1. Starts file_server.py (Port 8000)
2. Starts ngrok tunnel to Port 8000
3. Retrieves public ngrok URL
4. Displays worker code snippets for Colab / Kaggle
5. Monitors completion status
"""
import os
import sys
import time
import json
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path("/home/badr-eldeen/Documents/zeno_rag")
STAGING_DIR = BASE_DIR / "staging"
RAG_STORAGE = BASE_DIR / "rag_storage"

print("=" * 60)
print("  🚀 Starting Zeno RAG Master Server & Tunnel")
print("=" * 60)

# Check staging zips
zips = sorted(list(STAGING_DIR.glob("books_worker_*.zip")))
print(f"📦 Staging zips available: {len(zips)}")
for z in zips:
    print(f"   - {z.name} ({z.stat().st_size / (1024*1024):.1f} MB)")

# 1. Start zeno_server.py if not running
server_running = False
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/status?secret=zeno_secret_12345", timeout=2) as resp:
        if resp.status == 200:
            server_running = True
            print("✅ Zeno Server V4 already running on port 8000")
except Exception:
    pass

if not server_running:
    print("▶ Starting zeno_server.py on port 8000...")
    subprocess.Popen([sys.executable, str(BASE_DIR / "zeno_server.py")])
    time.sleep(2)

# 2. Get or start ngrok tunnel
tunnel_url = None
for _ in range(5):
    try:
        req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            for t in data.get("tunnels", []):
                if t.get("proto") == "https":
                    tunnel_url = t.get("public_url")
                    break
                elif t.get("proto") == "http" and not tunnel_url:
                    tunnel_url = t.get("public_url")
        if tunnel_url:
            break
    except Exception:
        print("▶ Launching ngrok tunnel...")
        subprocess.Popen(["ngrok", "http", "8000"])
        time.sleep(3)

if not tunnel_url:
    print("❌ Failed to get ngrok URL. Please check ngrok configuration.")
    sys.exit(1)

print(f"\n🌐 Server Public URL: {tunnel_url}")
print("=" * 60)

# 3. Read standalone_worker.py code
with open(BASE_DIR / "standalone_worker.py", "r", encoding="utf-8") as f:
    worker_code = f.read()

print(f"\n📋 Instructions for Colab / Kaggle Workers:")
print(f"Total Workers: 1 to {len(zips)}")
print("-" * 60)
print(f"Run the following snippet in each Colab GPU notebook (change WORKER_ID from 1 to {len(zips)}):\n")

colab_snippet = f"""# --- Zeno RAG Worker Run ---
import os
os.environ["SERVER_URL"] = "{tunnel_url}"
os.environ["WORKER_ID"] = "1"  # Change this to 1, 2, 3, ..., {len(zips)} for each notebook

code = '''{worker_code}'''
with open("worker.py", "w") as f:
    f.write(code)

!python3 worker.py
"""

print(colab_snippet)
print("-" * 60)
print("\n📡 Server is listening for worker uploads. Press Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(10)
        completed_file = RAG_STORAGE / "completed_books.json"
        comp_count = 0
        if completed_file.exists():
            try:
                comp_count = len(json.load(open(completed_file)))
            except:
                pass
        faiss_count = len(list(RAG_STORAGE.glob("**/*.faiss")))
        print(f"\r⏳ [PROGRESS] Completed Books: {comp_count} | Extracted RAG Indexes: {faiss_count}", end="", flush=True)
except KeyboardInterrupt:
    print("\nStopping...")
