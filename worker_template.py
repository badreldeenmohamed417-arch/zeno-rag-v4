import os
import shutil
import urllib.request
import urllib.parse
import json
import time
from pathlib import Path

# Fix colab asyncio loop error if run in colab notebook environment
import nest_asyncio
nest_asyncio.apply()

# Configuration
NGROK_URL = "https://naida-subnotochordal-incoherently.ngrok-free.dev"
RAG_STORAGE = Path("/content/rag_storage")

# Prepare directories
shutil.rmtree("/content/rag_storage", ignore_errors=True)
RAG_STORAGE.mkdir(parents=True, exist_ok=True)

# Install requirements if not present
try:
    import faiss
    import fitz
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Installing dependencies...")
    os.system("pip install -q faiss-cpu pymupdf sentence-transformers accelerate")
    import faiss
    import fitz
    from sentence_transformers import SentenceTransformer

# Load models (only once)
print("Loading models...")
embedder = SentenceTransformer("intfloat/multilingual-e5-large", device="cuda")

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch
    
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")
    llm = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-1.5B-Instruct",
        torch_dtype=torch.float16,
        device_map="auto"
    )
except ImportError:
    os.system("pip install -q transformers torch accelerate")
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")
    llm = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-1.5B-Instruct",
        torch_dtype=torch.float16,
        device_map="auto"
    )

def extract_metadata(text):
    prompt = f"""
قم بتحليل النص التالي المستخرج من كتاب دراسي مصري واستخرج المعلومات التالية في شكل JSON فقط.
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
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        return json.loads(response.strip())
    except:
        return {"stage": "unknown", "track": "unknown", "subject_type": "unknown", "subject": "unknown"}

def process_job():
    # 1. Fetch job
    print("Fetching next job...")
    req = urllib.request.Request(f"{NGROK_URL}/job", headers={'User-Agent': 'Mozilla/5.0', 'ngrok-skip-browser-warning': 'true'})
    try:
        with urllib.request.urlopen(req) as res:
            job_data = json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"Failed to connect to Master: {e}")
        time.sleep(10)
        return True # continue

    book_id = job_data.get("book_id")
    if not book_id:
        print("No jobs available! Master returned empty job.")
        return False # No more jobs, stop loop

    print(f"\n--- Assigned Job: {book_id} ---")
    
    # 2. Download PDF
    dl_url = f"{NGROK_URL}/download/{urllib.parse.quote(book_id)}"
    pdf_path = Path(f"/content/{book_id}.pdf")
    print("  Downloading...")
    req = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0', 'ngrok-skip-browser-warning': 'true'})
    with urllib.request.urlopen(req) as res, open(pdf_path, 'wb') as f:
        f.write(res.read())

    # 3. Process
    try:
        print("  Extracting text...")
        doc = fitz.open(pdf_path)
        text = ""
        for i in range(min(5, len(doc))):
            text += doc[i].get_text() + "\n"
            
        if not text.strip():
            print("  [Warning] Scanned book, skipping.")
            doc.close()
            pdf_path.unlink()
            # Send empty zip just to mark it done
            zip_path = Path(f"/content/{book_id}_result.zip")
            import zipfile
            with zipfile.ZipFile(zip_path, 'w') as zf:
                pass
            with open(zip_path, 'rb') as f:
                urllib.request.urlopen(urllib.request.Request(f"{NGROK_URL}/submit/{urllib.parse.quote(book_id)}", data=f.read(), method="POST"))
            zip_path.unlink()
            return True

        print("  Generating Metadata...")
        meta = extract_metadata(text)
        
        book_dir = RAG_STORAGE / meta.get("stage", "unknown") / meta.get("track", "unknown") / meta.get("subject_type", "unknown") / meta.get("subject", "unknown") / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        
        with open(book_dir / "config.yaml", "w", encoding="utf-8") as f:
            for k, v in meta.items():
                f.write(f"{k}: {v}\n")

        print("  Embedding...")
        chunks = []
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        doc.close()

        for i in range(0, len(full_text), 1000):
            chunk = full_text[i:i+1000]
            if chunk.strip():
                chunks.append(chunk)

        with open(book_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps({"text": c}, ensure_ascii=False) + "\n")

        embeddings = embedder.encode(chunks, normalize_embeddings=True)
        dim = embeddings.shape[1]
        idx = faiss.IndexFlatIP(dim)
        idx.add(embeddings)
        faiss.write_index(idx, str(book_dir / "index.faiss"))
        
        # 4. Zip the results
        print("  Zipping results...")
        zip_path = Path(f"/content/{book_id}_result.zip")
        import zipfile
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(RAG_STORAGE):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, RAG_STORAGE)
                    zf.write(file_path, arcname)

        # 5. POST to Master
        print("  Submitting to Master...")
        with open(zip_path, 'rb') as f:
            submit_req = urllib.request.Request(f"{NGROK_URL}/submit/{urllib.parse.quote(book_id)}", data=f.read(), method="POST")
            urllib.request.urlopen(submit_req)

        print(f"  [SUCCESS] Job {book_id} completed.")
        
        # Cleanup for next job
        shutil.rmtree(RAG_STORAGE)
        RAG_STORAGE.mkdir(parents=True, exist_ok=True)
        zip_path.unlink()
        pdf_path.unlink()
        
    except Exception as e:
        print(f"  [ERROR] {e}")
        
    return True

print("Worker initialized. Starting processing loop...")
while True:
    has_more = process_job()
    if not has_more:
        break
    time.sleep(2) # Small delay between jobs

print("Worker finished all available jobs.")
