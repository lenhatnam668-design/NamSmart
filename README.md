# Nam Smart AI Web Application

Trợ lý thông minh Nam Smart hỗ trợ học tập và trò chuyện với giao diện web thân thiện.

## Cấu trúc dự án
- `app.py`: Mã nguồn chính Flask kết nối Groq AI API.
- `templates/index.html`: Giao diện trang chủ và giao diện chat.
- `static/`: Chứa file logo (logo.jpg).
- `requirements.txt`: Các thư viện cần thiết.
- `render.yaml`: Cấu hình deploy tự động lên Render.

## Hướng dẫn chạy cục bộ
1. Cài đặt thư viện: `pip install -r requirements.txt`
2. Đặt biến môi trường `GROQ_API_KEY` của bạn.
3. Chạy ứng dụng: `python app.py`
