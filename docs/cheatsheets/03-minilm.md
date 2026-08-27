# 03 — Mô hình nhúng câu `all-MiniLM-L6-v2`

> **TL;DR**
> Mô hình biến mỗi câu thành **một điểm trên bản đồ 384 chiều**, bản đồ được vẽ sao cho câu
> nói về chuyện giống nhau thì nằm gần nhau. Nó được huấn luyện **contrastive trên hơn 1 tỉ
> cặp câu**, trong đó có hàng trăm triệu **cặp ghép ngẫu nhiên bị bắt phải đẩy ra xa** — đó
> chính là năng lực mà mô hình NLI không hề có. Nhưng nhớ kỹ: cosine đo **CÙNG CHỦ ĐỀ**, không
> đo **CÙNG QUAN ĐIỂM**.

Khai báo trong code: `relevance.py:17`, đổi được qua `SENTINEL_RELEVANCE_MODEL`.

```python
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
```

---

## 1. Hình ảnh trực quan: bản đồ ngữ nghĩa

Hãy tưởng tượng một tấm bản đồ. **Mỗi câu là một điểm** trên đó. Bản đồ được vẽ theo đúng một
quy tắc:

> **Hai câu nói về chuyện giống nhau thì nằm gần nhau. Hai câu nói về chuyện khác nhau thì
> nằm xa nhau.**

Việc của MiniLM chỉ đơn giản là: **đưa vào một câu, trả về toạ độ của nó trên bản đồ đó.**

Toạ độ gồm **384 con số** — tức một vector 384 chiều.

```
Bản đồ giấy   : mỗi điểm = 2 số  (kinh độ, vĩ độ)
Bản đồ ngữ nghĩa: mỗi điểm = 384 số
```

Vì sao cần tới 384 chiều? Vì "ý nghĩa" phức tạp hơn "vị trí" rất nhiều. Một câu có chủ thể,
hành động, đối tượng, địa điểm, thời gian, sắc thái, mức độ chắc chắn... Hai chiều không đủ
chỗ để mọi thứ đó cùng tồn tại mà không giẫm lên nhau. 384 chiều thì đủ rộng.

Khoảng cách trên bản đồ này được đo bằng **cosine** — cụ thể là góc giữa hai vector. Đây chính
là con số mà cổng liên quan so với ngưỡng 0,35.

## 2. Bóc tên `all-MiniLM-L6-v2` ra từng phần

Tên mô hình không phải nhãn marketing — mỗi mảnh là một quyết định kỹ thuật.

```
all  -  MiniLM  -  L6  -  v2
 |         |        |     |
 |         |        |     +--- phiên bản 2, cải tiến từ v1
 |         |        +--------- 6 lớp Transformer
 |         +------------------ chưng cất (distillation) từ BERT
 +---------------------------- huấn luyện contrastive trên "tất cả" (>1 tỉ cặp câu)
```

### 2.1 `Mini` — chưng cất (distillation) từ BERT

Distillation là kiểu học **thầy - trò**:

```
      cùng một câu đầu vào
            |
     +------+------+
     |             |
  THẦY (BERT)   TRÒ (MiniLM)
  110 triệu     22 triệu tham số
  tham số           |
     |              |
   đầu ra  <---- so sánh ----> đầu ra
                    |
        điều chỉnh TRÒ cho tới khi
        đầu ra của trò giống thầy
```

Điểm mấu chốt: **trò không học từ dữ liệu gốc, trò học CÁCH SUY NGHĨ của thầy.** Thầy đã tiêu
tốn hàng nghìn giờ GPU để rút ra các quy luật ngôn ngữ; trò chỉ cần bắt chước kết quả của
những quy luật đó, nên học nhanh hơn và gọn hơn rất nhiều.

| | BERT-base (thầy) | all-MiniLM-L6-v2 (trò) |
|---|---|---|
| Tham số | ~110 triệu | **~22 triệu** |
| Dung lượng | ~440 MB | **~80 MB** |
| Chạy trên | thường cần GPU | **CPU thoải mái** |

Dòng cuối là lý do thực dụng để chọn nó: phần cứng tham chiếu của đề tài là máy ảo 4 vCPU
**không có GPU**, và cổng phải chạy trong mỗi chu kỳ pipeline 15 phút.

