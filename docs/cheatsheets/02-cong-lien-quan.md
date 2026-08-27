# 02 — Thiết kế cổng liên quan ngữ nghĩa (FR-26)

> **TL;DR**
> Ý tưởng gốc là **tách một câu hỏi thành hai**: "hai câu này có nói về cùng một việc không?"
> (mô hình nhúng câu + cosine) và "nếu có thì chúng khớp hay chọi nhau?" (mô hình NLI).
> Mô hình NLI chỉ đủ tư cách trả lời câu thứ hai, và chỉ khi câu thứ nhất đã là "có".
> Ba ngưỡng (`MIN_SIM` 0,35 / `MIN_PEAK` 0,15 / `MAX_HOMOGENEITY` 0,75) và chính sách
> **fail-closed** là toàn bộ phần còn lại. Đo ngày 11/08/2026: cổng chặn **2.720 / 4.098 cặp
> (66,4%)**, tỉ lệ `disputed` giảm **50,8% → 16,8%**.

---

## 1. Ý tưởng gốc: một câu hỏi bị dồn vào một mô hình không trả lời được

Trước M8, hệ thống hỏi mô hình NLI **một câu hỏi gộp**:

```
"Hai câu này quan hệ thế nào?"     ->  NLI trả lời:  entail / neutral / contradict
```

Câu hỏi gộp đó thực ra chứa hai câu hỏi tách biệt:

```
Q1 (ABOUTNESS): "Hai câu có nói về CÙNG MỘT VIỆC không?"       <- NLI KHÔNG trả lời được
Q2 (STANCE)   : "Nếu có, chúng KHỚP hay CHỌI nhau?"            <- NLI trả lời rất tốt
```

FR-26 tách hai câu hỏi ra và giao mỗi câu cho đúng mô hình biết trả lời nó.

| | Mô hình nhúng câu (cổng) | Mô hình NLI (phán xử) |
|---|---|---|
| Tên | `sentence-transformers/all-MiniLM-L6-v2` | `cross-encoder/nli-deberta-v3-base` |
| Khai báo | `relevance.py:17`, đổi qua `SENTINEL_RELEVANCE_MODEL` | `nli.py:14`, đổi qua `SENTINEL_NLI_MODEL` |
| Huấn luyện trên | contrastive, hơn 1 tỉ cặp câu; hàng trăm triệu cặp là **cặp ghép ngẫu nhiên, không liên quan** | SNLI/MNLI, các cặp câu **luôn cùng mô tả một cảnh** |
| Đã từng thấy cặp KHÔNG liên quan chưa? | **Rồi**, và bị bắt phải đẩy chúng ra xa nhau | **Chưa bao giờ** |
| Trả lời được câu hỏi nào | **Q1** — cùng chủ đề hay không | **Q2** — khớp hay chọi |
| KHÔNG trả lời được | Q2: cosine không phân biệt "X xảy ra" với "X không xảy ra" | Q1: tập nhãn không có lớp "không liên quan" |
| Kiến trúc | bi-encoder (mã hoá từng câu riêng rồi so vector) | cross-encoder (nhét cả cặp vào cùng một lượt) |
| Chi phí | mã hoá N + M câu, rồi **một phép nhân ma trận** | N × M lượt chạy mô hình |

Dòng chi phí cuối bảng cũng là một lợi ích phụ đáng nói: cổng rẻ hơn hẳn thứ nó chặn.

## 2. Cổng cắm vào chỗ nào — luồng thật trong code

Toàn bộ nằm trong `run_consistency_engine` (`consistency.py:439-497`):

