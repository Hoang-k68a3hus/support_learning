# ĐỒ ÁN TỐT NGHIỆP  
# Personalized AI Learning Platform using LLM, RAG and Learning Analytics

> **Tên tiếng Việt đề xuất:** Nền tảng học tập cá nhân hóa ứng dụng Mô hình Ngôn ngữ Lớn, Retrieval-Augmented Generation và Learning Analytics  
> **Tên ngắn:** AI Study Assistant 2.0  
> **Loại đề tài:** Hệ thống phần mềm tích hợp AI / Web / Data Analytics  
> **Định hướng:** Xây dựng một nền tảng học tập thông minh, không chỉ là chatbot hỏi đáp tài liệu mà là một hệ thống khép kín từ **quản lý tri thức → học tập → đánh giá → mô hình hóa năng lực → cá nhân hóa → gợi ý học tiếp**.

---

# 1. Tóm tắt đề tài

AI Study Assistant 2.0 là nền tảng học tập cá nhân hóa cho phép người dùng:

- Quản lý tài liệu học tập.
- Tự động trích xuất và cấu trúc hóa nội dung tài liệu.
- Hỏi đáp dựa trên chính tài liệu bằng RAG.
- Tạo tóm tắt, quiz, flashcard và mindmap.
- Theo dõi quá trình học.
- Phân tích điểm mạnh, điểm yếu theo từng chủ đề.
- Ước lượng mức độ thành thạo kiến thức.
- Phát hiện kiến thức có nguy cơ quên.
- Đề xuất nội dung cần ôn.
- Sinh kế hoạch học cá nhân hóa.
- Theo dõi tiến độ qua dashboard.
- Hỗ trợ gamification để tăng động lực học tập.

Điểm khác biệt chính của hệ thống là AI không chỉ sinh nội dung mà còn sử dụng **dữ liệu học tập của từng người dùng** để đưa ra các khuyến nghị cá nhân hóa.

---

# 2. Bối cảnh và vấn đề

Các công cụ AI hiện nay hỗ trợ tốt việc:

- Hỏi đáp.
- Tóm tắt tài liệu.
- Sinh nội dung.
- Sinh câu hỏi.

Tuy nhiên, phần lớn các hệ thống đơn giản vẫn có các hạn chế:

1. Không quản lý được toàn bộ nguồn tài liệu của người học.
2. Không đảm bảo câu trả lời bám sát tài liệu.
3. Không lưu lại lịch sử học dưới dạng dữ liệu có cấu trúc.
4. Không biết người học đang mạnh/yếu ở chủ đề nào.
5. Không biết kiến thức nào sắp bị quên.
6. Không tự điều chỉnh kế hoạch học theo kết quả thực tế.
7. Các tính năng chat, quiz, flashcard, planner thường hoạt động tách rời.

Đề tài giải quyết vấn đề trên bằng cách xây dựng một vòng lặp:

```text
Knowledge
   ↓
Learning Interaction
   ↓
Learning Data
   ↓
Student Model
   ↓
Personalized Recommendation
   ↓
Next Learning Activity
```

---

# 3. Mục tiêu của đề tài

## 3.1. Mục tiêu tổng quát

Xây dựng một nền tảng học tập cá nhân hóa có khả năng:

- Quản lý tri thức học tập.
- Hiểu và truy xuất nội dung tài liệu.
- Sinh nội dung hỗ trợ học tập.
- Theo dõi hành vi học.
- Đánh giá mức độ hiểu bài.
- Phát hiện lỗ hổng kiến thức.
- Đề xuất nội dung học phù hợp.
- Hỗ trợ lập kế hoạch học.

## 3.2. Mục tiêu kỹ thuật

Hệ thống cần chứng minh được năng lực ở các nhóm sau:

### Software Engineering

- Kiến trúc phân tầng.
- Tách Backend nghiệp vụ và AI Service.
- REST API.
- Authentication / Authorization.
- Database design.
- File storage.
- Caching.
- Background processing.
- Logging.
- Testing.
- Docker deployment.

### Artificial Intelligence

- OCR.
- Document parsing.
- Chunking.
- Embedding.
- Semantic retrieval.
- Reranking.
- Retrieval-Augmented Generation.
- Grounded answer.
- AI content generation.
- Learning analytics.
- Recommendation logic.

### Data Analytics

- Study time.
- Quiz accuracy.
- Topic mastery.
- Learning streak.
- Learning heatmap.
- Weak-topic detection.
- Review priority.
- Forgetting estimation.

---

# 4. Phạm vi hệ thống

Để tránh đồ án quá rộng, hệ thống được chia thành 3 mức.

## 4.1. Core MVP — bắt buộc hoàn thiện

1. Authentication.
2. User Profile.
3. Document Management.
4. PDF/DOCX/PPTX processing.
5. RAG Chat.
6. Source Citation.
7. Summary.
8. Quiz.
9. Flashcard.
10. Study Session Tracking.
11. Learning Event Tracking.
12. Learning Analytics Dashboard.
13. Topic Mastery.
14. Weak-topic Detection.
15. Personalized Recommendation.
16. Study Planner.
17. Admin Dashboard.
18. Docker deployment.

## 4.2. Advanced Features — nên có nếu đủ thời gian

- Hybrid Search.
- Reranking.
- OCR ảnh.
- Knowledge Mindmap.
- Spaced Repetition.
- Forgetting Curve.
- Gamification.
- Notification.
- Calendar.
- Highlight.
- Bookmark.

## 4.3. Optional Features — chỉ làm cuối

- Voice input.
- Voice output.
- Ranking.
- Challenge.
- Social learning.
- Collaborative document sharing.
- Mobile application.

---

# 5. Đối tượng sử dụng

## 5.1. Student

Người học sử dụng hệ thống để:

- Quản lý tài liệu.
- Hỏi AI.
- Ôn tập.
- Làm quiz.
- Học flashcard.
- Theo dõi tiến độ.
- Nhận khuyến nghị.
- Lập kế hoạch học.

## 5.2. Admin

Quản trị viên:

- Quản lý người dùng.
- Theo dõi AI usage.
- Theo dõi storage.
- Xem system analytics.
- Quản lý báo cáo lỗi.
- Theo dõi trạng thái dịch vụ.

---

# 6. Các phân hệ chính

## 6.1. Identity & Access Management

Chức năng:

- Đăng ký.
- Đăng nhập.
- Refresh token.
- Đăng xuất.
- Quên mật khẩu.
- Đổi mật khẩu.
- Phân quyền.
- Profile.

Role:

```text
STUDENT
ADMIN
```

---

## 6.2. Knowledge Management

### Document

Hỗ trợ:

- PDF.
- DOCX.
- PPTX.
- TXT.
- Ảnh.

MVP ưu tiên:

```text
PDF
DOCX
PPTX
```

Chức năng:

- Upload.
- Rename.
- Delete.
- Download.
- Folder.
- Tag.
- Search.
- Filter.
- View processing status.

Document status:

```text
UPLOADED
QUEUED
PROCESSING
READY
FAILED
```

---

## 6.3. Document Processing Pipeline

Luồng xử lý:

```text
Upload
  ↓
File Validation
  ↓
Object Storage
  ↓
Processing Queue
  ↓
Text Extraction
  ↓
OCR if necessary
  ↓
Cleaning
  ↓
Structure Detection
  ↓
Chunking
  ↓
Metadata Generation
  ↓
Embedding
  ↓
Vector Database
  ↓
READY
```

Metadata của chunk:

```text
document_id
page
chapter
section
chunk_index
text
token_count
embedding
```

---

# 7. RAG Learning Engine

## 7.1. Mục tiêu

AI chỉ trả lời dựa trên nguồn tri thức được phép.

