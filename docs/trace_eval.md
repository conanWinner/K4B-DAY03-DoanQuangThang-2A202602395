# 📊 BÁO CÁO THU HOẠCH NGHIỆM THU BÀI LAB 3 (BƯỚC 3 — SUBMISSION ARTIFACT)

> **Họ và Tên Học viên:** Đoàn Quang Thắng
> **Mã Sinh Viên / Mã Học viên:** 02395
> **Chủ đề Lựa chọn:** Trợ lý AI nông nghiệp — thử nghiệm trên cây cà phê

### Bài toán và phạm vi

Người quản lý vườn cần tra cứu thông tin lô cà phê, xem dự báo thời tiết tại lô và ghi lịch chăm sóc như phun thuốc, tưới nước hoặc bón phân. Trợ lý kết hợp dữ liệu lô với dự báo để đề xuất thời điểm và hỏi lại khi thiếu thông tin; chỉ ghi lịch theo yêu cầu hoặc lựa chọn rõ ràng của người dùng.

Bản lab sử dụng dữ liệu lô mô phỏng, dự báo thời tiết từ API thật và lịch công việc lưu cục bộ. LLM thật được dùng ở bước nghiệm thu. Chế độ offline phục vụ kiểm tra logic và phải được phân biệt rõ trong báo cáo, không thay thế bằng chứng API thật.

Ba công cụ đã triển khai:

- `get_plot_info(plot_id)`: tra cứu vị trí và thông tin lô cà phê.
- `get_weather_forecast(latitude, longitude, days)`: lấy dự báo, kèm nguồn, thời điểm cập nhật và múi giờ.
- `schedule_farm_task(plot_id, task_type, scheduled_at, notes)`: ghi lịch công việc và trả mã lịch; thời gian được chuẩn hóa theo Asia/Ho_Chi_Minh.

Ví dụ nhiều bước: người dùng yêu cầu xem thời tiết lô CF001 trong ba ngày tới để chuẩn bị phun thuốc. Agent tra cứu lô, lấy dự báo theo tọa độ, trình bày các khung giờ và hỏi thông tin sản phẩm/điều kiện sử dụng còn thiếu. Khi người dùng chọn lịch, Agent ghi lịch và trả mã xác nhận. Dự báo không bảo đảm thời tiết thực tế; trợ lý không tự chọn thuốc, liều lượng hoặc khẳng định an toàn chỉ dựa trên thời tiết. Bản lab không điều khiển thiết bị thực tế.

---

## 1. BẢNG CHẤM ĐIỂM AGENTIC FIT SCORING MATRIX (ĐÁNH GIÁ CHỦ ĐỀ)

| Tiêu chí Đánh giá | Mức độ (1 - 5) | Giải trình chi tiết lý do chọn điểm |
| :--- | :---: | :--- |
| **1. Multi-step Reasoning** | 4 / 5 | Phải tìm vị trí lô, lấy dự báo, đối chiếu yêu cầu công việc rồi đề xuất hoặc ghi lịch; kết quả bước trước là đầu vào bước sau. |
| **2. Tool Interaction** | 5 / 5 | Cần công cụ đọc dữ liệu lô, lấy dự báo cập nhật và ghi lịch có mã xác nhận; chatbot chỉ sinh văn bản không thực hiện được các thao tác này. |
| **3. Dynamic Decision** | 4 / 5 | Tùy kết quả tra cứu và thời tiết, Agent có thể đề xuất thời điểm khác, hỏi thêm thông tin hoặc dừng khi lô không tồn tại/API lỗi. |
| **4. Long Horizon Goal** | 2 / 5 | Giữ mục tiêu qua các bước và lượt xác nhận trong một phiên; chưa tự theo dõi vườn dài hạn, cập nhật dự báo định kỳ hoặc tự điều chỉnh lịch. |
| **TỔNG ĐIỂM AGENTIC FIT** | **15 / 20** | Phù hợp với ReAct Agent cho tra cứu kết hợp lập lịch; câu hỏi giới thiệu đơn giản vẫn trả lời trực tiếp. |

### Bộ kiểm thử và điều kiện đạt

Chi tiết câu hỏi nằm trong `config/test_cases.json`. TC01 kiểm tra trả lời trực tiếp; TC02 lấy dự báo; TC03 ghi lịch cụ thể; TC04 kiểm tra chuỗi tra cứu lô → dự báo → đề xuất và hỏi lại; TC05 kiểm tra lô không tồn tại. TC04 chỉ được ghi lịch sau lượt người dùng chọn thời điểm. Khi nghiệm thu cần kiểm tra cả lịch thực sự được lưu, không chỉ câu trả lời của Agent.

Kiểm tra bổ sung cho các task kỹ thuật: dịch vụ thời tiết lỗi, thiếu tham số, lịch không hợp lệ, giới hạn vòng lặp và lỗi LLM. Khi nguồn dữ liệu lỗi, không được bịa dự báo hoặc báo thành công.

---

## 2. Kết quả nghiệm thu LLM thật

Ngày nghiệm thu: 13/09/2026, khoảng 20:09–20:12 (Asia/Ho_Chi_Minh).
Provider: NineRouterProvider, model yêu cầu: cx/gpt-5.5, qua 9router local.
Không dùng Mock cho bộ nghiệm thu này. Tên model là model yêu cầu qua gateway; không độc lập xác minh model upstream nếu router có fallback.

