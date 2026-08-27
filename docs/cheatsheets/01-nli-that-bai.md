# 01 — Vì sao mô hình NLI báo "mâu thuẫn" ở khắp nơi

> **TL;DR**
> Mô hình NLI được huấn luyện trên các cặp câu cùng mô tả MỘT cảnh, và tập nhãn của nó
> chỉ có ba lớp: entailment / contradiction / neutral — **không có lớp "không liên quan"**.
> Đưa vào hai câu nói về hai chuyện khác nhau, nó buộc phải chọn một trong ba, và nó chọn
> "contradiction" với xác suất rất cao. Sentinel gom hotspot theo không gian - thời gian chứ
> không theo nội dung, nên nó rơi đúng vào cái bẫy đó: đo ngày 28/07/2026 trên CSDL sạch,
> **50,8% mệnh đề bị đánh dấu tranh chấp và KHÔNG một mệnh đề nào được kiểm chứng chéo**.

---

## 1. NLI được huấn luyện như thế nào

NLI = Natural Language Inference (suy luận ngôn ngữ tự nhiên). Đầu vào là một cặp:

```
premise    (tiền đề)  : "Một người đàn ông đang chơi ghi-ta trên sân khấu."
hypothesis (giả thuyết): "Một người đang biểu diễn âm nhạc."
```

Đầu ra là phân bố xác suất trên **ba nhãn**.

Quy trình gán nhãn của SNLI/MNLI — hai bộ dữ liệu chuẩn của bài toán này — như sau:

```
       [ 1 bức ảnh / 1 đoạn văn ]
                  |
       annotator viết 1 câu mô tả  ->  PREMISE
                  |
    rồi viết tiếp ĐÚNG 3 câu, cùng nói về CÙNG cảnh đó:
      - chắc chắn đúng nếu premise đúng     -> entailment
      - có thể đúng, có thể sai             -> neutral
      - chắc chắn sai nếu premise đúng      -> contradiction
```

Điểm mấu chốt: **cả bốn câu luôn cùng một cảnh**. Không có bước nào trong quy trình sinh ra
một cặp câu nói về hai chuyện khác nhau.

## 2. Hệ quả cốt lõi: "neutral" KHÔNG có nghĩa là "không liên quan"

| Nhãn | Nghĩa mà con người hay gán nhầm | Nghĩa THẬT trong dữ liệu huấn luyện |
|---|---|---|
| entailment | "hai câu khớp nhau" | cùng một cảnh, premise kéo theo hypothesis |
| neutral | "hai câu chẳng liên quan gì" (SAI) | **cùng một cảnh**, nhưng chưa đủ dữ kiện để kết luận |
| contradiction | "hai câu chọi nhau" | cùng một cảnh, premise bác bỏ hypothesis |

Cả ba nhãn đều mang tiền giả định "cùng một cảnh". **Lớp "không liên quan" không tồn tại
trong tập nhãn**, và mô hình chưa từng nhìn thấy một cặp câu không liên quan nào trong suốt
quá trình huấn luyện.

## 3. Vậy khi đưa vào hai câu khác chuyện thì sao?

Trong không gian đặc trưng mà mô hình đã học, tín hiệu để phân biệt contradiction với
entailment là **mức độ lệch giữa các chi tiết**: chủ thể lệch, hành động lệch, địa điểm lệch,
thời gian lệch → càng lệch nhiều thì càng giống contradiction.

Hai câu khác chuyện thì **mọi chi tiết đều lệch**. Đó là biểu hiện cực đoan của chính cái tín
hiệu mà mô hình dùng để nhận ra mâu thuẫn. Kết quả: mô hình trả về `contradiction` với
**xác suất rất cao**, không phải với xác suất lưỡng lự.

### Vì sao "nâng ngưỡng tin cậy" KHÔNG cứu được

Đây là câu hỏi phản biện dễ gặp nhất. Trong Sentinel đã có sẵn một ngưỡng như thế:

```
SENTINEL_NLI_MIN_PROB = 0.6      # consistency.py:40-41, dùng ở consensus() consistency.py:354
```

Phán quyết dưới 0,6 bị bỏ qua hoàn toàn. Nhưng nó không cứu được gì, vì các "mâu thuẫn giả"
lệch chủ đề trả về xác suất cao hơn 0,6 rất nhiều. Logic của việc nâng ngưỡng:

```
ngưỡng thấp  -> rác lọt vào  + mâu thuẫn thật cũng lọt vào
ngưỡng cao   -> rác VẪN lọt  + mâu thuẫn thật (thường có xác suất thấp hơn) bị loại
```