## 7.2. Pipeline

```text
User Question
      ↓
Query Preprocessing
      ↓
Query Embedding
      ↓
Retriever
      ↓
Top-K Candidate Chunks
      ↓
Reranker
      ↓
Top-N Context Chunks
      ↓
Prompt Builder
      ↓
LLM
      ↓
Grounded Answer
      ↓
Citation
```

## 7.3. Answer Citation

Ví dụ:

```text
INNER JOIN chỉ trả về các bản ghi có giá trị khớp ở cả hai bảng.

Nguồn:
- Database Systems.pdf
- Chapter 5
- Page 87
```

## 7.4. Hallucination Control

Nếu retrieval không tìm được context đủ mạnh:

```text
IF max_retrieval_score < threshold
    return INSUFFICIENT_CONTEXT
```

AI trả lời:

> Không tìm thấy đủ thông tin trong các tài liệu hiện có để trả lời câu hỏi này một cách đáng tin cậy.

---

# 8. Semantic Search

Không chỉ tìm exact keyword.

Ví dụ:

```text
Query:
"Câu nói về tính đa hình"

Document:
"Polymorphism allows..."
```

Embedding search vẫn tìm được nội dung có liên quan.

Các chế độ có thể triển khai:

### MVP

- Dense Vector Search.

### Advanced

- BM25.
- Dense Search.
- Hybrid Search.
- Reranking.

---

# 9. AI Summary

Ba mức:

```text
QUICK
STANDARD
DETAILED
```

Ví dụ:

- Summary 1 phút.
- Summary 5 phút.
- Summary chi tiết.

Với tài liệu dài:

```text
Document
   ↓
Section Summary
   ↓
Chapter Summary
   ↓
Global Summary
```

Sử dụng hierarchical summarization thay vì đưa toàn bộ tài liệu vào một prompt.

---

# 10. AI Quiz

Quiz type:

```text
MULTIPLE_CHOICE
TRUE_FALSE
FILL_BLANK
SHORT_ANSWER
ESSAY
```

Mỗi câu hỏi lưu:

```text
question
type
topic
difficulty
correct_answer
explanation
source_document
source_chunk
```

Difficulty:

```text
EASY
MEDIUM
HARD
```

---

# 11. Flashcard

Flashcard gồm:

```text
Front
Back
Topic
Source
Difficulty
```

Mode:

- Learn.
- Shuffle.
- Test.

Advanced:

- Again.
- Hard.
- Good.
- Easy.

Có thể áp dụng thuật toán spaced repetition.

---

# 12. Mindmap

Nguồn dữ liệu:

```text
Document Structure
+
Detected Topics
+
Topic Relationships
```

Ví dụ:

```text
Database
├── SQL
│   ├── SELECT
│   ├── JOIN
│   │   ├── INNER JOIN
│   │   ├── LEFT JOIN
│   │   └── RIGHT JOIN
│   └── GROUP BY
└── Normalization
```

---

# 13. Notebook, Bookmark và Highlight

## Notebook

Người dùng:

- Tạo note.
- Gắn tag.
- Link note với tài liệu.
- Link note với topic.

AI có thể:

- Gợi ý tag.
- Tóm tắt note.
- Gom nhóm note.

## Bookmark

Lưu:

- Document.
- Page.
- Chunk.
- Quiz.
- Flashcard.

## Highlight

Lưu:

```text
document_id
page
start_offset
end_offset
selected_text
color
note
```

---

# 14. Learning Tracking

Đây là phần quan trọng để hệ thống thực sự cá nhân hóa.

## 14.1. Study Session

```text
StudySession
- id
- user_id
- started_at
- ended_at
- total_duration
- source
```

## 14.2. Learning Event

Mỗi hành vi học được lưu thành event.

```text
LearningEvent
- id
- user_id
- event_type
- resource_type
- resource_id
- topic_id
- occurred_at
- duration
- metadata
```

Event types:

```text
DOCUMENT_OPEN
DOCUMENT_READ
CHAT_QUESTION
SUMMARY_VIEW
QUIZ_START
QUIZ_SUBMIT
QUESTION_ANSWER
FLASHCARD_REVIEW
NOTE_CREATE
BOOKMARK_CREATE
HIGHLIGHT_CREATE
PLAN_TASK_COMPLETE
```

---

# 15. Learning Analytics

## 15.1. Descriptive Analytics

Trả lời:

> Người học đã học như thế nào?

Metric:

- Study Time.
- Quiz Score.
- Accuracy.
- Learning Streak.
- Daily Heatmap.
- Weekly Goal.
- Number of Documents.
- Number of Questions Asked.
- Flashcard Reviews.

## 15.2. Diagnostic Analytics

Trả lời:

> Người học đang yếu ở đâu?

Ví dụ:

```text
SQL                     0.78
├── SELECT              0.90
├── JOIN                0.52
│   ├── INNER JOIN      0.82
│   └── LEFT JOIN       0.39
└── GROUP BY            0.75
```

## 15.3. Prescriptive Analytics

Trả lời:

> Người học nên làm gì tiếp theo?

Ví dụ:

```text
Weak topic: LEFT JOIN

Recommendations:
1. Đọc lại Chapter 5.3
2. Xem summary
3. Học 5 flashcards
4. Làm quiz 10 câu
5. Ôn lại sau 2 ngày
```

---

# 16. Topic Model

Mỗi nội dung nên liên kết với Topic.

```text
Topic
- id
- parent_id
- name
- description
```

Ví dụ:

```text
Database
  SQL
    SELECT
    JOIN
      INNER JOIN
      LEFT JOIN
    GROUP BY
```

Topic giúp kết nối:

```text
Document Chunk
Quiz Question
Flashcard
Learning Event
User Mastery
Recommendation
```

---

# 17. User Topic Mastery

Mỗi user có mastery score theo từng topic.

```text
UserTopicMastery
- user_id
- topic_id
- mastery_score
- confidence
- last_practiced_at
- updated_at
```

Range:

```text
0.0 → chưa biết
1.0 → thành thạo
```

Ví dụ:

| Topic | Mastery |
|---|---:|
| SELECT | 0.91 |
| INNER JOIN | 0.82 |
| LEFT JOIN | 0.39 |
| GROUP BY | 0.76 |

---

# 18. Mastery Score

Phiên bản MVP có thể sử dụng công thức dễ giải thích:

\[
M = 0.50Q + 0.20F + 0.20R + 0.10C
\]

Trong đó:

- `Q`: Quiz accuracy.
- `F`: Flashcard performance.
- `R`: Recent performance.
- `C`: Study consistency.

Sau này có thể nghiên cứu:

- Item Response Theory.
- Bayesian Knowledge Tracing.
- Deep Knowledge Tracing.

---

# 19. Forgetting Model

Có thể dùng đường cong quên:

\[
R(t)=e^{-t/S}
\]

Trong đó:

- `R(t)`: khả năng ghi nhớ.
- `t`: thời gian từ lần ôn gần nhất.
- `S`: độ bền trí nhớ.

Nếu:

```text
R(t) < review_threshold
```

hệ thống tạo recommendation ôn tập.

---

# 20. Recommendation Engine

Input:

```text
Topic mastery
Quiz history
Flashcard history
Study frequency
Recent activity
Forgetting score
Upcoming deadline
```

Output:

```text
Recommended resource
Recommended topic
Recommended quiz
Recommended flashcard
Recommended study task
```

Rule MVP:

```text
IF mastery < 0.60
    priority += HIGH

IF forgetting_probability > threshold
    priority += HIGH

IF exam_deadline_is_near
    priority += HIGH
```

Recommendation có lý do:

```text
"Bạn nên ôn LEFT JOIN vì:
- mastery = 0.39
- sai 4/6 câu gần nhất
- đã 5 ngày chưa ôn"
```

