#!/usr/bin/env python3
"""
Automatically launch all 10 Kaggle GPU workers via Kaggle CLI:
1. Ensures local file_server.py & ngrok tunnel are active
2. Prepares kernel code with SERVER_URL and WORKER_ID (1..10)
3. Pushes and triggers all 10 Kaggle GPU kernels automatically
"""
import os
import sys
import time
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path("/home/badr-eldeen/Documents/zeno_rag")
STAGING_DIR = BASE_DIR / "staging"
RAG_STORAGE = BASE_DIR / "rag_storage"
KAGGLE_DIR = Path("/tmp/kaggle_workers")

print("=" * 60)
print("  🚀 Zeno RAG - Automatic Kaggle CLI Worker Launcher")
print("=" * 60)

# 1. Start file_server.py if not running
server_running = False
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/status", timeout=2) as resp:
        if resp.status == 200:
            server_running = True
            print("✅ File server running on port 8000")
except Exception:
    pass

if not server_running:
    print("▶ Starting file_server.py on port 8000...")
    subprocess.Popen([sys.executable, str(BASE_DIR / "file_server.py")])
    time.sleep(2)

# 2. Get ngrok tunnel URL
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
    print("❌ Failed to get ngrok URL!")
    sys.exit(1)

print(f"🌐 Server Public URL: {tunnel_url}")

# Read worker template script
with open(BASE_DIR / "standalone_worker.py", "r", encoding="utf-8") as f:
    standalone_code = f.read()

# Get username from kaggle credentials
username = "badreldeenmohamed417"
cred_path = Path.home() / ".kaggle" / "credentials.json"
if cred_path.exists():
    try:
        cred = json.load(open(cred_path))
        username = cred.get("username", username)
    except:
        pass

zips = sorted(list(STAGING_DIR.glob("books_worker_*.zip")))
total_workers = len(zips)
print(f"📦 Launching {total_workers} Kaggle Workers for user '{username}'...\n")

shutil.rmtree(KAGGLE_DIR, ignore_errors=True)
KAGGLE_DIR.mkdir(parents=True, exist_ok=True)

success_count = 0
for w_id in range(1, total_workers + 1):
    w_dir = KAGGLE_DIR / f"worker_{w_id}"
    w_dir.mkdir(parents=True, exist_ok=True)
    
    meta = {
        "id": f"{username}/zeno-worker-{w_id}",
        "title": f"zeno-worker-{w_id}",
        "code_file": "worker.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_tpu": "false",
        "enable_internet": "true",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": []
    }
    
    with open(w_dir / "kernel-metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        
    script_content = f"""import os
os.environ["SERVER_URL"] = "{tunnel_url}"
os.environ["WORKER_ID"] = "{w_id}"

{standalone_code}
"""
    with open(w_dir / "worker.py", "w", encoding="utf-8") as f:
        f.write(script_content)
        
    print(f"🚀 Pushing Kaggle Worker #{w_id} ({meta['id']})...")
    res = subprocess.run(["kaggle", "kernels", "push", "-p", str(w_dir)], capture_output=True, text=True)
    
    if res.returncode == 0:
        print(f"   ✅ Worker #{w_id} successfully launched on Kaggle GPU!")
        success_count += 1
    else:
        err = res.stderr.strip() or res.stdout.strip()
        print(f"   ⚠️ Worker #{w_id} push warning/error: {err}")
        # Retry once after 4 seconds if 409 Conflict
        if "409" in err or "Conflict" in err:
            time.sleep(4)
            res2 = subprocess.run(["kaggle", "kernels", "push", "-p", str(w_dir)], capture_output=True, text=True)
            if res2.returncode == 0:
                print(f"   ✅ Worker #{w_id} successfully launched on Kaggle GPU! (on retry)")
                success_count += 1
    
    time.sleep(3) # Avoid Kaggle API rate limiting

print("\n" + "=" * 60)
print(f"🎉 Successfully launched {success_count}/{total_workers} Kaggle GPU Workers!")
print("=" * 60)
print("📡 Listening for worker uploads in background. Monitoring progress...\n")

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
        print(f"\r⏳ [LIVE PROGRESS] Completed Books: {comp_count} | FAISS Indexes Saved: {faiss_count}", end="", flush=True)
except KeyboardInterrupt:
    print("\nStopping...")
