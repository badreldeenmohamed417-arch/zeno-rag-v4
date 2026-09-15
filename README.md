# Zeno RAG V4 Server & Kotlin Mobile App 🚀

A centralized, automated server architecture and companion Android application for processing Egyptian curriculum PDFs, generating FAISS vector indexes, and managing RAG chunk workflows.

## 🌟 Key Features
- **Secret Protection**: Secured via `X-Server-Secret` authentication.
- **Link-Based Downloads & Uploads**:
  - `POST /api/start_job`: Automatically fetches PDFs from `source_link/download`.
  - `POST /api/trigger_upload`: Packs RAG results into a `.zip` and uploads to `target_link/upload`.
- **Human-Readable Directory Naming (`name_sanitizer.py`)**: Automatically categorizes RAG chunks into readable folder names (`arabic_sec1`, `physics_sec2`, `chemistry_sec3`, etc.).
- **Live Monitoring & Notifications**: Exposes `/api/status` and `/api/logs`, with real-time push alerts for `SUCCESS` and `ERROR` events.
- **Kotlin Android Monitor App (`ZenoApp`)**: Single-screen native Android app to monitor progress, trigger jobs, view logs, and receive notifications.

---

## 🛠️ Repository Structure
```
zeno_rag/
├── zeno_server.py           # Main REST Server (Port 8000)
├── name_sanitizer.py        # Readable Folder Naming Sanitizer
├── standalone_worker.py     # Colab/Kaggle GPU Worker script
├── launch_kaggle_workers.py # Automated Kaggle CLI worker launcher
├── start_server_and_ngrok.py# Local runner script (Server + Ngrok)
├── ZenoApp/                 # Native Kotlin Android Application
└── README.md
```

---

## 🚀 Running the Server
```bash
python3 zeno_server.py
```
- Listening Port: `8000`
- Default Secret Key: `zeno_secret_12345` (Configurable via `SERVER_SECRET` environment variable).

---

## 📱 Android App
Open `ZenoApp/` in Android Studio or compile using Gradle:
```bash
cd ZenoApp
./gradlew assembleDebug
```
Output APK location: `ZenoApp/app/build/outputs/apk/debug/app-debug.apk`