---

# 21. AI Study Planner

Input:

```text
Goal
Deadline
Available hours/day
Topic list
Topic mastery
Difficulty
```

Output:

```text
Study Plan
├── Day 1
│   ├── Topic A
│   └── Quiz A
├── Day 2
│   ├── Topic B
│   └── Flashcards
└── ...
```

Planner không chỉ dùng LLM mà nên có scheduler logic.

Priority:

\[
Priority =
w_1(1-Mastery)
+
w_2 ForgettingRisk
+
w_3 ExamUrgency
+
w_4 Difficulty
\]

---

# 22. Calendar & Notification

Calendar:

- Study task.
- Quiz.
- Review.
- Exam.
- Deadline.

Notification:

- Daily study reminder.
- Review reminder.
- Plan task reminder.
- Streak warning.

---

# 23. Pomodoro

Mode:

```text
25 / 5
50 / 10
Custom
```

Pomodoro session có thể kết nối StudySession để tính study time thực tế.

---

# 24. Gamification

MVP:

- XP.
- Level.
- Badge.
- Daily streak.

Ví dụ XP:

```text
Complete quiz       +20 XP
Review flashcard    +5 XP
Complete study task +15 XP
7-day streak        +50 XP
```

Không ưu tiên leaderboard trong MVP.

---

# 25. Admin Module

Admin dashboard:

- Total users.
- Active users.
- Total documents.
- Total storage.
- AI requests.
- Token usage.
- Failed jobs.
- Average processing time.
- System errors.

Admin functions:

```text
User Management
Storage Monitoring
AI Usage Monitoring
Report Management
System Analytics
```

---

# 26. Kiến trúc tổng thể

```mermaid
flowchart TB
    U[Student / Admin]
    FE[Next.js Frontend]
    BE[Spring Boot Backend]
    PG[(PostgreSQL)]
    RD[(Redis)]
    FS[(MinIO)]
    MQ[Task Queue]
    AI[FastAPI AI Service]
    VDB[(Qdrant)]
    LLM[LLM Provider / Ollama]
    EMB[Embedding Model]
    RR[Reranker]

    U --> FE
    FE -->|REST + JWT| BE

    BE --> PG
    BE --> RD
    BE --> FS
    BE --> MQ

    MQ --> AI
    BE -->|AI Request| AI

    AI --> VDB
    AI --> LLM
    AI --> EMB
    AI --> RR

    AI -->|Result| BE
```

---

# 27. Component Diagram

```mermaid
flowchart LR
    subgraph Frontend
        UI[Web UI]
        DASH[Analytics Dashboard]
        DOCUI[Document Viewer]
        CHATUI[AI Chat]
        QUIZUI[Quiz / Flashcard UI]
        PLANUI[Planner UI]
    end

    subgraph Backend
        AUTH[Auth Module]
        USER[User Module]
        DOC[Document Module]
        LEARN[Learning Module]
        ANALYTICS[Analytics Module]
        PLAN[Planning Module]
        ADMIN[Admin Module]
        NOTI[Notification Module]
    end

    subgraph AI_Service
        PARSER[Document Parser]
        OCR[OCR]
        CHUNK[Chunker]
        RET[Retriever]
        RERANK[Reranker]
        RAG[RAG Engine]
        GEN[Content Generator]
        RECOMMEND[Recommendation Engine]
    end

    UI --> AUTH
    DOCUI --> DOC
    CHATUI --> LEARN
    QUIZUI --> LEARN
    DASH --> ANALYTICS
    PLANUI --> PLAN

    DOC --> PARSER
    PARSER --> OCR
    PARSER --> CHUNK
    LEARN --> RAG
    RAG --> RET
    RET --> RERANK
    LEARN --> GEN
    ANALYTICS --> RECOMMEND
    PLAN --> RECOMMEND
```

---

# 28. Deployment Diagram

```mermaid
flowchart TB
    BROWSER[User Browser]

    subgraph Server
        NGINX[Nginx / Reverse Proxy]
        NEXT[Next.js]
        SPRING[Spring Boot API]
        FASTAPI[FastAPI AI Service]
        WORKER[AI Worker]

        POSTGRES[(PostgreSQL)]
        REDIS[(Redis)]
        MINIO[(MinIO)]
        QDRANT[(Qdrant)]
    end

    EXTLLM[External LLM API]
    LOCAL[Local Ollama]

    BROWSER --> NGINX
    NGINX --> NEXT
    NGINX --> SPRING

    SPRING --> POSTGRES
    SPRING --> REDIS
    SPRING --> MINIO
    SPRING --> FASTAPI

    REDIS --> WORKER
    WORKER --> MINIO
    WORKER --> QDRANT

    FASTAPI --> QDRANT
    FASTAPI --> EXTLLM
    FASTAPI --> LOCAL
```

---

# 29. Use Case Diagram — Tổng quan

```mermaid
flowchart LR
    S((Student))
    A((Admin))

    UC1[Manage Account]
    UC2[Manage Documents]
    UC3[Ask AI]
    UC4[Generate Summary]
    UC5[Generate Quiz]
    UC6[Study Flashcards]
    UC7[View Analytics]
    UC8[Receive Recommendations]
    UC9[Manage Study Plan]
    UC10[Use Pomodoro]
    UC11[Manage Notes / Highlights]
    UC12[Manage Users]
    UC13[Monitor AI Usage]
    UC14[Monitor Storage]
    UC15[View System Analytics]

    S --> UC1
    S --> UC2
    S --> UC3
    S --> UC4
    S --> UC5
    S --> UC6
    S --> UC7
    S --> UC8
    S --> UC9
    S --> UC10
    S --> UC11

    A --> UC12
    A --> UC13
    A --> UC14
    A --> UC15
```

---

# 30. Use Case — Document Management

```mermaid
flowchart LR
    S((Student))

    U1[Upload Document]
    U2[Create Folder]
    U3[Assign Tag]
    U4[Rename]
    U5[Delete]
    U6[View Document]
    U7[Search Document]
    U8[Check Processing Status]

    S --> U1
    S --> U2
    S --> U3
    S --> U4
    S --> U5
    S --> U6
    S --> U7
    S --> U8
```

---

# 31. Use Case — AI Learning

```mermaid
flowchart LR
    S((Student))

    A1[Ask Question]
    A2[View Citation]
    A3[Generate Summary]
    A4[Generate Quiz]
    A5[Generate Flashcards]
    A6[Generate Mindmap]
    A7[Explain Simply]
    A8[Translate Content]

    S --> A1
    S --> A2
    S --> A3
    S --> A4
    S --> A5
    S --> A6
    S --> A7
    S --> A8
```

---

# 32. Activity Diagram — Upload Document

```mermaid
flowchart TD
    A([Start])
    B[Select File]
    C{Valid Type & Size?}
    D[Show Validation Error]
    E[Upload File]
    F[Save File to MinIO]
    G[Create Document Record]
    H[Set Status = QUEUED]
    I[Push Processing Job]
    J[Return Document ID]
    K([End])

    A --> B --> C
    C -- No --> D --> K
    C -- Yes --> E --> F --> G --> H --> I --> J --> K
```

---

# 33. Activity Diagram — Document Processing

```mermaid
flowchart TD
    A([Receive Job])
    B[Set PROCESSING]
    C[Load File]
    D[Extract Text]
    E{Need OCR?}
    F[Run OCR]
    G[Clean Text]
    H[Detect Chapters / Sections]
    I[Chunk Document]
    J[Generate Metadata]
    K[Generate Embeddings]
    L[Store in Qdrant]
    M[Set READY]
    N([Done])

    ERR[Set FAILED + Log Error]

    A --> B --> C --> D --> E
    E -- Yes --> F --> G
    E -- No --> G
    G --> H --> I --> J --> K --> L --> M --> N

    C -. Error .-> ERR
    D -. Error .-> ERR
    K -. Error .-> ERR
```

