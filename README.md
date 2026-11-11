# Sentinel — Hệ thống theo dõi OSINT địa chính trị thời gian thực

**Đồ án tốt nghiệp Đại học (Văn bằng 2, Học viện Kỹ thuật Quân sự)**
Tác giả: **Mạc Lê Đại Dương** · Giáo viên hướng dẫn: **Đại tá, TS. Phạm Văn Việt**

Sentinel là một pipeline (luồng xử lý tự động) khai thác tình báo nguồn mở
(OSINT) về các sự kiện quân sự và xung đột, vận hành theo chuỗi sáu bước:

**ingest → converge → cluster → score → verify → visualize**

1. **Thu thập (ingest)** — GDELT 2.0 (mã CAMEO gốc 14–19) và ACLED;
2. **Phát hiện hội tụ địa lý (converge)** — gán sự kiện vào ô lưới 1°×1°;
3. **Gom cụm mật độ (cluster)** — DBSCAN với khoảng cách Haversine trong từng ô;
4. **Chấm điểm tin cậy (score)** — `conf_score` (Điểm Tin cậy Đồng thuận);
5. **Kiểm chứng chéo nguồn + sinh bản tin (verify)** — cỗ máy nhất quán
   (`consistency_score`) và sinh SITREP có trích dẫn nguồn cho từng câu;
6. **Trực quan hoá (visualize)** — bản đồ tương tác hai chế độ (Next.js) và
   bảng điều khiển Streamlit kế thừa.

Tài liệu đặc tả thiết kế đầy đủ nằm trong **`specs.md`** (là tài liệu chuẩn
quyền uy, mọi chi tiết ở README này phải nhất quán với nó).

---

## 1. Tính năng chính

### 1.1. Nguồn dữ liệu và lọc sự kiện

- **GDELT 2.0**: sự kiện cập nhật mỗi 15 phút; chỉ giữ nhóm mã CAMEO gốc
  14–19 (hành vi đối đầu, bạo lực) và kéo cả tệp GKG 2.1 để lưu tiêu đề
  bài báo thật làm ngữ cảnh (FR-25); nếu GKG lỗi, tự hạ cấp về tên tác nhân.
- **ACLED**: bổ sung qua API myACLED (bậc học thuật, giới hạn 1 yêu cầu/giây);
  khi không có thông tin xác thực ACLED, hệ thống chạy chỉ với GDELT.
- Toàn bộ sự kiện được chuẩn hoá về bảng `events` (phân mảnh theo tháng).

### 1.2. Phát hiện hội tụ địa lý (World Monitor — FR-WM-CONVERGENCE)

- Chia bề mặt Trái Đất thành ô lưới 1°×1°; mỗi ô tính điểm hội tụ theo đúng
  công thức World Monitor:
  `type_score = số loại sự kiện × 25`, `count_boost = min(25, số sự kiện × 2)`,
  `convergence_score = min(100, type_score + count_boost)`.
- Một ô trở thành **vùng hội tụ khi `convergence_score ≥ 1`** (≥ 1 sự kiện
  đã phân loại trong cửa sổ 24 h); **2+ loại sự kiện khác nhau nâng mức cảnh
  báo chứ KHÔNG phải điều kiện bắt buộc** — vì vậy vùng chỉ có GDELT vẫn phát
  sinh điểm nóng.
- Mức cảnh báo (`alert_level`): **Critical** (≥ 4 loại, 80–100; ≥ 3 loại,
  70–100), **High** (2–3 loại, 50–80), **Medium** (2 loại, 25–55).

### 1.3. Gom cụm DBSCAN

- Trong từng ô hoạt động, gom cụm các sự kiện bằng DBSCAN
  (`eps` mặc định 50 km, `min_samples` mặc định 3 — cấu hình qua
  `SENTINEL_DBSCAN_EPS_KM`, `SENTINEL_DBSCAN_MIN_SAMPLES`) và phạt thời gian
  qua `SENTINEL_MAX_TIME_DIFF_H`; xử lý biên kinh tuyến ±180° và vùng cực.
