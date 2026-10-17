import os
import json
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai

app = Flask(__name__, static_folder='static', static_url_path='/static')

# Đảm bảo Flask trả về JSON chuẩn UTF-8 (không bị lỗi ký tự tiếng Việt)
app.config['JSON_AS_ASCII'] = False

# 1. Cấu hình Gemini AI API Key (Lấy từ môi trường hoặc điền trực tiếp)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
genai.configure(api_key=GEMINI_API_KEY)

# Khởi tạo model Gemini
model = genai.GenerativeModel('gemini-1.5-flash')

# Tệp lưu trữ lịch sử cuộc trò chuyện
HISTORY_FILE = 'chat_history.json'

def load_history():
    """Tải lịch sử chat từ file JSON"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Lỗi đọc file lịch sử: {e}")
            return []
    return []

def save_history(history):
    """Lưu lịch sử chat vào file JSON"""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Lỗi lưu file lịch sử: {e}")

@app.route('/')
def home():
    """Trang chủ hiển thị giao diện Web"""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """API tiếp nhận câu hỏi của người dùng và gọi AI trả lời"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()

        if not user_message:
            return jsonify({'error': 'Tin nhắn không được để trống'}), 400

        # Gọi mô hình Gemini AI để tạo phản hồi
        # Bạn có thể thêm ngữ cảnh cho bot Nam Smart ở đây
        prompt = f"Bạn là trợ lý thông minh Nam Smart. Hãy trả lời câu hỏi sau bằng tiếng Việt lịch sự, chính xác: {user_message}"
        response = model.generate_content(prompt)
        
        bot_reply = response.text if response and response.text else "Xin lỗi, Nam Smart chưa thể trả lời câu hỏi này ngay bây giờ."

        # Lưu cuộc trò chuyện vào lịch sử
        history = load_history()
        history.append({
            'user': user_message,
            'bot': bot_reply
        })
        save_history(history)

        return jsonify({'reply': bot_reply})

    except Exception as e:
        print(f"Lỗi xử lý chat: {e}")
        return jsonify({'reply': 'Đã có lỗi xảy ra khi kết nối với máy chủ AI. Vui lòng thử lại sau!'}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """API lấy toàn bộ lịch sử trò chuyện đã lưu"""
    return jsonify(load_history())

@app.route('/api/clear', methods=['POST'])
def clear_history():
    """API xóa lịch sử trò chuyện để bắt đầu cuộc hội thoại mới"""
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
        except Exception as e:
            print(f"Lỗi xóa file: {e}")
    return jsonify({'status': 'success', 'message': 'Đã xóa lịch sử chat thành công'})

if __name__ == '__main__':
    # Chạy ứng dụng Flask
    app.run(host='0.0.0.0', port=5000, debug=True)