---

# 34. Activity Diagram — RAG Chat

```mermaid
flowchart TD
    A([User asks])
    B[Normalize Query]
    C[Generate Query Embedding]
    D[Retrieve Top-K Chunks]
    E[Rerank Chunks]
    F{Enough Context?}
    G[Return Insufficient Context]
    H[Build Prompt]
    I[Call LLM]
    J[Generate Answer]
    K[Attach Citations]
    L[Save Chat History]
    M[Create Learning Event]
    N([Display Answer])

    A --> B --> C --> D --> E --> F
    F -- No --> G --> L --> M --> N
    F -- Yes --> H --> I --> J --> K --> L --> M --> N
```

---

# 35. Activity Diagram — Quiz Learning Loop

```mermaid
flowchart TD
    A([Generate Quiz])
    B[Select Topic / Document]
    C[Generate Questions]
    D[Validate Grounding]
    E[User Starts Quiz]
    F[Answer Questions]
    G[Submit]
    H[Calculate Score]
    I[Store Attempts]
    J[Update Topic Mastery]
    K[Detect Weak Topics]
    L[Generate Recommendations]
    M([Show Result])

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> K --> L --> M
```

---

# 36. Activity Diagram — Personalized Recommendation

```mermaid
flowchart TD
    A([Start])
    B[Load User Topic Mastery]
    C[Load Recent Quiz Results]
    D[Load Flashcard Reviews]
    E[Calculate Forgetting Risk]
    F[Load Upcoming Deadlines]
    G[Calculate Topic Priority]
    H[Rank Recommendations]
    I[Generate Explanation]
    J[Save Recommendation]
    K([Display])

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> K
```

---

# 37. Sequence Diagram — Login

```mermaid
sequenceDiagram
    actor User
    participant FE as Next.js
    participant BE as Spring Boot
    participant DB as PostgreSQL
    participant R as Redis

    User->>FE: Enter email/password
    FE->>BE: POST /auth/login
    BE->>DB: Find user
    DB-->>BE: User + password hash
    BE->>BE: Verify password
    BE->>R: Store refresh session
    BE-->>FE: Access token + refresh token
    FE-->>User: Login success
```

---

# 38. Sequence Diagram — Upload & Process Document

```mermaid
sequenceDiagram
    actor Student
    participant FE as Next.js
    participant BE as Spring Boot
    participant FS as MinIO
    participant DB as PostgreSQL
    participant Q as Redis Queue
    participant W as AI Worker
    participant V as Qdrant

    Student->>FE: Upload PDF
    FE->>BE: POST /documents
    BE->>FS: Store file
    FS-->>BE: Object key
    BE->>DB: Create document
    BE->>Q: Enqueue processing job
    BE-->>FE: 202 Accepted + documentId

    Q->>W: Consume job
    W->>FS: Download file
    W->>W: Extract + Chunk + Embed
    W->>V: Store vectors
    W->>DB: Update status READY

    FE->>BE: GET /documents/{id}
    BE-->>FE: READY
```

---

# 39. Sequence Diagram — RAG Question Answering

```mermaid
sequenceDiagram
    actor Student
    participant FE as Next.js
    participant BE as Spring Boot
    participant AI as FastAPI
    participant V as Qdrant
    participant RR as Reranker
    participant LLM as LLM

    Student->>FE: Ask question
    FE->>BE: POST /chat/messages
    BE->>AI: RAG request
    AI->>V: Retrieve Top-K
    V-->>AI: Candidate chunks
    AI->>RR: Rerank
    RR-->>AI: Top context
    AI->>AI: Check context confidence

    alt Enough context
        AI->>LLM: Prompt + context
        LLM-->>AI: Answer
        AI-->>BE: Answer + citations
    else Insufficient context
        AI-->>BE: INSufficient context
    end

    BE->>BE: Save conversation + learning event
    BE-->>FE: Response
    FE-->>Student: Display answer
```

---

# 40. Sequence Diagram — Quiz Submission

```mermaid
sequenceDiagram
    actor Student
    participant FE as Next.js
    participant BE as Spring Boot
    participant DB as PostgreSQL
    participant ANA as Analytics Service
    participant REC as Recommendation Engine

    Student->>FE: Submit quiz
    FE->>BE: POST /quiz-attempts/{id}/submit
    BE->>DB: Save question attempts
    BE->>BE: Calculate score
    BE->>ANA: Update mastery
    ANA->>DB: Store UserTopicMastery
    ANA->>REC: Trigger weak-topic analysis
    REC->>DB: Save recommendations
    BE-->>FE: Score + weak topics + recommendations
    FE-->>Student: Show learning feedback
```

---

# 41. Sequence Diagram — Study Planner

```mermaid
sequenceDiagram
    actor Student
    participant FE as Next.js
    participant BE as Spring Boot
    participant DB as PostgreSQL
    participant REC as Recommendation Engine
    participant AI as LLM Planner

    Student->>FE: Enter goal/deadline/time
    FE->>BE: POST /study-plans
    BE->>DB: Load mastery + topics
    BE->>REC: Calculate priorities
    REC-->>BE: Ranked topics
    BE->>AI: Generate structured schedule
    AI-->>BE: Draft plan
    BE->>BE: Validate schedule constraints
    BE->>DB: Save plan/tasks
    BE-->>FE: Study plan
```

---

# 42. State Diagram — Document

```mermaid
stateDiagram-v2
    [*] --> UPLOADED
    UPLOADED --> QUEUED
    QUEUED --> PROCESSING
    PROCESSING --> READY
    PROCESSING --> FAILED
    FAILED --> QUEUED: Retry
    READY --> PROCESSING: Re-index
    READY --> [*]: Delete
```

---

# 43. State Diagram — Study Task

```mermaid
stateDiagram-v2
    [*] --> TODO
    TODO --> IN_PROGRESS
    IN_PROGRESS --> COMPLETED
    TODO --> SKIPPED
    IN_PROGRESS --> SKIPPED
    COMPLETED --> [*]
    SKIPPED --> TODO: Reschedule
```

---

# 44. Class Diagram — Domain Model