### 2.2 `L6` — 6 lớp Transformer

Bản MiniLM đầy đủ có 12 lớp. Bản `L6` được tạo bằng cách **giữ một lớp, bỏ một lớp** (lấy lớp
1, 3, 5, 7, 9, 11).

```
12 lớp:  [1][2][3][4][5][6][7][8][9][10][11][12]
 6 lớp:  [1]   [3]   [5]   [7]   [9]    [11]
```

Đánh đổi có chủ đích: **chất lượng giảm rất ít, tốc độ gấp đôi**. Với bài toán của Sentinel —
một phép lọc thô đứng trước một mô hình nặng hơn — đây là đúng phía cần đứng của đường đánh đổi.

### 2.3 `all` — phần quan trọng nhất

`all` nghĩa là mô hình được huấn luyện **contrastive** trên **hơn 1 tỉ cặp câu** gom từ mọi
nguồn có sẵn:

- cặp hỏi - đáp trên Stack Exchange, Quora, Reddit
- cặp tiêu đề - nội dung bài báo, tiêu đề - tóm tắt paper
- cặp hai cách diễn đạt cùng một ý (paraphrase)
- cặp câu - bản dịch, cặp đoạn văn - câu hỏi trả lời được bằng đoạn đó

Huấn luyện contrastive gồm **hai mệnh lệnh chạy song song**:

```
Cặp THẬT SỰ LIÊN QUAN   ->  KÉO hai điểm lại GẦN nhau
Cặp GHÉP NGẪU NHIÊN     ->  ĐẨY hai điểm ra XA nhau
```

Lặp một tỉ lần. Không ai vẽ bản đồ cả — **bản đồ tự hình thành** từ hàng tỉ lần kéo và đẩy đó.

Vế thứ hai đáng chú ý về mặt số lượng: trong huấn luyện contrastive, cặp âm thường được lấy từ
chính lô dữ liệu (in-batch negatives), nên mỗi cặp dương sinh ra hàng chục cặp âm. Tổng cộng
mô hình đã bị bắt xử lý **hàng trăm triệu cặp câu không liên quan**.

### 2.4 `v2`

Phiên bản cải tiến của v1: dữ liệu huấn luyện lớn hơn và sạch hơn, siêu tham số được chỉnh lại.
Không có thay đổi kiến trúc. Chi tiết này ít khi bị hỏi.

## 3. CÂU CHỐT: vì sao chính mô hình này bổ khuyết đúng chỗ NLI thiếu

```
+----------------------------------------------------------------------+
|  MiniLM  ĐÃ được cho xem HÀNG TRĂM TRIỆU cặp câu KHÔNG LIÊN QUAN,     |
|          và bị bắt phải nhận ra rằng chúng không liên quan.           |
|                                                                       |
|  NLI     CHƯA BAO GIỜ thấy một cặp câu không liên quan nào.           |
+----------------------------------------------------------------------+
```

Vế **"đẩy cặp ngẫu nhiên ra xa"** trong mục tiêu huấn luyện contrastive **chính là** cái mà
tập nhãn ba lớp của SNLI/MNLI không có. Không phải MiniLM "thông minh hơn" NLI — nó chỉ được
huấn luyện **cho đúng câu hỏi mà cổng cần trả lời**.

Đó là toàn bộ lập luận của FR-26, gói trong một câu:

> **Mỗi mô hình chỉ được hỏi câu hỏi mà dữ liệu huấn luyện của nó cho phép nó trả lời.**

## 4. Ví dụ số thật

Các con số dưới đây chạy trực tiếp trên `all-MiniLM-L6-v2` với đúng cách gộp vector của
`relevance.py` (mean-pool + L2). Ngưỡng cổng = 0,35.

### 4.1 Nó đo NGỮ NGHĨA, không đo TỪ VỰNG

| Cặp câu | Từ chung | cosine | Cổng |
|---|---|---|---|
| "Airstrike hits ammunition depot in **Kharkiv**" ↔ "A missile strike destroyed a weapons warehouse in **Kharkiv** region" | gần như chỉ có "Kharkiv" | **0,643** | qua |
| "Airstrike hits ammunition **depot** in Kharkiv" ↔ "The bus **depot** closed at midnight" | có chung "depot" | **0,094** | chặn |