```
fetch_hotspot_evidence(conn, hotspot_id)                 consistency.py:449
    -> mỗi TÊN MIỀN một dòng bằng chứng (tối đa 20)
extract_claims(evidence, llm=llm)                        consistency.py:452
    -> 1 lời gọi LLM  ->  tối đa 8 mệnh đề nguyên tử
dedupe_claims(claims)                                    consistency.py:455
    -> gộp các mệnh đề trùng chữ, hợp nhất source_indices
+------------------ CỔNG LIÊN QUAN (FR-26) --------------------------+   consistency.py:463-474
|  if relevance_enabled():                                           |
|      embedder    = get_embedder()                                  |   :467
|      sim         = similarity_matrix(claims, evidence, embedder)   |   :469  (n_claims x n_evidence)
|      homogeneity = evidence_homogeneity(evidence_texts, embedder)  |   :470
|      claims, sim, dropped = filter_vacuous_claims(...)             |   :471
|      if not claims: return None                                    |   :472-473
|      gated = count_gated_pairs(sim)                                |   :474
+--------------------------------------------------------------------+
judge_claims(claims, evidence, judge, sim=sim)           consistency.py:479
    -> CHỈ cặp có sim >= MIN_SIM mới được đưa vào NLI    consistency.py:303
consensus(claims, evidence, judgments)                   consistency.py:480
hotspot_consistency_score(verdicts)                      consistency.py:481
ConsistencyRepository.save(..., gated_pairs, vacuous_claims_dropped)  consistency.py:483
```

**Cổng nằm giữa `extract_claims` và `consensus`** — cụ thể là ngay trước `judge_claims`. Đó là
vị trí duy nhất đúng: sau khi đã có mệnh đề để so, và trước khi bất kỳ cặp nào chạm tới NLI.

### Chi tiết thiết kế quan trọng: cặp bị chặn vẫn được ghi

`judge_claims` (`consistency.py:288-321`) bỏ qua cặp bị chặn khi gọi mô hình, nhưng **vẫn phát
ra một phán quyết cho MỌI cặp**, cặp bị chặn nhận `relation="neutral", probability=0.0`
(`consistency.py:315`).

Nhờ vậy bảng `claim_evidence` và hợp đồng trích dẫn FR-16 **không đổi một dòng nào**. Cổng chỉ
thay đổi **phán quyết**, không thay đổi **cấu trúc dữ liệu**. Đây là lý do có thể lắp cổng vào
một hệ thống đang chạy mà không phải sửa API, frontend hay bất kỳ consumer nào phía sau.

## 3. Ba ngưỡng — và vì sao cần từng cái

### 3.1 `SENTINEL_RELEVANCE_MIN_SIM = 0.35` — lọc từng cặp

`relevance.py:33-34`, dùng ở `consistency.py:298, 303`.

Một cặp (mệnh đề, bằng chứng) chỉ được đưa vào NLI khi cosine ≥ 0,35.

**Ví dụ số thật** (chạy trực tiếp trên `all-MiniLM-L6-v2`, tái dựng cấu hình hotspot số 8):

Bằng chứng:

```
E1: "Indian government issues notice to Meta over data sharing"
E2: "Rajya Sabha adjourned after opposition uproar"
E3: "Chief Justice of Pakistan warns against protest marches"
E4: "Court rules on the lathicharge incident"
```

Mệnh đề `C1: "The Indian government issued a notice to Meta."`

| cặp | cosine | ngưỡng 0,35 | đưa vào NLI? |
|---|---|---|---|
| C1 × E1 | **0,733** | ≥ | có |
| C1 × E2 | 0,189 | < | chặn |
| C1 × E3 | 0,241 | < | chặn |
| C1 × E4 | 0,139 | < | chặn |

Trước M8, ba cặp bị chặn kia được hỏi NLI và trả về `contradiction` với xác suất cao — đó
chính là ba lá phiếu đã biến C1 thành `disputed`. Sau M8 chúng không bao giờ tới được NLI.

### 3.2 `SENTINEL_RELEVANCE_MIN_PEAK = 0.15` — bộ lọc mệnh đề RỖNG NGHĨA

`relevance.py:37-38`, dùng ở `filter_vacuous_claims` (`consistency.py:239-265`).

Đây **không phải** ngưỡng bỏ cả cụm, và **không phải** một giá trị cosine tuyệt đối. Nó là
**độ nhô** của một hàng trong ma trận tương đồng:

```python
# consistency.py:258-262
peak = min_peak()
keep = [i for i in range(len(claims))
        if float(np.max(sim[i]) - np.median(sim[i])) >= peak]
```

