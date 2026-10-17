
import os
import json
import uuid
import base64
import sqlite3
import logging

from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge


# ==================================================
# 1. CẤU HÌNH
# ==================================================

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "nam_smart.db"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TEXT_MODEL = os.getenv(
    "GROQ_TEXT_MODEL",
    "openai/gpt-oss-120b"
)

VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "qwen/qwen3.8-27b"
)

SYSTEM_PROMPT = r"""
Bạn là Nam Smart, trợ lý AI học tập thân thiện dành cho học sinh Việt Nam.

- Trả lời bằng tiếng Việt, dễ hiểu, chính xác.
- Giải bài tập theo từng bước khi cần thiết.
- Dùng Markdown để trình bày tiêu đề, danh sách và bảng.
- Khi nhận ảnh, đọc đề bài trong ảnh rồi giải thích.
- Nếu ảnh mờ hoặc thiếu dữ kiện, hãy hỏi lại.
- Không bịa thông tin khi không chắc chắn.
- Công thức toán trong dòng dùng \( ... \).
- Công thức riêng dòng dùng \[ ... \].
- Ví dụ: \(a^2+b^2=c^2\).
- Không dùng dấu $ để bao công thức toán.
"""


# ==================================================
# 2. DATABASE
# ==================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with db() as conn:
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
            ON messages(conversation_id, id)
        """)


# ==================================================
# 3. KIỂM TRA ẢNH
# ==================================================

def validate_image(image):
    if image is None or image == "":
        return None

    if not isinstance(image, str):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    prefixes = (
        "data:image/jpeg;base64,",
        "data:image/png;base64,",
        "data:image/webp;base64,",
        "data:image/gif;base64,",
    )

    prefix = next(
        (p for p in prefixes if image.startswith(p)),
        None
    )

    if prefix is None:
        raise ValueError(
            "Ảnh phải là JPEG, PNG, WEBP hoặc GIF."
        )

    try:
        raw = base64.b64decode(
            image[len(prefix):],
            validate=True
        )
    except Exception as exc:
        raise ValueError("Dữ liệu ảnh bị lỗi.") from exc

    if len(raw) > 7 * 1024 * 1024:
        raise ValueError("Ảnh không được vượt quá 7 MB.")

    return image


# ==================================================
# 4. GỌI GROQ API
# ==================================================

def ai_answer(history):
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "Thiếu GROQ_API_KEY. Hãy thêm API key trong "
            "Render > Environment."
        )

    has_image = any(
        isinstance(message.get("content"), list)
        and any(
            isinstance(part, dict)
            and part.get("type") == "image_url"
            for part in message["content"]
        )
        for message in history
    )

    model = VISION_MODEL if has_image else TEXT_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    req = Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    app.logger.info(
        "Gửi yêu cầu Groq: model=%s, image=%s",
        model,
        has_image
    )

    try:
        with urlopen(req, timeout=90) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        choices = result.get("choices", [])

        if not choices:
            raise RuntimeError(
                "Groq phản hồi nhưng không có câu trả lời."
            )

        answer = choices[0].get(
            "message", {}
        ).get("content")

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(
                "Groq trả về nội dung rỗng."
            )

        return answer.strip()

    except HTTPError as exc:
        # Giữ lại thông báo lỗi gốc từ Groq.
        raw_error = exc.read().decode(
            "utf-8", errors="replace"
        )

        try:
            parsed = json.loads(raw_error)
            error_obj = parsed.get("error", {})
            detail = error_obj.get("message", raw_error)
            error_code = error_obj.get("code", "")
            error_type = error_obj.get("type", "")
        except (json.JSONDecodeError, AttributeError):
            detail = raw_error
            error_code = ""
            error_type = ""

        app.logger.error(
            "Groq HTTP %s | model=%s | code=%s | type=%s | detail=%s",
            exc.code,
            model,
            error_code,
            error_type,
            detail
        )

        if exc.code == 401:
            message = (
                "Groq HTTP 401: API key không hợp lệ hoặc đã bị thu hồi. "
                "Kiểm tra GROQ_API_KEY trên Render."
            )
        elif exc.code == 403:
            message = (
                f"Groq HTTP 403 khi dùng model '{model}'. "
                f"Thông báo gốc: {detail}"
            )
        elif exc.code == 404:
            message = (
                f"Groq HTTP 404 với model '{model}'. "
                f"Thông báo gốc: {detail}"
            )
        elif exc.code == 429:
            message = (
                "Groq HTTP 429: đã chạm giới hạn yêu cầu hoặc hạn mức. "
                f"Thông báo gốc: {detail}"
            )
        else:
            message = (
                f"Groq HTTP {exc.code}, model '{model}'. "
                f"Thông báo gốc: {detail}"
            )

        raise RuntimeError(message) from exc

    except URLError as exc:
        app.logger.exception("Không kết nối được Groq")
        raise RuntimeError(
            f"Không kết nối được Groq API: {exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise RuntimeError(
            "Groq phản hồi quá lâu. Hãy thử lại."
        ) from exc


# ==================================================
# 5. TRANG CHỦ
# ==================================================

@app.route("/")
def index():
    return render_template("index.html")


# ==================================================
# 6. DANH SÁCH CUỘC TRÒ CHUYỆN
# ==================================================

@app.route("/api/conversations", methods=["GET"])
def get_conversations():
    with db() as conn:
        rows = conn.execute("""
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


