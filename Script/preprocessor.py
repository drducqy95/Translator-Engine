import zhconv
import re

# Từ điển ánh xạ Pinyin phổ biến sang Hán tự giản thể
# Dùng để xử lý các từ viết tắt/pinyin lách luật kiểm duyệt của tác giả mạng.
PINYIN_MAP = {
    r'\bshabi\b': '傻逼',
    r'\bsb\b': '傻逼',
    r'\bcao\b': '草',
    r'\bwo cao\b': '卧槽',
    r'\bwocao\b': '卧槽',
    r'\bmmp\b': '妈卖批',
    r'\btmd\b': '他妈的',
    r'\bnmb\b': '你妈逼',
    r'\bnt\b': '脑瘫',
    r'\bcnm\b': '草泥马',
}

def preprocess_text(text: str) -> str:
    """
    Tiền xử lý text thô trước khi đưa vào dịch:
    1. Chuyển đổi Phồn thể -> Giản thể.
    2. Thay thế các pinyin/abbreviations kiểm duyệt thành Hán tự gốc.
    """
    if not text:
        return text
        
    # 1. Convert Traditional to Simplified
    text = zhconv.convert(text, 'zh-hans')
    
    # 2. Replace Pinyin/Acronyms with Hanzi
    for pattern, hanzi in PINYIN_MAP.items():
        text = re.sub(pattern, hanzi, text, flags=re.IGNORECASE)
        
    return text
