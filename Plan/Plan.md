Với mục tiêu bạn đang hướng tới, tôi sẽ không gọi đây là "hệ thống dịch truyện" nữa mà là một **Translation Knowledge Platform (TKP)**.

Khác biệt lớn nhất:

```text
Hệ thống dịch thông thường

Raw
↓
AI
↓
Bản dịch
```

so với

```text
Translation Knowledge Platform

Raw
↓
Knowledge Engine
↓
Draft Translation
↓
AI Refiner
↓
Knowledge Evolution
↓
Knowledge Base
↓
Các chương tiếp theo
```

Nghĩa là AI chỉ là một thành phần, còn tài sản cốt lõi là Knowledge Base được tích lũy theo thời gian.

# TRANSLATION KNOWLEDGE PLATFORM (TKP)

## PHIÊN BẢN TERMUX + UBUNTU

Mục tiêu:

- Dịch hàng loạt nhiều truyện.
    
- Chạy cron tự động.
    
- Dashboard quản lý.
    
- Telegram điều khiển.
    
- Dịch thô bằng Dict Graph.
    
- AI chỉ hiệu chỉnh.
    
- Tích lũy tri thức.
    
- Tự tiến hóa theo thời gian.
    
- Giảm chi phí token.
    
- Tăng độ nhất quán.
    

---

# I. KIẾN TRÚC TỔNG THỂ

```
                Dashboard
                     │
                     ▼
                 SQLite
                     │
                     ▼
                Scheduler
                     │
                     ▼
                  Queue
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
    Worker1      Worker2      WorkerN
                     │
                     ▼
           Translation Engine
                     │
                     ▼
            Knowledge Engine
                     │
                     ▼
                AI Refiner
                     │
                     ▼
            Knowledge Extractor
                     │
                     ▼
              Knowledge Base
```

---

# II. THƯ MỤC HỆ THỐNG

project_root/

├── dashboard/  
├── scheduler/  
├── workers/  
├── telegram/  
├── database/  
├── config/  
├── logs/  
│  
├── knowledge/  
│  
│ ├── graph/  
│ ├── memory/  
│ ├── grammar/  
│ ├── terminology/  
│ ├── style/  
│ ├── character/  
│ └── relationship/  
│  
└── projects/

---

# III. CẤU TRÚC TRUYỆN

projects/{novel_slug}/

├── home.json  
├── toc.json  
├── translation_config.json  
│  
├── readme.md  
├── cover_prompt.md  
│  
├── raw/  
├── draft/  
├── translated/  
├── epub/  
│  
├── logs/  
│  
└── entity/

---

# IV. KNOWLEDGE BASE

Knowledge Base là tài sản quan trọng nhất.

Nó tồn tại độc lập với model AI.

Knowledge Base gồm:

1. Dict Graph
    
2. Translation Memory
    
3. Grammar Graph
    
4. Character Graph
    
5. Relationship Graph
    
6. Terminology Graph
    
7. Style Graph
    

---

# V. DICT GRAPH

Không lưu từ điển kiểu key-value.

Sai:

元婴 → Nguyên Anh

Đúng:

元婴

├─ Nguyên Anh  
├─ Danh từ  
├─ Cảnh giới  
├─ Tiên hiệp  
├─ Rank 4  
└─ Confidence 0.99

---

# VI. TRANSLATION MEMORY

Lưu câu đã dịch.

Ví dụ:

修士踏空而行

↓

Tu sĩ ngự không phi hành

Lần sau:

Không cần AI.

Lấy trực tiếp.

---

# VII. GRAMMAR GRAPH

Lưu cấu trúc ngữ pháp.

Ví dụ:

虽A但B

↓

Tuy A nhưng B

---

# VIII. CHARACTER GRAPH

Mỗi nhân vật là một node.

Ví dụ:

王默

├─ Vương Mặc  
├─ Nam  
├─ Main Character  
└─ Cảnh giới hiện tại

---

# IX. RELATIONSHIP GRAPH

Ví dụ:

Vương Mặc

