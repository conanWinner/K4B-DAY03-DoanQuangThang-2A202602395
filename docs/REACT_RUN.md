# Chạy Task 2.2 — ReAct cho cà phê

Lịch chăm sóc hiện lưu tại `data/farm_tasks.json`: file text UTF-8 có xuống dòng, thụt lề và tiếng Việt đầy đủ. Mở file bằng VS Code để xem từng mã lịch, mã lô, công việc, thời gian và ghi chú. Có thể đổi đường dẫn qua biến `FARM_TASKS_FILE`; biến `FARM_TASKS_DB` cũ không còn sử dụng.

Một lịch từ `data/farm_tasks.sqlite3` đã được chuyển sang JSON; SQLite gốc vẫn được giữ lại làm bản đối chiếu, không còn được ứng dụng ghi thêm. Bộ lưu JSON dùng khóa file Linux để tránh mất lịch khi UI và CLI ghi đồng thời. Khi JSON lỗi, hệ thống báo lỗi và giữ nguyên file. Nếu máy chủ UI đang chạy phiên bản cũ, khởi động lại để dùng bộ lưu mới.

Vòng xử lý: LLM đề xuất tool → MCP mô phỏng thực thi → Observation được đưa vào lịch sử → LLM tiếp tục hoặc trả lời. CLI giữ lịch sử trong một phiên; test cases chạy với lịch sử độc lập. Có giới hạn 8 lượt LLM và tối đa 8 tool call mỗi lượt; từng lời gọi LLM có timeout 30 giây, không tự retry hoặc chuyển sang Mock khi lỗi.

## Chạy thử

```bash
# Demo offline chỉ tra cứu lô, không chứng minh khả năng suy luận của LLM:
LLM_PROVIDER=mock .venv/bin/python src/app.py --interactive

# Dùng provider/model và key đã cấu hình trong .env:
.venv/bin/python src/app.py --interactive

# Chạy các câu hỏi, không lưu lịch khi chưa xác nhận:
.venv/bin/python src/app.py --all

# Cho phép hỏi xác nhận từng lịch trong bộ câu hỏi:
.venv/bin/python src/app.py --all --confirm-schedules

# In thêm phản hồi chatbot không có tool trên cùng câu hỏi:
.venv/bin/python src/app.py --all --baseline

# Kiểm tra logic và adapter với dữ liệu/SDK giả lập:
.venv/bin/python -m unittest discover -s tests -v
```

CLI hiển thị tham số lịch và yêu cầu gõ `yes` trước khi lưu. Nếu không xác nhận, Observation trả `CANCELLED` hoặc `CONFIRMATION_REQUIRED`, không tạo lịch. Đây là chốt kiểm tra tại lớp thực thi; prompt cũng yêu cầu không đề xuất ghi lịch khi người dùng nói “chưa tạo lịch”. Callback trong kiểm thử chỉ cho phép ghi vào JSON thử nghiệm riêng.

`--all` chỉ báo đã thực thi, chưa tự chấm đáp án đạt/không đạt. TC03 cần xác nhận để kiểm tra lưu lịch; TC04 cần thêm lượt trò chuyện để chọn thời gian, cung cấp thông tin còn thiếu và ghi lịch. Nghiệm thu đủ 5 tình huống với API thật thuộc Task 3.1.

## Bằng chứng và phạm vi

Trace mới được lưu riêng trong `docs/traces/`, có run_id, case_id, provider/model, mode, lời gọi tool, Observation và thời gian đo bằng đồng hồ đơn điệu. Trường `thought` là tóm tắt hành động, không phải suy luận nội bộ của mô hình. Có thể dùng `--trace <tệp-mới.json>`; chương trình từ chối ghi đè tệp tồn tại. Trace starter `docs/trace_waterfall.json` được giữ nguyên; chưa coi là bằng chứng đề tài cà phê.

Gemini giữ nguyên Content và chữ ký do provider trả về khi gửi lịch sử; OpenAI giữ tool_call_id và các tool message tương ứng. Các kiểm thử adapter không phát sinh lời gọi LLM thật.

Tài liệu đối chiếu: [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling), [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).