**Điều kiện loại: `max(hàng) − median(hàng) < 0,15`.**

Lý do: một mệnh đề **rỗng nghĩa** như `"Russia is mentioned"` được **mọi** tiền đề kéo theo,
nên nó được "kiểm chứng" một cách tầm thường. Dấu hiệu nhận biết là hàng tương đồng của nó
**phẳng** — nó hơi giống mọi thứ và không đặc biệt giống thứ gì.

**Ca thật:** hotspot **24795** từng chứa **ba dòng** mệnh đề `"Russia is mentioned"`, mỗi dòng
đóng góp một trọng số riêng và đẩy điểm lên **87,4**. Điểm cao đó hoàn toàn vô nghĩa. FR-26
xử lý ca này bằng hai cơ chế cùng lúc:

- `dedupe_claims` (`consistency.py:220-236`) — gộp ba dòng trùng chữ thành một;
- `filter_vacuous_claims` — loại nốt cái còn lại vì hàng của nó phẳng.

**Ví dụ số thật**, vẫn trên bốn bằng chứng ở trên:

| Mệnh đề | hàng cosine | max | median | max − median | Kết quả |
|---|---|---|---|---|---|
| "The Indian government issued a notice to Meta." | 0,733 / 0,189 / 0,241 / 0,139 | 0,733 | 0,215 | **0,518** | giữ |
| "Officials responded to the situation." | 0,225 / 0,063 / 0,102 / 0,309 | 0,309 | 0,163 | 0,146 | **loại** |
| "Authorities took action in the region." | 0,281 / −0,031 / 0,059 / 0,284 | 0,284 | 0,170 | 0,114 | **loại** |

Số bị loại được ghi vào `hotspots.vacuous_claims_dropped`. Đo ngày 11/08/2026: **138 mệnh đề**
bị loại vì rỗng nghĩa trên toàn CSDL.

### 3.3 `SENTINEL_RELEVANCE_MAX_HOMOGENEITY = 0.75` — chốt an toàn cho bộ lọc trên

`relevance.py:41-42`, dùng ở `consistency.py:255`.

```python
# consistency.py:255-256
if not claims or homogeneity >= max_homogeneity():
    return list(claims), sim, 0        # -> BỘ LỌC RỖNG NGHĨA KHÔNG CHẠY
```

`evidence_homogeneity` (`relevance.py:126-138`) = **trung vị độ tương đồng từng cặp giữa các
dòng bằng chứng**, bỏ đường chéo:

```python
sim = vectors @ vectors.T
upper = sim[np.triu_indices(len(evidence_texts), k=1)]   # relevance.py:137
return float(np.median(upper))                            # relevance.py:138
```

**Vì sao cần chốt này — và vì sao nó là phần QUAN TRỌNG NHẤT, không phải một sự tinh chỉnh.**

Khi mọi dòng bằng chứng đều nói về **cùng một sự việc** (thường do nhiều báo đăng lại cùng một
bản tin gốc), thì một mệnh đề **CỤ THỂ và ĐÚNG** cũng có hàng tương đồng **phẳng** — nó giống
đều tất cả, vì tất cả đều đang nói đúng chuyện đó. Nếu để bộ lọc chạy, nó sẽ ném đi **đúng
trường hợp kiểm chứng chéo mà cỗ máy sinh ra để tưởng thưởng**.

**Ví dụ số thật.** Bốn bản tin cùng một sự việc:

```
"Airstrike hits ammunition depot in Kharkiv"
"Air strike hits an ammunition depot in Kharkiv"
"Ammunition depot in Kharkiv hit by airstrike"
"Kharkiv ammunition depot hit in airstrike"
```

```
evidence_homogeneity = 0,930      (>= 0,75  -> bộ lọc rỗng nghĩa TẮT)

Mệnh đề "An airstrike struck an ammunition depot in Kharkiv."
    hàng cosine = 0,912 / 0,864 / 0,911 / 0,911
    max - median = 0,912 - 0,911 = 0,001    (<< 0,15)
```

Một bộ lọc "phẳng thì loại" ngây thơ sẽ **ném đi mệnh đề tốt nhất trong toàn hệ thống**. Chốt
homogeneity giữ nó lại. Đối chiếu với cụm hotspot số 8 ở trên: `homogeneity = 0,128` — bốn chủ
đề khác nhau, có thứ để phân biệt, nên bộ lọc được phép chạy.

**Vì sao hàm trả về `1.0` khi có dưới 2 dòng bằng chứng** (`relevance.py:133-134`):

```python
if len(evidence_texts) < 2:
    return 1.0
```

Một dòng bằng chứng duy nhất thì **hiển nhiên là một chủ đề** — không có cặp nào để tính
trung vị, và cũng không có gì để phân biệt. Trả về 1,0 tức là "đồng nhất tuyệt đối", và vì
1,0 ≥ 0,75 nên bộ lọc rỗng nghĩa **không bao giờ kích hoạt** trong trường hợp một nguồn.
Đây là giá trị được chọn để **fail-safe**: trả 0,0 sẽ khiến mọi hotspot một nguồn bị bộ lọc
càn quét, vì hàng tương đồng chỉ có một phần tử nên `max − median = 0 < 0,15` luôn đúng.

### 3.4 Điểm yếu phải tự thừa nhận trước hội đồng

**0,35 được chọn bằng thực nghiệm trên dữ liệu của chính dự án, không lấy từ paper nào.**
Không có bộ dữ liệu chuẩn nào định nghĩa "ngưỡng aboutness đúng" cho tin tức OSINT quân sự.

Nên chủ động nêu điều này trước khi bị hỏi, kèm hai lập luận bù lại:

1. **Hai ngưỡng còn lại là chốt chặn ở hai đầu.** `MIN_PEAK` bắt các mệnh đề vượt cổng nhưng
   không phân biệt được gì; `MAX_HOMOGENEITY` chặn chính bộ lọc đó khi nó có nguy cơ làm hại.
   Sai số của một ngưỡng không truyền thẳng thành sai phán quyết.
2. **Hai cột quan trắc của migration 022 tồn tại đúng để tinh chỉnh con số này về sau.**
   Không có `gated_pairs` thì ngưỡng sẽ được chỉnh mù.

Và nêu luôn hướng làm đúng chuẩn: **thí nghiệm A/B có kiểm soát** — chạy lại **cùng một tập
hotspot** hai lần với `SENTINEL_RELEVANCE_ENABLED` bật/tắt trên **cùng một lần chụp dữ liệu**.
Đây là hạng mục đã được ghi vào phần hướng phát triển của báo cáo.

## 4. `RelevanceUnavailable` và chính sách FAIL-CLOSED

`relevance.py:22-23` định nghĩa ngoại lệ; `Embedder._ensure_loaded` (`relevance.py:61-74`) ném
nó ra khi torch/transformers/model không nạp được.

Trong `run_consistency_engine`, ngoại lệ này **cố ý không được bắt riêng**:

```python
# consistency.py:464-466
# RelevanceUnavailable propagates to the handler below: the engine
# skips rather than judging ungated, which is measured to be wrong
# on ~65% of claims (FR-26, fail-closed).
```

Nó rơi xuống `except Exception` ở `consistency.py:489`, engine `return None`, hotspot đó bị bỏ
qua, `consistency_score` giữ **NULL**. Thêm một khối `try/except` hẹp hơn quanh đoạn cổng sẽ
**vô hiệu hoá chính sách** — vì nuốt ngoại lệ đồng nghĩa với chạy tiếp mà không có cổng.

**Vì sao đây là lựa chọn đúng:**

```
Cổng hỏng  ->  phương án A: quay về cách cũ (phán xử không cổng)
                            = quay về hành vi ĐÃ ĐƯỢC ĐO là sai ~65% số mệnh đề
           ->  phương án B: KHÔNG KẾT LUẬN GÌ  (consistency_score = NULL)
```

Phương án A nghe có vẻ "suy giảm chức năng nhẹ nhàng", nhưng thực chất là **suy giảm về một
đầu ra sai đã biết trước**. Không có giá trị nào trong việc đó. Phương án B trả về "chưa đánh
giá" — trung thực và vô hại.

### Đây là một NGOẠI LỆ CÓ CHỦ ĐÍCH đối với NFR-3

NFR-3 (Tính sẵn sàng) quy định hệ thống phải chịu được gián đoạn của dịch vụ thượng nguồn —
tức mọi phụ thuộc ngoài đều theo triết lý **fail-open**: thành phần không dùng được thì suy
giảm chức năng chứ không chặn pipeline. FR-26 **cố ý đảo ngược** nguyên tắc này cho **riêng**
mô hình nhúng câu:

| Phụ thuộc | Chính sách | Khi không nạp được |
|---|---|---|
| Mô hình NLI (FR-22) | fail-**open** | Bỏ qua hotspot, `consistency_score` NULL, pipeline chạy tiếp, SITREP quay về prompt tiêu đề FR-11 |
| Mô hình nhúng câu (FR-26) | fail-**closed** | Cũng bỏ qua — **không** phán xử khi thiếu cổng lọc |
| Lối thoát vận hành | `SENTINEL_RELEVANCE_ENABLED=false` (`relevance.py:26-30`) | Người vận hành chủ động chấp nhận chế độ cũ |

Nguyên tắc thiết kế được bổ sung, đáng học thuộc:

> **Hệ thống được phép im lặng (`consistency_score` NULL = "chưa đánh giá"), nhưng không được
> phép nói sai một cách tự tin.**

Đây cũng là lý do `consistency_score` được khai báo nullable ngay từ migration 020, và giao diện
phân biệt rõ "chưa đánh giá" với "điểm bằng 0". Đo ngày 11/08/2026: 859 / 1.065 hotspot có
`consistency_score` NULL — **đó là chính sách đang hoạt động, không phải thất bại**.

## 5. Vì sao `gated_pairs` và `vacuous_claims_dropped` để NULL chứ không để 0

Migration 022 (`db/init/022_relevance_gate_stats.sql`):

```sql
-- FR-26: observability for the relevance gate. Without these counters the
-- thresholds would be tuned blind and the evaluation could not quantify the
-- gate's effect. Nullable: rows scored before M8 have no measurement.
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS gated_pairs INTEGER;
ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS vacuous_claims_dropped INTEGER;
```

Và chú thích tại chỗ khởi tạo (`consistency.py:458-462`):

```python
sim = None
# NULL, not 0: the columns record a measurement, and a gate that never
# ran made none. Writing 0 would be indistinguishable from a gate that
# ran and suppressed nothing, which is the comparison they exist for.
gated = None
dropped = None
```

Diễn giải:

| Giá trị cột | Nghĩa |
|---|---|
| `NULL` | **Cổng chưa từng chạy** trên hotspot này (chạy trước M8, hoặc `RELEVANCE_ENABLED=false`, hoặc engine bỏ qua) |
| `0` | **Cổng ĐÃ chạy và không chặn gì** — mọi cặp đều trên ngưỡng |
| `> 0` | Cổng đã chạy và chặn đúng chừng này cặp |

Hai dòng đầu là **hai sự kiện hoàn toàn khác nhau**, và phân biệt được chúng **chính là phép
so sánh mà hai cột này tồn tại để phục vụ**. Ghi 0 thay cho NULL sẽ xoá sạch khả năng đó và
biến mọi phép đo hiệu quả của cổng thành vô nghĩa.

Đây cũng là lý do bảng kết quả 11/08/2026 báo được **"205 hotspot cổng đã chạy / 24 hotspot
cột thống kê NULL"** — con số đó không tồn tại nếu cột mặc định 0.

> Ghi chú liên quan: migration 023 (`claims.origin_domains`) dùng đúng lập luận NULL này cho
> một cột khác — *"NULL means written before this migration -> cannot verify. It must never be
> read as 'no origin domains', which would treat every domain as independent and inflate
> corroboration."* Cùng một nguyên tắc: **NULL là "không biết", 0 là "biết và bằng không".**

## 6. Kết quả đo được

Đo ngày **11/08/2026** trên CSDL vận hành:

