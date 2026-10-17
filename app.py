
"""Nam Smart - Flask AI assistant with persistent chat and vision support."""

import base64
import binascii
import json
import logging
import os
import re
import sqlite3
import urllib.error
import urllib.request
import uuid

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request


# =========================================================
# 1. APPLICATION CONFIGURATION
# =========================================================

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "nam_smart.db"

app = Flask(__name__)
app.json.ensure_ascii = False

app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

logging.basicConfig(level=logging.INFO)


# =========================================================
# 2. DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            image TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id)
                REFERENCES conversations(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id, id);
        """)


def now():
    return datetime.now(timezone.utc).isoformat()


# =========================================================
# 3. IMAGE VALIDATION
# =========================================================

MAX_IMAGE_BYTES = 7 * 1024 * 1024

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


def validate_image(data):
    if not data:
        return None

    if not isinstance(data, str):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    if not data.startswith("data:image/") or ";base64," not in data:
        raise ValueError("Ảnh không đúng định dạng.")

    header, payload = data.split(",", 1)
    mime = header[5:].split(";", 1)[0].lower()

    if mime not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Chỉ hỗ trợ ảnh JPG, PNG, WEBP hoặc GIF.")

    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh vượt quá 7 MB.")

    if not raw:
        raise ValueError("Ảnh đang trống.")

    # Kiểm tra chữ ký định dạng cơ bản.
    signatures = {
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/gif": (b"GIF87a", b"GIF89a"),
        "image/webp": (b"RIFF",),
    }

    if not any(
        raw.startswith(signature)
        for signature in signatures[mime]
    ):
        raise ValueError("Nội dung ảnh không khớp với định dạng khai báo.")

    if mime == "image/webp" and raw[8:12] != b"WEBP":
        raise ValueError("Tệp WEBP không hợp lệ.")

    return data


# =========================================================
# 4. SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = r"""
Bạn là Nam Smart, trợ lý AI học tập thông minh, thân thiện,
giải thích bằng tiếng Việt tự nhiên, dễ hiểu.

MỤC TIÊU:
- Giúp học sinh hiểu bản chất kiến thức.
- Giải bài tập theo từng bước.
- Trình bày rõ ràng, chính xác, có ví dụ khi cần.
- Không bịa dữ kiện nếu không đủ thông tin.

QUY TẮC TOÁN HỌC BẮT BUỘC:

1. Dùng LaTeX để viết công thức toán.

2. Công thức ngắn trong câu dùng:
   \( ... \)

3. Công thức dài hoặc quan trọng dùng:
   \[
   ...
   \]

4. Tuyệt đối không dùng $...$ hoặc $$...$$ làm dấu
   phân cách công thức trong câu trả lời.

5. Các lệnh LaTeX phải viết chính xác:
   - Phân số: \frac{a}{b}
   - Căn bậc hai: \sqrt{x}
   - Căn bậc n: \sqrt[n]{x}
   - Lũy thừa: x^{2}
   - Chỉ số dưới: x_{1}
   - Nhân: \times
   - Chia: \div
   - Góc: \angle ABC
   - Song song: \parallel
   - Vuông góc: \perp
   - Vô cực: \infty
   - Tổng: \sum
   - Tích phân: \int
   - Giới hạn: \lim

6. Hệ phương trình:
   \[
   \begin{cases}
   x+y=5\\
   x-y=1
   \end{cases}
   \]

7. Ma trận:
   \[
   A=\begin{bmatrix}
   1&2\\
   3&4
   \end{bmatrix}
   \]

8. Không đặt công thức LaTeX trong dấu backtick,
   trừ khi người dùng yêu cầu xem mã nguồn.

9. Không tự ý bỏ dấu ngoặc nhọn, dấu căn, số mũ,
   chỉ số dưới hoặc các ký hiệu toán học.

10. Kiểm tra dấu mở và đóng của các công thức trước khi gửi.

11. Nếu giải phương trình, trình bày biến đổi từng bước
    và kết luận rõ ràng.

12. Không sử dụng LaTeX cho đoạn văn thông thường
    nếu không cần thiết.

13. Nếu người dùng gửi ảnh bài tập, đọc đề cẩn thận.
    Nếu không đọc được một phần, nói rõ phần đó.

VÍ DỤ TRÌNH BÀY ĐÚNG:

Ta có phương trình:
\[
2x-1=0
\]