Môi trường `.venv` hiện dùng Python 3.13.12 và đã chạy bộ kiểm thử; chưa kiểm tra trên Python 3.10–3.12 theo khuyến nghị của CODELAB. Dữ liệu lô mô phỏng; dự báo thật khi gọi Open-Meteo; lịch chỉ lưu cục bộ. Mock demo không gọi API thời tiết và không tự động tạo lịch.

## Task 3.1 — Nghiệm thu LLM thật

Điền key hợp lệ trực tiếp trong `.env`, chọn `LLM_PROVIDER` và `LLM_MODEL` tương ứng rồi chạy:

```bash
.venv/bin/python scripts/run_acceptance.py
```

Mỗi lần chạy tạo thư mục mới trong `docs/acceptance/` chứa snapshot kết quả, trace theo TC và DB thử nghiệm riêng. Script probe LLM trước; dừng khi lỗi LLM, không fallback Mock. Chỉ tự cho phép đúng lịch mẫu TC03 trong DB thử nghiệm; không ghi vào lịch sử dụng. Sau khi chạy phải đọc câu trả lời để chấm nội dung, thử CLI với LLM thật và kiểm tra lượt tiếp theo TC04. Chưa tự thay thế `docs/trace_waterfall.json` hay đánh dấu báo cáo đã hoàn thành.

## Kết nối 9router

Dự án hỗ trợ provider `9router` qua Chat Completions tương thích OpenAI. Điền vào `.env`:

```dotenv
LLM_PROVIDER=9router
NINE_ROUTER_BASE_URL=http://localhost:20128/v1
NINE_ROUTER_API_KEY=your_9router_api_key_here
NINE_ROUTER_MODEL=your_model_id_from_9router
```

URL trên chỉ là ví dụ chạy local; dùng URL thực tế của bạn. Model phải là ID model/combo trên dashboard có hỗ trợ tool calling. `NINE_ROUTER_MODEL` độc lập với `LLM_MODEL`, tránh vô tình dùng tên Gemini cũ. Key là key do 9router cấp, không cần key Gemini/OpenAI trực tiếp trong app. Không gửi key qua chat hoặc commit `.env`.

```bash
.venv/bin/python scripts/run_acceptance.py
.venv/bin/python src/app.py --interactive
```

Trace ghi provider `NineRouterProvider` và tên model yêu cầu. Nếu 9router dùng combo/fallback, tên này không chứng minh model upstream thực sự phục vụ; đối chiếu log 9router khi nghiệm thu. App không tự fallback Mock. 25 kiểm thử local đã đạt, trong đó bài kiểm tra 9router dùng HTTP giả lập với SDK thật, chưa chứng minh router/LLM live đã hoạt động.

Tham khảo: [Hướng dẫn tích hợp chính thức 9router](https://github.com/decolua/9router/blob/master/gitbook/content/en/integration/other-tools.md).

## Giao diện quan sát bài lab

Có thể xác nhận lịch qua chat bằng “Tôi đồng ý lưu lịch” hoặc bật ô cho phép ghi lịch. Với lịch đang chờ, backend đối chiếu tham số để chỉ lưu đúng lịch đã đề xuất; không cần bật thêm checkbox sau khi xác nhận qua chat. Chưa xác nhận trả `CONFIRMATION_REQUIRED`, không gán nhầm thành người dùng từ chối.

```bash
.venv/bin/python src/web_server.py --port 8080
```

Mở `http://127.0.0.1:8080`. UI có khu chat, trình sửa system prompt, trạng thái provider, danh sách MCP tools và trace trực tiếp khi LLM hoặc tool chạy. Tùy chọn “Cho phép ghi lịch trong lượt này” chỉ có hiệu lực cho đúng một yêu cầu và tự tắt sau đó. Nút “Phiên mới” tạo session mới, không xóa session trước.

UI dùng HTML, CSS và JavaScript thuần để bài lab không cần thêm dependency frontend. Máy chủ chỉ lắng nghe `127.0.0.1` theo mặc định. Mục tiêu kiểm tra: desktop local, LCP dưới 2,5 giây, JavaScript dưới 80 KB, Lighthouse accessibility và performance từ 90 điểm, WCAG AA ở mức bài lab.
