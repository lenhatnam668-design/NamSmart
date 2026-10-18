
import os
import re
import uuid
import base64
import binascii
import sqlite3
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TEXT_MODEL = os.getenv(
    "GROQ_TEXT_MODEL", "openai/gpt-oss-120b"
).strip()
VISION_MODEL = os.getenv("GROQ_MODEL", "").strip()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DB_PATH = os.getenv("DATABASE_PATH", "nam_smart.db")

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

SYSTEM_PROMPT = r"""
Bạn là NamSmart, trợ lý học tập AI.

NGÔN NGỮ:
- Mặc định trả lời bằng tiếng Việt tự nhiên.
- Nếu người dùng hỏi hoàn toàn bằng tiếng Anh, hãy trả lời bằng tiếng Anh.
- Nếu người dùng yêu cầu ngôn ngữ cụ thể, hãy dùng ngôn ngữ đó.
- Nếu câu hỏi pha trộn ngôn ngữ, ưu tiên tiếng Việt.

CHẤT LƯỢNG:
- Trả lời rõ ràng, chính xác, phù hợp với học sinh.
- Giải bài tập theo từng bước khi cần thiết.
- Không tự bịa dữ kiện.
- Khi phân tích ảnh, chỉ kết luận dựa trên nội dung nhìn thấy.
- Với IELTS, đưa ra ví dụ tự nhiên và phù hợp trình độ.

TOÁN HỌC:
- Dùng LaTeX chuẩn.
- Công thức trong dòng viết bằng \( ... \).
- Công thức riêng dòng viết bằng \[ ... \].
- Không đặt công thức toán trong khối mã.
- Giải thích các bước biến đổi rõ ràng.
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                image TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id)
        """)


init_db()


def save_message(conversation_id, role, content, image=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, image, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            role,
            content,
            image,
            now_iso(),
        ))
        conn.execute("""
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
        """, (now_iso(), conversation_id))


def create_conversation(title):
    conversation_id = str(uuid.uuid4())
    timestamp = now_iso()

    with get_db() as conn:
        conn.execute("""
            INSERT INTO conversations
            (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (
            conversation_id,
            title[:80] or "Cuộc trò chuyện mới",
            timestamp,
            timestamp,
        ))

    return conversation_id


def valid_conversation(conversation_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

    return row is not None


def decode_image(image, mime):
    if not isinstance(image, str):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    # Trình duyệt hiện gửi Data URI từ FileReader.
    if image.startswith("data:"):
        try:
            header, image = image.split(",", 1)
        except ValueError:
            raise ValueError("Data URI ảnh không hợp lệ.")

        if ";base64" not in header.lower():
            raise ValueError("Ảnh phải được mã hóa base64.")

        actual_mime = header[5:].split(";")[0].lower()

        if actual_mime != mime:
            raise ValueError("Định dạng ảnh không khớp image_mime.")

    if mime not in ALLOWED_MIME:
        raise ValueError("Chỉ hỗ trợ ảnh JPEG, PNG hoặc WEBP.")

    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Dữ liệu ảnh base64 không hợp lệ.")

    if not raw:
        raise ValueError("Ảnh đang trống.")

    if len(raw) > 6 * 1024 * 1024:
        raise ValueError("Ảnh tối đa 6 MB.")

    return raw, image


def ask_groq(model, messages):
    if not API_KEY:
        return None, 500, {
            "error": {
                "message": "Chưa cấu hình GROQ_API_KEY trên Render."
            }
        }

    if not model:
        return None, 500, {
            "error": {
                "message": "Chưa cấu hình tên model."
            }
        }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "NamSmart/1.0",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }

    try:
        response = requests.post(
            GROQ_URL,
            headers=headers,
            json=payload,
            timeout=90,
        )

        try:
            data = response.json()
        except ValueError:
            data = {
                "error": {
                    "message": response.text[:1500]
                }
            }

        if not response.ok:
            app.logger.error(
                "Groq HTTP %s | model=%s | detail=%s",
                response.status_code,
                model,
                data,
            )
            return None, response.status_code, data

        answer = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        if not isinstance(answer, str) or not answer.strip():
            return None, 502, {
                "error": {
                    "message": "Groq trả về câu trả lời rỗng."
                }
            }

        return answer.strip(), None, None

    except requests.Timeout:
        return None, 504, {
            "error": {
                "message": "Groq phản hồi quá lâu. Hãy thử lại."
            }
        }

    except requests.RequestException as exc:
        app.logger.exception("Lỗi kết nối Groq")
        return None, 502, {
            "error": {
                "message": str(exc)
            }
        }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "NamSmart",
    })


# API lịch sử: app.js đang gọi /api/conversations
@app.get("/api/conversations")
def list_conversations():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
        """).fetchall()

    return jsonify([
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ])