├─ Sư phụ → Lý Thanh  
├─ Phụ thân → Vương Thiên  
├─ Đạo lữ → Tần Dao  
└─ Kẻ thù → Huyết Ma

---

# X. TERMINOLOGY GRAPH

Lưu thuật ngữ.

Ví dụ:

筑基

├─ Trúc Cơ  
├─ Confidence 0.99  
└─ Xianxia

---

# XI. STYLE GRAPH

Lưu quyết định biên tập.

Ví dụ:

本座

↓

Bổn tọa

Nếu AI sửa 100 lần giống nhau:

Tạo rule tự động.

---

# XII. WORKFLOW DỊCH

Raw Chapter

↓

Text Normalize

↓

Segmentation

↓

Entity Detection

↓

Dict Graph Translation

↓

Grammar Rewrite

↓

Translation Memory Lookup

↓

Draft Translation

↓

AI Refiner

↓

QC

↓

Final Translation

↓

Knowledge Extractor

↓

Knowledge Base Update

---

# XIII. AI REFINER

AI không dịch từ đầu.

AI chỉ nhận:

Raw

Draft

Character

Glossary

Relationship

Style Guide

Sau đó hiệu chỉnh.

Mục tiêu:

Giảm token.

Tăng tốc.

Tăng tính nhất quán.

---

# XIV. KNOWLEDGE EXTRACTOR

Sau mỗi chapter.

AI phân tích:

- Thuật ngữ mới
    
- Nhân vật mới
    
- Quan hệ mới
    
- Rule ngữ pháp mới
    
- Phong cách mới
    

Sinh candidate.

---

# XV. KNOWLEDGE VALIDATOR

Candidate không được thêm ngay.

Pipeline:

Candidate

↓

Validator

↓

Score

↓

Approved

↓

Knowledge Base

---

# XVI. EVOLUTION ENGINE

Sau mỗi chapter.

So sánh:

Draft Translation

và

Final Translation

Nếu AI sửa liên tục:

Tạo rule mới.

Ví dụ:

Linh thạch

↓

Linh Thạch

500 lần

Tự thêm vào Style Graph.

---

# XVII. VERSIONING

Knowledge Base có version.

v1

v2

v3

v4

...

Có thể rollback.

---

# XVIII. CRON SYSTEM

Chỉ có một cron.

*/5 * * * * scheduler.py

---

# XIX. BRANCH SCHEDULER

Mỗi truyện có cron ảo.

Tiên Nghịch

5 phút

Già Thiên

30 phút

Phàm Nhân

60 phút

Scheduler tạo Job.

---

# XX. WORKER POOL

Worker 1

Worker 2

Worker 3

Worker 4

...

Mỗi worker xử lý một chapter.

---

# XXI. DASHBOARD

Modules:

Overview

Sources

Novels

Queue

Workers

Knowledge

Logs

Statistics

Settings

---

# XXII. KNOWLEDGE DASHBOARD

Hiển thị:

Characters

Glossary

Relationships

Grammar Rules

Translation Memory

Style Rules

---

# XXIII. TELEGRAM

/status

/queue

/retry

/pause

/resume

/workers

/stats

---

# XXIV. CHỈ SỐ QUAN TRỌNG

Graph Coverage

Translation Memory Hit Rate

AI Correction Rate

Consistency Score

New Terms

New Characters

---

# XXV. MỤC TIÊU SAU 3000 CHƯƠNG

Graph Coverage:  
90%+

Translation Memory:  
Hàng triệu segment

AI Correction Rate:  
< 10%

Consistency:

> 98%

Token Cost:  
Giảm 70-90%

Tốc độ:  
Nhanh hơn nhiều lần so với dịch AI thuần.

Nếu triển khai đến mức này, phần khó nhất không phải Dashboard hay Telegram mà là thiết kế **schema SQLite cho Dict Graph + Translation Memory + Relationship Graph + Versioning**, vì đó sẽ là "bộ não" quyết định chất lượng hệ thống sau hàng chục nghìn chương dịch.