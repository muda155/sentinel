# 04 — Biến một câu thành vector, từng bước

> **TL;DR**
> Năm bước: **cắt câu thành token → tra bảng embedding → 6 lớp self-attention viết lại nghĩa
> theo ngữ cảnh → mean-pooling gộp thành 1 vector → chuẩn hoá L2**. Toàn bộ nằm trong
> `Embedder.embed` (`relevance.py:76-98`), 23 dòng code. Bước 5 quan trọng gấp đôi: nó xoá ảnh
> hưởng của độ dài câu, **và** biến phép tính cosine thành một phép nhân ma trận duy nhất ở
> `relevance.py:123`.

Câu ví dụ dùng xuyên suốt:

```
"Airstrike hits ammunition depot in Kharkiv"
```

Mọi con số dưới đây được chạy thật trên `sentence-transformers/all-MiniLM-L6-v2`.

---

## Bước 1 — Tokenize: cắt câu thành số

Code: `relevance.py:86-89`

```python
enc = self._tokenizer(
    batch, padding=True, truncation=True,
    max_length=_MAX_LENGTH, return_tensors="pt",
)
```

(`_MAX_LENGTH = 256`, `relevance.py:19`; `_BATCH_SIZE = 32`, `relevance.py:18`.)

Máy chỉ đọc số. Bước này cắt câu thành **token** rồi tra từ điển đổi mỗi token thành một **ID**.
Thuật toán là **WordPiece**: cắt tham lam từ trái sang, ưu tiên mảnh dài nhất có trong từ điển.

Kết quả thật cho câu ví dụ — **13 token**:

```
['[CLS]', 'airs', '##tri', '##ke', 'hits', 'ammunition', 'depot', 'in', 'k', '##har', '##ki', '##v', '[SEP]']
[  101,   14369,  18886,   3489,   4978,     9290,       8470,   1999, 1047,  8167,   3211,  2615,   102  ]
```

Hai điểm phải nhớ:

**(1) Từ hiếm bị cắt nhỏ với tiền tố `##`, nên mô hình KHÔNG BAO GIỜ gặp từ lạ hoàn toàn.**

`##` nghĩa là "mảnh này nối tiếp mảnh trước, không có dấu cách". Từ điển chỉ có **30.522** dòng,
nhưng nhờ cơ chế này nó phủ được mọi chuỗi ký tự:

```
"airstrike"  ->  airs + ##tri + ##ke      (không có trong từ điển như một từ nguyên)
"Kharkiv"    ->  k + ##har + ##ki + ##v   (tên riêng, chắc chắn không có)
"depot"      ->  depot                     (từ thông dụng, có sẵn 1 dòng)
```

Điểm này **cực kỳ quan trọng với dữ liệu OSINT**: nguồn tin đầy tên riêng lạ — Avdiivka,
Kharkiv, lathicharge, Rajya Sabha. Một mô hình có tập từ vựng cố định kiểu word2vec sẽ trả về
`<UNK>` cho tất cả và mất sạch thông tin. WordPiece thì luôn tách được thành các mảnh có nghĩa,
và các mảnh giống nhau giữa hai bài báo vẫn khớp nhau.

**(2) `[CLS]` và `[SEP]` là token đánh dấu đầu - cuối.**

Không phải từ trong câu. `[CLS]` (ID 101) đứng đầu mọi chuỗi, `[SEP]` (ID 102) đánh dấu hết
chuỗi. Chúng là quy ước kiến trúc kế thừa từ BERT.

## Bước 2 — Tra bảng embedding: mỗi ID thành 384 số

Bảng embedding có kích thước thật:

```
(30522, 384)      # 30.522 dòng x 384 cột
   |       |
   |       +--- mỗi dòng là một vector 384 số
   +----------- mỗi dòng ứng với một token ID; token ID CHÍNH LÀ số thứ tự dòng
```

Tra bảng là phép tra cứu thuần tuý: ID 8470 → lấy dòng 8470. Không tính toán gì.

**Lúc này nghĩa còn MƠ HỒ, vì chưa có ngữ cảnh.** Dòng 8470 là vector của từ "depot" nói chung:

```
depot = ?  kho hàng    (nhà kho thương mại)
        ?  bến xe      (bus depot)
        ?  kho quân sự (ammunition depot)
```

Cả ba nghĩa cùng bị nén vào **một** dòng duy nhất, vì bảng chỉ có một dòng cho mỗi ID.

Cũng ở bước này, **vị trí của token được cộng thêm vào** (position embedding). Đây là nơi
thông tin về **thứ tự từ** đi vào mô hình — nhớ chi tiết này cho mục "nếu thầy hỏi bí" ở cuối.

Kết quả bước 2: một bảng kích thước **(13 × 384)** cho câu ví dụ.

## Bước 3 — 6 lớp self-attention: viết lại nghĩa theo ngữ cảnh

Code: `relevance.py:90-91`

```python
with torch.no_grad():
    hidden = self._model(**enc).last_hidden_state
```

Một dòng gọi hàm, nhưng bên trong là toàn bộ phần "hiểu ngôn ngữ". Mỗi lớp làm đúng ba việc,
cho **mọi** token cùng lúc:

```
   với mỗi token:
   1. NHÌN quanh tất cả các token khác trong câu
   2. QUYẾT ĐỊNH token nào đáng chú ý (trọng số attention)
   3. HÚT thông tin từ những token đó về, rồi TỰ VIẾT LẠI vector của chính mình
```

Với câu ví dụ, token `"depot"`:

```
depot  --chú ý MẠNH-->  ammunition
depot  --chú ý MẠNH-->  airs/##tri/##ke
depot  --gần như bỏ qua-->  in
```

Sau khi hút thông tin về, vector của `depot` không còn là "depot nói chung" nữa, mà là
**"kho đạn quân sự đang bị tấn công"**. Cùng ID 8470 đó trong câu *"The bus depot closed at
midnight"* sẽ được viết lại thành **"bến xe buýt"**.

**Ví dụ số thật** — cùng token ID 8470, hai ngữ cảnh:

| So sánh | cosine |
|---|---|
| vector `depot` tĩnh (dòng 8470) ↔ vector `depot` sau 6 lớp trong câu "airstrike…" | **0,455** |
| vector `depot` tĩnh ↔ vector `depot` sau 6 lớp trong câu "the bus depot…" | 0,470 |
| `depot`("airstrike…") ↔ `depot`("bus depot…") | 0,847 |
| **cả hai CÂU** sau khi gộp (bước 4-5) | **0,094** |

Đọc bảng này: hai dòng đầu cho thấy bước 3 **viết lại rất mạnh** — vector cuối chỉ còn giống
dòng tra bảng ban đầu khoảng 0,46. Dòng cuối là con số thực sự quan trọng với cổng: dù hai câu
dùng chung hẳn một từ khoá, **vector câu** của chúng chỉ giống nhau 0,094 và bị chặn ngay.

Việc này lặp **6 lần** (6 lớp), mỗi lớp làm nghĩa rõ thêm một tầng: lớp đầu nắm quan hệ cú
pháp gần, các lớp sau nắm quan hệ ngữ nghĩa xa hơn.

Đầu ra `last_hidden_state` có shape thật **(1, 13, 384)** = (số câu, số token, số chiều).

## Bước 4 — Mean-pooling: gộp N vector token thành 1 vector câu

Code: `relevance.py:94-95`

```python
mask = enc["attention_mask"].unsqueeze(-1).float()
pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
```

Phép tính đơn giản đến bất ngờ: **trung bình cộng từng chiều**.

```
             token1  token2  ...  token13
chiều 1  :    0.12   -0.35   ...   0.08     ->  trung bình  ->  chiều 1 của vector câu
chiều 2  :   -0.41    0.22   ...  -0.11     ->  trung bình  ->  chiều 2
   ...
chiều 384:    0.07    0.19   ...   0.31     ->  trung bình  ->  chiều 384

(13 x 384)  ------------------------------->  (1 x 384)
```

### Vì sao một cách gộp thô sơ như vậy lại hiệu quả?

Vì **sau bước 3, MỖI TOKEN ĐÃ MANG THÔNG TIN CỦA CẢ CÂU rồi.** Self-attention đã cho mọi token
nhìn thấy mọi token khác, sáu lần liên tiếp. Vector của `depot` lúc này đã chứa dấu vết của
`ammunition`, `airstrike`, `Kharkiv`. Lấy trung bình không phải là "nén thông tin lại" — nó chỉ
là **chốt lại** thứ đã được trộn đều từ trước.

### Vai trò của `attention_mask`

Khi xử lý **nhiều câu một lượt** (`padding=True` ở bước 1), mọi câu trong lô phải cùng độ dài,
nên câu ngắn bị chèn thêm **token rỗng** (`[PAD]`) cho bằng câu dài nhất:

```
"Airstrike hits ammunition depot in Kharkiv"  -> 13 token thật
"India is mentioned."                          ->  6 token thật + 7 token RỖNG
                                                   attention_mask = [1,1,1,1,1,1, 0,0,0,0,0,0,0]
```

Nếu tính trung bình trên cả phần rỗng, vector của câu ngắn sẽ bị **kéo lệch về phía rác** — và
lệch nhiều hay ít lại phụ thuộc vào việc **câu nào tình cờ nằm chung lô**, tức là kết quả không
còn tất định. Code loại token rỗng khỏi **CẢ tử số lẫn mẫu số**:

```
tử số   : (hidden * mask).sum(dim=1)     -> token rỗng nhân 0, không đóng góp gì
mẫu số  : mask.sum(dim=1)                -> đếm ĐÚNG 6 token thật, không đếm 13
```

`.clamp(min=1e-9)` là chốt chặn chia cho 0 khi gặp chuỗi rỗng hoàn toàn.

## Bước 5 — Chuẩn hoá L2: đưa mọi vector về độ dài 1

Code: `relevance.py:96`

```python
pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
```

Chia vector cho chính độ dài của nó. Với câu ví dụ, độ dài trước khi chuẩn hoá đo được là
**5,259** → chia cho 5,259 → độ dài mới đúng bằng **1,000**.

Quay lại hình ảnh bản đồ ở [file 03](03-minilm.md): bước này **đẩy mọi điểm ra nằm trên bề mặt
một quả cầu**. Từ giờ hai câu chỉ còn khác nhau ở **HƯỚNG**, không khác nhau ở khoảng cách từ
tâm.

```
       trước L2                      sau L2
      .   .                         .-''''-.
        .    .                    .'   .    '.
   .        .          --->      (  .        . )
      .  .                        '.   .    .'
                                    '-....-'
   (điểm rải rác)              (mọi điểm trên mặt cầu bán kính 1)
```

### Lợi ích 1 — Xoá ảnh hưởng của độ dài câu

Độ dài vector trước chuẩn hoá phản ánh **câu dài hay ngắn**, chứ không phản ánh **nội dung**.
Giữ nguyên nó thì một bản tin viết dài sẽ tự động "khác" một bản tin viết ngắn về cùng sự việc.
Bỏ nó đi thì hai câu vẫn cùng hướng:

```
"Airstrike hits depot"                                              (3 từ)
"An airstrike carried out this morning struck an ammunition depot"  (10 từ)

cosine = 0.718     -> vượt ngưỡng 0,35, được đưa xuống NLI
```

Đây đúng là hai cách một hãng tin ngắn và một hãng tin dài đưa cùng một sự việc — và cổng phải
cho cặp này qua.

### Lợi ích 2 (thuần kỹ thuật) — Tích vô hướng CHÍNH LÀ cosine

Công thức cosine:

```
cos(a, b) = (a · b) / (|a| x |b|)
```

Khi `|a| = |b| = 1`, mẫu số bằng 1 và **phép cosine rút gọn thành phép nhân vô hướng**. Nhờ đó
`similarity_matrix` (`relevance.py:111-123`) tính **toàn bộ** ma trận tương đồng bằng **một**
phép nhân ma trận:

```python
# relevance.py:112-114
"""Cosine similarity of every claim against every evidence row.

Vectors are already L2-normalised, so the dot product is the cosine."""
...
claims = embedder.embed(claim_texts)        # relevance.py:121
evidence = embedder.embed(evidence_texts)   # relevance.py:122
return claims @ evidence.T                  # relevance.py:123  <-- toàn bộ ma trận
```

```
claims       (n_claims   x 384)
evidence.T   (384 x n_evidence)
   @         ------------------
kết quả      (n_claims x n_evidence)   = mọi cosine, một lệnh
```

Đây là lý do **chi phí của cổng gần như không đáng kể** so với chi phí NLI mà nó tiết kiệm
được: một phép nhân ma trận thay cho `n_claims × n_evidence` lượt chạy cross-encoder. Đo ngày
11/08/2026, cổng đã cắt **2.720 / 4.098 = 66,4%** số lượt gọi NLI.

`evidence_homogeneity` (`relevance.py:126-138`) dùng đúng thủ thuật đó với chính tập bằng
chứng: `vectors @ vectors.T` rồi lấy trung vị nửa trên đường chéo (`relevance.py:136-138`).

## Sơ đồ tóm tắt cả 5 bước

```
  "Airstrike hits ammunition depot in Kharkiv"
                    |
   [1] TOKENIZE                                          relevance.py:86-89
       [CLS] airs ##tri ##ke hits ammunition depot in k ##har ##ki ##v [SEP]
       [101, 14369, 18886, 3489, 4978, 9290, 8470, 1999, 1047, 8167, 3211, 2615, 102]
                    |                                    13 ID
                    v
   [2] TRA BẢNG EMBEDDING  (30522 x 384) + vị trí        (bên trong model)
       13 vector, nghĩa còn MƠ HỒ, chưa có ngữ cảnh
                    |                                    (13 x 384)
                    v
   [3] 6 LỚP SELF-ATTENTION                              relevance.py:90-91
       mỗi token nhìn quanh, hút thông tin, tự viết lại
       "depot" -> "kho đạn quân sự đang bị tấn công"
                    |                                    (13 x 384)  last_hidden_state
                    v
   [4] MEAN-POOLING trên token THẬT                      relevance.py:94-95
       trung bình cộng từng chiều; attention_mask loại
       token rỗng khỏi cả tử số lẫn mẫu số
                    |                                    (1 x 384), độ dài 5,259
                    v
   [5] CHUẨN HOÁ L2                                      relevance.py:96
       chia cho chính độ dài -> mọi vector dài đúng 1
                    |                                    (1 x 384), độ dài 1,000
                    v
       VECTOR CÂU  ->  claims @ evidence.T  =  ma trận cosine   relevance.py:123
                    ->  so với SENTINEL_RELEVANCE_MIN_SIM = 0,35
```

## Nếu thầy hỏi bí

### (a) "Lấy trung bình như thế thì mất thứ tự từ à?"

**Thông tin thứ tự KHÔNG bị bỏ qua ở bước 4 — nó đã đi vào từ bước 2.** Mô hình cộng
**position embedding** vào mỗi token ngay tại bảng tra, nên hai câu cùng bộ từ nhưng khác thứ tự
tạo ra **hai bảng token khác nhau ngay từ đầu**, rồi bước 3 tiếp tục khuếch đại khác biệt đó
qua attention. Trung bình cộng ở bước 4 gộp các vector **đã mang dấu vết vị trí**, không phải
các vector trần.

**Nhưng phải trả lời trung thực phần thứ hai**, vì đây là chỗ dễ bị bắt bí ngược:

```
"Russia attacked Ukraine"  vs  "Ukraine attacked Russia"
cosine = 0,996
```

Nghĩa là **trên thực tế, vector câu gần như không phân biệt được ai tấn công ai**. Thứ tự có
vào mô hình (0,996 chứ không phải 1,000), nhưng mean-pooling làm mờ vai trò chủ ngữ / tân ngữ
gần hết.

Và đây **không phải lỗi trong ngữ cảnh của Sentinel** — nó nhất quán với chính cảnh báo ở
[file 03, mục 5](03-minilm.md): **cosine đo CÙNG CHỦ ĐỀ, không đo CÙNG QUAN ĐIỂM.** Hai câu đó
đúng là cùng chủ đề (một cuộc tấn công Nga - Ukraine), nên **cổng phải cho chúng qua**; việc
phân biệt ai tấn công ai là **việc của mô hình NLI** ở bước sau. Nếu cổng tự phân biệt được vai
trò thì nó đã chặn mất đúng những cặp mâu thuẫn thật mà hệ thống cần phát hiện.

### (b) "Sao không lấy luôn vector của token `[CLS]` cho gọn?"

BERT gốc đúng là dùng `[CLS]` làm đại diện cho cả câu. Nhưng với **bài toán so sánh câu**,
mean-pooling đo tốt hơn: `[CLS]` được tối ưu cho các tác vụ phân loại, còn trung bình trên toàn
bộ token giữ được nhiều tín hiệu ngữ nghĩa phân tán hơn.

Quan trọng hơn — và đây mới là câu trả lời đúng: **`all-MiniLM-L6-v2` được HUẤN LUYỆN VỚI
mean-pooling.** Bản đồ ngữ nghĩa của nó được hình thành dưới đúng phép gộp đó. Dùng `[CLS]` khi
suy luận là dùng sai cách gộp so với lúc huấn luyện, và kết quả sẽ không còn là bản đồ mà mô
hình đã học.

Vì Sentinel dùng `transformers` thuần chứ **không** cài gói `sentence-transformers` (chủ ý:
không thêm một gói phụ thuộc nào), lớp `Embedder` phải tự tái hiện đúng phép đó. Chú thích
trong code nói thẳng điều này:

```python
# relevance.py:92-93
# Mean-pool over real tokens only, then L2-normalise. This is what
# the sentence-transformers wrapper does for this model.
```

### (c) "Truncation ở 256 token có làm mất thông tin không?"

`_MAX_LENGTH = 256` (`relevance.py:19`) — trong khi mô hình NLI dùng 512 (`nli.py:16`). Trên
thực tế không mất gì: văn bản bằng chứng của Sentinel được dựng từ **tiêu đề bài báo và siêu dữ
liệu** (`render_evidence_text`, `consistency.py:48-73`), không phải toàn văn — đề tài chủ động
không cào toàn văn, và bảng `events` chỉ lưu URL với tiêu đề. Câu ví dụ ở trên dài đúng 13 token.

← Quay lại: [02-cong-lien-quan.md](02-cong-lien-quan.md) · [03-minilm.md](03-minilm.md)
