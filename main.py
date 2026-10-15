import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import bcrypt
import jwt
from faster_whisper import WhisperModel
from fastapi import (
    FastAPI, Depends, HTTPException, UploadFile, File,
    Form, Header, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
from evaluator import evaluate_reading, evaluate_wpm_mode

# Evaluation criteria per grade (matched by source_id prefix)
GRADE_CRITERIA = {
    "a_":  {"wpm_target":  45, "w_acc": 0.85, "w_spd": 0.15, "w_pun": 0.00},
    "b_":  {"wpm_target":  60, "w_acc": 0.75, "w_spd": 0.20, "w_pun": 0.05},
    "g_":  {"wpm_target":  75, "w_acc": 0.65, "w_spd": 0.25, "w_pun": 0.10},
    "d_":  {"wpm_target":  85, "w_acc": 0.60, "w_spd": 0.30, "w_pun": 0.10},
    "e_":  {"wpm_target":  95, "w_acc": 0.55, "w_spd": 0.35, "w_pun": 0.10},
    "st_": {"wpm_target": 110, "w_acc": 0.55, "w_spd": 0.35, "w_pun": 0.10},
}
_DEFAULT_CRITERIA = {"wpm_target": 80, "w_acc": 0.60, "w_spd": 0.30, "w_pun": 0.10}

# ── Config ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "change-me-in-production-32chars!!")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 1 week

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny/base/small/medium

# ── Startup ─────────────────────────────────────────────────────────────────
print(f"[startup] Φόρτωση Whisper model '{WHISPER_MODEL}'...")
_whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
print("[startup] Whisper έτοιμο.")

db.init_db()

app = FastAPI(title="Reading Practice", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Source metadata (flat, used by existing text endpoints)
SOURCES = {
    "a_dimotikou":   "Γλώσσα Α' Δημοτικού — Τεύχος Α",
    "a_dimotikou_b": "Γλώσσα Α' Δημοτικού — Τεύχος Β",
    "b_dimotikou":   "Γλώσσα Β' Δημοτικού — Τεύχος Α",
    "b_dimotikou_b": "Γλώσσα Β' Δημοτικού — Τεύχος Β",
    "b_dimotikou_g": "Γλώσσα Β' Δημοτικού — Τεύχος Γ",
    "g_dimotikou":   "Γλώσσα Γ' Δημοτικού — Τεύχος Α",
    "g_dimotikou_b": "Γλώσσα Γ' Δημοτικού — Τεύχος Β",
    "g_dimotikou_g": "Γλώσσα Γ' Δημοτικού — Τεύχος Γ",
    "d_dimotikou":   "Γλώσσα Δ' Δημοτικού — Τεύχος Α",
    "d_dimotikou_b": "Γλώσσα Δ' Δημοτικού — Τεύχος Β",
    "d_dimotikou_g": "Γλώσσα Δ' Δημοτικού — Τεύχος Γ",
    "e_dimotikou":    "Γλώσσα Ε' Δημοτικού — Τεύχος Α",
    "e_dimotikou_b":  "Γλώσσα Ε' Δημοτικού — Τεύχος Β",
    "e_dimotikou_g":  "Γλώσσα Ε' Δημοτικού — Τεύχος Γ",
    "st_dimotikou":   "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Α",
    "st_dimotikou_b": "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Β",
    "st_dimotikou_g": "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Γ",
}

# Class hierarchy for the new UI navigation
CLASS_HIERARCHY = [
    {
        "id": "a",
        "name": "Α' Δημοτικού",
        "emoji": "🌱",
        "color": "#22c55e",
        "volumes": [
            {"id": "a_dimotikou",   "name": "Τεύχος Α"},
            {"id": "a_dimotikou_b", "name": "Τεύχος Β"},
        ],
    },
    {
        "id": "b",
        "name": "Β' Δημοτικού",
        "emoji": "📗",
        "color": "#10b981",
        "volumes": [
            {"id": "b_dimotikou",   "name": "Τεύχος Α"},
            {"id": "b_dimotikou_b", "name": "Τεύχος Β"},
            {"id": "b_dimotikou_g", "name": "Τεύχος Γ"},
        ],
    },
    {
        "id": "g",
        "name": "Γ' Δημοτικού",
        "emoji": "📘",
        "color": "#6366f1",
        "volumes": [
            {"id": "g_dimotikou",   "name": "Τεύχος Α"},
            {"id": "g_dimotikou_b", "name": "Τεύχος Β"},
            {"id": "g_dimotikou_g", "name": "Τεύχος Γ"},
        ],
    },
    {
        "id": "d",
        "name": "Δ' Δημοτικού",
        "emoji": "📙",
        "color": "#f59e0b",
        "volumes": [
            {"id": "d_dimotikou",   "name": "Τεύχος Α"},
            {"id": "d_dimotikou_b", "name": "Τεύχος Β"},
            {"id": "d_dimotikou_g", "name": "Τεύχος Γ"},
        ],
    },
    {
        "id": "e",
        "name": "Ε' Δημοτικού",
        "emoji": "📕",
        "color": "#ef4444",
        "volumes": [
            {"id": "e_dimotikou",   "name": "Τεύχος Α"},
            {"id": "e_dimotikou_b", "name": "Τεύχος Β"},
            {"id": "e_dimotikou_g", "name": "Τεύχος Γ"},
        ],
    },
    {
        "id": "st",
        "name": "ΣΤ' Δημοτικού",
        "emoji": "📓",
        "color": "#8b5cf6",
        "volumes": [
            {"id": "st_dimotikou",   "name": "Τεύχος Α"},
            {"id": "st_dimotikou_b", "name": "Τεύχος Β"},
            {"id": "st_dimotikou_g", "name": "Τεύχος Γ"},
        ],
    },
]

# ── Auth helpers ─────────────────────────────────────────────────────────────
def _make_token(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Η συνεδρία έληξε. Παρακαλώ συνδεθείτε ξανά.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Μη έγκυρο token.")


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Απαιτείται σύνδεση.")
    payload = _decode_token(authorization.split(" ", 1)[1])
    user = db.get_user_by_username(payload["username"])
    if not user:
        raise HTTPException(status_code=401, detail="Χρήστης δεν βρέθηκε.")
    return user


# ── Auth routes ──────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register")
def register(body: RegisterRequest):
    if len(body.username) < 3:
        raise HTTPException(400, "Το όνομα χρήστη πρέπει να έχει τουλάχιστον 3 χαρακτήρες.")
    if len(body.password) < 4:
        raise HTTPException(400, "Ο κωδικός πρέπει να έχει τουλάχιστον 4 χαρακτήρες.")
    if db.get_user_by_username(body.username):
        raise HTTPException(400, "Το όνομα χρήστη υπάρχει ήδη.")
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = db.create_user(body.username, pw_hash, body.full_name)
    token = _make_token(user["id"], user["username"])
    return {"token": token, "username": user["username"], "full_name": user["full_name"]}


@app.post("/api/auth/login")
def login(body: LoginRequest):
    user = db.get_user_by_username(body.username)
    if not user or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Λάθος όνομα χρήστη ή κωδικός.")
    token = _make_token(user["id"], user["username"])
    return {"token": token, "username": user["username"], "full_name": user["full_name"]}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"username": user["username"], "full_name": user["full_name"]}


# ── Class hierarchy ──────────────────────────────────────────────────────────
@app.get("/api/classes")
def list_classes(_: dict = Depends(current_user)):
    return CLASS_HIERARCHY


@app.get("/api/stats/texts")
def text_stats(source_id: str, user: dict = Depends(current_user)):
    if source_id not in SOURCES:
        raise HTTPException(404, "Πηγή δεν βρέθηκε.")
    return db.get_text_stats(user["id"], source_id)


# ── Text routes ───────────────────────────────────────────────────────────────
@app.get("/api/sources")
def list_sources(_: dict = Depends(current_user)):
    return [{"id": k, "name": v} for k, v in SOURCES.items()]


@app.get("/api/texts/{source_id}")
def list_texts(source_id: str, _: dict = Depends(current_user)):
    if source_id not in SOURCES:
        raise HTTPException(404, "Πηγή δεν βρέθηκε.")
    texts = db.get_texts_by_source(source_id)
    return {"source_id": source_id, "source_name": SOURCES[source_id], "texts": texts}


@app.get("/api/texts/{source_id}/{text_id}")
def get_text(source_id: str, text_id: str, _: dict = Depends(current_user)):
    text = db.get_text(text_id)
    if not text or text["source_id"] != source_id:
        raise HTTPException(404, "Κείμενο δεν βρέθηκε.")
    return text


class AddTextRequest(BaseModel):
    source_id: str
    title: str
    content: str
    page_number: int = 0


class UpdateTextRequest(BaseModel):
    title: str
    content: str


@app.put("/api/texts/{text_id}")
def update_text(text_id: str, body: UpdateTextRequest, _: dict = Depends(current_user)):
    if not body.title.strip() or not body.content.strip():
        raise HTTPException(400, "Τίτλος και κείμενο δεν μπορούν να είναι κενά.")
    text = db.get_text(text_id)
    if not text:
        raise HTTPException(404, "Κείμενο δεν βρέθηκε.")
    db.update_text(text_id, body.title.strip(), body.content.strip())
    return {"message": "Το κείμενο ενημερώθηκε."}


@app.post("/api/texts/add")
def add_text(body: AddTextRequest, _: dict = Depends(current_user)):
    if body.source_id not in SOURCES:
        raise HTTPException(400, "Άγνωστη πηγή.")
    # Generate unique id
    existing = db.get_texts_by_source(body.source_id)
    next_num = len(existing) + 1
    text_id = f"{body.source_id}_{next_num:04d}"
    db.upsert_text(text_id, body.source_id, body.title, body.content, body.page_number)
    return {"id": text_id, "message": "Το κείμενο προστέθηκε."}


# ── Transcription & evaluation ────────────────────────────────────────────────
@app.post("/api/evaluate")
async def evaluate(
    audio: UploadFile = File(...),
    text_id: str = Form(...),
    duration_sec: float = Form(...),
    mode: str = Form("normal"),        # "normal" | "wpm"
    user: dict = Depends(current_user),
):
    text_row = db.get_text(text_id)
    if not text_row:
        raise HTTPException(404, "Κείμενο δεν βρέθηκε.")

    # Save audio to temp file for Whisper
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        segments, _ = _whisper_model.transcribe(
            tmp_path,
            language="el",
            task="transcribe",
            beam_size=5,
        )
        transcribed = " ".join(seg.text for seg in segments).strip()
    finally:
        os.unlink(tmp_path)

    original = text_row["content"]
    src = text_row["source_id"]
    crit = next((v for k, v in GRADE_CRITERIA.items() if src.startswith(k)), _DEFAULT_CRITERIA)
    if mode == "wpm":
        scores = evaluate_wpm_mode(original, transcribed, duration_sec)
    else:
        scores = evaluate_reading(
            original, transcribed, duration_sec,
            wpm_target=crit["wpm_target"],
            w_acc=crit["w_acc"],
            w_spd=crit["w_spd"],
            w_pun=crit["w_pun"],
        )

    session_id = db.save_session({
        "user_id": user["id"],
        "source_id": text_row["source_id"],
        "text_id": text_id,
        "text_title": text_row["title"],
        "original_text": original,
        "transcribed_text": transcribed,
        "mode": mode,
        "word_accuracy": scores.get("word_accuracy"),
        "wpm": scores.get("wpm"),
        "punctuation_score": scores.get("punctuation_score"),
        "overall_score": scores.get("overall_score"),
        "duration_sec": duration_sec,
        "correct_words": scores.get("correct_words"),
        "total_words": scores.get("total_words"),
    })

    return {
        "session_id": session_id,
        "transcribed": transcribed,
        **scores,
    }


# ── History routes ────────────────────────────────────────────────────────────
@app.get("/api/history")
def history(user: dict = Depends(current_user)):
    return db.get_user_sessions(user["id"])


@app.get("/api/history/{session_id}")
def session_detail(session_id: int, user: dict = Depends(current_user)):
    s = db.get_session(session_id, user["id"])
    if not s:
        raise HTTPException(404, "Συνεδρία δεν βρέθηκε.")
    return s


# ── SPA fallback ──────────────────────────────────────────────────────────────
@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    return FileResponse(STATIC_DIR / "index.html")
