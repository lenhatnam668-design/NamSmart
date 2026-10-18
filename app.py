
import os
import base64
import binascii
import requests

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TEXT_MODEL = os.getenv(
    "GROQ_TEXT_MODEL", "openai/gpt-oss-120b"
).strip()
VISION_MODEL = os.getenv("GROQ_MODEL", "").strip()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

SYSTEM_PROMPT = r"""
Bạn là NamSmart, trợ lý học tập AI thông minh.

NGÔN NGỮ:
- Mặc định trả lời bằng tiếng Việt tự nhiên.
- Nếu người dùng hỏi hoàn toàn bằng tiếng Anh, hãy trả lời bằng tiếng Anh.
- Nếu người dùng yêu cầu ngôn ngữ cụ thể, hãy sử dụng ngôn ngữ đó.

CHẤT LƯỢNG:
- Giải thích rõ ràng, chính xác, phù hợp với học sinh.
- Giải bài tập từng bước khi cần thiết.
- Không tự bịa dữ kiện hoặc kết quả.
- Với IELTS, cung cấp từ vựng, cấu trúc và ví dụ phù hợp mục tiêu.
- Khi phân tích ảnh, chỉ kết luận dựa trên nội dung nhìn thấy.

TOÁN HỌC:
- Viết công thức bằng LaTeX chuẩn.
- Công thức trong dòng dùng \( ... \).
- Công thức riêng dòng dùng \[ ... \].
- Không đặt công thức toán trong khối mã.
- Trình bày các bước biến đổi rõ ràng.
"""


def ask_groq(model, messages):
    if not model:
        return None, 500, {
            "error": {
                "message": "Chưa cấu hình tên model."
            }
        }

    if not API_KEY:
        return None, 500, {
            "error": {
                "message": "Thiếu GROQ_API_KEY trong Render Environment."
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
            data = {"error": {"message": response.text[:1500]}}

        if not response.ok:
            app.logger.error(
                "Groq API error: status=%s model=%s detail=%s",
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
                    "message": "Groq trả về nội dung rỗng hoặc không đúng định dạng."
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
        app.logger.exception("Không thể kết nối Groq")
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


@app.post("/chat")
def chat():
    if not API_KEY:
        return jsonify({
            "error": "Chưa cấu hình GROQ_API_KEY trong Environment của Render."
        }), 500

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({
            "error": "Dữ liệu gửi lên không hợp lệ."
        }), 400

    prompt = str(body.get("message") or "").strip()
    image = body.get("image")
    mime = str(
        body.get("image_mime") or "image/jpeg"
    ).lower().strip()

    if not prompt and not image:
        return jsonify({
            "error": "Nhập câu hỏi hoặc chọn ảnh trước nhé."
        }), 400

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    if image:
        if not isinstance(image, str):
            return jsonify({
                "error": "Dữ liệu ảnh không hợp lệ."
            }), 400

        if not VISION_MODEL:
            return jsonify({
                "error": (
                    "Chưa đặt GROQ_MODEL. Hãy chọn model Groq "
                    "có hỗ trợ đầu vào hình ảnh."
                )
            }), 500

        if mime not in ALLOWED_MIME:
            return jsonify({
                "error": "Chỉ hỗ trợ ảnh JPEG, PNG hoặc WEBP."
            }), 400

        # Hỗ trợ cả base64 thuần và data URI.
        if image.startswith("data:"):
            try:
                header, image = image.split(",", 1)
            except ValueError:
                return jsonify({
                    "error": "Data URI ảnh không hợp lệ."
                }), 400

            if ";base64" not in header.lower():
                return jsonify({
                    "error": "Ảnh phải được mã hóa base64."
                }), 400

            header_mime = header[5:].split(";")[0].lower()

            if header_mime != mime:
                return jsonify({
                    "error": "Định dạng ảnh không khớp image_mime."
                }), 400

        try:
            raw = base64.b64decode(image, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({
                "error": "Dữ liệu ảnh base64 không hợp lệ."
            }), 400

        if len(raw) > 6 * 1024 * 1024:
            return jsonify({
                "error": "Ảnh tối đa 6 MB."
            }), 413

        user_content = [
            {
                "type": "text",
                "text": prompt or "Hãy phân tích hình ảnh này bằng tiếng Việt.",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{image}"
                },
            },
        ]

        model = VISION_MODEL

    else:
        user_content = prompt
        model = TEXT_MODEL

    messages.append({
        "role": "user",
        "content": user_content,
    })

    answer, status, detail = ask_groq(model, messages)

    if status:
        return jsonify({
            "error": "Không thể nhận câu trả lời từ Groq API.",
            "status": status,
            "detail": detail,
            "model_used": model,
        }), status

    return jsonify({
        "reply": answer,
        "model_used": model,
    })


@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "error": "Dữ liệu quá lớn. Hãy giảm kích thước ảnh."
    }), 413


@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "error": "Không tìm thấy đường dẫn API."
    }), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify({
        "error": "Máy chủ gặp lỗi. Hãy kiểm tra Render Logs."
    }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
