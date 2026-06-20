import jieba
import jieba.posseg as pseg
from pathlib import Path

_JIEBA_INITIALIZED = False

# Các hậu tố không được phép nằm cuối tên riêng (trạng từ, bộ phận cơ thể, vũ khí...)
INVALID_ENTITY_SUFFIXES = {
    '刚', '就', '也', '会', '能', '想', '要', '在', '到', '了', '着', '过',
    '手', '头', '脚', '腿', '脸', '眼', '嘴', '心', '魂', '身',
    '剑', '刀', '枪', '棍', '印', '鼎', '钟', '塔', '镜'
}

def init_jieba():
    global _JIEBA_INITIALIZED
    if _JIEBA_INITIALIZED:
        return
        
    # Jieba Dictionary sẽ được inject (add_word) động từ DictManager
    # Hàm này chỉ đóng vai trò khởi tạo base
    jieba.initialize()
    _JIEBA_INITIALIZED = True
    print("[Jieba] Hệ thống NLP đã khởi tạo, các Entities được nạp tự động qua DictManager.")

def clean_entity(entity_str: str, flag: str) -> str:
    """
    Loại bỏ các hậu tố sai (trạng thái, bộ phận cơ thể) bị dính vào Entity.
    """
    if not entity_str or len(entity_str) <= 1:
        return entity_str
        
    # Chỉ xử lý tên người (nr)
    if flag == 'nr':
        while len(entity_str) > 1 and entity_str[-1] in INVALID_ENTITY_SUFFIXES:
            entity_str = entity_str[:-1]
            
    return entity_str

def get_char_pos_map(text: str) -> list:
    """
    Trả về danh sách POS tag cho từng ký tự trong text.
    """
    init_jieba()
    char_tags = []
    for w, flag in pseg.cut(text):
        char_tags.extend([flag] * len(w))
    return char_tags