Nói ngắn: **rác nằm ở phía tự tin của phân bố, không nằm ở phía lưỡng lự**. Không có điểm
cắt nào tách được hai loại, vì trục xác suất không phải là trục phân biệt chúng. Cái cần
phân biệt là "có cùng chủ đề hay không" — một chiều thông tin mà mô hình NLI **không hề tạo ra**.

## 4. Ví von để hội đồng hiểu ngay

> Có một vị giám khảo cả đời chỉ làm đúng một việc: đọc hai lời khai về **cùng một vụ tai nạn**
> rồi tick vào phiếu chấm ba ô — *khớp nhau*, *chưa đủ dữ kiện*, *chọi nhau*.
>
> Hôm nay đưa cho ông một lời khai về vụ tai nạn ở Hà Nội và một lời khai về đám cháy ở Cần Thơ.
> Phiếu chấm của ông **không có ô "hai chuyện này không liên quan"**. Ông buộc phải tick một
> trong ba ô đang có. Mọi chi tiết đều khác nhau, nên ông tick **"chọi nhau"** — và ký tên
> rất dứt khoát bên dưới.
>
> Ông không sai. Người sai là kẻ đưa cho ông tờ phiếu chấm đó với hai lời khai đó.

## 5. Vì sao Sentinel dính đúng bẫy này

Hotspot của Sentinel được gom theo **KHÔNG GIAN và THỜI GIAN**, không gom theo **NỘI DUNG**:

```
ô lưới 1° x 1°  +  cửa sổ 24h   ->  grid cell "hoạt động"
                                ->  DBSCAN theo khoảng cách haversine
                                ->  hotspot
```

Không có bước nào hỏi "các sự kiện này có nói về cùng một chuyện không?". Một ô lưới 1°×1°
phủ trọn một vùng đô thị lớn; trong 24h vùng đó hoàn toàn có thể sinh ra bốn câu chuyện
chẳng liên quan gì đến nhau. Sau đó:

```
fetch_hotspot_evidence()   -> mỗi tên miền một dòng bằng chứng (consistency.py:82)
extract_claims()           -> LLM rút mệnh đề từ TOÀN BỘ đống bằng chứng đó (consistency.py:193)
judge_claims()             -> ghép TÍCH ĐỀ-CÁC mệnh đề x bằng chứng, đẩy hết vào NLI (consistency.py:288)
```

Dòng thứ ba là chỗ chết người: mọi mệnh đề bị đối chiếu với **mọi** bằng chứng, kể cả bằng
chứng của một câu chuyện hoàn toàn khác.

### Ca thật đã truy vết đầu-cuối: hotspot số 8 ("India")

13 sự kiện, 100% đã được làm giàu tiêu đề bài báo thật (FR-25). Bên trong trộn lẫn **bốn câu
chuyện khác nhau**:

| # | Câu chuyện |
|---|---|
| 1 | Chính phủ Ấn Độ và Meta |
| 2 | Hoãn phiên họp Rajya Sabha |
| 3 | Cảnh báo biểu tình của Chánh án **Pakistan** |
| 4 | Phán quyết về vụ lathicharge |

Kết quả: cả **năm** mệnh đề đúng ngữ pháp đều bị đánh dấu `disputed`, `consistency_score = 0`,
và giao diện hiển thị dòng **"Phát hiện mâu thuẫn giữa các nguồn"**.

Không có mâu thuẫn nào cả. Chỉ có bốn chủ đề khác nhau.

### Vì sao chỉ cần MỘT phán quyết rác là đủ để bôi đen cả mệnh đề

Quy tắc trong `consensus()` (`consistency.py:369`):

```python
if contradictors and dispute >= ratio * support:   # ratio = SENTINEL_CONSISTENCY_DISPUTE_RATIO = 0.5
    status = "disputed"
```

Ví dụ số với một mệnh đề không có nguồn nào ủng hộ (`support = 0`) và đúng một tên miền
"phản bác" do lệch chủ đề, xác suất NLI 0,94, trust mặc định 0,4 (`consistency.py:97`):

```
support  = 0
dispute  = 0.4 x 0.94 = 0.376
điều kiện: 0.376 >= 0.5 x 0 = 0     -> ĐÚNG  -> disputed
```

Vế phải bằng 0, nên **bất kỳ** phản bác nào cũng thắng. Mệnh đề nhận giá trị 0,0 trong công
thức điểm (`_STATUS_VALUE`, `consistency.py:384`), kéo `consistency_score` xuống.

## 6. Số đo thực tế TRƯỚC khi có cổng

