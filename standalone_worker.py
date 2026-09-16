#!/usr/bin/env python3
"""
Zeno RAG Standalone Worker V3
1. Downloads books from our server (fast - Colab download speed)
2. Processes all books locally with GPU
3. Uploads results back to our server (fast - Colab upload speed)
No ongoing connection - just download at start, upload at end.
"""
import os
import sys
import json
import shutil
import zipfile
import urllib.request
from pathlib import Path

import nest_asyncio
nest_asyncio.apply()

# ============ CONFIG ============
SERVER_URL = os.environ.get("SERVER_URL", "")
WORKER_ID = os.environ.get("WORKER_ID", "0")

BOOKS_ZIP = Path("/content/books.zip")
WORK_DIR = Path("/content/work")
RAG_OUTPUT = Path("/content/rag_output")
RESULTS_ZIP = Path("/content/results.zip")

HEADERS = {'User-Agent': 'Mozilla/5.0', 'ngrok-skip-browser-warning': 'true'}

print("=" * 50)
print(f"  Zeno RAG Worker #{WORKER_ID}")
print("=" * 50)

if not SERVER_URL:
    print("ERROR: SERVER_URL not set!")
    sys.exit(1)

# ============ STEP 1: DOWNLOAD BOOKS ============
SERVER_URL = SERVER_URL.rstrip('/')
download_url = f"{SERVER_URL}/books_worker_{WORKER_ID}.zip"
print(f"Downloading: {download_url}")

def download_books_with_resume(url, save_path):
    attempts = 0
    while attempts < 10:
        attempts += 1
        existing_bytes = save_path.stat().st_size if save_path.exists() else 0
        req_headers = {**HEADERS}
        if existing_bytes > 0:
            req_headers['Range'] = f"bytes={existing_bytes}-"
        
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                code = resp.getcode()
                content_len = resp.headers.get('Content-Length')
                total = int(content_len) + existing_bytes if (content_len and code == 206) else (int(content_len) if content_len else 0)
                
                mode = "ab" if (code == 206 and existing_bytes > 0) else "wb"
                if mode == "wb":
                    existing_bytes = 0

                got = existing_bytes
                with open(save_path, mode) as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            print(f"\r  {got/(1024*1024):.1f}/{total/(1024*1024):.1f} MB ({got*100/total:.0f}%)", end="", flush=True)

            # Validate Zip Integrity
            with zipfile.ZipFile(save_path, 'r') as zf:
                if zf.testzip() is None:
                    print(f"\n✅ Downloaded & Verified ({save_path.stat().st_size/(1024*1024):.1f} MB)")
                    return True
        except Exception as e:
            print(f"\n⚠️ Download attempt {attempts}/10 issue: {e}")
            time.sleep(3)
            
    print(f"❌ Failed to download valid zip after {attempts} attempts")
    return False

if not download_books_with_resume(download_url, BOOKS_ZIP):
    sys.exit(1)

# ============ STEP 2: EXTRACT ============
shutil.rmtree(WORK_DIR, ignore_errors=True)
shutil.rmtree(RAG_OUTPUT, ignore_errors=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)
RAG_OUTPUT.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(BOOKS_ZIP, 'r') as zf:
    zf.extractall(WORK_DIR)
BOOKS_ZIP.unlink()

pdf_files = sorted(WORK_DIR.glob("*.pdf"))
print(f"📚 {len(pdf_files)} PDFs to process")

if not pdf_files:
    sys.exit(1)

# ============ STEP 3: INSTALL & LOAD ============
try:
    import faiss
    import pymupdf
    from sentence_transformers import SentenceTransformer
except ImportError:
    os.system("pip install -q faiss-cpu pymupdf sentence-transformers accelerate transformers torch")
    import faiss
    import pymupdf
    from sentence_transformers import SentenceTransformer

print("Loading models...")
embedder = SentenceTransformer("intfloat/multilingual-e5-large", device="cuda")

from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")
llm = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct", torch_dtype=torch.float16, device_map="auto")
print("✅ Models loaded!")

# ============ FUNCTIONS ============
def extract_metadata(text):
    prompt = f"""قم بتحليل النص التالي المستخرج من كتاب دراسي مصري واستخرج المعلومات التالية في شكل JSON فقط.
النص:
{text[:2000]}

يجب أن يكون الرد JSON يحتوي على المفاتيح التالية:
"stage": (مثلاً "1_ثانوي", "2_ثانوي", "3_ثانوي")
"track": (مثلاً "علمي", "أدبي", "عام", "أزهري_علمي", "أزهري_أدبي", "أزهري_عام")
"subject_type": (مثلاً "ثانية لغة", "تخصص", "مشتركة")
"subject": (اسم المادة، مثلاً "اللغة العربية", "فيزياء", "قرآن كريم")

JSON:
"""
    inputs = tokenizer(prompt, return_tensors="pt").to(llm.device)
    outputs = llm.generate(**inputs, max_new_tokens=150)
    response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    try:
        clean_resp = response.strip()
        if "```json" in clean_resp:
            clean_resp = clean_resp.split("```json")[1].split("```")[0]
        elif "```" in clean_resp:
            clean_resp = clean_resp.split("```")[1].split("```")[0]
        s_idx = clean_resp.find("{")
        e_idx = clean_resp.rfind("}")
        if s_idx != -1 and e_idx != -1:
            clean_resp = clean_resp[s_idx:e_idx+1]
        return json.loads(clean_resp.strip())
    except:
        return {"stage": "unknown", "track": "unknown", "subject_type": "unknown", "subject": "unknown"}

