
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

# ==========================================
# NamSmart - Flask + Groq AI
# ==========================================

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

API_KEY = os.getenv("GROQ_API_KEY", "").strip()

TEXT_MODEL = os.getenv(
    "GROQ_TEXT_MODEL",
    "openai/gpt-oss-120b",
).strip()

VISION_MODEL = os.getenv("GROQ_MODEL", "").strip()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DB_PATH = os.getenv("DATABASE_PATH", "nam_smart.db")

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_HISTORY_MESSAGES = 20

# ==========================================
# SYSTEM PROMPT - CHỐNG BỊA KIẾN THỨC
# ==========================================

SYSTEM_PROMPT = r"""
Bạn là NamSmart, trợ lý AI học tập dành cho học sinh Việt Nam.
Ưu tiên hàng đầu: chính xác, trung thực và giải thích dễ hiểu.

I. NGÔN NGỮ
- Mặc định trả lời bằng tiếng Việt tự nhiên.
- Nếu người dùng hỏi hoàn toàn bằng tiếng Anh, hãy trả lời
  bằng tiếng Anh.
- Nếu người dùng yêu cầu ngôn ngữ cụ thể, hãy dùng ngôn ngữ đó.
- Trình bày rõ ràng, phù hợp với học sinh.

II. NGUYÊN TẮC CHÍNH XÁC
- Không tự bịa dữ kiện, số liệu, công thức, sự kiện hoặc đáp án.
- Không trình bày suy đoán như một sự thật đã được xác minh.
- Không bịa nguồn tài liệu, đường dẫn, tên sách, số trang,
  trích dẫn hoặc thông tin xuất bản.
- Không khẳng định đã tra cứu hay kiểm chứng khi chưa thực sự
  có nguồn để đối chiếu.
- Nếu không chắc chắn, hãy nói rõ giới hạn và phần chưa chắc.
- Nếu thiếu dữ kiện, hãy hỏi lại hoặc nêu rõ giả định cần thiết.
- Không đồng ý với người dùng chỉ để làm họ hài lòng.
- Khi phát hiện lỗi trong lập luận, hãy sửa và giải thích.

III. NGỮ VĂN VÀ TÁC PHẨM VĂN HỌC
- Phân biệt nguyên văn, tóm tắt, diễn giải và phân tích.
- Không tự sáng tác câu thơ hoặc câu văn rồi gán cho tác giả.
- Chỉ chép nguyên văn khi có căn cứ đủ tin cậy.
- Nếu không chắc chính xác từng câu chữ, hãy nói rõ chưa thể
  xác minh nguyên văn; không dùng trí nhớ không chắc chắn
  để tạo ra một bản gốc giả.
- Không tự bịa năm sáng tác, năm xuất bản, tập thơ,
  nhà xuất bản, số trang hoặc dị bản.
- Khi phân tích tác phẩm, dựa vào văn bản có căn cứ.
- Phân biệt dẫn chứng trong tác phẩm với nhận xét của người viết.
- Nếu người dùng cung cấp ảnh hoặc văn bản, ưu tiên nội dung đó.
- Nếu ảnh mờ hoặc thiếu chữ, hãy yêu cầu ảnh rõ hơn.
- Không tự ý sửa câu chữ trong văn bản được trích dẫn.

IV. CÁC MÔN HỌC
- Toán: giải từng bước và kiểm tra kết quả.
- Ngữ văn: lập luận có căn cứ, không bịa dẫn chứng.
- Lịch sử: phân biệt sự kiện, thời gian và nhận định.
- Địa lí: giải thích số liệu, bản đồ và khái niệm có căn cứ.
- Khoa học: nêu điều kiện áp dụng và đơn vị khi cần.
- Với câu hỏi phụ thuộc chương trình học, hãy hỏi rõ lớp,
  bộ sách hoặc yêu cầu đề bài nếu cần thiết.
- Nếu đề thiếu dữ kiện hoặc có nhiều cách hiểu, hãy chỉ rõ.

V. GIẢI BÀI TẬP
- Đọc kỹ đề trước khi giải.
- Không tự thêm dữ kiện không có trong đề.
- Giải thích các bước biến đổi và phương pháp.
- Kiểm tra phép tính và đáp án cuối.
- Với câu hỏi trắc nghiệm, giải thích lý do chọn đáp án khi cần.
- Nếu có nhiều phương pháp, ưu tiên phương pháp phù hợp trình độ.

VI. PHÂN TÍCH ẢNH
- Chỉ kết luận từ nội dung nhìn thấy và kiến thức có căn cứ.
- Không đoán chữ bị che, mờ hoặc nằm ngoài ảnh.
- Phân biệt nội dung đọc được với phần suy luận.
- Nếu không đọc được đề chính xác, hãy yêu cầu ảnh rõ hơn.

VII. IELTS VÀ TIẾNG ANH
- Đưa ra ví dụ tự nhiên, đúng ngữ pháp và phù hợp trình độ.
- Phân biệt câu trả lời mẫu với đáp án duy nhất.
- Điểm IELTS do AI đưa ra chỉ là ước lượng, không phải điểm
  chính thức của giám khảo.

VIII. CÔNG THỨC TOÁN
- Dùng LaTeX chuẩn.
- Công thức trong dòng dùng \( ... \).
- Công thức riêng dòng dùng \[ ... \].
- Giải thích các bước biến đổi rõ ràng.
- Không đặt công thức trong khối mã nếu không cần thiết.

IX. NGUỒN VÀ GIỚI HẠN
- Không nói đã tra cứu nếu không có công cụ tra cứu thực tế.
- Không tạo nguồn tham khảo hoặc đường dẫn giả.
- Với thông tin quan trọng, hãy khuyến khích đối chiếu sách giáo khoa
  hoặc tài liệu chính thức.
- Nếu không có tài liệu để xác minh nguyên văn, hãy nói rõ.

X. NGUYÊN TẮC CUỐI
- Chính xác quan trọng hơn trả lời dài hoặc tỏ ra chắc chắn.
- Không bịa thông tin để lấp chỗ trống.
- Trung thực về giới hạn của mình.
- Khi cần, đề nghị người dùng cung cấp tài liệu để kiểm tra.
"""