@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    with get_db() as conn:
        conversation = conn.execute("""
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE id = ?
        """, (conversation_id,)).fetchone()

        if conversation is None:
            return jsonify({
                "error": "Không tìm thấy cuộc trò chuyện."
            }), 404

        rows = conn.execute("""
            SELECT role, content, image, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
        """, (conversation_id,)).fetchall()

    return jsonify({
        "id": conversation["id"],
        "title": conversation["title"],
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
        "messages": [
            {
                "role": row["role"],
                "content": row["content"],
                "image": row["image"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    })


@app.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    with get_db() as conn:
        conn.execute("BEGIN")
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        result = conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )

        if result.rowcount == 0:
            return jsonify({
                "error": "Không tìm thấy cuộc trò chuyện."
            }), 404

    return jsonify({"ok": True})


# API chat: giữ đúng đường dẫn /api/chat của app.js
@app.post("/api/chat")
def chat():
    if not API_KEY:
        return jsonify({
            "error": "Chưa cấu hình GROQ_API_KEY trên Render."
        }), 500

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({
            "error": "Dữ liệu gửi lên không hợp lệ."
        }), 400

    prompt = str(body.get("message") or "").strip()
    image = body.get("image")
    conversation_id = body.get("conversation_id")

    if not prompt and not image:
        return jsonify({
            "error": "Nhập câu hỏi hoặc chọn ảnh trước nhé."
        }), 400

    mime = "image/jpeg"
    image_for_ai = None
    image_for_history = None

    if image:
        # Đọc MIME từ Data URI do app.js gửi.
        if isinstance(image, str) and image.startswith("data:"):
            match = re.match(
                r"^data:(image/(?:jpeg|png|webp));base64,",
                image,
                flags=re.IGNORECASE,
            )
            if not match:
                return jsonify({
                    "error": "Ảnh phải là JPEG, PNG hoặc WEBP."
                }), 400
            mime = match.group(1).lower()

        try:
            raw, encoded = decode_image(image, mime)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        image_for_ai = (
            f"data:{mime};base64,{encoded}"
        )
        image_for_history = image_for_ai

    if conversation_id:
        conversation_id = str(conversation_id)

        if not valid_conversation(conversation_id):
            return jsonify({
                "error": "Cuộc trò chuyện không tồn tại. Hãy tạo cuộc trò chuyện mới."
            }), 404
    else:
        title = prompt or "Phân tích ảnh bài tập"
        conversation_id = create_conversation(title)

    # Lưu câu hỏi người dùng và ảnh để xem lại lịch sử.
    save_message(
        conversation_id,
        "user",
        prompt or "📷 Hãy đọc và giải bài trong ảnh này.",
        image_for_history,
    )

    # Lấy ngữ cảnh hội thoại gần nhất.
    with get_db() as conn:
        rows = conn.execute("""
            SELECT role, content, image
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 20
        """, (conversation_id,)).fetchall()

    rows = list(reversed(rows))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    for row in rows:
        role = row["role"]
        content = row["content"]
        saved_image = row["image"]

        if role == "user" and saved_image:
            user_content = [
                {
                    "type": "text",
                    "text": content or "Phân tích ảnh này.",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": saved_image},
                },
            ]
            messages.append({
                "role": "user",
                "content": user_content,
            })
        else:
            messages.append({
                "role": role,
                "content": content,
            })

    model = VISION_MODEL if image_for_ai else TEXT_MODEL

    if image_for_ai and not VISION_MODEL:
        return jsonify({
            "error": (
                "Chưa cấu hình GROQ_MODEL cho ảnh. "
                "Hãy chọn model vision đang được Groq hỗ trợ."
            ),
            "conversation_id": conversation_id,
        }), 500

    answer, status, detail = ask_groq(model, messages)

    if status:
        app.logger.error(
            "Chat failed | status=%s | model=%s | detail=%s",
            status,
            model,
            detail,
        )
        return jsonify({
            "error": f"Groq API báo lỗi HTTP {status}.",
            "status": status,
            "detail": detail,
            "model_used": model,
            "conversation_id": conversation_id,
        }), 502

    save_message(conversation_id, "assistant", answer)

    return jsonify({
        "answer": answer,
        "conversation_id": conversation_id,
        "model_used": model,
    })


@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "error": "Dữ liệu quá lớn. Hãy chọn ảnh nhỏ hơn."
    }), 413


@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "error": "Không tìm thấy đường dẫn API."
    }), 404


@app.errorhandler(500)
def server_error(_error):
    app.logger.exception("Lỗi máy chủ")
    return jsonify({
        "error": "Máy chủ gặp lỗi. Hãy kiểm tra Render Logs."
    }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