# Name Sanitizer Helper
SUBJECT_MAP = {
    "فيزياء": "physics", "physics": "physics", "كيمياء": "chemistry", "chemistry": "chemistry",
    "احياء": "biology", "أحياء": "biology", "biology": "biology", "جيولوجيا": "geology", "geology": "geology",
    "علوم": "science", "science": "science", "رياضيات": "math", "رياضة": "math", "mathematics": "math", "math": "math",
    "احصاء": "statistics", "إحصاء": "statistics", "statistics": "statistics", "تطبيقة": "applied_math",
    "تاريخ": "history", "history": "history", "جغرافيا": "geography", "geography": "geography",
    "فلسفة": "philosophy", "philosophy": "philosophy", "منطق": "logic", "logic": "logic",
    "علم نفس": "psychology", "psychology": "psychology", "sociology": "sociology",
    "دين": "religion", "christian": "christian_religion", "اسلامي": "islamic_religion",
    "فقه": "fiqh", "حديث": "hadith", "تفسير": "tafseer", "توحيد": "tawheed", "شافعى": "fiqh_shafii",
    "الماني": "german", "deutsch": "german", "ايطالي": "italian", "italian": "italian",
    "اسباني": "spanish", "spanish": "spanish", "فرنساوي": "french", "french": "french",
    "انجليزي": "english", "english": "english", "عربي": "arabic", "arabic": "arabic", "naho": "arabic_naho", "قصة": "arabic_story"
}

def get_readable_book_name(pdf_name, meta):
    raw = (pdf_name + " " + str(meta.get("stage","")) + " " + str(meta.get("subject",""))).lower()
    stage = "sec1"
    if any(k in raw for k in ["3ث", "sec3", "3_sec", "3sec", "3_ثانوي"]): stage = "sec3"
    elif any(k in raw for k in ["2ث", "sec2", "2_sec", "2sec", "2_ثانوي"]): stage = "sec2"
    elif any(k in raw for k in ["1ث", "sec1", "1_sec", "1sec", "1_ثانوي"]): stage = "sec1"

    subj = "general"
    for key, val in SUBJECT_MAP.items():
        if key in raw:
            subj = val
            break
    
    return f"{subj}_{stage}"

def process_book(pdf_path, book_id):
    try:
        doc = pymupdf.open(pdf_path)
        sample = "".join(doc[i].get_text() + "\n" for i in range(min(5, len(doc))))
        
        if not sample.strip():
            doc.close()
            return "skipped"
        
        meta = extract_metadata(sample)
        folder_name = get_readable_book_name(pdf_path.name, meta)
        book_dir = RAG_OUTPUT / meta.get("stage","unknown") / meta.get("track","unknown") / meta.get("subject_type","unknown") / folder_name
        book_dir.mkdir(parents=True, exist_ok=True)
        
        with open(book_dir / "config.yaml", "w", encoding="utf-8") as f:
            for k, v in meta.items():
                f.write(f"{k}: {v}\n")
        
        full_text = "".join(p.get_text() + "\n" for p in doc)
        doc.close()
        
        chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 1000) if full_text[i:i+1000].strip()]
        if not chunks:
            return "skipped"
        
        with open(book_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps({"text": c}, ensure_ascii=False) + "\n")
        
        embeddings = embedder.encode(chunks, normalize_embeddings=True, show_progress_bar=False)
        idx = faiss.IndexFlatIP(embeddings.shape[1])
        idx.add(embeddings)
        faiss.write_index(idx, str(book_dir / "index.faiss"))
        
        return "success"
    except Exception as e:
        return f"error: {e}"

# ============ PROCESS ============
total = len(pdf_files)
success = skip = 0
errors = []
all_ids = []

for i, pdf in enumerate(pdf_files):
    bid = pdf.stem
    all_ids.append(bid)
    print(f"\n[{i+1}/{total}] {pdf.name}")
    
    r = process_book(pdf, bid)
    if r == "success":
        success += 1
        print(f"  ✅")
    elif r == "skipped":
        skip += 1
        print(f"  ⏭ scanned/empty")
    else:
        errors.append(bid)
        print(f"  ❌ {r}")
    
    pdf.unlink(missing_ok=True)

print(f"\n{'='*50}")
print(f"  Done! ✅{success} ⏭{skip} ❌{len(errors)}")
print(f"{'='*50}")

# ============ STEP 4: ZIP & UPLOAD RESULTS ============
print("Zipping results...")
with zipfile.ZipFile(RESULTS_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, _, files in os.walk(RAG_OUTPUT):
        for file in files:
            fp = os.path.join(root, file)
            zf.write(fp, os.path.relpath(fp, RAG_OUTPUT))

sz = RESULTS_ZIP.stat().st_size
print(f"Results: {sz/(1024*1024):.1f} MB")

# Upload results back to server
print(f"Uploading results to {SERVER_URL}/submit/{WORKER_ID}...")
try:
    with open(RESULTS_ZIP, 'rb') as f:
        data = f.read()
    req = urllib.request.Request(
        f"{SERVER_URL}/submit/{WORKER_ID}",
        data=data,
        method="POST",
        headers={**HEADERS, 'Content-Type': 'application/octet-stream', 'Content-Length': str(len(data))}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        print(f"  Server response: {resp.read().decode()}")
    print("✅ Results uploaded!")
except Exception as e:
    print(f"❌ Upload failed: {e}")
    print("Results are saved locally at /content/results.zip")

# Send completed IDs
print("Sending completed book IDs...")
try:
    id_data = json.dumps(all_ids).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/complete/{WORKER_ID}",
        data=id_data,
        method="POST",
        headers={**HEADERS, 'Content-Type': 'application/json'}
    )
    urllib.request.urlopen(req, timeout=60)
    print("✅ IDs sent!")
except Exception as e:
    print(f"⚠ Failed to send IDs: {e}")

print("\n🎉 Worker #{} FINISHED!".format(WORKER_ID))