# ==================================================
# 7. LẤY MỘT CUỘC TRÒ CHUYỆN
# ==================================================

@app.route("/api/conversations/<conversation_id>", methods=["GET"])
def get_conversation(conversation_id):
    with db() as conn:
        conversation = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

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
        **dict(conversation),
        "messages": [dict(row) for row in rows]
    })


# ==================================================
# 8. XÓA CUỘC TRÒ CHUYỆN
# ==================================================

@app.route(
    "/api/conversations/<conversation_id>",
    methods=["DELETE"]
)
def delete_conversation(conversation_id):
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if existing is None:
            return jsonify({
                "error": "Không tìm thấy cuộc trò chuyện."
            }), 404

        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,)
        )

        conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,)
        )

    return jsonify({"ok": True})


# ==================================================
# 9. GỬI CÂU HỎI
# ==================================================

@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({
            "error": "Dữ liệu gửi lên không hợp lệ."
        }), 400

    message = body.get("message", "")
    conversation_id = body.get("conversation_id")
    image = body.get("image")

    if not isinstance(message, str):
        return jsonify({
            "error": "Nội dung tin nhắn không hợp lệ."
        }), 400

    message = message.strip()

    if not message and not image:
        return jsonify({
            "error": "Hãy nhập câu hỏi hoặc gửi ảnh."
        }), 400

    if len(message) > 20000:
        return jsonify({
            "error": "Tin nhắn quá dài."
        }), 400

    try:
        image = validate_image(image)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    if not isinstance(conversation_id, str):
        return jsonify({
            "error": "Mã cuộc trò chuyện không hợp lệ."
        }), 400

    timestamp = now()
    user_text = message or "Hãy phân tích ảnh này."

    with db() as conn:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if conversation is None:
            title = (
                message[:60]
                if message
                else "Câu hỏi bằng hình ảnh"
            )

            conn.execute("""
                INSERT INTO conversations
                (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (
                conversation_id,
                title,
                timestamp,
                timestamp
            ))

        rows = conn.execute("""
            SELECT role, content, image
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
        """, (conversation_id,)).fetchall()

        history = []

        for row in rows:
            if row["image"]:
                history.append({
                    "role": row["role"],
                    "content": [
                        {
                            "type": "text",
                            "text": row["content"]
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": row["image"]
                            }
                        }
                    ]
                })
            else:
                history.append({
                    "role": row["role"],
                    "content": row["content"]
                })

        if image:
            current_content = [
                {
                    "type": "text",
                    "text": user_text
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image
                    }
                }
            ]
        else:
            current_content = user_text

        history.append({
            "role": "user",
            "content": current_content
        })

        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, image, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            "user",
            user_text,
            image,
            timestamp
        ))

        conn.execute("""
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
        """, (timestamp, conversation_id))

    try:
        answer = ai_answer(history)

    except RuntimeError as exc:
        # Trả về chi tiết thật để giao diện có thể hiển thị.
        return jsonify({
            "error": str(exc),
            "conversation_id": conversation_id
        }), 502

    except Exception:
        app.logger.exception("Lỗi xử lý câu hỏi")
        return jsonify({
            "error": "Đã xảy ra lỗi nội bộ khi xử lý câu hỏi.",
            "conversation_id": conversation_id
        }), 500

    with db() as conn:
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, image, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            "assistant",
            answer,
            None,
            now()
        ))

        conn.execute("""
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
        """, (now(), conversation_id))

    return jsonify({
        "answer": answer,
        "conversation_id": conversation_id
    })


# ==================================================
# 10. XỬ LÝ LỖI
# ==================================================

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    return jsonify({
        "error": "Dữ liệu quá lớn. Hãy thử ảnh nhỏ hơn 7 MB."
    }), 413


@app.errorhandler(500)
def handle_internal_error(error):
    app.logger.exception("Lỗi máy chủ")
    return jsonify({
        "error": "Máy chủ gặp lỗi nội bộ."
    }), 500


# ==================================================
# 11. KHỞI ĐỘNG
# ==================================================

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