| Chỉ số | Giá trị |
|---|---|
| Hotspot đã đánh giá / bỏ qua (NULL) | 206 / 859 |
| Tổng mệnh đề đã chấm | 695 |
| corroborated / uncorroborated / disputed | 6 (0,9%) / 572 (82,3%) / 117 (16,8%) |
| Cặp (mệnh đề, bằng chứng) đã ghi | 4.098 |
| supports / contradicts / neutral | 742 (18,1%) / 204 (5,0%) / 3.152 (76,9%) |
| **Σ `gated_pairs`** | **2.720 (66,4% tổng số cặp)** |
| **Σ `vacuous_claims_dropped`** | **138** |
| Hotspot cổng đã chạy / chưa chạy | 205 / 24 (cột thống kê NULL) |

So với mốc nền 28/07/2026:

| Trạng thái | Trước cổng (n = 63) | Sau cổng (n = 695) |
|---|---|---|
| disputed | 32 (**50,8%**) | 117 (**16,8%**) |
| uncorroborated | 31 (49,2%) | 572 (82,3%) |
| corroborated | **0 (0%)** | **6 (0,9%)** |
| Số hotspot đã chấm điểm | 24 | 206 |

Hai điều đáng nói nhất:

1. **66,4%** — gần **hai phần ba** số cặp mà cỗ máy trước đây đem hỏi NLI là những cặp **không
   cùng nói về một việc**. Con số này xác nhận trực tiếp chẩn đoán ở file 01.
2. Xuất hiện **6 mệnh đề được kiểm chứng chéo thật** — điều mà CSDL sạch trước cổng không có
   lấy một trường hợp.

> **Hạn chế phải tự nêu:** đây **không phải** thí nghiệm A/B có kiểm soát. Hai con số bắc qua
> **hai lần chụp CSDL khác nhau** (63 mệnh đề / 24 hotspot so với 695 mệnh đề / 206 hotspot,
> cách nhau hai tuần vận hành). Cỡ mẫu, thời điểm và thành phần dữ liệu đều khác. Đây là
> **bằng chứng chỉ dấu mạnh, không phải bằng chứng nhân quả nghiêm ngặt**.
> Nhóm 24 hotspot chưa qua cổng còn tồn trong CSDL **không dùng làm nhóm đối chứng được**: cả
> 24 hotspot đó chỉ có đúng một mệnh đề mỗi cái và đều `uncorroborated` — một quần thể có cấu
> trúc khác hẳn, không phải mẫu ngẫu nhiên.

### Đo an toàn: cổng có chặn nhầm mâu thuẫn THẬT không?

Một bộ lọc luôn có **hai kiểu sai**, và cả hai đều phải đo:

```
bỏ lọt thứ cần chặn  ->  đo bằng phân bố trạng thái trước/sau + gated_pairs
chặn nhầm thứ cần giữ ->  đo bằng harness tiêm mâu thuẫn (eval/consistency/inject.py)
```

Harness chạy hai lần, bật và tắt cổng, rồi so `detection_rate`. Nếu cổng an toàn, hai con số
phải gần bằng nhau. **Bắt buộc báo cáo kèm `planted_premise_detected`** — vì một tiền đề tiêm
mà NLI không đọc ra là mâu thuẫn sẽ khiến mọi dispute đếm được đều đến từ bằng chứng lệch chủ
đề; khi đó `detection_rate` trích một mình **không phải là bằng chứng**.

> Mục đích của cổng **không phải** "giảm số dispute" — nếu chỉ cần thế thì nâng
> `SENTINEL_CONSISTENCY_DISPUTE_RATIO` là xong, không cần mô hình nào cả. Mục đích là **giảm
> dispute GIẢ trong khi giữ nguyên khả năng phát hiện dispute THẬT**. Một phép đo chỉ báo cáo
> vế đầu không phân biệt được cổng với việc bịt miệng hệ thống.

## 7. Câu hỏi thầy sẽ hỏi + cách trả lời

**H: Sao không fine-tune lại mô hình NLI cho đúng miền dữ liệu OSINT quân sự?**

