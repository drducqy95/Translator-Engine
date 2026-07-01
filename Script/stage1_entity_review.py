import os
import re
import sys
import json
from pathlib import Path

# Add Script dir to path to import local modules
sys.path.append(str(Path(__file__).parent))
try:
    from qt_engine import QTEngine
    from jieba_env import clean_entity, init_jieba
    import jieba.posseg as pseg
    HAS_NLP = True
except ImportError as e:
    HAS_NLP = False
    print(f"[Stage 1] Lỗi Import NLP: {e}")

try:
    import opencc
except ImportError:
    opencc = None

try:
    from foreign_converter import analyze_and_convert_entity
except Exception:
    analyze_and_convert_entity = None

HV_OVERRIDES = {
    "释": "Thích",
}

def _hv_reading(qt, char: str):
    if char in HV_OVERRIDES:
        return HV_OVERRIDES[char]
    hv = qt.dict_mgr.get_hv(char)
    return hv.split(',')[0].strip() if hv else char

def convert_traditional_to_simplified(text: str) -> str:
    """Chuyển đổi Phồn thể sang Giản thể sử dụng OpenCC."""
    if opencc:
        try:
            converter = opencc.OpenCC('t2s')
            return converter.convert(text)
        except Exception as e:
            print(f"[Stage 1] Lỗi OpenCC: {e}")
            return text
    return text

def extract_entities_and_pronouns_offline(novel_id: str, content: str) -> dict:
    characters = {}
    glossary = {}
    
    if not HAS_NLP:
        print("[Stage 1] Không có Jieba/QTEngine, bỏ qua quét Entity Offline.")
        return {"characters": {}, "glossary": {}, "pronouns": {}}
        
    # Khởi tạo QT Engine để tận dụng bộ từ điển Hán Việt cực chuẩn
    qt = QTEngine()
    qt.dict_mgr.load_project(novel_id)
    qt.set_context(content)
    init_jieba()
    
    print("[Stage 1] Đang quét Entity bằng Jieba & QTEngine (Offline 100%)...")
    for w, flag in pseg.cut(content):
        # nr: Tên người | ns: Địa danh | nt: Tổ chức | nz: Danh từ riêng khác
        if flag in ('nr', 'ns', 'nt', 'nz'):
            cleaned_w = clean_entity(w, flag)
            if len(cleaned_w) > 1:
                # 1. Thử lookup xem trong từ điển có bản dịch chuẩn chưa
                res = qt._lookup(cleaned_w)
                tgt = None
                if res and res[0]:
                    tgt = res[0]
                else:
                    # 2. Ưu tiên bối cảnh Latin/Western nếu nhận diện được
                    foreign = analyze_and_convert_entity(cleaned_w) if analyze_and_convert_entity else None
                    if foreign and foreign.get("converted"):
                        tgt = foreign["converted"]
                    else:
                        # 3. Nếu chưa có, dịch Hán Việt từng chữ ghép lại
                        tgt_chars = []
                        for char in cleaned_w:
                            tgt_chars.append(_hv_reading(qt, char))
                        tgt = ' '.join(tgt_chars).title()
                
                # Phân loại
                if flag == 'nr':
                    characters[cleaned_w] = tgt
                else:
                    glossary[cleaned_w] = tgt

    # Đóng DB để tránh locked
    qt.close()

    print("[Stage 1] Đang quét Xưng hô (Pronouns)...")
    # Đếm số lượng đại từ để đoán ngôi kể
    count_1st = len(re.findall(r'[我吾俺老夫本座]', content))
    count_3rd = len(re.findall(r'[他她它]', content))
    pov = "Ngôi 3 (hắn, y, nàng)" if count_3rd > count_1st else "Ngôi 1 (ta, tôi)"
    
    addressing = []
    # Quét trong ngoặc kép để tìm các từ xưng hô cổ trang / dị giới đặc biệt
    quotes = re.findall(r'“(.*?)”', content)
    special_self = ['老夫', '本座', '朕', '贫道', '妾身', '晚辈', '本尊', '在下', '老朽']
    found_self = set()
    for q in quotes:
        for s in special_self:
            if s in q:
                found_self.add(s)
                
    if found_self:
        # Nếu có xưng hô đặc biệt, ghim lại vào context pack
        addressing.append({
            "speaker": "Unknown",
            "target": "Unknown",
            "self": list(found_self)[0],
            "target_pronoun": "ngươi"
        })

    pronouns = {
        "narration_pov": pov,
        "dialogue_addressing": addressing
    }

    return {
        "characters": characters,
        "glossary": glossary,
        "pronouns": pronouns
    }

def run(novel_id: str, chapter_content: str, output_dir: str):
    print(f"\n[Stage 1] Bắt đầu Entity Review (OFFLINE MODE) cho truyện {novel_id}")
    
    # 1. Tiền xử lý: Chuyển Phồn thể sang Giản thể (t2s)
    print("[Stage 1] Chuyển đổi Phồn thể -> Giản thể (OpenCC)...")
    simplified_content = convert_traditional_to_simplified(chapter_content)
    
    # 2. Xử lý Trích xuất bằng Python NLP (Tốc độ ánh sáng, Không cần Internet)
    data = extract_entities_and_pronouns_offline(novel_id, simplified_content)
    
    # Validation
    if not isinstance(data.get("characters"), dict): data["characters"] = {}
    if not isinstance(data.get("glossary"), dict): data["glossary"] = {}
    if not isinstance(data.get("pronouns"), dict): data["pronouns"] = {}
    
    print(f"[Stage 1] Hoàn tất. Quét được {len(data['characters'])} nhân vật và {len(data['glossary'])} thuật ngữ.")
    return data