Đây là bằng chứng gọn nhất cho việc vì sao **Jaccard/TF-IDF bị loại**: cặp trên gần như không
chung từ nào nhưng phải được giữ; cặp dưới chung hẳn một từ khoá nhưng phải bị chặn. Đếm từ
làm sai **cả hai**.

### 4.2 Bốn chủ đề của hotspot số 8 tách nhau rất rõ

```
E1 "Indian government issues notice to Meta over data sharing"
E2 "Rajya Sabha adjourned after opposition uproar"
E3 "Chief Justice of Pakistan warns against protest marches"
E4 "Court rules on the lathicharge incident"

        E1      E2      E3      E4
E1     1.000   0.190   0.185   0.106
E2     0.190   1.000   0.138   0.118
E3     0.185   0.138   1.000  -0.089
E4     0.106   0.118  -0.089   1.000
```

Mọi cặp chéo đều nằm sâu dưới 0,35 — mô hình nhúng nhìn ra ngay bốn chủ đề khác nhau, đúng thứ
mà mô hình NLI đã đọc nhầm thành "bốn nguồn chọi nhau". Trung vị của sáu giá trị trên đường
chéo trên = **0,128** = `evidence_homogeneity`.

## 5. CẢNH BÁO BẮT BUỘC NHỚ: cosine đo CÙNG CHỦ ĐỀ, không đo CÙNG QUAN ĐIỂM

Đây là chỗ hội đồng dễ bắt bí nhất.

```
A: "Russia controls the city of Avdiivka"
B: "Russia does NOT control the city of Avdiivka"

cosine(A, B) = 0.897        <-- RẤT CAO
```

Hai câu **phủ định lẫn nhau** mà cosine gần 0,9. Với người mới nhìn, đây trông như một thất bại
của mô hình.

**Nó không phải thất bại. Nó ĐÚNG Ý ĐỒ.**

Hai câu đó **đang nói về đúng cùng một việc** — quyền kiểm soát Avdiivka. Đó chính xác là định
nghĩa của "cùng chủ đề". Và cặp này chính là cặp **cần được đưa xuống mô hình NLI**, vì chỉ NLI
mới phân biệt được `controls` với `does not control`.

Phân vai rõ ràng:

```
+---------------------+---------------------------------------------------+
| Cổng (MiniLM)       | "Hai câu này có nói về cùng một việc không?"       |
| cosine = 0.897      | -> CÓ. Cho qua.                                    |
+---------------------+---------------------------------------------------+
| NLI (DeBERTa)       | "Vậy chúng khớp hay chọi nhau?"                    |
|                     | -> CONTRADICTION. Đây là mâu thuẫn THẬT.           |
+---------------------+---------------------------------------------------+
```

### Nếu thầy hỏi: "Sao không dùng luôn cosine để phát hiện mâu thuẫn, bỏ NLI đi cho gọn?"

Trả lời: **cosine không thể phát hiện mâu thuẫn, về mặt nguyên lý.**

Cả hai cặp dưới đây đều cho cosine cao, và cosine **không phân biệt được chúng**:

| Cặp | cosine | Quan hệ thật |
|---|---|---|
| "Russia controls Avdiivka" ↔ "Russia does not control Avdiivka" | 0,897 | **contradiction** |
| "Airstrike hits ammunition depot in Kharkiv" ↔ "A missile strike destroyed a weapons warehouse in Kharkiv region" | 0,643 | **entailment / khớp nhau** |

Bỏ NLI đi thì hệ thống **mất hẳn khả năng phát hiện mâu thuẫn** — vốn là **mục tiêu chính của
cả module M6**. Cổng không thay thế NLI; cổng **bảo vệ** NLI bằng cách chỉ đưa cho nó những câu
hỏi nó trả lời được.

Có thể chốt bằng một câu:

> **Cổng trả lời "có đáng hỏi không". NLI trả lời "câu trả lời là gì". Bỏ cái nào cũng hỏng.**

→ Chi tiết cách một câu biến thành 384 con số: [04-vector-hoa-cau.md](04-vector-hoa-cau.md)