Chuyển vế:
\[
2x=1
\]

Suy ra:
\[
x=\frac{1}{2}
\]

Kết luận: \(x=\frac{1}{2}\).

Với môn học khác, hãy trình bày phù hợp với nội dung
và trình độ của người học.

Không tiết lộ API key, biến môi trường bí mật hoặc dữ liệu
nội bộ của máy chủ.
"""


# =========================================================
# 5. MATH TEXT NORMALIZATION
# =========================================================

def normalize_math(text):
    """
    Chuẩn hóa một số cách viết công thức thường gặp.

    Không cố sửa sâu nội dung LaTeX vì việc thay thế
    ký hiệu tùy tiện có thể làm hỏng công thức hợp lệ.
    """

    if not isinstance(text, str):
        return str(text or "")

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Chuẩn hóa dấu phân cách công thức kiểu Markdown:
    # $$ ... $$ -> \[ ... \]
    # Chỉ chuyển đổi khi cặp dấu đóng tồn tại.
    text = re.sub(
        r"(?<!\\)\$\$(.*?)\$\$",
        lambda match: "\\[\n" + match.group(1).strip() + "\n\\]",
        text,
        flags=re.DOTALL,
    )

    # Chuyển $...$ sang \( ... \), nhưng tránh thay đổi
    # các dấu phân cách LaTeX đã chuẩn hóa ở trên.
    text = re.sub(
        r"(?<!\\)\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)",
        lambda match: "\\(" + match.group(1).strip() + "\\)",
        text,
    )

    return text


# =========================================================
# 6. GROQ API
# =========================================================

def ai_answer(history):
    groq_key = os.getenv("GROQ_API_KEY", "").strip()

    if not groq_key:
        raise RuntimeError(
            "Chưa cấu hình GROQ_API_KEY trên Render. "
            "Hãy thêm biến môi trường trong phần Environment."
        )

    recent_history = history[-18:]

    has_image = any(
        item.get("image")
        for item in recent_history
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    for item in recent_history:
        role = item.get("role", "user")
        text_content = item.get("content") or ""

        if role not in {"user", "assistant"}:
            continue

        if role == "user" and item.get("image"):
            content = [
                {
                    "type": "text",
                    "text": text_content
                    or "Hãy đọc và giải thích nội dung trong ảnh.",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": item["image"]
                    },
                },
            ]
        else:
            content = text_content

        messages.append({
            "role": role,
            "content": content,
        })

    if has_image:
        model_name = os.getenv(
            "GROQ_VISION_MODEL",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        )
    else:
        model_name = os.getenv(
            "GROQ_MODEL",
            "llama-3.3-70b-versatile",
        )

    url = "https://api.groq.com/openai/v1/chat/completions"

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 3000,
    }

    req_data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {groq_key}",
            "User-Agent": "NamSmart/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            response_data = response.read().decode("utf-8")
            result = json.loads(response_data)

        answer = result["choices"][0]["message"]["content"]

        if not isinstance(answer, str) or not answer.strip():
            return "Mình chưa tạo được câu trả lời. Bạn hãy thử lại nhé."

        return normalize_math(answer.strip())

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        app.logger.error(
            "Groq API HTTP %s: %s",
            exc.code,
            error_body[:1500],
        )

        if exc.code == 401:
            raise RuntimeError(
                "Groq API key không hợp lệ. Hãy kiểm tra GROQ_API_KEY."
            ) from exc

        if exc.code == 429:
            raise RuntimeError(
                "Groq đang giới hạn số yêu cầu hoặc hạn mức sử dụng. "
                "Hãy chờ rồi thử lại."
            ) from exc

        raise RuntimeError(
            f"Groq API gặp lỗi HTTP {exc.code}. "
            "Hãy kiểm tra tên model và cấu hình API."
        ) from exc

    except urllib.error.URLError as exc:
        app.logger.exception("Groq connection error")
        raise RuntimeError(
            "Không thể kết nối Groq. Hãy thử lại sau."
        ) from exc

    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        app.logger.exception("Invalid Groq response")
        raise RuntimeError(
            "Phản hồi từ AI không đúng định dạng."
        ) from exc


# =========================================================
# 7. HOME PAGE
# =========================================================

@app.get("/")
def home():
    return render_template("index.html")


# =========================================================
# 8. CONVERSATION LIST
# =========================================================

@app.get("/api/conversations")
def conversations():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, updated_at
            FROM conversations
            ORDER BY updated_at DESC
            """
        ).fetchall()

    return jsonify([dict(row) for row in rows])