Đo lại ngày **28/07/2026** trên CSDL đã dựng lại sạch: 63 mệnh đề thuộc 24 hotspot đã chấm
điểm, tổng hợp từ 319 sự kiện GDELT (318 sự kiện có tiêu đề đã làm giàu, 98 tiêu đề phân biệt
— tức khoảng một tiêu đề cho mỗi bài, dữ liệu lành mạnh).

| Trạng thái mệnh đề | Số lượng | Tỉ lệ |
|---|---|---|
| `disputed` (bị tranh chấp) | 32 | **50,8%** |
| `uncorroborated` (đơn nguồn) | 31 | 49,2% |
| `corroborated` (được kiểm chứng chéo) | **0** | **0%** |

Chi tiết còn mạnh hơn con số thô: trong 24 hotspot được chấm, **7 hotspot đạt đúng 0 điểm**
(mọi mệnh đề đều bị tranh chấp) và **13 hotspot đạt đúng 50 điểm** (mọi mệnh đề đều đơn nguồn).
**Không một mệnh đề nào trong toàn bộ cơ sở dữ liệu được kiểm chứng chéo.**

> Câu chốt dùng được nguyên văn trước hội đồng:
> **"Đây không phải là một hệ thống thận trọng, mà là một hệ thống đang khẳng định sai theo cả hai chiều."**

> **Cảnh báo về tính trung thực số liệu.** Một bản nháp trước đó từng trích con số
> *5 corroborated / 31 uncorroborated / 67 disputed*. Con số đó đo trên CSDL mà cột
> `events.title` đã bị hỏng bởi một lần chạy backfill M7 có lỗi — một tiêu đề bị ghi đè lên
> **7.825 dòng trải trên 2.727 URL phân biệt**. Nó **đã bị loại bỏ** và không được dùng ở bất
> cứ đâu. Nếu bị hỏi, trả lời đúng như vậy: số liệu đo trên dữ liệu hỏng phải bị **loại bỏ hoàn
> toàn**, không được "điều chỉnh", và việc loại bỏ phải được ghi lại.

## 7. Vì sao đây là lỗi nguy hiểm, không chỉ là sai số

Với một nhà phân tích tình báo, hai đầu ra này có giá trị hoàn toàn khác nhau:

| Đầu ra | Ý nghĩa với người phân tích |
|---|---|
| "hai nguồn **chọi nhau**" | Tín hiệu **rất mạnh**: có bên đang đưa tin sai, hoặc đang có chiến dịch thông tin. Phải điều tra ngay. |
| "hai nguồn nói **hai chuyện khác nhau**" | Không có tín hiệu gì. Chuyện bình thường. |

Hệ thống trước M8 **biến cái thứ hai thành cái thứ nhất**. Nó không bỏ sót tín hiệu — nó
**tạo ra tín hiệu giả**. Trong bài toán OSINT, tín hiệu giả tệ hơn tín hiệu bị bỏ sót, vì nó
tiêu tốn nguồn lực phân tích và làm mất niềm tin vào toàn bộ chỉ số.

Tệ hơn nữa: trạng thái này **xấu hơn cả trạng thái trước đó**, khi cỗ máy chưa có tiêu đề thật
và trung thực trả về NULL ("chưa đánh giá"). Cải tiến ở M7 đã biến một hệ thống im lặng thành
một hệ thống nói sai một cách tự tin.

## 8. Bài học đóng lại

**Lỗi không nằm ở dòng code nào. Code chạy đúng thiết kế.**

`judge_claims` gọi mô hình đúng cách, `consensus` áp đúng quy tắc, công thức điểm đúng đặc tả.
Mọi unit test đều xanh — và đều phải xanh, vì chúng kiểm tra code làm đúng thứ nó được viết ra
để làm.

Lỗi nằm ở tầng cao hơn: **dùng một mô hình ở NGOÀI PHÂN BỐ DỮ LIỆU nó được huấn luyện, rồi
diễn giải đầu ra như thể mô hình hiểu khái niệm "không liên quan"** — một khái niệm chưa bao
giờ tồn tại trong tập nhãn của nó.

```
Không unit test nào bắt được lỗi này, vì code đúng.
Chỉ có một cách phát hiện: nhìn PHÂN BỐ kết quả trên dữ liệu THẬT.
"0 corroborated trên toàn bộ CSDL" là con số đã tố cáo mọi thứ.
```

Bài học tổng quát để nói trước hội đồng: **kiểm thử đơn vị xác nhận code khớp với thiết kế;
chỉ có đo đạc trên dữ liệu thật mới xác nhận thiết kế khớp với hiện thực.**

→ Cách sửa: [02-cong-lien-quan.md](02-cong-lien-quan.md)