# ==========================================
# DATABASE
# ==========================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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


def save_message(conversation_id, role, content, image=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO messages (
                conversation_id,
                role,
                content,
                image,
                created_at
            )
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

    clean_title = (title or "Cuộc trò chuyện mới").strip()
    clean_title = clean_title[:80] or "Cuộc trò chuyện mới"

    with get_db() as conn:
        conn.execute("""
            INSERT INTO conversations (
                id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            conversation_id,
            clean_title,
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


init_db()

# ==========================================
# IMAGE VALIDATION
# ==========================================

def decode_image(image, mime):
    if not isinstance(image, str):
        raise ValueError("Dữ liệu ảnh không hợp lệ.")

    if image.startswith("data:"):
        try:
            header, encoded = image.split(",", 1)
        except ValueError:
            raise ValueError("Data URI ảnh không hợp lệ.")

        if ";base64" not in header.lower():
            raise ValueError("Ảnh phải được mã hóa base64.")

        actual_mime = header[5:].split(";")[0].lower()

        if actual_mime != mime:
            raise ValueError(
                "Định dạng ảnh không khớp với image_mime."
            )

        image = encoded

    if mime not in ALLOWED_MIME:
        raise ValueError(
            "Chỉ hỗ trợ ảnh JPEG, PNG hoặc WEBP."
        )

    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Dữ liệu ảnh base64 không hợp lệ.")

    if not raw:
        raise ValueError("Ảnh đang trống.")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh tối đa 6 MB.")

    return raw


# ==========================================
# GROQ API
# ==========================================

def ask_groq(model, messages):
    if not API_KEY:
        return None, 500, {
            "error": {
                "message":
                    "Chưa cấu hình GROQ_API_KEY trên Render."
            }
        }

    if not model:
        return None, 500, {
            "error": {
                "message": "Chưa cấu hình tên model Groq."
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
        "temperature": 0.2,
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

        choices = data.get("choices") or []

        if not choices:
            return None, 502, {
                "error": {
                    "message": "Groq không trả về choices."
                }
            }

        answer = (
            choices[0]
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
        app.logger.warning(
            "Groq timeout | model=%s",
            model,
        )

        return None, 504, {
            "error": {
                "message": "Groq phản hồi quá lâu. Hãy thử lại."
            }
        }

    except requests.RequestException:
        app.logger.exception(
            "Lỗi kết nối Groq | model=%s",
            model,
        )

        return None, 502, {
            "error": {
                "message": "Không thể kết nối đến Groq API."
            }
        }


# ==========================================
# WEBSITE ROUTES
# ==========================================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "NamSmart",
    })


# ==========================================
# CONVERSATION HISTORY API
# ==========================================

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

        exists = conn.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

        if exists is None:
            return jsonify({
                "error": "Không tìm thấy cuộc trò chuyện."
            }), 404

        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )

        conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )

    return jsonify({"ok": True})


# ==========================================
# CHAT API
# ==========================================

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

    # --------------------------------------
    # Validate image if provided
    # --------------------------------------

    image_for_ai = None
    image_for_history = None

    if image:
        if not isinstance(image, str):
            return jsonify({
                "error": "Dữ liệu ảnh không hợp lệ."
            }), 400

        mime = "image/jpeg"

        if image.startswith("data:"):
            match = re.match(
                r"^data:(image/(?:jpeg|png|webp));base64,",
                image,
                flags=re.IGNORECASE,
            )

            if not match:
                return jsonify({
                    "error":
                        "Ảnh phải là JPEG, PNG hoặc WEBP."
                }), 400

            mime = match.group(1).lower()

        try:
            decode_image(image, mime)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if image.startswith("data:"):
            image_for_ai = image
        else:
            image_for_ai = f"data:{mime};base64,{image}"

        image_for_history = image_for_ai

    # --------------------------------------
    # Create or validate conversation
    # --------------------------------------

    if conversation_id:
        conversation_id = str(conversation_id)

        if not valid_conversation(conversation_id):
            return jsonify({
                "error": (
                    "Cuộc trò chuyện không tồn tại. "
                    "Hãy tạo cuộc trò chuyện mới."
                )
            }), 404
    else:
        title = prompt or "Phân tích ảnh bài tập"
        conversation_id = create_conversation(title)

    # --------------------------------------
    # Save current user message
    # --------------------------------------

    user_text = prompt or "📷 Hãy đọc và giải bài trong ảnh này."

    save_message(
        conversation_id,
        "user",
        user_text,
        image_for_history,
    )

    # --------------------------------------
    # Load recent conversation context
    # --------------------------------------

    with get_db() as conn:
        rows = conn.execute("""
            SELECT role, content, image
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            conversation_id,
            MAX_HISTORY_MESSAGES,
        )).fetchall()

    rows = list(reversed(rows))

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    for row in rows:
        role = row["role"]
        content = row["content"]
        saved_image = row["image"]

        if role not in ("user", "assistant"):
            continue

        if role == "user" and saved_image:
            user_content = [
                {
                    "type": "text",
                    "text": content or "Phân tích ảnh này.",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": saved_image,
                    },
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

    # --------------------------------------
    # Select model
    # --------------------------------------

    if image_for_ai:
        model = VISION_MODEL

        if not model:
            return jsonify({
                "error": (
                    "Chưa cấu hình GROQ_MODEL cho ảnh. "
                    "Hãy chọn model vision được Groq hỗ trợ."
                ),
                "conversation_id": conversation_id,
            }), 500
    else:
        model = TEXT_MODEL

    # --------------------------------------
    # Request Groq
    # --------------------------------------

    answer, status, detail = ask_groq(model, messages)

    if status:
        app.logger.error(
            "Chat failed | status=%s | model=%s",
            status,
            model,
        )

        # Giữ thông tin chi tiết trong log máy chủ.
        # Không trả toàn bộ lỗi nội bộ của nhà cung cấp
        # về trình duyệt.
        return jsonify({
            "error": (
                "Groq API gặp lỗi. "
                "Hãy kiểm tra cấu hình và Render Logs."
            ),
            "status": status,
            "model_used": model,
            "conversation_id": conversation_id,
        }), 502

    # --------------------------------------
    # Save and return assistant response
    # --------------------------------------

    save_message(
        conversation_id,
        "assistant",
        answer,
    )

    return jsonify({
        "answer": answer,
        "conversation_id": conversation_id,
        "model_used": model,
    })


# ==========================================
# ERROR HANDLERS
# ==========================================

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


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
