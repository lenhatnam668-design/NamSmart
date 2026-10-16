import os
import json
import urllib.request
import urllib.error
import logging
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """Bạn là Study AI, trợ lý học tập thân thiện cho học sinh Việt Nam.
Trả lời bằng tiếng Việt trừ khi người học yêu cầu ngôn ngữ khác.
Giải thích dễ hiểu, có cấu trúc và phù hợp học sinh phổ thông.
Với bài Toán/Khoa học: trình bày từng bước, nêu công thức và kiểm tra kết quả khi phù hợp.
Với IELTS/tiếng Anh: sửa lỗi cụ thể, giải thích ngắn gọn và đưa ví dụ tự nhiên.
Với Ngữ văn: giúp phân tích, lập dàn ý, diễn đạt tự nhiên; không bịa dẫn chứng.
Nếu đề bài thiếu dữ kiện, hỏi lại thay vì đoán. Nói rõ khi không chắc.
Không làm thay việc gian lận trong kiểm tra đang diễn ra; ưu tiên hướng dẫn để người học tự hiểu."""

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/status")
def status():
    return jsonify({"configured": bool(os.getenv("GROQ_API_KEY"))})

@app.post("/api/chat")
def chat():
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "error": "Chưa cấu hình GROQ_API_KEY trong Render Environment."
        }), 503

    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "Hãy nhập câu hỏi rồi gửi lại."}), 400

    clean_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for item in messages[-16:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if role not in ("user", "assistant") or not isinstance(content, str):
            continue

        content = content.strip()[:6000]
        if content:
            clean_messages.append({
                "role": role,
                "content": content
            })

    if len(clean_messages) == 1:
        return jsonify({"error": "Không tìm thấy nội dung câu hỏi."}), 400

    payload = json.dumps({
        "model": os.getenv(
            "GROQ_MODEL",
            "llama-3.3-70b-versatile"
        ),
        "messages": clean_messages,
        "temperature": 0.5,
        "max_tokens": 1200
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StudyAI/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
            answer = result["choices"][0]["message"]["content"].strip()
        return jsonify({"answer": answer})

    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            detail = ""

        # Log chi tiết để tìm nguyên nhân, không ghi API key.
        app.logger.error(
            "Groq HTTP error: status=%s, detail=%s",
            e.code,
            detail
        )

        if e.code == 401:
            message = "API key bị từ chối. Hãy kiểm tra GROQ_API_KEY trên Render."
        elif e.code == 403:
            message = (
                "Groq từ chối yêu cầu (403). "
                "Hãy kiểm tra log Render để xem chi tiết."
            )
        elif e.code == 429:
            message = "Groq đang giới hạn yêu cầu hoặc đã hết hạn mức. Hãy thử lại sau."
        else:
            message = f"Groq trả lỗi HTTP {e.code}. Hãy kiểm tra Render Logs."

        return jsonify({"error": message}), 502

    except Exception:
        app.logger.exception("Lỗi khi gọi Groq API")
        return jsonify({
            "error": "Không kết nối được dịch vụ AI. Hãy kiểm tra Render Logs."
        }), 502

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False
    )