- Kết quả là các **điểm nóng (hotspot)**; tâm cụm tính bằng PostGIS
  `ST_Centroid(ST_Collect(...))`. Mỗi điểm nóng có định danh bất biến khi
  chạy lại để chỉ tốn đúng một lượt LLM.

### 1.4. Điểm Tin cậy Đồng thuận — `conf_score` (đóng góp nghiên cứu 1, FR-7/8/9)

```
source_density = tanh( Σ_domain trust_score(domain) / D ),   D = SENTINEL_CONF_DENSITY_DIVISOR (mặc định 3)
geo_diversity  = entropy Shannon(mã quốc gia nguồn) / log2(N)
conf_score     = (0,7 × source_density + 0,3 × geo_diversity) × 100
```

- Các trọng số 0,7 / 0,3 và ước số D cấu hình được qua biến môi trường
  `SENTINEL_CONF_W_DENSITY`, `SENTINEL_CONF_W_DIVERSITY`,
  `SENTINEL_CONF_DENSITY_DIVISOR`.
- Bậc tin cậy nguồn (`sources.trust_tier`) quản trị được qua API/UI; thay đổi
  được lan truyền xuống điểm số ở chu kỳ kế tiếp.

### 1.5. Cỗ máy Nhất quán — `consistency_score` (đóng góp nghiên cứu 2, FR-22)

- **Bước 6a**: LLM (NIM/Ollama/DeepSeek/Kimi) chỉ đóng vai trò *trích xuất
  mệnh đề* từ văn bản bằng chứng; phán xử do mô hình NLI cục bộ
  (cross-encoder, CPU) đảm nhiệm; thuật toán tổng hợp do đề tài tự thiết kế:
  mỗi mệnh đề quy về các trạng thái **corroborated / uncorroborated /
  disputed** theo trọng số tin cậy tên miền (`support`, `dispute`), rồi
  `consistency_score = 100 × Σ|support − dispute| × v / Σ w` (v = 1 / 0,5 / 0).
- Mô-đun chạy trong `pipeline/consistency.py`, `pipeline/nli.py`; điểm và
  dữ liệu mệnh đề lưu ở `hotspots`, `claims`, `claim_evidence`
  (migration 020–023).
- Trích dẫn bắt buộc: mỗi câu SITREP phải kết thúc bằng chỉ số `[N]`
  (một hoặc hai bên dấu chấm câu; FR-11/12/23) và được kiểm định bằng
  `validate_citations()`.

### 1.6. Cổng liên quan ngữ nghĩa (FR-26) — bảo vệ chất lượng NLI

- Trước khi đưa cặp (bằng chứng, mệnh đề) vào NLI, kiểm tra độ tương đồng
  ngữ nghĩa bằng mô hình nhúng câu cục bộ; cặp dưới ngưỡng bị chặn
  (`SENTINEL_RELEVANCE_MIN_SIM`/`MIN_PEAK`/`MAX_HOMOGENEITY`).
- Mô hình nhúng theo chính sách **fail-closed**: không nạp được thì bỏ qua
  điểm nóng đó (im lặng) chứ không phán xử thiếu cổng lọc; chỉ số quan trắc
  lưu ở cột `relevance_gate_*` (migration 022).

### 1.7. Sinh bản tin SITREP và các tính năng hiển thị

- `generate_sitrep()` là điểm vào chung cho pha 6a (nhất quán) và 6b
  (sinh bản tin có trích dẫn); có cơ chế dự phòng LLM khi dịch vụ chính lỗi.
- Gộp URL trùng (`collapse_duplicate_urls`) với hợp đồng "lockstep" giữa các
  truy vấn sinh danh sách nguồn (FR-27) và script vận hành
  `scripts/invalidate_stale_sitreps.py`.
- So sánh điểm nóng hai cửa sổ thời gian + **tự kiểm chứng phía máy khách**
  (FR-28): giao diện chạy lại đúng công thức trên dữ liệu cửa sổ để đối chiếu
  với điểm máy chủ công bố; nếu lệch, hạ cấp về chế độ chỉ-số-đếm.
- Điểm truy cập báo cáo `GET /hotspots/{id}/report` (FR-29) sinh bản tường
  trình chuỗi xử lý; dịch hiển thị tiếng Việt (FR-30) và chuỗi nhà cung cấp
  LLM trả phí DeepSeek/Kimi (FR-31) bật theo biến môi trường.

---

## 2. Kiến trúc và các thành phần

Hệ thống có **hai chế độ vận hành dùng chung mã nghiệp vụ**:

1. **Monolith** điều phối bằng APScheduler (`python -m pipeline.pipeline`);
2. **Phân tán** — 5 worker nối thành dây chuyền qua Redis Streams:

```
ingestion-worker → gridcell-worker → clustering-worker → consensus-worker → llm-worker
   (GDELT/ACLED)     (ô lưới 1°)       (DBSCAN)           (conf_score)       (SITREP 6a/6b)
```

| Thư mục / tệp | Vai trò |
| --- | --- |
| `pipeline/` | Mã nghiệp vụ: ingestion (GDELT+ACLED+GKG), clustering (lưới+DBSCAN), scoring (conf_score), consistency.py + nli.py + relevance.py (cỗ máy nhất quán & cổng liên quan), llm_verifier.py (SITREP), gkg.py, streams.py + workers/ (5 worker), db.py + pool.py (gộp kết nối PgBouncer, luôn `get_pooled_connection()` + trả kết nối trong `finally`), pipeline.py (điều phối) |
| `api/` | Cổng FastAPI (REST + SSE), xác thực JWT, giới hạn tốc độ, chỉ số |
| `frontend-next/` | Giao diện chính (Next.js): bản đồ kép 2D (MapLibre + deck.gl) / địa cầu 3D (globe.gl), mã màu + vòng cảnh báo FR-13, bảng chi tiết hotspot/SITREP/bằng chứng, tìm kiếm–bộ lọc–song ngữ, login/SSE |
| `frontend/` | Bảng điều khiển Streamlit (Pydeck) — bản kế thừa, đọc trực tiếp DB |
| `db/init/` | 22 migration đánh số 001→023 (không có 004): bảng sự kiện (phân mảnh theo tháng), hotspots, sources (trust_tier), grid_cells, users, phân vùng, chỉ mục GIST + FTS, các migration cỗ máy nhất quán 020–023 |
| `tests/` | Bộ kiểm thử pytest (đơn vị, tích hợp, hồi quy ghim bằng dữ liệu thật) |
| `eval/consistency/` | Bộ công cụ đánh giá khoa học: xuất/chấm tập chuẩn vàng, tiêm mâu thuẫn, chụp dữ liệu & quay lui trọng số |
| `scripts/` | Tác vụ vận hành: tạo/dọn phân vùng, nạp polygon quốc gia, vô hiệu hoá SITREP cũ, rescore consistency |
| `load/` | Kiểm thử tải SSE/API bằng Locust |
| `docker/` | Dockerfile và cấu hình đóng gói |
| `docs/` | Runbook vận hành, cheatsheet bảo vệ đồ án (`docs/cheatsheets/`), tài liệu phân tích |
| `specs.md` | Tài liệu đặc tả thiết kế (chuẩn quyền uy) |

---

## 3. Yêu cầu vận hành và cấu hình

Mọi cấu hình qua biến môi trường; tệp mẫu: **`sentinel.env.example`**
(chép sang `sentinel.env` khi chạy). Một số nhóm chính:

| Nhóm | Biến tiêu biểu |
| --- | --- |
| Cơ sở dữ liệu | `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`, `PGBOUNCER_*` |
| LLM (SITREP/trích mệnh đề) | `NVIDIA_NIM_ENDPOINT/_API_KEY/_MODEL`, `OLLAMA_ENDPOINT`, `SENTINEL_LLM_THRESHOLD` |
| Chuỗi LLM trả phí | `SENTINEL_LLM_PROVIDERS`, `DEEPSEEK_*`, `MOONSHOT_*`, `SENTINEL_LLM_PAID_MIN_CONF` |
| ACLED | `ACLED_EMAIL/_PASSWORD` hoặc `ACLED_ACCESS_TOKEN` / `ACLED_REFRESH_TOKEN` |
| Pipeline | `SENTINEL_LOOKBACK_HOURS`, `SENTINEL_DBSCAN_WINDOW_HOURS`, `SENTINEL_DBSCAN_EPS_KM`, `SENTINEL_DBSCAN_MIN_SAMPLES`, `SENTINEL_POLL_INTERVAL_S`, `SENTINEL_RETENTION_DAYS` |
| conf_score (FR-7/8/9) | `SENTINEL_CONF_W_DENSITY` (0,7), `SENTINEL_CONF_W_DIVERSITY` (0,3), `SENTINEL_CONF_DENSITY_DIVISOR` (3) |
| Cỗ máy nhất quán (FR-22) | `SENTINEL_NLI_MODEL`, `SENTINEL_NLI_MIN_PROB` (0,6), `SENTINEL_CONSISTENCY_DISPUTE_RATIO`, `SENTINEL_CONSISTENCY_MAX_CLAIMS`, `SENTINEL_CONSISTENCY_MAX_DOMAINS`, `SENTINEL_CONSISTENCY_MIN_CLAIM_WORDS` |
| GKG (FR-25) | `SENTINEL_GKG_ENABLED`, `SENTINEL_GKG_TIMEOUT_S`, `SENTINEL_GKG_BACKFILL_DAYS` |
| Cổng liên quan (FR-26) | `SENTINEL_RELEVANCE_ENABLED`, `SENTINEL_RELEVANCE_MODEL`, `SENTINEL_RELEVANCE_MIN_SIM` (0,35), `SENTINEL_RELEVANCE_MIN_PEAK` (0,15), `SENTINEL_RELEVANCE_MAX_HOMOGENEITY` (0,75) |
| Báo cáo cửa sổ (FR-29), dịch (FR-30) | `SENTINEL_REPORT_RATE_PER_MIN`, `GOOGLE_TRANSLATE_API_KEY`, `SENTINEL_TRANSLATE_*` |
| Bảo mật | `SENTINEL_JWT_SECRET`, `SENTINEL_JWT_ALG`, `SENTINEL_JWT_TTL_MIN`, `SENTINEL_ENV`, `SENTINEL_TRUSTED_PROXIES` |

---

## 4. Chạy nhanh toàn bộ hệ thống (Docker)

```bash
cp sentinel.env.example sentinel.env   # lần đầu; sửa biến nếu cần
docker compose up -d --build
```

| Dịch vụ | Cổng host | Chức năng |
| --- | --- | --- |
| `frontend-next` | **3000** | Giao diện Next.js — **ứng dụng chính** |
| `api` | **8000** | FastAPI (REST + SSE), xác thực JWT |
| `postgres` | 5433 | PostgreSQL 15 + PostGIS |
| `pgbouncer` | 6432 | Gộp kết nối chế độ giao dịch |
| `redis` | 6379 | Bus luồng worker + bộ đệm |
| `ingestion/gridcell/clustering/consensus/llm-worker` | — | 5 worker pipeline |

Mở **http://localhost:3000** và đăng nhập. Tài khoản mặc định (seed lần đầu
khởi tạo DB):

| Người dùng | Mật khẩu | Vai trò |
| --- | --- | --- |
| `admin` | `admin` | quản trị |
| `analyst` | `analyst` | nhà phân tích |

