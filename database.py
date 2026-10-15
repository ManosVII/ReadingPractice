import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "reading.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name   TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            source_id       TEXT NOT NULL,
            text_id         TEXT NOT NULL,
            text_title      TEXT,
            original_text   TEXT,
            transcribed_text TEXT,
            mode            TEXT NOT NULL DEFAULT 'normal',
            word_accuracy   REAL,
            wpm             REAL,
            punctuation_score REAL,
            overall_score   REAL,
            duration_sec    REAL,
            correct_words   INTEGER,
            total_words     INTEGER,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS texts (
            id          TEXT PRIMARY KEY,
            source_id   TEXT NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            word_count  INTEGER,
            page_number INTEGER,
            chapter     TEXT
        );
    """)
    conn.commit()
    conn.close()


def get_user_by_username(username: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, full_name: str):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name) VALUES (?, ?, ?)",
            (username, password_hash, full_name)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_texts_by_source(source_id: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, source_id, title, word_count, page_number, chapter FROM texts WHERE source_id = ? ORDER BY page_number",
        (source_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_text(text_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM texts WHERE id = ?", (text_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_session(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO sessions
          (user_id, source_id, text_id, text_title, original_text, transcribed_text,
           mode, word_accuracy, wpm, punctuation_score, overall_score,
           duration_sec, correct_words, total_words)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["user_id"], data["source_id"], data["text_id"], data.get("text_title"),
        data.get("original_text"), data.get("transcribed_text"),
        data.get("mode", "normal"),
        data.get("word_accuracy"), data.get("wpm"),
        data.get("punctuation_score"), data.get("overall_score"),
        data.get("duration_sec"), data.get("correct_words"), data.get("total_words")
    ))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    return session_id


def update_text(text_id: str, title: str, content: str):
    word_count = len(content.split())
    conn = get_conn()
    conn.execute(
        "UPDATE texts SET title=?, content=?, word_count=? WHERE id=?",
        (title, content, word_count, text_id)
    )
    conn.commit()
    conn.close()


def get_text_stats(user_id: int, source_id: str) -> dict:
    conn = get_conn()
    rows = conn.execute("""
        SELECT text_id,
               COUNT(*)          AS attempts,
               MAX(overall_score) AS best_score,
               MAX(created_at)   AS last_attempt
        FROM sessions
        WHERE user_id = ? AND source_id = ?
        GROUP BY text_id
    """, (user_id, source_id)).fetchall()
    conn.close()
    return {r["text_id"]: dict(r) for r in rows}


def get_user_sessions(user_id: int, limit: int = 50):
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, source_id, text_title, mode, word_accuracy, wpm,
               overall_score, correct_words, total_words, created_at
        FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: int, user_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_text(text_id: str, source_id: str, title: str, content: str, page: int, chapter: str = None):
    word_count = len(content.split())
    conn = get_conn()
    # Add chapter column if it doesn't exist yet (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE texts ADD COLUMN chapter TEXT")
        conn.commit()
    except Exception:
        pass
    conn.execute("""
        INSERT INTO texts (id, source_id, title, content, word_count, page_number, chapter)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title, content=excluded.content,
          word_count=excluded.word_count, page_number=excluded.page_number,
          chapter=excluded.chapter
    """, (text_id, source_id, title, content, word_count, page, chapter))
    conn.commit()
    conn.close()
