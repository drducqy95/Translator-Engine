#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translator Engine - Chapter Parser
Chia tệp raw thành các chương markdown và cắt đoạn (segment) chuẩn bị cho pipeline dịch.
"""

import re
from pathlib import Path

# RegExp nhận diện chương
RE_CHAPTER = re.compile(r'^第\s*[0-9０-９零〇○一二三四五六七八九十百千万兩两]+\s*[章节回](?:[\s:：、.．\-—–]+|(?=[一-鿿])|$)(.*)$')

def detect_chapter_heading(line: str):
    s = line.strip().lstrip('\ufeff').replace('　', ' ')
    if not s or s.endswith('：'): return None
    
    m = RE_CHAPTER.match(s)
    if m:
        return s
        
    m2 = re.match(r'^(?:Chương|Chapter)\s*([0-9]+)\s*[:：\-—–]?\s*(.*)$', s, re.IGNORECASE)
    if m2:
        return s
        
    return None

class ChapterParser:
    def __init__(self, raw_text: str):
        self.raw_text = raw_text

    def split_to_chapters(self):
        """
        Tách một văn bản dài thành danh sách các chương.
        Trả về list các tuple: (heading, body_text)
        """
        lines = self.raw_text.splitlines()
        chapters = []
        current_heading = "Mở Đầu"
        current_body = []
        
        for line in lines:
            heading = detect_chapter_heading(line)
            if heading:
                if current_body:
                    chapters.append((current_heading, '\n'.join(current_body).strip()))
                current_heading = heading
                current_body = []
            else:
                if line.strip():
                    current_body.append(line)
                    
        if current_body:
            chapters.append((current_heading, '\n'.join(current_body).strip()))
            
        return chapters

    @staticmethod
    def segment_chapter(body_text: str):
        """
        Chia phần nội dung chương (body) thành các segment nhỏ (câu/đoạn).
        Rất quan trọng cho việc matching Translation Memory và Translation API.
        """
        # Chia theo đoạn văn (paragraph) trước
        paragraphs = [p.strip() for p in re.split(r'\n+', body_text) if p.strip()]
        segments = []
        
        for p in paragraphs:
            if len(p) <= 500:
                segments.append(p)
                continue
                
            # Nếu đoạn văn quá dài (trên 500 ký tự), chia nhỏ theo dấu câu và giữ nguyên ngoặc kép
            sentences = re.split(r'([。！？!\?]+[”’"\'\]\)]*)', p)
            current_sentence = ""
            for i in range(0, len(sentences)-1, 2):
                current_sentence += sentences[i] + sentences[i+1]
                if len(current_sentence) > 200:
                    segments.append(current_sentence.strip())
                    current_sentence = ""
                    
            if current_sentence:
                segments.append(current_sentence.strip())
                
            if len(sentences) % 2 != 0 and sentences[-1].strip():
                segments.append(sentences[-1].strip())
                
        return [s for s in segments if s]

if __name__ == '__main__':
    sample = "第1章 穿越\n\n方元醒来发现自己穿越了。这地方灵气浓郁。\n\n第2章 修仙\n\n方元开始修炼。"
    parser = ChapterParser(sample)
    chaps = parser.split_to_chapters()
    for h, b in chaps:
        print(f"Heading: {h}")
        print(f"Segments: {ChapterParser.segment_chapter(b)}\n")