> Đổi mật khẩu trước khi triển khai ra ngoài môi trường local. Auth dùng JWT
> (`SENTINEL_JWT_SECRET`); API **từ chối khởi động** ở `SENTINEL_ENV=production`
> nếu vẫn còn secret mặc định.

### Kiểm tra hệ thống

```bash
curl -s http://localhost:8000/health                                   # {"status":"ok"}
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'                         # -> {access_token,...}
```

Các route chính của API: `/health`, `/auth/login`, `/hotspots`,
`/hotspots/{id}/summary`, `/hotspots/{id}/report`, `/hotspots/stream` (SSE),
`/grid_cells`, `/events`, `/sources`, `/metrics`. Các route dữ liệu yêu cầu
header `Authorization: Bearer <token>`.

> Lưu ý khi phát triển: image Docker dùng `COPY . .` nên sau khi sửa mã Python
> (`api`, `pipeline`) hay frontend phải **build lại dịch vụ tương ứng**
> (`docker compose build <service> && docker compose up -d <service>`).

---

## 5. Chạy pipeline độc lập (không worker)

Chạy trực tiếp bằng Python với DB ở cổng `6432` (PgBouncer) hoặc `5433`:

```bash
python -m pipeline.ingestion --insert-db                          # nạp GDELT (kèm GKG nếu bật)
python -m pipeline.gkg --backfill --days 7                        # làm giàu tiêu đề (FR-25)
python -m pipeline.clustering --lookback-hours 6 --run-scoring    # lưới + DBSCAN + chấm điểm
python -m pipeline.scoring                                        # chỉ chấm điểm
python -m pipeline.consistency --hotspot-id N                     # cỗ máy nhất quán (FR-22)
python -m pipeline.llm_verifier --threshold 40                    # SITREP (cần LLM)
python -m pipeline.pipeline                                       # toàn bộ pipeline + lập lịch
```

Bảng điều khiển Streamlit kế thừa:

```bash
streamlit run frontend/app.py       # http://localhost:8501
```

---

## 6. Kiểm thử và đánh giá

```bash
pytest tests/                       # toàn bộ (Python)
pytest tests/test_ingestion.py -q   # một tệp
cd frontend-next && npm test        # giao diện (vitest)
```

Bộ đánh giá khoa học đặt tại `eval/consistency/`:

- Xuất và chấm **tập chuẩn vàng** gán nhãn tay (`export_gold.py`, `score_gold.py`);
- **Tiêm mâu thuẫn tổng hợp** (`inject.py`) để đo khả năng phát hiện mâu thuẫn
  (luôn kèm chỉ số `planted_premise_detected` khi trích kết quả);
- Chụp dữ liệu nhất quán (`snapshot.py`) và quay lui trọng số
  (`weight_backtest.py`) để so công thức `consistency_score`.

Kết quả đo, phương pháp và hạn chế được trình bày đầy đủ trong báo cáo đồ án
và `specs.md`.

---

## 7. Ghi chú triển khai

- Các migration trong `db/init/` chỉ chạy **một lần khi khởi tạo volume trống**;
  với volume đã tồn tại hoặc triển khai quản lý, áp dụng migration tường minh
  bằng `python -m pipeline.migrate apply`.
- Không sửa migration đã áp dụng; mọi thay đổi lược đồ về sau phải thêm
  migration mới (số tiếp theo).
- Mã nguồn tuân theo: `ruff.toml` (kiểm tra bằng `ruff check`), không truy
  vấn SQL thô ngoài `pipeline/db.py`, `api/queries.py` và các tệp migration,
  luôn dùng gộp kết nối `SentinelConnectionPool`.
- Xem thêm: `specs.md` (đặc tả), `AGENTS.md`/`CLAUDE.md` (quy ước dự án),
  `docs/` (runbook vận hành và cheatsheet bảo vệ).
