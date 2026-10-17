
import os
import uuid
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from groq import Groq, APIStatusError, APIConnectionError

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
logging.basicConfig(level=logging.INFO)

DB = Path(__file__).resolve().parent / "nam_smart.db"
SYSTEM_PROMPT = r"""
Bạn là Nam Smart, trợ lý học tập bằng tiếng Việt.
Giải thích rõ ràng, từng bước khi giải bài tập.
Dùng Markdown để trình bày.
Công thức toán trong dòng dùng \( ... \), riêng dòng dùng \[ ... \].
Không dùng dấu $ để bao công thức toán.
"""


def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT, role TEXT, content TEXT, image TEXT,
            created_at TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id))""")


def ai_answer(history):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Thiếu GROQ_API_KEY trong Render.")

    has_image = any(
        isinstance(m.get("content"), list) for m in history
    )
    model = os.getenv(
        "GROQ_VISION_MODEL" if has_image else "GROQ_TEXT_MODEL",
        "qwen/qwen3.8-27b" if has_image else "openai/gpt-oss-120b"
    )

    try:
        client = Groq(api_key=key, timeout=60, max_retries=1)
        result = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history],
            temperature=0.7,
            max_tokens=2000
        )
        return result.choices[0].message.content or "AI chưa có câu trả lời."

    except APIStatusError as e:
        detail = e.response.text
        app.logger.error("Groq HTTP %s | model=%s | %s",
                         e.status_code, model, detail)
        raise RuntimeError(
            f"Groq HTTP {e.status_code}, model {model}: {detail}"
        ) from e
    except APIConnectionError as e:
        raise RuntimeError(f"Không kết nối được Groq: {e}") from e


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/conversations")
def conversations():
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/conversations/<cid>")
def conversation(cid):
    with connect() as c:
        conv = c.execute(
            "SELECT * FROM conversations WHERE id=?", (cid,)
        ).fetchone()
        if not conv:
            return jsonify(error="Không tìm thấy hội thoại"), 404
        rows = c.execute(
            "SELECT role,content,image,created_at FROM messages "
            "WHERE conversation_id=? ORDER BY id", (cid,)
        ).fetchall()
    return jsonify({**dict(conv), "messages": [dict(r) for r in rows]})


@app.route("/api/conversations/<cid>", methods=["DELETE"])
def delete_conversation(cid):
    with connect() as c:
        c.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))
    return jsonify(ok=True)


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True) or {}
    text = body.get("message", "")
    image = body.get("image")
    cid = body.get("conversation_id") or str(uuid.uuid4())

    if not isinstance(text, str) or not isinstance(cid, str):
        return jsonify(error="Dữ liệu không hợp lệ"), 400
    text = text.strip()
    if not text and not image:
        return jsonify(error="Hãy nhập câu hỏi hoặc gửi ảnh"), 400
    if image and (
        not isinstance(image, str) or
        not image.startswith(("data:image/jpeg;base64,",
                              "data:image/png;base64,",
                              "data:image/webp;base64,"))
    ):
        return jsonify(error="Ảnh không hợp lệ"), 400

    now = datetime.now(timezone.utc).isoformat()
    content = text or "Hãy phân tích ảnh này."

    with connect() as c:
        exists = c.execute(
            "SELECT id FROM conversations WHERE id=?", (cid,)
        ).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO conversations VALUES(?,?,?,?)",
                (cid, content[:60], now, now)
            )
        rows = c.execute(
            "SELECT role,content,image FROM messages "
            "WHERE conversation_id=? ORDER BY id", (cid,)
        ).fetchall()

        history = []
        for r in rows:
            if r["image"]:
                history.append({"role": r["role"], "content": [
                    {"type": "text", "text": r["content"]},
                    {"type": "image_url", "image_url": {"url": r["image"]}}
                ]})
            else:
                history.append({"role": r["role"], "content": r["content"]})

        current = [{"type": "text", "text": content},
                   {"type": "image_url", "image_url": {"url": image}}] if image else content
        history.append({"role": "user", "content": current})
        c.execute(
            "INSERT INTO messages(conversation_id,role,content,image,created_at) "
            "VALUES(?,?,?,?,?)", (cid, "user", content, image, now)
        )

    try:
        answer = ai_answer(history)
    except RuntimeError as e:
        return jsonify(error=str(e), conversation_id=cid), 502

    with connect() as c:
        c.execute(
            "INSERT INTO messages(conversation_id,role,content,created_at) "
            "VALUES(?,?,?,?)", (cid, "assistant", answer, now)
        )
        c.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now, cid)
        )
    return jsonify(answer=answer, conversation_id=cid)


@app.errorhandler(413)
def too_large(e):
    return jsonify(error="Ảnh hoặc dữ liệu vượt quá giới hạn tải lên"), 413


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
