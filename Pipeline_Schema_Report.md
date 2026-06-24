# Báo cáo Toàn diện Pipeline Dịch Thuật

## 1. Tổng quan Pipeline
Pipeline dịch thuật của hệ thống hoạt động theo quy trình 5 bước nghiêm ngặt (Stage 1→5) với cơ chế resume và fallback thông minh. Các Artifact trung gian được lưu tại `Intermediate/<chapter-key>/pre-trans/`.

## 2. Schema chi tiết từng Stage

### Stage 1: Entity Review (Offline)
- **Input**: Chương thô (`.md`)
- **Action**: Dùng Jieba + QTEngine quét thực thể & xưng hô.
- **Output Schema (`stage1_entity_review.json`)**:
```json
{
  "characters": {"Tên gốc": "Tên dịch"},
  "glossary": {"Tên gốc": "Tên dịch"},
  "pronouns": {"我": "ta", "他": "hắn"}
}
```

### Stage 2: Context Pack
- **Input**: Nội dung thô, Stage 1 Data, Locked Dict (Project DB), Translation Memory.
- **Action**: Đóng gói config, lookup TM, chia đoạn, gán bản dịch thô (QT Engine).
- **Lưu ý**: `locked_dictionary` chỉ giữ entity xuất hiện trong chương hiện tại; `raw_segments` luôn gồm `text` + `qt`.
- **Output Schema (`stage2_context_pack.json`)**:
```json
{
  "translation_config": {...},
  "current_chapter": {"file": "...", "index": 1},
  "story_timeline": [...],
  "locked_dictionary": {"characters": {}, "glossary": {}},
  "suggested_dictionary": {"characters": {}, "glossary": {}},
  "relationships_graph": [],
  "pronouns_addressing": {},
  "translation_memory_hits": [],
  "raw_segments": [
    {"id": 1, "text": "原始文本", "qt": "Bản dịch thô bởi QT Engine"}
  ]
}
```

### Stage 3: AI Refiner
- **Input**: Context Pack JSON từ Stage 2.
- **Action**: AI hiệu chỉnh QT theo RAW, giữ JSON input/output, trích entity mới, grammar notes, story timeline.
- **Output Schema (`stage3_ai_refiner.json`)**:
```json
{
  "refined_segments": [
    {"id": 1, "refined_translation": "# Chương 0001 Tiêu đề chương"}
  ],
  "story_timeline": {"summary": {"main_events": "...", "new_characters": []}},
  "new_entities": [{"raw": "...", "target": "...", "type": "...", "origin": "chinese", "name_type": "person"}],
  "relationships": [{"source": "...", "target": "...", "relationship": "..."}],
  "grammar_notes": []
}
```

### Stage 4: Post Process
- **Input**: AI Output, Context Pack.
- **Action**: Format tiêu đề `# Chương XXXX <Title>`, ép kiểu file `.md`, chặn CJK, cập nhật TOC/Timeline/Readme.
- **Output**: File final tại `Output/<novel_id>/Final_Translated/Chương XXXX <Title>.md`.

### Stage 5: Git Push
- **Action**: Checkpoint thay đổi vào Git.

## 3. Fallback & QC
- **Fallback**: Nếu AI fail, Stage 3 gọi `stage3_offline_hymt.py` parse JSON fallback.
- **QC**: `qc_checker.py` chặn mọi file chứa CJK (`[\u4e00-\u9fff]`).

## 4. Trạng thái thực tế

- Stage 3 vẫn là JSON input/output đúng thiết kế.
- Hy-MT đang tạm tắt theo yêu cầu.
- Crawl init hiện đã có bước sinh cover sau khi ghi `prompt_cover.txt`.
- Final filename đã ép về `Chương 0001 <tiêu đề tiếng việt>.md`.