```mermaid
classDiagram
    class User {
        +UUID id
        +String email
        +String passwordHash
        +String fullName
        +Role role
        +DateTime createdAt
    }

    class Document {
        +UUID id
        +String title
        +String fileType
        +String objectKey
        +DocumentStatus status
        +DateTime uploadedAt
    }

    class DocumentChunk {
        +UUID id
        +UUID documentId
        +int page
        +String chapter
        +String section
        +String text
        +int chunkIndex
    }

    class Topic {
        +UUID id
        +UUID parentId
        +String name
    }

    class Conversation {
        +UUID id
        +UUID userId
        +String title
    }

    class Message {
        +UUID id
        +Role sender
        +String content
        +DateTime createdAt
    }

    class Quiz {
        +UUID id
        +String title
        +Difficulty difficulty
    }

    class Question {
        +UUID id
        +QuestionType type
        +String content
        +String correctAnswer
        +String explanation
    }

    class QuizAttempt {
        +UUID id
        +double score
        +DateTime startedAt
        +DateTime completedAt
    }

    class QuestionAttempt {
        +UUID id
        +String answer
        +boolean correct
        +int responseTime
    }

    class Flashcard {
        +UUID id
        +String front
        +String back
    }

    class FlashcardReview {
        +UUID id
        +ReviewRating rating
        +DateTime nextReviewAt
    }

    class LearningEvent {
        +UUID id
        +EventType eventType
        +DateTime occurredAt
        +long duration
    }

    class UserTopicMastery {
        +UUID userId
        +UUID topicId
        +double masteryScore
        +double confidence
    }

    class StudyPlan {
        +UUID id
        +String goal
        +Date deadline
    }

    class StudyTask {
        +UUID id
        +DateTime scheduledAt
        +TaskStatus status
    }

    class Recommendation {
        +UUID id
        +String type
        +double priority
        +String reason
    }

    User "1" --> "*" Document
    Document "1" --> "*" DocumentChunk
    DocumentChunk "*" --> "*" Topic

    User "1" --> "*" Conversation
    Conversation "1" --> "*" Message

    User "1" --> "*" QuizAttempt
    Quiz "1" --> "*" Question
    QuizAttempt "1" --> "*" QuestionAttempt
    Question "1" --> "*" QuestionAttempt
    Question "*" --> "*" Topic

    User "1" --> "*" FlashcardReview
    Flashcard "1" --> "*" FlashcardReview
    Flashcard "*" --> "*" Topic

    User "1" --> "*" LearningEvent
    LearningEvent "*" --> "0..1" Topic

    User "1" --> "*" UserTopicMastery
    Topic "1" --> "*" UserTopicMastery

    User "1" --> "*" StudyPlan
    StudyPlan "1" --> "*" StudyTask

    User "1" --> "*" Recommendation
    Recommendation "*" --> "0..1" Topic
```

---

# 45. ERD rút gọn

```mermaid
erDiagram
    USERS ||--o{ DOCUMENTS : owns
    USERS ||--o{ CONVERSATIONS : creates
    USERS ||--o{ QUIZ_ATTEMPTS : performs
    USERS ||--o{ FLASHCARD_REVIEWS : performs
    USERS ||--o{ LEARNING_EVENTS : generates
    USERS ||--o{ USER_TOPIC_MASTERY : has
    USERS ||--o{ STUDY_PLANS : creates
    USERS ||--o{ RECOMMENDATIONS : receives

    DOCUMENTS ||--o{ DOCUMENT_CHUNKS : contains
    DOCUMENTS }o--o{ TAGS : tagged

    TOPICS ||--o{ TOPICS : parent
    TOPICS }o--o{ DOCUMENT_CHUNKS : maps
    TOPICS }o--o{ QUESTIONS : maps
    TOPICS }o--o{ FLASHCARDS : maps

    CONVERSATIONS ||--o{ MESSAGES : contains

    QUIZZES ||--o{ QUESTIONS : contains
    QUIZZES ||--o{ QUIZ_ATTEMPTS : attempted
    QUIZ_ATTEMPTS ||--o{ QUESTION_ATTEMPTS : contains
    QUESTIONS ||--o{ QUESTION_ATTEMPTS : answered

    FLASHCARDS ||--o{ FLASHCARD_REVIEWS : reviewed

    STUDY_PLANS ||--o{ STUDY_TASKS : contains
```

---

# 46. Cấu trúc cơ sở dữ liệu đề xuất

## users

```text
id
email
password_hash
full_name
role
avatar_url
created_at
updated_at
```

## documents

```text
id
user_id
folder_id
title
original_filename
file_type
object_key
status
page_count
error_message
created_at
processed_at
```

## document_chunks

```text
id
document_id
page_number
chapter
section
chunk_index
content
token_count
vector_id
```

## topics

```text
id
parent_id
name
description
```

## document_chunk_topics

```text
chunk_id
topic_id
confidence
```

## conversations

```text
id
user_id
title
created_at
```

## messages

```text
id
conversation_id
role
content
metadata
created_at
```

## quizzes

```text
id
user_id
document_id
title
difficulty
created_at
```

## questions

```text
id
quiz_id
type
content
correct_answer
explanation
difficulty
source_chunk_id
```

## question_topics

```text
question_id
topic_id
```

## quiz_attempts

```text
id
quiz_id
user_id
score
started_at
completed_at
```

## question_attempts

```text
id
quiz_attempt_id
question_id
user_answer
is_correct
response_time_ms
```

## flashcards

```text
id
user_id
document_id
front
back
source_chunk_id
created_at
```

## flashcard_reviews

```text
id
flashcard_id
user_id
rating
reviewed_at
next_review_at
interval_days
```

## learning_events

```text
id
user_id
event_type
resource_type
resource_id
topic_id
duration_seconds
metadata
occurred_at
```

## user_topic_mastery

```text
user_id
topic_id
mastery_score
confidence
last_practiced_at
updated_at
```

## study_plans

```text
id
user_id
goal
deadline
hours_per_day
status
created_at
```

## study_tasks

```text
id
plan_id
topic_id
resource_type
resource_id
scheduled_at
estimated_minutes
status
```

## recommendations

```text
id
user_id
topic_id
recommendation_type
resource_id
priority
reason
created_at
expires_at
```

---

# 47. API Design

Base:

```text
/api/v1
```

## Authentication

```text
POST   /auth/register
POST   /auth/login
POST   /auth/refresh
POST   /auth/logout
POST   /auth/forgot-password
POST   /auth/reset-password
```

## User

```text
GET    /users/me
PATCH  /users/me
GET    /users/me/dashboard
```

## Documents

```text
POST   /documents
GET    /documents
GET    /documents/{id}
PATCH  /documents/{id}
DELETE /documents/{id}

GET    /documents/{id}/status
POST   /documents/{id}/reprocess
```

## Search

```text
POST   /search/semantic
```

## Chat

```text
POST   /conversations
GET    /conversations
GET    /conversations/{id}
POST   /conversations/{id}/messages
```

## Summary

```text
POST   /documents/{id}/summaries
GET    /documents/{id}/summaries
```

## Quiz

```text
POST   /quizzes/generate
GET    /quizzes/{id}

POST   /quizzes/{id}/attempts
POST   /quiz-attempts/{id}/answers
POST   /quiz-attempts/{id}/submit
```

## Flashcard

```text
POST   /flashcards/generate
GET    /flashcards
POST   /flashcards/{id}/reviews
```

## Analytics

```text
GET /analytics/overview
GET /analytics/study-time
GET /analytics/quiz-performance
GET /analytics/topics
GET /analytics/mastery
GET /analytics/weak-topics
```

## Recommendation

```text
GET  /recommendations
POST /recommendations/{id}/complete
POST /recommendations/{id}/dismiss
```

## Study Plan

```text
POST   /study-plans
GET    /study-plans
GET    /study-plans/{id}
PATCH  /study-plans/{id}

POST   /study-plans/{id}/tasks
PATCH  /study-tasks/{id}
```

## Admin

```text
GET /admin/users
GET /admin/storage
GET /admin/ai-usage
GET /admin/jobs
GET /admin/system-analytics
```

---

# 48. Kiến trúc Backend

## Spring Boot

Phụ trách:

```text
Authentication
Authorization
Users
Documents metadata
Folders
Tags
Conversations
Quiz records
Flashcard records
Learning events
Analytics APIs
Study plans
Notifications
Admin
```

Package gợi ý:

```text
com.studyassistant
├── auth
├── user
├── document
├── knowledge
├── chat
├── quiz
├── flashcard
├── learning
├── analytics
├── recommendation
├── planner
├── notification
├── admin
├── common
└── infrastructure
```

---

# 49. Kiến trúc AI Service

FastAPI:

```text
ai_service/
├── api/
├── ingestion/
│   ├── parser/
│   ├── ocr/
│   ├── cleaner/
│   ├── chunker/
│   └── metadata/
├── embeddings/
├── retrieval/
├── reranking/
├── rag/
├── generation/
│   ├── summary/
│   ├── quiz/
│   ├── flashcard/
│   └── mindmap/
├── analytics/
├── recommendation/
├── planner/
├── evaluation/
└── core/
```

