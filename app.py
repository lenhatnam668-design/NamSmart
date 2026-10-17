import os
import json
import urllib.request
import urllib.error
import logging
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Tệp lưu trữ lịch sử cuộc trò chuyện
HISTORY_FILE = 'chat_history.json'

SYSTEM_PROMPT = """Bạn là Nam Smart, trợ lý học tập và công nghệ thân thiện. 
Trả lời ngắn gọn, chính xác bằng tiếng Việt."""

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "error": "Chưa cấu hình GROQ_API_KEY trong Render Environment."
        }), 503

    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Hãy nhập câu hỏi rồi gửi lại."}), 400

    # Chuẩn bị tin nhắn gửi tới Groq API
    clean_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]

    payload = json.dumps({
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
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
            "User-Agent": "NamSmart/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
            answer = result["choices"][0]["message"]["content"].strip()

        # Lưu vào lịch sử
        history = load_history()
        history.append({"user": user_message, "bot": answer})
        save_history(history)

        return jsonify({"answer": answer})

    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            detail = ""

        app.logger.error("Groq HTTP error: status=%s, detail=%s", e.code, detail)

        if e.code == 401:
            message = "API key bị từ chối. Hãy kiểm tra GROQ_API_KEY trên Render."
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

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(load_history())

@app.route('/api/clear', methods=['POST'])
def clear_history():
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
        except Exception:
            pass
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False
    )