# =========================================================
# 9. GET ONE CONVERSATION
# =========================================================

@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id):
    with db() as conn:
        conversation = conn.execute(
            """
            SELECT id, title
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()

        if not conversation:
            return jsonify(
                error="Không tìm thấy cuộc trò chuyện."
            ), 404

        rows = conn.execute(
            """
            SELECT role, content, image
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()

    return jsonify(
        id=conversation["id"],
        title=conversation["title"],
        messages=[dict(row) for row in rows],
    )


# =========================================================
# 10. DELETE CONVERSATION
# =========================================================

@app.delete("/api/conversations/<conversation_id>")
def delete_conversation(conversation_id):
    with db() as conn:
        exists = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

        if not exists:
            return jsonify(
                error="Không tìm thấy cuộc trò chuyện."
            ), 404

        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )

        conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )

    return jsonify(ok=True)


# =========================================================
# 11. CHAT API
# =========================================================

@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(
            error="Dữ liệu gửi lên không hợp lệ."
        ), 400

    prompt = str(data.get("message") or "").strip()

    try:
        image = validate_image(data.get("image"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not prompt and not image:
        return jsonify(
            error="Hãy nhập câu hỏi hoặc chọn ảnh."
        ), 400

    if len(prompt) > 12000:
        return jsonify(
            error="Câu hỏi quá dài. Vui lòng rút gọn."
        ), 400

    conversation_id = str(
        data.get("conversation_id") or ""
    ).strip()

    # Không cho phép người dùng tạo ID dài bất thường.
    if len(conversation_id) > 100:
        return jsonify(
            error="Mã cuộc trò chuyện không hợp lệ."
        ), 400

    with db() as conn:
        existing = None

        if conversation_id:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

        if not existing:
            conversation_id = str(uuid.uuid4())

            title = (
                prompt or "Câu hỏi từ hình ảnh"
            )[:65]

            conn.execute(
                """
                INSERT INTO conversations
                    (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    title,
                    now(),
                    now(),
                ),
            )

        history = [
            dict(row)
            for row in conn.execute(
                """
                SELECT role, content, image
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id
                """,
                (conversation_id,),
            ).fetchall()
        ]

        history.append({
            "role": "user",
            "content": prompt,
            "image": image,
        })

        conn.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, image, created_at)
            VALUES (?, 'user', ?, ?, ?)
            """,
            (
                conversation_id,
                prompt,
                image,
                now(),
            ),
        )

        conn.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
            """,
            (now(), conversation_id),
        )

    try:
        answer = ai_answer(history)

    except RuntimeError as exc:
        return jsonify(
            error=str(exc),
            conversation_id=conversation_id,
        ), 503

    except Exception:
        app.logger.exception("Unexpected AI error")

        return jsonify(
            error="Đã xảy ra lỗi hệ thống. Hãy thử lại sau.",
            conversation_id=conversation_id,
        ), 502

    with db() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, image, created_at)
            VALUES (?, 'assistant', ?, NULL, ?)
            """,
            (
                conversation_id,
                answer,
                now(),
            ),
        )

        conn.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
            """,
            (
                now(),
                conversation_id,
            ),
        )

    return jsonify(
        answer=answer,
        conversation_id=conversation_id,
    )


# =========================================================
# 12. ERROR HANDLERS
# =========================================================

@app.errorhandler(413)
def too_large(_error):
    return jsonify(
        error="Ảnh hoặc yêu cầu quá lớn. Giới hạn tổng là 12 MB."
    ), 413


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(
            error="Không tìm thấy API được yêu cầu."
        ), 404

    return "Không tìm thấy trang.", 404


@app.errorhandler(500)
def internal_error(_error):
    app.logger.exception("Internal server error")

    if request.path.startswith("/api/"):
        return jsonify(
            error="Lỗi máy chủ nội bộ. Hãy thử lại sau."
        ), 500

    return "Đã xảy ra lỗi máy chủ.", 500


# =========================================================
# 13. START APPLICATION
# =========================================================

init_db()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"

    app.run(
        host="0.0.0.0",
        debug=debug_mode,
        port=int(os.getenv("PORT", "5000")),
    )