---

# 50. Background Processing

Không chạy document ingestion trong HTTP request.

```text
POST /documents
      ↓
Save file
      ↓
Create document row
      ↓
Push job
      ↓
Return 202
```

Worker:

```text
Consume job
   ↓
Process
   ↓
Store embeddings
   ↓
Update document status
```

---

# 51. Cache Strategy

Redis có thể cache:

- Session.
- Rate limit.
- Dashboard statistics.
- Popular retrieval result.
- Temporary generation result.
- Processing progress.

Không cache dữ liệu cá nhân nhạy cảm một cách tùy tiện.

---

# 52. File Storage

MinIO structure:

```text
/users/{user_id}/documents/{document_id}/original.pdf
/users/{user_id}/documents/{document_id}/preview/
/users/{user_id}/exports/
```

---

# 53. Vector Database

Qdrant collection:

```text
document_chunks
```

Payload:

```json
{
  "user_id": "...",
  "document_id": "...",
  "page": 10,
  "chapter": "Chapter 3",
  "section": "Polymorphism",
  "chunk_index": 20
}
```

Retrieval bắt buộc filter theo ownership:

```text
user_id = current_user
```

hoặc collection/domain tương ứng.

---

# 54. Chunking Strategy

Không chỉ fixed character.

MVP:

```text
Recursive chunking
chunk_size ≈ 500–1000 tokens
overlap ≈ 10–20%
```

Advanced:

```text
Structure-aware chunking
Chapter
Section
Paragraph
Table
```

Các tham số cần được benchmark thay vì cố định cảm tính.

---

# 55. Retrieval Strategy

## Baseline A

```text
Dense Retrieval
Top-K = 10
```

## Baseline B

```text
Dense Retrieval
+
Reranking
Top-10 → Top-5
```

## Advanced

```text
BM25
+
Dense Retrieval
+
Reciprocal Rank Fusion
+
Cross-Encoder Reranking
```

---

# 56. Prompt Grounding

Prompt cần chứa rule:

```text
- Chỉ sử dụng context được cung cấp.
- Không tự bổ sung kiến thức ngoài nguồn nếu chế độ grounded-only được bật.
- Nếu context không đủ, nói rõ không đủ thông tin.
- Trích dẫn nguồn tương ứng.
```

---

# 57. AI Content Generation Safety

Quiz/summary/flashcard phải liên kết với source chunk.

Sau sinh:

```text
Generated Content
      ↓
Source Grounding Check
      ↓
Quality Validation
      ↓
Save
```

Không coi nội dung LLM sinh ra là chính xác mặc định.

---

# 58. Logging

Log:

```text
request_id
user_id
endpoint
latency
status
ai_model
token_usage
retrieval_latency
llm_latency
error_code
```

Không log:

- Password.
- Refresh token.
- Full sensitive content khi không cần thiết.

---

# 59. Security

## Authentication

- Password hashing: BCrypt/Argon2.
- Access token ngắn hạn.
- Refresh token.
- Rotation.
- Revoke session.

## Authorization

Object-level permission:

```text
current_user.id == document.user_id
```

## Upload Security

- MIME validation.
- Extension validation.
- Max file size.
- Safe filename.
- Virus scanning nếu có điều kiện.
- Không execute uploaded files.

## API

- Rate limiting.
- CORS policy.
- Request validation.
- SQL injection prevention.
- XSS prevention.
- CSRF tùy cơ chế token/cookie.

## AI Security

- Prompt injection defense.
- Retrieval ownership filter.
- No cross-user retrieval.
- Input length limit.
- Output sanitation.

---

# 60. Non-Functional Requirements

## Performance

Mục tiêu đề xuất:

```text
Normal API p95          < 500 ms
Dashboard cached p95    < 1 s
RAG first response      < 5–10 s
Upload request          < 2 s để trả 202
```

Document processing chạy background.

## Reliability

- Job retry.
- Dead-letter mechanism.
- Idempotent processing.
- Graceful failure.

## Scalability

Có thể scale riêng:

```text
Spring Boot
FastAPI
Worker
Qdrant
```

## Maintainability

- Modular architecture.
- API versioning.
- Unit test.
- Integration test.
- Docker.

---

# 61. Testing Strategy

## Unit Test

- Auth.
- Mastery calculation.
- Recommendation scoring.
- Quiz grading.
- Scheduler.

## Integration Test

- Spring Boot + PostgreSQL.
- Upload + MinIO.
- AI Service + Qdrant.
- Queue + worker.

## E2E Test

Flow:

```text
Register
→ Login
→ Upload
→ Wait READY
→ Ask
→ Generate Quiz
→ Submit
→ View Analytics
→ View Recommendation
```

## Security Test

- Unauthorized access.
- Cross-user document access.
- Invalid upload.
- Token expiration.
- Prompt injection test.

---

# 62. AI Evaluation

Đây là phần bắt buộc nếu muốn đồ án có chiều sâu.

## 62.1. RAG Retrieval Dataset

Tạo:

```text
100–300 question–evidence pairs
```

Mỗi mẫu:

```text
question
relevant_document
relevant_page
relevant_chunk
reference_answer
```

## 62.2. Retrieval Metrics

- Recall@K.
- Hit Rate@K.
- MRR.
- Precision@K.

## 62.3. RAG Answer Metrics

- Answer Correctness.
- Faithfulness.
- Context Relevance.
- Citation Correctness.

## 62.4. Ablation

Ví dụ:

| Method | Recall@5 | MRR |
|---|---:|---:|
| BM25 | x | x |
| Dense | x | x |
| Dense + Reranker | x | x |
| Hybrid + Reranker | x | x |

Không điền số trước khi thực nghiệm.

---

# 63. Quiz Evaluation

Đánh giá:

- Relevance.
- Correctness.
- Groundedness.
- Difficulty appropriateness.
- Explanation correctness.

Có thể đánh giá thủ công bằng rubric 1–5.

---

# 64. Recommendation Evaluation

Offline scenario:

```text
Student A:
SELECT mastery = 0.90
JOIN mastery = 0.42
GROUP BY mastery = 0.81

Expected top recommendation:
JOIN
```

Metric:

- Weak-topic detection accuracy.
- Precision@K.
- Recommendation relevance rating.

---

# 65. Usability Evaluation

Có thể mời 10–20 sinh viên test.

Survey:

- Ease of use.
- Helpfulness.
- Trust in citations.
- Quiz usefulness.
- Recommendation usefulness.
- Dashboard clarity.

Dùng Likert scale 1–5.

---

# 66. KPI đồ án

Ví dụ KPI kỹ thuật:

```text
Document success processing rate
RAG Recall@5
RAG answer correctness
Citation correctness
Quiz groundedness
Average response latency
Recommendation relevance
User task completion rate
```

---

# 67. Dữ liệu và quyền riêng tư

Dữ liệu người dùng:

- Tài liệu.
- Chat history.
- Quiz attempts.
- Study events.
- Learning profile.

Nguyên tắc:

- User chỉ truy cập dữ liệu của chính mình.
- Có chức năng delete.
- Không đưa tài liệu riêng vào training model.
- Chỉ gửi phần context cần thiết đến external LLM nếu dùng cloud API.
- Có thông báo cho người dùng về external AI provider.

---

# 68. Công nghệ đề xuất

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Backend | Spring Boot |
| AI Service | FastAPI |
| Main DB | PostgreSQL |
| Vector DB | Qdrant |
| Cache / Queue | Redis |
| File Storage | MinIO |
| Authentication | JWT + Refresh Token |
| Container | Docker Compose |
| Local LLM | Ollama |
| External LLM | API provider tùy cấu hình |
| AI Framework | Có thể dùng LangChain/LlamaIndex hoặc tự xây pipeline |

Khuyến nghị: không phụ thuộc quá sâu vào framework AI để dễ trình bày pipeline khi bảo vệ.

---

# 69. UI Screens

## Authentication

- Login.
- Register.
- Forgot password.

## Home Dashboard

- Continue Learning.
- Weekly Goal.
- Study Time.
- Streak.
- Weak Topics.
- Recommendations.

## Library

- Folder sidebar.
- Document cards.
- Upload.
- Search.
- Filter.
- Tag.

## Document Workspace

```text
┌───────────────────────────────────────┐
│ Document Viewer        │ AI Assistant │
│                        │              │
│ PDF                    │ Chat         │
│                        │              │
├────────────────────────┴──────────────┤
│ Summary | Quiz | Flashcard | Notes    │
└───────────────────────────────────────┘
```

## Analytics

- Heatmap.
- Study time.
- Quiz trend.
- Topic mastery.
- Weak topics.
- Recommended review.

## Planner

- Goal.
- Calendar.
- Daily tasks.
- Completion status.

---

# 70. Dashboard Information Architecture

```text
Dashboard
├── Today
│   ├── Study tasks
│   ├── Reviews due
│   └── Continue learning
│
├── Progress
│   ├── Study time
│   ├── Quiz score
│   └── Streak
│
├── Knowledge
│   ├── Mastery map
│   ├── Weak topics
│   └── Forgetting risk
│
└── Recommendations
    ├── Read
    ├── Quiz
    ├── Flashcard
    └── Review
```

---

# 71. Demo Scenario bảo vệ

Demo không nên trình bày hàng chục feature rời rạc.

## Kịch bản

### Bước 1

Student đăng nhập.

### Bước 2

Upload:

```text
Database Systems.pdf
```

System hiển thị:

```text
PROCESSING
```

sau đó:

```text
READY
```

### Bước 3

Student hỏi:

```text
"INNER JOIN khác LEFT JOIN như thế nào?"
```

AI trả lời và trích dẫn:

```text
Database Systems.pdf
Chapter 5
Page 87
```

### Bước 4

Student chọn:

```text
Generate 10-question quiz
```

### Bước 5

Student làm sai nhiều câu về LEFT JOIN.

### Bước 6

Analytics cập nhật:

```text
LEFT JOIN mastery = 0.42
```

### Bước 7

Recommendation:

```text
Bạn nên ôn LEFT JOIN.
Reason:
- 4/6 câu gần nhất trả lời sai
- mastery thấp
- 5 ngày chưa ôn
```

### Bước 8

System đề xuất:

- Đọc section 5.3.
- 5 flashcards.
- 10-question practice quiz.
- Review tomorrow.

### Bước 9

Planner tự chèn task vào study plan.

Đây là luồng thể hiện trọn vẹn giá trị:

```text
Document
→ RAG
→ Learning
→ Analytics
→ Personalization
```

---

# 72. Điểm mới và giá trị của đề tài

## 72.1. Không phải PDF chatbot

Hệ thống không dừng ở:

```text
Upload
→ Ask
→ Answer
```

mà là:

```text
Upload
→ Understand
→ Learn
→ Assess
→ Model learner
→ Recommend
```

## 72.2. Kết nối nội dung với hành vi

Một topic có thể xuất hiện đồng thời trong:

- Document.
- Chat.
- Quiz.
- Flashcard.
- Analytics.
- Mastery.
- Recommendation.

## 72.3. Recommendation có giải thích

Không chỉ:

> Hãy học SQL.

Mà:

> Hãy ôn LEFT JOIN vì mastery hiện chỉ 0.39, bạn sai 4/6 câu gần nhất và đã 5 ngày chưa ôn.

---

# 73. Các câu hỏi hội đồng có thể hỏi

## Vì sao phải dùng RAG?

Vì kiến thức chính nằm trong tài liệu cá nhân của user và cần câu trả lời bám sát nguồn.

## Vì sao cần Qdrant?

Để lưu embedding và truy xuất semantic các document chunks.

## Vì sao tách Spring Boot và FastAPI?

Spring Boot xử lý business logic; FastAPI xử lý AI pipeline. Hai thành phần có lifecycle và dependency khác nhau.

## Vì sao không gọi LLM trực tiếp từ frontend?

Vì:
- lộ API key;
- khó kiểm soát quyền;
- khó logging;
- khó lưu learning events;
- khó grounding;
- khó áp dụng business rules.

## Làm thế nào hạn chế hallucination?

- Retrieval.
- Reranking.
- Confidence threshold.
- Prompt grounding.
- Source citation.
- Insufficient-context response.

## Personalization có thật hay chỉ prompt?

Có student model:

```text
UserTopicMastery
ForgettingRisk
QuizHistory
FlashcardHistory
StudyHistory
```

Planner/recommendation dùng các tín hiệu này trước khi dùng LLM.

---

# 74. Rủi ro kỹ thuật

| Risk | Impact | Mitigation |
|---|---|---|
| OCR lỗi | Retrieval sai | OCR fallback + quality check |
| Chunking kém | RAG kém | Benchmark nhiều chunk size |
| LLM hallucination | Sai kiến thức | Grounding + threshold + citation |
| Token cost cao | Tốn chi phí | Cache + local model + context limit |
| File lớn | Timeout | Background worker |
| Scope quá rộng | Không hoàn thiện | Core MVP + Phase 2 |
| Recommendation đơn giản | Ít thuyết phục | Có mastery + forgetting + explainability |
| Cross-user data leak | Nghiêm trọng | Ownership filtering toàn pipeline |

---

# 75. Lộ trình 14 tuần

## Tuần 1 — Phân tích

- Problem statement.
- Functional requirements.
- Non-functional requirements.
- Use Case.
- Architecture draft.

## Tuần 2 — Thiết kế

- ERD.
- Database.
- API contract.
- UI/UX Figma.
- Docker skeleton.

## Tuần 3 — Backend Core

- User.
- Auth.
- JWT.
- Refresh token.
- Role.
- PostgreSQL.

## Tuần 4 — Document Management

- Upload.
- Folder.
- Tag.
- MinIO.
- File metadata.

## Tuần 5 — Ingestion Pipeline

- PDF parser.
- DOCX parser.
- PPTX parser.
- Chunking.
- Background worker.

## Tuần 6 — RAG v1

- Embedding.
- Qdrant.
- Semantic retrieval.
- Chat.
- Citation.

## Tuần 7 — RAG v2

- Reranker.
- Confidence threshold.
- Grounded response.
- Evaluation dataset.
- Retrieval benchmark.

## Tuần 8 — Learning Content

- Summary.
- Quiz.
- Flashcard.
- Source grounding.

## Tuần 9 — Learning Tracking

- StudySession.
- LearningEvent.
- QuizAttempt.
- FlashcardReview.

## Tuần 10 — Analytics

- Study time.
- Accuracy.
- Heatmap.
- Topic mastery.
- Weak-topic detection.

## Tuần 11 — Personalization

- Recommendation Engine.
- Forgetting score.
- Study Planner.

## Tuần 12 — Enhancement

Ưu tiên:

- Spaced repetition.
- Mindmap.
- Gamification.
- Pomodoro.

## Tuần 13 — Production Readiness

- Security.
- Logging.
- Testing.
- Performance.
- Docker Compose.
- Deployment.

## Tuần 14 — Evaluation & Defense

- AI benchmark.
- User testing.
- Report.
- Slides.
- Demo script.
- Video backup.

---

# 76. Work Breakdown Structure

