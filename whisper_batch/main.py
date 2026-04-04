import os
import json
import zipfile
import io
import threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
import aiofiles

# ─────────────────────────────────────────────
# PFADE
# ─────────────────────────────────────────────
BASE          = Path("/data")
AUDIO_DIR     = BASE / "audio"
TRANSCRIPTS   = BASE / "transcripts"
MODEL_CACHE   = BASE / "model_cache"
STATUS_FILE   = BASE / "status.json"

for d in [AUDIO_DIR, TRANSCRIPTS, MODEL_CACHE]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI()
_running = False

# ─────────────────────────────────────────────
# STATUS HELPERS
# ─────────────────────────────────────────────
def load_status():
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text())
    return {"state": "idle", "files": {}, "log": []}

def save_status(data):
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def log(data, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    data["log"].append(f"[{ts}] {msg}")
    data["log"] = data["log"][-200:]
    save_status(data)
    print(msg)

# ─────────────────────────────────────────────
# TRANSKRIPTIONS-WORKER (läuft im Background-Thread)
# ─────────────────────────────────────────────
def run_transcription():
    global _running
    _running = True

    status = load_status()
    status["state"] = "running"
    log(status, "🚀 Starte Whisper large-v3 — Pro-Modus (8 Threads, int8_float16)")
    log(status, "⏳ Modell wird geladen / aus Cache geholt (~3 GB, einmalig)...")

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            "large-v3",
            device="cpu",
            compute_type="int8_float16",  # Pro: bessere Qualität als reines int8
            cpu_threads=8,                 # nutzt Railway Pro vCPUs
            num_workers=2,                 # 2 Dateien parallel vorbereiten
            download_root=str(MODEL_CACHE)
        )
        log(status, "✅ Modell geladen — bereit")
    except Exception as e:
        status["state"] = "error"
        log(status, f"❌ Modell-Fehler: {e}")
        _running = False
        return

    extensions = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus", ".mp4"}
    audio_files = sorted([f for f in AUDIO_DIR.iterdir() if f.suffix.lower() in extensions])

    if not audio_files:
        status["state"] = "idle"
        log(status, "⚠️ Keine Audiodateien gefunden. Bitte erst hochladen.")
        _running = False
        return

    log(status, f"📁 {len(audio_files)} Audiodateien gefunden — starte Batch...")
    status = load_status()

    for i, audio_path in enumerate(audio_files, 1):
        fname    = audio_path.name
        out_path = TRANSCRIPTS / (audio_path.stem + ".md")

        # Bereits fertig → überspringen (Resume-Funktion)
        if out_path.exists():
            log(status, f"[{i}/{len(audio_files)}] ⏭  Übersprungen (fertig): {fname}")
            status["files"][fname] = "done"
            save_status(status)
            status = load_status()
            continue

        log(status, f"[{i}/{len(audio_files)}] 🎙  Transkribiere: {fname}")
        status["files"][fname] = "running"
        save_status(status)

        try:
            segments, info = model.transcribe(
                str(audio_path),
                language="de",
                beam_size=5,
                best_of=5,              # mehr Kandidaten → bessere Qualität
                patience=1.0,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    threshold=0.45
                ),
                word_timestamps=False   # auf True setzen für Wort-Timestamps
            )

            # Markdown-Output mit Zeitstempeln
            lines = [f"# {audio_path.stem}", ""]
            for seg in segments:
                mm  = int(seg.start // 60)
                ss  = int(seg.start % 60)
                ts  = f"[{mm:02d}:{ss:02d}]"
                lines.append(f"{ts} {seg.text.strip()}")

            full_text = "\n".join(lines)
            out_path.write_text(full_text, encoding="utf-8")

            status = load_status()
            status["files"][fname] = "done"
            log(status, f"[{i}/{len(audio_files)}] ✅ Fertig: {fname} ({len(full_text):,} Zeichen)")

        except Exception as e:
            status = load_status()
            status["files"][fname] = "error"
            log(status, f"[{i}/{len(audio_files)}] ❌ Fehler bei {fname}: {e}")

        status = load_status()

    status = load_status()
    done  = sum(1 for s in status["files"].values() if s == "done")
    error = sum(1 for s in status["files"].values() if s == "error")
    status["state"] = "done"
    log(status, f"🏁 Fertig! ✅ {done} erfolgreich | ❌ {error} Fehler")
    _running = False


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def ui():
    status    = load_status()
    state     = status.get("state", "idle")
    files     = status.get("files", {})
    done_cnt  = sum(1 for s in files.values() if s == "done")
    err_cnt   = sum(1 for s in files.values() if s == "error")
    run_cnt   = sum(1 for s in files.values() if s == "running")
    total_cnt = len(files)

    files_html = ""
    for fname, st in files.items():
        icon = {"done": "✅", "running": "🔄", "error": "❌"}.get(st, "⏳")
        files_html += f"<li>{icon} {fname}</li>"

    log_html = "<br>".join(status.get("log", [])[-40:]) or "Noch keine Aktivität."

    transcripts = sorted(TRANSCRIPTS.glob("*.md"))
    dl_html = "".join(
        f'<li><a href="/download/{t.name}" download>{t.name}</a></li>'
        for t in transcripts
    ) or "<li>Noch keine Transkripte</li>"

    btn_disabled = 'disabled style="opacity:.4;cursor:not-allowed"' if state == "running" else ""
    btn_label    = "⏳ Läuft..." if state == "running" else "▶️ Transkription starten"

    state_color = {"idle": "#888", "running": "#ffd166", "done": "#7fffb2", "error": "#ff6b6b"}.get(state, "#888")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Whisper Batch | ELBFABRIK</title>
<meta http-equiv="refresh" content="10">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Courier New", monospace;
    background: #0a0a0a;
    color: #d0d0d0;
    min-height: 100vh;
    padding: 40px 20px;
  }}
  .container {{ max-width: 860px; margin: 0 auto; }}

  h1 {{
    font-size: 22px;
    color: #7fffb2;
    letter-spacing: 2px;
    text-transform: uppercase;
    border-bottom: 1px solid #222;
    padding-bottom: 16px;
    margin-bottom: 32px;
  }}
  h2 {{
    font-size: 12px;
    color: #555;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin: 32px 0 12px;
  }}

  .stat-bar {{
    display: flex;
    gap: 24px;
    background: #111;
    border: 1px solid #1e1e1e;
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }}
  .stat {{ display: flex; flex-direction: column; gap: 2px; }}
  .stat-label {{ font-size: 10px; color: #444; letter-spacing: 2px; text-transform: uppercase; }}
  .stat-value {{ font-size: 20px; font-weight: bold; }}

  .log-box {{
    background: #080808;
    border: 1px solid #1a1a1a;
    border-radius: 6px;
    padding: 16px;
    font-size: 12px;
    line-height: 1.8;
    color: #7fffb2;
    max-height: 320px;
    overflow-y: auto;
  }}

  ul {{ list-style: none; }}
  li {{
    padding: 6px 0;
    border-bottom: 1px solid #141414;
    font-size: 13px;
  }}
  a {{ color: #7fffb2; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  .upload-area {{
    background: #0f0f0f;
    border: 1px dashed #2a2a2a;
    border-radius: 8px;
    padding: 20px;
  }}
  input[type=file] {{
    background: transparent;
    color: #aaa;
    font-size: 13px;
    width: 100%;
    cursor: pointer;
  }}

  .btn {{
    display: inline-block;
    margin-top: 12px;
    background: #7fffb2;
    color: #000;
    border: none;
    padding: 10px 24px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 13px;
    letter-spacing: 1px;
    cursor: pointer;
    text-transform: uppercase;
  }}
  .btn:hover {{ background: #5fffaa; }}
  .btn-start {{
    background: #7fffb2;
    font-size: 15px;
    padding: 14px 32px;
  }}

  .zip-link {{
    display: inline-block;
    margin-top: 16px;
    border: 1px solid #7fffb2;
    color: #7fffb2;
    padding: 10px 20px;
    border-radius: 4px;
    font-size: 13px;
    letter-spacing: 1px;
  }}
  .zip-link:hover {{ background: #7fffb2; color: #000; text-decoration: none; }}

  .footer {{ margin-top: 48px; font-size: 11px; color: #2a2a2a; text-align: center; }}
</style>
</head>
<body>
<div class="container">

  <h1>🎙 Whisper Batch — ELBFABRIK</h1>

  <!-- STAT BAR -->
  <div class="stat-bar">
    <div class="stat">
      <span class="stat-label">Status</span>
      <span class="stat-value" style="color:{state_color}">{state.upper()}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Gesamt</span>
      <span class="stat-value">{total_cnt}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Fertig</span>
      <span class="stat-value" style="color:#7fffb2">{done_cnt}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Läuft</span>
      <span class="stat-value" style="color:#ffd166">{run_cnt}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Fehler</span>
      <span class="stat-value" style="color:#ff6b6b">{err_cnt}</span>
    </div>
  </div>

  <!-- 1. UPLOAD -->
  <h2>01 — Audiodateien hochladen</h2>
  <div class="upload-area">
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="file" name="files" multiple accept="audio/*,.mp4,.m4a,.mp3,.wav,.ogg,.flac">
      <br>
      <button type="submit" class="btn">📤 Hochladen</button>
    </form>
  </div>

  <!-- 2. START -->
  <h2>02 — Transkription starten</h2>
  <form action="/start" method="post">
    <button type="submit" class="btn btn-start" {btn_disabled}>{btn_label}</button>
  </form>

  <!-- 3. LOG -->
  <h2>03 — Live-Log</h2>
  <div class="log-box">{log_html}</div>

  <!-- 4. DATEI-STATUS -->
  <h2>04 — Dateistatus</h2>
  <ul>{files_html or '<li style="color:#444">Noch keine Dateien hochgeladen</li>'}</ul>

  <!-- 5. DOWNLOAD -->
  <h2>05 — Transkripte herunterladen</h2>
  <ul>{dl_html}</ul>
  <a href="/download-all" class="zip-link">📦 Alle als ZIP herunterladen</a>

  <div class="footer">Seite aktualisiert alle 10 Sek automatisch · Railway Pro · Whisper large-v3</div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────
@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    saved = []
    for f in files:
        out = AUDIO_DIR / f.filename
        async with aiofiles.open(out, "wb") as buf:
            await buf.write(await f.read())
        saved.append(f.filename)

    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/" />')


@app.post("/start")
async def start():
    global _running
    if _running:
        return HTMLResponse('<meta http-equiv="refresh" content="0; url=/" />')
    thread = threading.Thread(target=run_transcription, daemon=True)
    thread.start()
    return HTMLResponse('<meta http-equiv="refresh" content="2; url=/" />')


@app.get("/status")
async def get_status():
    return JSONResponse(load_status())


@app.get("/download/{filename}")
async def download_file(filename: str):
    path = TRANSCRIPTS / filename
    if not path.exists():
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return FileResponse(path, filename=filename, media_type="text/markdown")


@app.get("/download-all")
async def download_all():
    buf = io.BytesIO()
    files = list(TRANSCRIPTS.glob("*.md"))
    if not files:
        return JSONResponse({"error": "Noch keine Transkripte"}, status_code=404)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=transkripte.zip"}
    )


@app.delete("/reset")
async def reset_audio():
    """Audiodateien löschen (nach erfolgreichem Job)"""
    deleted = []
    for f in AUDIO_DIR.iterdir():
        f.unlink()
        deleted.append(f.name)
    status = load_status()
    status["files"] = {}
    status["state"] = "idle"
    save_status(status)
    return JSONResponse({"deleted": deleted})
