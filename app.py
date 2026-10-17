
import os
import json
import sqlite3
import base64
import uuid

from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# =========================
# CẤU HÌNH ỨNG DỤNG
# =========================

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "nam_smart.db"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TEXT_MODEL = os.getenv(
    "GROQ_TEXT_MODEL",
    "openai/gpt-oss-120b"
)

VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "qwen/qwen3.8-27b"
)

SYSTEM_PROMPT = """
Bạn là Nam Smart, trợ lý AI học tập thân thiện dành cho học sinh Việt Nam.

NGUYÊN TẮC:
- Trả lời bằng tiếng Việt, rõ ràng, chính xác và dễ hiểu.
- Giải thích từng bước đối với bài tập Toán, Lý, Hóa, Tin học và các môn khác.
- Nếu người dùng yêu cầu đáp án ngắn, hãy trả lời ngắn gọn.
- Không bịa dữ kiện hoặc tự khẳng định điều chưa chắc chắn.
- Với câu hỏi trắc nghiệm, giải thích ngắn gọn vì sao chọn đáp án.
- Khi nhận ảnh đề bài, đọc nội dung ảnh rồi giải quyết yêu cầu.
- Nếu ảnh mờ hoặc thiếu dữ kiện, hãy hỏi lại người dùng.
- Có thể dùng Markdown để trình bày tiêu đề, danh sách và bảng.

QUY TẮC CÔNG THỨC TOÁN:
- Công thức trong dòng dùng \\( ... \\).
- Công thức riêng dòng dùng \\[ ... \\].
- Ví dụ: \\(a^2+b^2=c^2\\).
- Ví dụ công thức riêng dòng:
  \\[
  x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}
  \\]
- Không dùng dấu $ để bao quanh công thức.
- Viết công thức LaTeX đúng cú pháp.
"""


# =========================
# DATABASE
# =========================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
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


# =========================
# KIỂM TRA ẢNH
# =========================

def validate_image(image):
    if not image:
        return None

    if not isinstance(image, str):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    allowed_types = {
        "data:image/jpeg;base64,": "image/jpeg",
        "data:image/png;base64,": "image/png",
        "data:image/webp;base64,": "image/webp",
        "data:image/gif;base64,": "image/gif",
    }

    prefix = next(
        (
            item for item in allowed_types
            if image.startswith(item)
        ),
        None
    )

    if prefix is None:
        raise ValueError(
            "Chỉ hỗ trợ ảnh JPEG, PNG, WEBP hoặc GIF."
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


# =========================
# GỌI GROQ API
# =========================

def ai_answer(history):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Chưa cấu hình GROQ_API_KEY trên Render."
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
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            *history
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    data = json.dumps(payload).encode("utf-8")

    req = Request(
        GROQ_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urlopen(req, timeout=90) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        choices = result.get("choices", [])

        if not choices:
            raise RuntimeError(
                "Groq không trả về câu trả lời."
            )

        answer = choices[0].get(
            "message", {}
        ).get("content")

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(
                "Nội dung phản hồi từ Groq đang trống."
            )

        return answer.strip()

    except HTTPError as exc:
        body = exc.read().decode(
            "utf-8", errors="replace"
        )

        try:
            error_data = json.loads(body)
            detail = error_data.get(
                "error", {}
            ).get("message", body)
        except (json.JSONDecodeError, AttributeError):
            detail = body

        if exc.code == 401:
            message = "API key Groq không hợp lệ."
        elif exc.code == 403:
            message = "API key không có quyền truy cập."
        elif exc.code == 404:
            message = (
                f"Không tìm thấy model '{model}' hoặc endpoint. "
                f"Chi tiết: {detail}"
            )
        elif exc.code == 429:
            message = (
                "Groq đã giới hạn yêu cầu hoặc hết hạn mức. "
                f"Chi tiết: {detail}"
            )
        else:
            message = f"Groq HTTP {exc.code}: {detail}"

        raise RuntimeError(message) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Không kết nối được Groq API: {exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise RuntimeError(
            "Groq phản hồi quá lâu. Hãy thử lại."
        ) from exc


# =========================
# TRANG CHỦ
# =========================

@app.route("/")
def index():
    return render_template("index.html")


# =========================
# DANH SÁCH CUỘC TRÒ CHUYỆN
# =========================

@app.route("/api/conversations", methods=["GET"])
def get_conversations():
    with db() as conn:
        rows = conn.execute("""
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


# =========================
# CHI TIẾT CUỘC TRÒ CHUYỆN
# =========================

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


# =========================
# XÓA CUỘC TRÒ CHUYỆN
# =========================

@app.route(
    "/api/conversations/<conversation_id>",
    methods=["DELETE"]
)
def delete_conversation(conversation_id):
    with db() as conn:
        conn.execute("PRAGMA foreign_keys = ON")

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


# =========================
# CHAT
# =========================

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

    with db() as conn:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if conversation is None:
            title = message[:60] if message else "Câu hỏi bằng hình ảnh"

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

        # Lấy lịch sử trước khi lưu tin nhắn hiện tại
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
                            "text": row["content"] or "Hãy xem ảnh."
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

        # Thêm câu hỏi mới vào lịch sử gửi Groq
        if image:
            current_content = [
                {
                    "type": "text",
                    "text": message or "Hãy phân tích và giải thích nội dung ảnh này."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image
                    }
                }
            ]
        else:
            current_content = message

        history.append({
            "role": "user",
            "content": current_content
        })

        # Lưu tin nhắn người dùng
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, image, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            "user",
            message or "Câu hỏi bằng hình ảnh",
            image,
            timestamp
        ))

    try:
        answer = ai_answer(history)

    except RuntimeError as exc:
        return jsonify({
            "error": str(exc),
            "conversation_id": conversation_id
        }), 502

    except Exception:
        app.logger.exception("Lỗi xử lý câu hỏi")
        return jsonify({
            "error": "Đã xảy ra lỗi khi xử lý câu hỏi."
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


# =========================
# XỬ LÝ LỖI FILE QUÁ LỚN
# =========================

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    return jsonify({
        "error": "Dữ liệu gửi lên quá lớn. Hãy dùng ảnh nhỏ hơn 7 MB."
    }), 413


# =========================
# KHỞI ĐỘNG
# =========================

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )
