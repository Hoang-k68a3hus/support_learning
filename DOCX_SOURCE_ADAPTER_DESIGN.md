# DOCX SOURCE ADAPTER DESIGN
# AI Study Assistant 2.0 — Universal Source Understanding

> **Mục tiêu:** Thiết kế adapter cho nguồn `.docx` sao cho bảo toàn tối đa source facts, reading order và provenance trước khi dữ liệu đi vào Universal Source Understanding.
>
> **Vai trò:** DOCX adapter là format adapter. Nó không phải chunker, semantic parser hay RAG pipeline.
>
> **Core architecture:** `DOCX → RawElement[] → Element → ContentRegion → LogicalUnit → RetrievalUnit → Evidence → Citation`.

---

# 1. Architectural boundary

DOCX adapter chỉ chịu trách nhiệm biến OOXML package thành representation gần source nhất có thể:

```text
.docx bytes
   ↓
Package / OOXML validation
   ↓
Document-order extraction
   ↓
RawElement[]
   ↓
Universal Source Understanding
```

Adapter được phép extract:

```text
text
paragraph/table order
native style
numbering/list metadata
section/break signals
hyperlink/bookmark references
images/drawings references
comments/footnotes/formulas nếu hỗ trợ
format-specific source locators
quality warnings
```

Adapter **không** làm:

```text
RAG token chunking
semantic topic extraction
LLM grouping
global hierarchy hallucination
RetrievalUnit creation
embedding
reranking
```

Nguyên tắc:

> **Preserve first, interpret second.**

---

# 2. DOCX khác PDF ở điểm nào?

DOCX là một **reflowable OOXML package**. Layout cuối cùng phụ thuộc vào Word/rendering engine, font, margin, image size, line wrapping, printer settings và section configuration.

Do đó không được áp dụng tư duy PDF:

```text
paragraph
→ page
→ bbox
```

cho DOCX nếu source không cung cấp rendered layout đáng tin cậy.

Default:

```text
page = null
bbox = null
```

là trạng thái hợp lệ.

Nếu hệ thống render DOCX thành PDF/preview sau đó:

```text
DOCX source anchor
      ↓
render mapping
      ↓
DERIVED page/bbox anchor
```

Rendered anchor không được overwrite source anchor gốc.

---

# 3. Recommended implementation stack

P0 đề xuất:

```text
python-docx
+
low-level OOXML traversal
```

`python-docx` phù hợp cho high-level object model như paragraph, table, section, comment, style và drawing references.

OOXML fallback cần dùng cho những trường hợp high-level API không expose đầy đủ hoặc có nguy cơ bỏ qua information như:

```text
tracked changes / revision marks
advanced fields
content controls
text boxes
OMML equations
footnotes/endnotes nếu API chưa đủ
nested/unsupported OOXML
```

Không để limitation của một parsing library trở thành limitation vô hình của canonical representation.

---

# 4. Reading order là invariant P0

Không được extract theo kiểu:

```python
document.paragraphs
+
document.tables
```

vì cách này tách hai collection và có thể làm mất thứ tự xen kẽ thực tế của body.

Phải traverse theo document order:

```text
Paragraph
Table
Paragraph
Paragraph
Table
...
```

Với `python-docx` 1.2.x có thể tận dụng document/container `iter_inner_content()` cho paragraph/table order, kết hợp OOXML traversal khi cần coverage cao hơn.

Nested container cũng phải giữ order:

```text
Table
 └ Cell
    ├ Paragraph
    ├ Nested Table
    └ Paragraph
```

Không chỉ lấy top-level tables.

Mỗi source-near block nhận một `order` ổn định theo traversal.

---

# 5. Paragraph extraction

Một paragraph nên preserve tối thiểu:

```text
raw text
paragraph style id/name
outline level nếu source có
alignment
indentation
spacing hints
keep-with-next
page-break-before
numbering references
run boundaries khi hữu ích
hyperlink/bookmark/field references
source locator
```

Mapping type hint:

```text
native Title style            → TITLE candidate
native Heading / outline      → HEADING candidate
normal paragraph              → PARAGRAPH
```

Phân biệt rõ:

```text
Native Heading 2 style
→ strong EXPLICIT structure signal

Large + bold + short paragraph
→ style facts only
→ downstream may INFER heading
```

Adapter không được biến typography heuristic thành source heading fact.

---

# 6. Runs

Không cần biến mọi run thành một `Element` mặc định.

Run chủ yếu cung cấp fine-grained source/style evidence:

```text
text span
font
font size
bold
italic
underline
hidden
language
breaks
inline drawing
hyperlink membership
revision state
```

Một paragraph có thể giữ run map trong `RawElement.attributes`:

```json
{
  "runs": [
    {
      "start": 0,
      "end": 5,
      "bold": true,
      "style_id": null
    }
  ]
}
```

Không normalize từng run trước rồi mới ghép raw paragraph text, vì điều đó có thể phá raw offsets.

---

# 7. Lists and numbering

Không nhận diện list chỉ dựa vào ký tự đầu dòng.

Preserve OOXML numbering facts nếu có:

```text
numId
ilvl
abstract numbering reference
paragraph style
```

Downstream có thể xây:

```text
LIST_ITEM Elements
       ↓
LIST_GROUP LogicalUnit
```

Adapter không tự merge toàn list thành retrieval chunk.

Nested list phải giữ level và source order.

---

# 8. Tables are first-class source content

Không flatten table thành một string ở adapter stage.

Preserve tối thiểu:

```text
table identity
row order
cell coordinates
cell raw text
nested paragraph/table content
horizontal merge / grid span
vertical merge nếu có
header-row hints nếu có
style/name nếu source có
```

Canonical conceptual structure:

```text
TABLE
 ├ TABLE_ROW
 │   ├ TABLE_CELL
 │   └ TABLE_CELL
 └ TABLE_ROW
```

Large-table chunking là downstream RetrievalUnit policy.

Ví dụ sau này có thể:

```text
Parent table
 ├ rows 1–10 + header
 ├ rows 11–20 + header
 └ ...
```

nhưng canonical table source vẫn phải tồn tại.

---

# 9. Images and drawings

Inline/floating graphics không được silently drop.

Adapter nên giữ:

```text
relationship id
asset/package part reference
inline/floating hint nếu biết
nearby paragraph/run
alt text/title nếu source có
source locator
```

Conceptually:

```text
FIGURE Element / visual source reference
        +
Asset
        +
relations to nearby text/caption
```

Vision-generated description là:

```text
DERIVED semantic enrichment
```

không phải source fact.

---

# 10. Hyperlinks and bookmarks

Preserve:

```text
visible hyperlink text
external target hoặc internal anchor
relationship/source reference
bookmark name/id
```

Hyperlink visible text vẫn nằm đúng vị trí trong paragraph raw text.

URL target chỉ là source metadata; không tự động trở thành trusted retrieval source.

---

# 11. Comments

Comments không được tự động nối vào body text.

Có thể biểu diễn như side content:

```text
COMMENT source object / element
        ↓
relation to referenced range
```

Metadata có thể gồm:

```text
comment_id
author
initials
timestamp
```

Canonical layer nên preserve comments khi adapter hỗ trợ; retrieval policy có thể exclude mặc định.

---

# 12. Headers and footers

Header/footer là source facts và không nên bị xóa khỏi master representation.

Default:

```text
HEADER / FOOTER Element
exclude_from_retrieval = true
```

Repeated-content detection có thể xác nhận boilerplate sau đó.

Phải preserve section linkage nếu có thể để tránh nhân bản header/footer một cách sai nghĩa.

---

# 13. Footnotes and endnotes

Nếu high-level API không expose đầy đủ:

```text
inspect OOXML package directly
```

Nếu P0 chưa implement được thì phải emit warning rõ:

```text
DOCX_UNSUPPORTED_FOOTNOTE
DOCX_UNSUPPORTED_ENDNOTE
```

Không được silently bỏ qua rồi báo parse quality hoàn hảo.

Khi hỗ trợ:

```text
FOOTNOTE Element
+
FOOTNOTE_OF relation
```

---

# 14. Equations / OMML

Office Math không được flatten mù thành text rác.

Preserve:

```text
FORMULA Element
raw OMML or OOXML source reference
nearby text/source relation
```

Nếu convert sang MathML/LaTeX:

```text
OMML source
  ↓
DERIVED transformation
  ↓
MathML / LaTeX view
```

Raw representation/reference vẫn phải còn.

---

# 15. Fields and generated content

DOCX có thể chứa fields:

```text
TOC
PAGE
NUMPAGES
REF
DATE
HYPERLINK
...
```

Preserve nếu có:

```text
field instruction
visible/result text
source locator
```

Không dùng `PAGE`/`NUMPAGES` field result làm canonical page anchor.

TOC có thể là hierarchy signal nhưng thường:

```text
exclude_from_retrieval = true
```

trong normal question answering.

---

# 16. Breaks and sections

Preserve explicit source signals:

```text
line break
hard page break
column break
section break
page-break-before paragraph property
```

Quan trọng:

```text
explicit hard page break = SOURCE FACT
rendered page number     = DERIVED layout fact
```

Section metadata có thể preserve:

```text
orientation
page size
margins
section start type
header/footer linkage
```

Những field này không đủ để adapter tự tính chính xác page number cho mọi paragraph.

---

# 17. SourceLocation policy for DOCX

## 17.1. Page/bbox

Default:

```text
page = null
bbox = null
```

Không làm:

```text
count hard page breaks
→ paragraph page number
```

vì pagination còn phụ thuộc layout engine.

## 17.2. Character offsets

Nếu adapter xây một linear source-text view thì convention phải cố định:

```text
start_char = zero-based inclusive
end_char   = zero-based exclusive
```

Offset tham chiếu vào adapter source text **trước canonical normalization**.

Normalization không được silently thay đổi anchor basis.

## 17.3. OOXML locator

DOCX cần format-specific source locator trong `RawElement.attributes`, ví dụ:

```json
{
  "part_uri": "/word/document.xml",
  "xml_path": "...",
  "paragraph_index": 12,
  "run_index": 3,
  "table_index": null,
  "row_index": null,
  "cell_index": null
}
```

Các locator này dùng cho trace/debug/correction, không phải semantic hierarchy.

---

# 18. Tracked changes / revision marks

Đây là failure mode P0 cần detect.

DOCX có thể chứa:

```text
<w:ins>
<w:del>
```

High-level paragraph/table APIs có thể không expose revision-mark content giống body content bình thường.

Policy:

```text
1. detect revision marks ở OOXML level;
2. định nghĩa explicit visible/current-text policy;
3. lưu revision handling policy trong processing metadata;
4. nếu không preserve full revision history, emit warning;
5. không claim lossless extraction.
```

P1/P2 có thể mở rộng thành revision-aware source representation.

---

# 19. Content controls, text boxes và unsupported OOXML

Các content class như:

```text
w:sdt content controls
DrawingML/VML text boxes
embedded objects
advanced fields
unsupported custom XML structures
```

phải có detection path.

Nếu chưa extract được:

```text
quality warning
+
source/package locator khi có
```

Không silently drop.

---

# 20. ContentRegion integration

DOCX adapter không tự tạo semantic regions.

Nó chỉ cung cấp đủ source signals để shared `ContentProfiler` và structure layer tạo:

```text
Heading + paragraphs → narrative / HIERARCHICAL region
Table                → table / LOCAL region
FAQ-style paragraphs → QA / LOCAL region
Code-styled content  → code / LOCAL region
Raw appendix dump    → FLAT region
```

`ContentRegion` là first-class downstream boundary cho mixed content.

Không route toàn DOCX bằng:

```text
document_type = BOOK
```

---

# 21. Source hierarchy vs retrieval hierarchy

Hai graph phải tách biệt.

Source structure:

```text
Heading 1
 └ Heading 2
```

có thể tạo `ContextNode.parent_id` / structural hierarchy.

Retrieval policy sau này có thể tạo:

```text
section RetrievalUnit parent
 ├ child RU 1
 └ child RU 2
```

Parent-child do chunking sinh ra không được ghi ngược thành source hierarchy.

---

# 22. Provenance and source revision

Mỗi ingestion của DOCX cần có immutable source-content identity:

```text
document_id      = business identity
source_revision  = immutable revision identity
content_hash     = hash của exact DOCX bytes/snapshot
```

Citation chain:

```text
RetrievalUnit
 ↓
LogicalUnit
 ↓
Element
 ↓
DOCX source locator
 ↓
source_revision
 ↓
original DOCX snapshot
```

Nếu user upload phiên bản mới cùng document business ID, citation cũ không được tự động resolve sang revision mới.

---

# 23. RetrievalUnit validation boundary

DOCX adapter không tạo RetrievalUnit, nhưng contract phải cho phép downstream validator kiểm tra:

```text
RetrievalUnit.source/document id
source revision
all element refs exist
all logical-unit refs exist
all context refs exist
subdocument ref exists
all SourceAnchors resolve
anchor location matches canonical source facts
```

Invalid RetrievalUnit:

```text
must not enter vector/sparse index
```

---

# 24. Confidence policy

Unknown không đồng nghĩa perfect.

Không dùng mặc định kiểu:

```text
confidence = 1.0
```

chỉ vì adapter không tính được confidence.

Semantics:

```text
None / UNKNOWN → chưa đánh giá
0.3            → đã đánh giá và thấp
1.0            → explicit/measured high confidence
```

Native DOCX facts như text/order có thể có confidence rất cao; inferred heading/topic phải được đánh giá riêng downstream.

---

# 25. Diagnostics

DOCX adapter nên xuất diagnostics đủ để biết có information loss hay không.

Metrics gợi ý:

```text
paragraph_count
table_count
nested_table_count
image_count
header_footer_count
comment_count
hyperlink_count
revision_mark_count
field_count
formula_count
unsupported_ooxml_count
empty_text_ratio
```

Warnings gợi ý:

```text
DOCX_REVISION_MARKS_PRESENT
DOCX_UNSUPPORTED_TEXTBOX
DOCX_UNSUPPORTED_FOOTNOTE
DOCX_UNSUPPORTED_ENDNOTE
DOCX_LAYOUT_LOCATION_UNAVAILABLE
DOCX_PARTIAL_FORMULA_EXTRACTION
DOCX_UNSUPPORTED_EMBEDDED_OBJECT
```

Warning không có nghĩa toàn document fail. Base extraction vẫn tiếp tục nếu có thể.

---

# 26. Example mapping

Input:

```text
Heading 1: SQL JOIN
Paragraph: JOIN kết hợp dữ liệu...

1. INNER JOIN ...
2. LEFT JOIN ...

[table]

Figure 2 ...
```

DOCX adapter conceptually emits:

```text
RawElement(HEADING candidate)
RawElement(PARAGRAPH)
RawElement(LIST_ITEM candidate)
RawElement(LIST_ITEM candidate)
RawElement(TABLE)
RawElement(FIGURE/CAPTION source reference)
```

Shared source-understanding layer mới tạo:

```text
ContextNode(SQL JOIN)
ContentRegion(narrative)
LogicalUnit(LIST_GROUP)
LogicalUnit(TABLE_BLOCK)
relations
```

Retrieval builder sau đó mới quyết định:

```text
1 large section RU
or
multiple child RUs
```

---

# 27. Tests

P0 DOCX fixture corpus phải có:

```text
plain paragraphs
native Heading 1/2/3
custom bold pseudo-heading
nested lists
paragraph-table-paragraph order
table with merged cells
nested table
inline image + caption
hyperlink
header/footer
hard page break
section break
comments
tracked changes
flat notes
mixed content
```

Critical invariants:

```text
all extracted source text traceable
body order stable
paragraph/table interleaving preserved
nested table not lost
no fake page/bbox
native heading distinguishable from inferred pseudo-heading
adapter performs no RAG token chunking
unsupported OOXML emits diagnostics
source revision preserved
```

Regression tests phải kiểm tra information preservation, không chỉ parser không crash.

---

# 28. Implementation phases

## P0 — reliable source-near extraction

```text
package validation
content hash / revision identity
body document-order traversal
paragraph/raw text extraction
native style/heading signals
list numbering signals
table and nested-table extraction
header/footer preservation
inline image references
explicit breaks/section signals
OOXML source locator attributes
revision/unsupported feature detection
quality warnings
```

## P1 — richer DOCX coverage

```text
comments
hyperlinks/bookmarks richer mapping
footnotes/endnotes
fields/TOC
OMML preservation
merged-cell semantics
content controls
```

## P2 — advanced provenance/layout

```text
revision-aware representation
text-box/floating-shape extraction
advanced embedded objects
rendered DOCX → source-anchor mapping
layout-aware derived citation highlighting
```

---

# 29. Definition of Done

DOCX adapter được coi là đủ tốt cho Universal Source Understanding khi:

```text
1. giữ đúng body reading order;
2. paragraph/table/list không bị flatten mất source structure;
3. native headings được giữ như explicit signal;
4. typography heuristic không tự biến thành source fact;
5. nested tables không bị mất;
6. headers/footers được preserve nhưng có thể exclude retrieval mặc định;
7. image/formula/unsupported OOXML không bị silently drop;
8. page/bbox không bị hallucinate;
9. source revision và source locator traceable;
10. adapter output không chứa RAG chunking policy.
```

Mục tiêu cuối:

```text
DOCX
 ↓
loss-minimizing source representation
 ↓
shared Universal Source Understanding
 ↓
adaptive RetrievalUnits
 ↓
traceable Evidence
 ↓
Grounded Answer + Citation
```
