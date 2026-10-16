# Study AI — chatbot học tập có AI thật

Ứng dụng web dùng Flask làm backend và gọi Groq Chat Completions API. API key chỉ nằm trong biến môi trường của máy chủ, không nằm trong mã giao diện.

## Cách chạy trên máy tính

1. Cài Python 3.10 trở lên.
2. Tạo API key trong tài khoản Groq Console: https://console.groq.com/keys
3. Cài thư viện:
   ```bash
   pip install -r requirements.txt
   ```
4. Đặt biến môi trường `GROQ_API_KEY`:
   - macOS/Linux:
     ```bash
     export GROQ_API_KEY="dán_api_key_của_bạn_vào_đây"
     python app.py
     ```
   - Windows PowerShell:
     ```powershell
     $env:GROQ_API_KEY="dán_api_key_của_bạn_vào_đây"
     python app.py
     ```
5. Mở http://127.0.0.1:5000

Không gửi API key cho người khác và không ghi key vào `app.py`, `index.html` hoặc GitHub.

## Đưa lên mạng bằng GitHub + Render

1. Giải nén thư mục này.
2. Tạo repository mới trên GitHub và tải các file trong thư mục lên. Không tải API key lên GitHub.
3. Mở https://render.com, đăng nhập và chọn **New → Web Service**, kết nối repository.
4. Dùng các thiết lập:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Instance Type: Free (nếu tài khoản còn lựa chọn này)
5. Trong mục **Environment**, thêm:
   - `GROQ_API_KEY` = API key lấy từ Groq Console
   - `GROQ_MODEL` = `llama-3.3-70b-versatile`
6. Deploy. Render sẽ cấp URL dạng `https://ten-ung-dung.onrender.com`.

Render free có thể ngủ khi không có người dùng và cần một lúc để khởi động lại. Hạn mức API do nhà cung cấp AI quy định và có thể thay đổi; hãy kiểm tra bảng giá/hạn mức hiện tại trước khi dùng nhiều.

## Kiểm tra nhanh

- Trang chính: `/`
- Trạng thái cấu hình: `/api/status`
- Gửi câu hỏi: `POST /api/chat` với JSON `{"messages":[{"role":"user","content":"Giải thích định luật Newton"}]}`

## Ghi chú bảo mật

Bản mẫu chưa có đăng nhập, giới hạn sử dụng theo người dùng, cơ sở dữ liệu dùng chung hay chống lạm dụng nâng cao. Không đưa dữ liệu riêng tư/nhạy cảm vào chatbot. Nếu chia sẻ công khai, nên bổ sung giới hạn tần suất và theo dõi chi phí/hạn mức.
