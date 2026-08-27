# Cheatsheet — Cổng liên quan ngữ nghĩa (M8 / FR-26)

Bộ tài liệu ôn tập tiếng Việt để **bảo vệ đồ án**, không phải tài liệu API và không phải hướng
dẫn vận hành. Mục tiêu: hiểu **bản chất** của cổng liên quan và trả lời được câu hỏi phản biện.

Mỗi file mở đầu bằng một hộp **TL;DR** để ôn nhanh ngay trước khi vào phòng.

| File | Nội dung |
|---|---|
| [01-nli-that-bai.md](01-nli-that-bai.md) | Vì sao mô hình NLI báo "mâu thuẫn" ở khắp nơi — tập nhãn 3 lớp không có lớp "không liên quan", vì sao nâng ngưỡng không cứu được, ca thật hotspot số 8, và số đo 50,8% disputed / 0 corroborated trước khi có cổng |
| [02-cong-lien-quan.md](02-cong-lien-quan.md) | Thiết kế cổng: tách một câu hỏi thành hai, luồng thật trong `consistency.py`, ba ngưỡng và lý do từng cái, chính sách fail-closed như ngoại lệ có chủ đích với NFR-3, vì sao hai cột thống kê để NULL chứ không để 0, và mục "câu hỏi thầy sẽ hỏi" |
| [03-minilm.md](03-minilm.md) | Mô hình nhúng câu `all-MiniLM-L6-v2` — bản đồ ngữ nghĩa 384 chiều, bóc tên `all`/`Mini`/`L6`/`v2`, vì sao huấn luyện contrastive bổ khuyết đúng chỗ NLI thiếu, và cảnh báo cosine đo cùng chủ đề chứ không đo cùng quan điểm |
| [04-vector-hoa-cau.md](04-vector-hoa-cau.md) | Năm bước biến một câu thành vector, bám sát `relevance.py` theo từng dòng — tokenize, tra bảng embedding, 6 lớp self-attention, mean-pooling với `attention_mask`, chuẩn hoá L2 |

## Nguồn đối chiếu

Mọi con số trong bộ tài liệu này khớp với **code hiện tại** hoặc với **báo cáo cuối kỳ**:

- Code: `pipeline/relevance.py`, `pipeline/consistency.py`, `pipeline/nli.py`,
  `db/init/022_relevance_gate_stats.sql`, `db/init/023_claim_origin_domains.sql`
- Đặc tả: `specs.md` §4.10 (FR-26-RELEVANCE_GATE)
- Báo cáo cuối kỳ: mục 2.2.1 (fail-closed / NFR-3), 3.4.3, 3.4.4, 4.3.3

Các ví dụ cosine được chạy trực tiếp trên `sentence-transformers/all-MiniLM-L6-v2` với đúng
phép gộp của `Embedder.embed` (mean-pool trên token thật + chuẩn hoá L2).

> **Số liệu đã bị loại bỏ:** con số *5 corroborated / 31 uncorroborated / 67 disputed* từng xuất
> hiện trong một bản nháp là **KHÔNG hợp lệ** — đo trên CSDL có cột `events.title` bị hỏng bởi
> một lần backfill M7 lỗi (một tiêu đề ghi đè lên 7.825 dòng / 2.727 URL phân biệt). Mốc nền
> đúng là **32 disputed / 31 uncorroborated / 0 corroborated** trên 63 mệnh đề, đo ngày
> 28/07/2026.