Bằng chứng: [trace nộp bài](trace_waterfall.json), [thư mục nghiệm thu](acceptance/20260913-200916-ae09f696/).
Trace starter cũ được giữ tại [bản lưu](traces/starter-waterfall-preserved.json).

| Ca | Kết quả | Bằng chứng quan sát |
| --- | --- | --- |
| TC01 | Đạt | Giới thiệu chức năng, trả lời trực tiếp, không gọi tool. |
| TC02 | Đạt | Gọi get_weather_forecast đúng tọa độ và 3 ngày; SUCCESS, dữ liệu LIVE_API từ Open-Meteo, có nguồn và thời điểm truy xuất. |
| TC03 | Đạt | schedule_farm_task trả SUCCESS; lịch CF001 lúc 07:00 ngày 14/09/2026 được đọc lại từ JSON, ghi chú đúng. |
| TC04 | Đạt theo phạm vi lab | get_plot_info → get_weather_forecast theo tọa độ trả về; đề xuất hai khung giờ, nhắc kiểm tra nhãn sản phẩm và không ghi lịch. Nội dung là gợi ý từ dự báo, chưa được chuyên gia nông nghiệp thẩm định. |
| TC05 | Đạt | get_plot_info trả NOT_FOUND cho CF999; yêu cầu kiểm tra lại mã lô, không gọi tool ghi lịch. |

Cả 5 ca qua kiểm tra cấu trúc; đã đọc câu trả lời cuối và đối chiếu các số liệu thời tiết tiêu biểu với Observation. TC04 nhắc người dùng kiểm tra sản phẩm/nhãn, nhưng có thể cải thiện bằng câu hỏi trực tiếp về sản phẩm trước khi đề xuất chi tiết.

Mã lịch TC03: `0cfc23ee-1cb2-4eea-9cf4-5f49dd779782`. Tổng số tool execution trong bộ 5 ca: 5 lượt (4 SUCCESS, 1 NOT_FOUND đúng kỳ vọng). Tổng cộng 15 sự kiện trong trace chính.

Trích đoạn Observation thực chạy (rút gọn trường để trình bày; bản đầy đủ ở trace chính):

```json
{
  "case_id": "TC03",
  "provider": "NineRouterProvider",
  "model": "cx/gpt-5.5",
  "mode": "LIVE_API",
  "action_type": "TOOL_EXECUTION",
  "tool_name": "schedule_farm_task",
  "observation": {
    "status": "SUCCESS",
    "storage": "LOCAL_JSON",
    "task": {
      "task_id": "0cfc23ee-1cb2-4eea-9cf4-5f49dd779782",
      "plot_id": "CF001",
      "task_type": "irrigation_inspection",
      "scheduled_at": "2026-09-14T07:00:00+07:00",
      "notes": "kiểm tra đầu tưới bị tắc"
    }
  }
}
```

### Hội thoại tương tác và so sánh baseline

Đã chạy `src/app.py --interactive` qua 9router thật: lượt đầu tra cứu CF001 và thời tiết, chưa ghi lịch; lượt tiếp theo yêu cầu ghi lịch cho “lô vừa tra cứu”, Agent dùng đúng CF001, hỏi xác nhận lịch cụ thể và ghi JSON sau khi nhập `yes`. Mã lịch: `ff9ff27b-8e3e-45dd-8e0a-f509589bcd5f`. Đã đọc lại file và xác nhận có 1 lịch. [Trace tương tác](acceptance/20260913-200916-ae09f696/interactive-trace.json).

Chatbot baseline trên cùng yêu cầu TC03 nói rõ không có công cụ lưu lịch và chỉ đưa nội dung để người dùng tự ghi. Agent tạo được lịch với mã xác nhận. Lịch nghiệm thu lưu riêng, không ghi vào lịch sử dụng.

UI có chat, sửa system prompt, trạng thái tool và Observation. API UI đã kiểm tra bằng giả lập; chưa nghiệm thu trực quan UI bằng trình duyệt ở lần này. Bản sửa xác nhận qua chat đã có kiểm thử HTTP hai lượt: CONFIRMATION_REQUIRED → SUCCESS → ALREADY_EXISTS khi gửi lại. Không dùng kiểm thử này thay cho bằng chứng LLM live.

## 3. Tổng kết và nộp bài

- [x] Có bảng Agentic Fit và 5 test case.
- [x] Có 3 tool schema, MCP mô phỏng và vòng ReAct nhiều bước.
- [x] Nghiệm thu 5/5 ca qua LLM thật trên 9router.
- [x] Có trace chính và trích đoạn thực chạy trong báo cáo.
- [x] Thử CLI nhiều lượt, xác nhận lịch và kiểm tra JSON.
- [x] 33 kiểm thử tự động local đạt.
- [x] Commit/push bản hoàn thiện và xác minh GitHub: commit `3858ed6`, nhánh `main` trên remote khớp commit local.
- [ ] Nộp URL repository lên LMS VLearn (học viên thực hiện).

Repository: https://github.com/conanWinner/K4B-DAY03-DoanQuangThang-2A202602395

Giới hạn: dữ liệu lô mô phỏng; dự báo từ API thật; lưu lịch JSON cục bộ, chưa điều khiển thiết bị. MCP là mô phỏng trong tiến trình theo starter, chưa có transport/handshake đầy đủ. Môi trường chạy Python 3.13.12; CODELAB khuyến nghị 3.10–3.12, chưa kiểm tra lại trên các phiên bản này. Ứng dụng không tự chọn thuốc/liều hoặc bảo đảm an toàn phun.
