import os, base64, binascii, requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
API_KEY = os.getenv("GROQ_API_KEY", "").strip()
VISION_MODEL = os.getenv("GROQ_MODEL", "").strip()
TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-120b").strip()
URL = "https://api.groq.com/openai/v1/chat/completions"
ALLOWED = {"image/jpeg", "image/png", "image/webp"}

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "NamSmart"})

def ask_groq(model, messages):
    r = requests.post(URL, headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.4}, timeout=90)
    if not r.ok:
        try: detail = r.json()
        except ValueError: detail = r.text[:1000]
        return None, r.status_code, detail
    try: return r.json()["choices"][0]["message"]["content"], None, None
    except (KeyError, IndexError, TypeError): return None, 502, {"error": {"message": "Unexpected Groq response"}}

@app.post("/chat")
def chat():
    if not API_KEY:
        return jsonify({"error": "Chưa cấu hình GROQ_API_KEY trong Environment của Render."}), 500
    body = request.get_json(silent=True) or {}
    prompt = str(body.get("message", "")).strip()
    image = body.get("image")
    mime = str(body.get("image_mime", "image/jpeg")).lower().strip()
    if not prompt and not image:
        return jsonify({"error": "Nhập câu hỏi hoặc chọn ảnh trước nhé."}), 400
    system = {"role": "system", "content": (
        "Bạn là NamSmart, trợ lý học tập AI. Mặc định trả lời bằng tiếng Việt tự nhiên, rõ ràng, chính xác và phù hợp với học sinh. "
        "Nếu người dùng hỏi hoàn toàn bằng tiếng Anh, hãy trả lời bằng tiếng Anh; nếu họ yêu cầu một ngôn ngữ cụ thể, hãy dùng ngôn ngữ đó. "
        "Nếu câu hỏi pha trộn nhiều ngôn ngữ mà không có yêu cầu rõ ràng, ưu tiên tiếng Việt. "
        "Giải bài tập theo từng bước khi phù hợp, không bịa thông tin, và trình bày công thức toán bằng LaTeX chuẩn. "
        "Dùng \\(...\\) cho công thức trong dòng và \\[...\\] cho công thức riêng dòng; không đặt công thức toán trong khối mã. "
        "Khi phân tích ảnh, mô tả đúng những gì nhìn thấy và nói rõ nếu ảnh không đủ rõ để kết luận."
    )}
    if image:
        if not VISION_MODEL:
            return jsonify({"error": "Hãy đặt GROQ_MODEL thành mã model có hỗ trợ hình ảnh."}), 500
        if mime not in ALLOWED:
            return jsonify({"error": "Chỉ hỗ trợ JPEG, PNG hoặc WEBP."}), 400
        try: raw = base64.b64decode(image, validate=True)
        except (binascii.Error, ValueError): return jsonify({"error": "Dữ liệu ảnh không hợp lệ."}), 400
        if len(raw) > 6 * 1024 * 1024:
            return jsonify({"error": "Ảnh tối đa 6 MB."}), 413
        content = [{"type": "text", "text": prompt or "Phân tích hình ảnh này bằng tiếng Việt."},
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}}]
        model, user_content = VISION_MODEL, content
    else:
        model, user_content = TEXT_MODEL, prompt
    answer, status, detail = ask_groq(model, [system, {"role": "user", "content": user_content}])
    if status:
        return jsonify({"error": "Groq API báo lỗi.", "status": status, "detail": detail, "model_used": model}), status
    return jsonify({"reply": answer, "model_used": model})

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "Dữ liệu quá lớn; hãy giảm kích thước ảnh."}), 413

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
