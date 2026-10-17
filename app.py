import os
import logging
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# Tải biến môi trường từ tệp .env (dùng khi chạy local)
load_dotenv()

# Cấu hình logging để theo dõi hoạt động và debug trên server (Render/Heroku/...)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Kiểm tra và khởi tạo OpenAI client
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    logger.warning("CẢNH BÁO: Chưa tìm thấy OPENAI_API_KEY trong biến môi trường!")

client = OpenAI(api_key=api_key)

@app.route('/')
def index():
    """Route hiển thị giao diện chính của trang web."""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def api_chat():
    """API endpoint nhận tin nhắn và hình ảnh từ giao diện, gọi OpenAI API và trả về kết quả."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dữ liệu yêu cầu không hợp lệ (không phải JSON)."}), 400

        messages = data.get('messages', [])
        if not messages:
            return jsonify({"error": "Danh sách tin nhắn trống."}), 400

        logger.info(f"Nhận yêu cầu xử lý chat, số lượng messages: {len(messages)}")

        # Lấy tên mô hình từ biến môi trường hoặc mặc định là gpt-4o-mini
        model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

        # Gọi OpenAI API (hỗ trợ cả văn bản và hình ảnh base64 gửi lên)
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7,
            max_tokens=2500
        )
        
        reply = response.choices[0].message.content
        logger.info("Đã nhận phản hồi thành công từ OpenAI API.")
        
        return jsonify({"reply": reply})

    except Exception as e:
        logger.error(f"Lỗi xử lý tại /api/chat: {str(e)}", exc_info=True)
        return jsonify({"error": f"Lỗi hệ thống từ phía Server: {str(e)}"}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Không tìm thấy đường dẫn API yêu cầu."}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Đã xảy ra lỗi máy chủ nội bộ."}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Đang khởi động máy chủ Flask tại cổng {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