Hai lớp lý do, nêu cả hai:

1. *Thực tế:* không có dữ liệu gán nhãn NLI cho miền OSINT quân sự. Tự gán sẽ cần hàng chục
   nghìn cặp câu do người làm, vượt xa phạm vi đồ án. (Tập gold 142 mệnh đề của đề tài đã là
   công sức đáng kể, và nó gán nhãn **phán quyết**, không phải nhãn NLI từng cặp.)
2. *Nguyên tắc — quan trọng hơn:* **kể cả có dữ liệu cũng không giải quyết được gốc**. Vấn đề
   không phải mô hình học chưa đủ tốt, mà là **tập nhãn chỉ có 3 lớp và không lớp nào là
   "không liên quan"**. Fine-tune trong cùng một không gian nhãn thì mô hình vẫn buộc phải
   chọn một trong ba khi gặp cặp lệch chủ đề. Muốn sửa bằng fine-tune thì phải **thêm lớp thứ
   tư** — tức là đổi bài toán, và khi đó ta đang tự xây lại chính cái cổng aboutness, chỉ bằng
   con đường đắt hơn nhiều.

**H: Sao không chỉ nâng ngưỡng xác suất của NLI cho chặt lại?**

Vì các mâu thuẫn giả **nằm ở phía tự tin của phân bố**, không nằm ở phía lưỡng lự. Nâng ngưỡng
thì mất mâu thuẫn thật (thường có xác suất thấp hơn) mà rác vẫn lọt. Trục xác suất không phải
trục phân biệt hai loại. Chi tiết ở [file 01, mục 3](01-nli-that-bai.md). Hệ thống đã có sẵn
ngưỡng đó — `SENTINEL_NLI_MIN_PROB = 0.6` — và nó không cứu được gì.

**H: Ngưỡng 0,35 lấy ở đâu ra?**

Trả lời thẳng: **thực nghiệm trên dữ liệu của dự án, không lấy từ paper**. Rồi nêu ngay hai
chốt chặn bù lại (`MIN_PEAK`, `MAX_HOMOGENEITY`), hai cột quan trắc để tinh chỉnh về sau, và
thí nghiệm A/B có kiểm soát là hướng làm đúng chuẩn. Xem mục 3.4.

**H: Các phương án khác đã cân nhắc chưa?**

| Phương án | Vì sao bị loại |
|---|---|
| Trùng lặp từ vựng (Jaccard, TF-IDF) | Bỏ sót các cách diễn đạt tương đương — *"IDF strike"* so với *"Israeli forces attacked"* gần như không chung từ nào. Sẽ đẩy đúng các ca kiểm chứng chéo **thật** thành `uncorroborated`, tức làm hỏng đúng thứ cần bảo vệ |
| Thêm một lời gọi NIM hỏi "hai câu này có cùng chủ đề không" | Tái lập chính sự phụ thuộc mạng đã hỏng ở M6, và thêm một lời gọi cho **mỗi cặp** sẽ nhân chi phí lên hàng chục lần |
| Siêu dữ liệu actor của GDELT | Quá thô: `"THE US"` không tách được hai câu chuyện Mỹ khác nhau |
| **Nhúng câu bằng mô hình cục bộ** (chọn) | Nắm được tương đồng **ngữ nghĩa** chứ không chỉ từ vựng; chạy trên chính ngăn xếp `transformers` đã có sẵn cho NLI nên **không thêm gói phụ thuộc nào**; chi phí là một phép nhân ma trận |

**H: Sao không siết `SENTINEL_MIN_GEO_PRECISION` từ 2 lên 3 để hotspot bớt trộn lẫn?**

Đã cân nhắc và **cố ý hoãn**: sẽ làm mất 196 sự kiện đã phân cụm trên 38 hotspot, và **không
giải quyết được** việc trộn lẫn chủ đề giữa các sự kiện **thật sự đồng vị trí** — đúng ca
hotspot số 8, nơi mọi sự kiện đều thật sự ở Ấn Độ.

→ Nền tảng của mô hình nhúng: [03-minilm.md](03-minilm.md)