```mermaid
flowchart TD
    P[Graduation Project]

    P --> A[Analysis & Design]
    P --> B[Core Platform]
    P --> C[AI Engine]
    P --> D[Learning Intelligence]
    P --> E[Quality & Deployment]
    P --> F[Report & Defense]

    A --> A1[SRS]
    A --> A2[UML]
    A --> A3[ERD]
    A --> A4[UI/UX]

    B --> B1[Auth]
    B --> B2[Documents]
    B --> B3[Storage]
    B --> B4[Quiz / Flashcard]

    C --> C1[Ingestion]
    C --> C2[RAG]
    C --> C3[Summary]
    C --> C4[Generation]

    D --> D1[Learning Events]
    D --> D2[Analytics]
    D --> D3[Mastery]
    D --> D4[Recommendation]
    D --> D5[Planner]

    E --> E1[Test]
    E --> E2[Security]
    E --> E3[Docker]
    E --> E4[Evaluation]

    F --> F1[Report]
    F --> F2[Slides]
    F --> F3[Demo]
```

---

# 77. Phân chia độ ưu tiên

## P0 — bắt buộc

- Auth.
- Document management.
- File processing.
- RAG.
- Citation.
- Quiz.
- Flashcard.
- Learning events.
- Analytics.
- Mastery.
- Recommendation.
- Planner.

## P1 — rất nên có

- Reranker.
- Hybrid search.
- Spaced repetition.
- Forgetting curve.
- Mindmap.
- Gamification.

## P2 — chỉ làm nếu còn thời gian

- Speech.
- Ranking.
- Challenge.
- Collaboration.

---

# 78. Tiêu chí hoàn thành MVP

MVP được coi là hoàn thành khi một user có thể:

```text
1. Register/Login
2. Upload document
3. Wait until READY
4. Search document semantically
5. Ask grounded questions
6. See citations
7. Generate summary
8. Generate quiz
9. Complete quiz
10. Generate/review flashcards
11. See learning analytics
12. See topic mastery
13. Receive weak-topic recommendations
14. Create a personalized study plan
```

---

# 79. Cấu trúc repository gợi ý

```text
ai-study-assistant/
├── frontend/
├── backend/
├── ai-service/
├── infra/
│   ├── docker/
│   ├── nginx/
│   └── monitoring/
├── docs/
│   ├── srs/
│   ├── uml/
│   ├── api/
│   ├── database/
│   └── evaluation/
├── scripts/
├── docker-compose.yml
└── README.md
```

---

# 80. Cấu trúc báo cáo đồ án gợi ý

## Chương 1 — Tổng quan

- Lý do chọn đề tài.
- Bài toán.
- Mục tiêu.
- Phạm vi.
- Đóng góp.

## Chương 2 — Cơ sở lý thuyết

- LLM.
- Embedding.
- Vector Search.
- RAG.
- Reranking.
- Learning Analytics.
- Knowledge Mastery.
- Forgetting Curve.
- Recommendation.

## Chương 3 — Phân tích và thiết kế

- Requirement.
- Use Case.
- UML.
- ERD.
- Architecture.
- Security.

## Chương 4 — Xây dựng hệ thống

- Frontend.
- Backend.
- AI service.
- Database.
- RAG.
- Analytics.
- Recommendation.

## Chương 5 — Thực nghiệm và đánh giá

- RAG dataset.
- Retrieval benchmark.
- Answer evaluation.
- Quiz evaluation.
- Recommendation evaluation.
- Performance.
- User testing.

## Chương 6 — Kết luận

- Kết quả.
- Hạn chế.
- Hướng phát triển.

---

# 81. Hướng nghiên cứu nâng cao

Sau khi MVP hoàn thiện có thể mở rộng:

## RAG

- Query rewriting.
- Multi-query retrieval.
- HyDE.
- Parent-child retrieval.
- Knowledge graph RAG.

## Student Modeling

- Bayesian Knowledge Tracing.
- Deep Knowledge Tracing.
- Item Response Theory.

## Personalization

- Learning-to-rank.
- Contextual bandit.
- Adaptive difficulty.

## Multimodal

- Image understanding.
- Diagram understanding.
- Lecture video ingestion.

---

# 82. Kết luận kiến trúc

Trọng tâm của đồ án không nên là số lượng feature.

Trái tim hệ thống là:

```text
                    ┌──────────────┐
                    │  Documents   │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Knowledge DB │
                    └──────┬───────┘
                           │
                 ┌─────────┴──────────┐
                 ▼                    ▼
            ┌─────────┐          ┌─────────┐
            │   RAG   │          │Learning │
            └────┬────┘          │ Content │
                 │               └────┬────┘
                 └─────────┬──────────┘
                           ▼
                  ┌────────────────┐
                  │ Learning Event │
                  └───────┬────────┘
                          ▼
                  ┌────────────────┐
                  │ Student Model  │
                  └───────┬────────┘
                          ▼
                  ┌────────────────┐
                  │Recommendation  │
                  └───────┬────────┘
                          ▼
                  ┌────────────────┐
                  │ Next Learning  │
                  └────────────────┘
```

Giá trị cốt lõi:

> **Knowledge → Interaction → Learning Data → Student Model → Personalized Learning**

Đây là hướng giúp AI Study Assistant 2.0 trở thành một **đồ án tốt nghiệp có chiều sâu về Software Engineering, AI và Data Analytics**, thay vì chỉ là một ứng dụng CRUD tích hợp chatbot.

---

# 83. Ranh giới giữa ý tưởng gốc và phần mở rộng trong tài liệu này

## Kế thừa trực tiếp từ ý tưởng ban đầu

- AI Study Assistant / personalized learning platform.
- Quản lý PDF, Word, PPT, ảnh, TXT.
- OCR và trích xuất nội dung.
- Chat với tài liệu.
- Summary.
- Quiz.
- Flashcard.
- Mindmap.
- Explain.
- Translate.
- Notebook.
- Bookmark.
- Highlight.
- Semantic Search.
- Learning Analytics.
- Dashboard.
- Gamification.
- Roadmap / Planner.
- Calendar.
- Notification.
- Pomodoro.
- Speech.
- Admin.
- Next.js.
- Spring Boot.
- FastAPI.
- PostgreSQL.
- Redis.
- MinIO.
- Qdrant.
- Docker Compose.

## Phần được mở rộng để phù hợp mức đồ án tốt nghiệp

- Scope MVP / P0 / P1 / P2.
- Background job architecture.
- Student model.
- Topic mastery.
- Learning event model.
- Forgetting curve.
- Explainable recommendation.
- Grounded citation.
- Hallucination control.
- Reranking.
- RAG evaluation.
- Quiz evaluation.
- Recommendation evaluation.
- Security model.
- Testing strategy.
- Non-functional requirements.
- API design.
- Detailed database schema.
- UML diagrams.
- Deployment architecture.
- Demo scenario.
- Defense questions.
- Technical risk management.

---

# 84. Tên đề tài khuyến nghị cuối cùng

## Tiếng Việt

**Xây dựng nền tảng học tập cá nhân hóa ứng dụng mô hình ngôn ngữ lớn, Retrieval-Augmented Generation và Learning Analytics**

## Tiếng Anh

**Design and Development of a Personalized AI Learning Platform using Large Language Models, Retrieval-Augmented Generation and Learning Analytics**

## Tên sản phẩm

**AI Study Assistant 2.0**

---

# 85. Một câu mô tả dùng khi bảo vệ

> AI Study Assistant 2.0 là một nền tảng học tập cá nhân hóa, trong đó RAG giúp người học tương tác đáng tin cậy với tài liệu của chính mình, Learning Analytics xây dựng hồ sơ kiến thức của từng người học, và Recommendation Engine sử dụng hồ sơ đó để đề xuất nội dung, bài luyện tập và kế hoạch học phù hợp theo thời gian.

