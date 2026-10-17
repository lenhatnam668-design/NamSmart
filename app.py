"""Nam Smart: Flask app with persistent conversations and optional vision AI."""
import base64
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "nam_smart.db"
app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, image TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
        """)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_image(data):
    if not data:
        return None
    if not isinstance(data, str) or not data.startswith("data:image/") or ";base64," not in data:
        raise ValueError("Ảnh không đúng định dạng.")
    header, payload = data.split(",", 1)
    mime = header[5:].split(";", 1)[0]
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise ValueError("Chỉ hỗ trợ ảnh JPG, PNG, WEBP hoặc GIF.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")
    if len(raw) > 7 * 1024 * 1024:
        raise ValueError("Ảnh vượt quá 7 MB.")
    return data


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/conversations")
def conversations():
    with db() as conn:
        rows = conn.execute("SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    with db() as conn:
        conversation = conn.execute("SELECT id, title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conversation:
            return jsonify(error="Không tìm thấy cuộc trò chuyện."), 404
        messages = conn.execute("SELECT role, content, image FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()
    return jsonify(id=conversation["id"], title=conversation["title"], messages=[dict(m) for m in messages])


@app.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    with db() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    return jsonify(ok=True)


SYSTEM_PROMPT = """Bạn là Nam Smart, trợ lý học tập thân thiện bằng tiếng Việt. Giải thích rõ ràng, có bước giải và ưu tiên hướng dẫn để học sinh hiểu. Nếu người dùng gửi ảnh, hãy đọc nội dung trong ảnh rồi trả lời câu hỏi; nếu ảnh mờ, hãy nói rõ phần không đọc được, không đoán. Với toán học, luôn dùng LaTeX: công thức trong dòng đặt trong \\( ... \\), công thức riêng dòng đặt trong \\[ ... \\]. Ví dụ: \\[2x-1=0 \\Rightarrow 2x=1 \\Rightarrow x=\\dfrac{1}{2}\\]. Không dùng dấu $ làm ký hiệu toán. Không tiết lộ thông tin bí mật."""


def ai_answer(history):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY trên máy chủ. Hãy thêm khóa API để bật AI và nhận diện ảnh.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Thiếu thư viện openai. Hãy chạy: pip install -r requirements.txt") from exc
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-18:]:
        if item["role"] == "user" and item["image"]:
            content = [
                {"type": "text", "text": item["content"] or "Hãy đọc ảnh và giải thích nội dung/bài tập trong ảnh."},
                {"type": "image_url", "image_url": {"url": item["image"], "detail": "auto"}},
            ]
        else:
            content = item["content"]
        messages.append({"role": item["role"], "content": content})
    client = OpenAI(api_key=key, timeout=45.0)
    response = client.chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), messages=messages)
    return response.choices[0].message.content or "Mình chưa tạo được câu trả lời."


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("message") or "").strip()
    try:
        image = validate_image(data.get("image"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not prompt and not image:
        return jsonify(error="Hãy nhập câu hỏi hoặc chọn ảnh."), 400
    if len(prompt) > 12000:
        return jsonify(error="Câu hỏi quá dài."), 400
    conversation_id = str(data.get("conversation_id") or "")
    with db() as conn:
        existing = conn.execute("SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone() if conversation_id else None
        if not existing:
            conversation_id = str(uuid.uuid4())
            title = (prompt or "Câu hỏi từ hình ảnh")[:65]
            conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (conversation_id, title, now(), now()))
        history = [dict(m) for m in conn.execute("SELECT role, content, image FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)).fetchall()]
        history.append({"role": "user", "content": prompt, "image": image})
        conn.execute("INSERT INTO messages(conversation_id, role, content, image, created_at) VALUES (?, 'user', ?, ?, ?)", (conversation_id, prompt, image, now()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
    try:
        answer = ai_answer(history)
    except Exception as exc:
        # Keep user input saved, so they can retry after fixing API configuration.
        if isinstance(exc, RuntimeError):
            return jsonify(error=str(exc), conversation_id=conversation_id), 503
        app.logger.exception("AI request failed")
        return jsonify(error="Không gọi được dịch vụ AI. Kiểm tra API key, kết nối mạng hoặc hạn mức sử dụng.", conversation_id=conversation_id), 502
    with db() as conn:
        conn.execute("INSERT INTO messages(conversation_id, role, content, image, created_at) VALUES (?, 'assistant', ?, NULL, ?)", (conversation_id, answer, now()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id))
    return jsonify(answer=answer, conversation_id=conversation_id)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Ảnh hoặc yêu cầu quá lớn."), 413


init_db()
if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=int(os.getenv("PORT", "5000")))
