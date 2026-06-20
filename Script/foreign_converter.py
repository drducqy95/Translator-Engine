import pykakasi
import hanja
import re
import zhconv

# Khởi tạo pykakasi cho tiếng Nhật (Kanji -> Romaji) - API mới
kakasi = pykakasi.kakasi()

# Tập ký tự thường dùng phiên âm tiếng Anh/phương Tây
WESTERN_CHARS = set(
    "斯特克尔亚罗玛哈里德兰琼华夫曼顿巴杰威丹尼托索鲁普诺"
    "奥巴马格莱西贝卡麦林纳雷恩泰菲波比科莉伊艾沙"
    "历山大吉姆乔治"
)

# Họ phổ biến Hàn Quốc -> English
KOREAN_SURNAMES = {
    '金': 'Kim', '李': 'Lee', '朴': 'Park', '崔': 'Choi', '郑': 'Jung',
    '姜': 'Kang', '赵': 'Cho', '尹': 'Yoon', '张': 'Jang', '林': 'Lim',
    '韩': 'Han', '申': 'Shin', '吴': 'Oh', '徐': 'Seo', '权': 'Kwon'
}

# Họ/Tên phổ biến Nhật Bản (2-3 chữ) để nhận diện
JAPANESE_SURNAMES = [
    '佐藤', '铃木', '高桥', '田中', '渡边', '伊藤', '山本', '中村', '小林', '加藤',
    '吉田', '山田', '佐佐木', '山口', '松本', '井上', '木村', '林', '清水', '山崎',
    '宇智波', '千手', '日向', '漩涡', '大筒木', '春野', '旗木', '波风'
]

def analyze_and_convert_entity(entity: str) -> dict:
    """
    Phân tích một Entity (Danh từ riêng) xem nó thuộc bối cảnh nước nào
    (Anh, Nhật, Hàn) và thử chuyển đổi sang Romaji/Tiếng Anh.
    Trả về dict: {"type": type, "converted": str} hoặc None nếu không xác định được.
    """
    if not entity or len(entity) < 2:
        return None
        
    # 1. Phân tích bối cảnh Hàn Quốc (Korean)
    if len(entity) in (2, 3, 4):
        first_char = entity[0]
        if first_char in KOREAN_SURNAMES:
            hangul = hanja.translate(entity, 'substitution')
            if hangul != entity:
                surname_en = KOREAN_SURNAMES[first_char]
                return {
                    "type": "Korean",
                    "converted": f"{surname_en} ({hangul})"
                }
                
    # 2. Phân tích bối cảnh Nhật Bản (Japanese)
    is_japanese = False
    for sur in JAPANESE_SURNAMES:
        if entity.startswith(sur):
            is_japanese = True
            break
            
    jap_kanji = set("郎樱奈崎藤井丸宫泽田村桥助")
    if not is_japanese and any(c in jap_kanji for c in entity):
        is_japanese = True
        
    # Xử lý các họ đặc biệt (Anime) mà pykakasi thường đọc sai (Ateji)
    JAPANESE_SPECIAL_NAMES = {
        '宇智波': 'Uchiha',
        '漩涡': 'Uzumaki',
        '日向': 'Hyuga',
        '大筒木': 'Otsutsuki',
        '千手': 'Senju',
        '波风': 'Namikaze',
        '春野': 'Haruno',
        '旗木': 'Hatake'
    }
        
    if is_japanese:
        romaji_parts = []
        remaining_entity = entity
        
        # Thay thế họ đặc biệt nếu có
        for kanji, romaji_val in JAPANESE_SPECIAL_NAMES.items():
            if remaining_entity.startswith(kanji):
                romaji_parts.append(romaji_val)
                remaining_entity = remaining_entity[len(kanji):]
                break
                
        # Các chữ còn lại dùng pykakasi chuyển đổi
        if remaining_entity:
            traditional_entity = zhconv.convert(remaining_entity, 'zh-hant')
            result = kakasi.convert(traditional_entity)
            part2 = "".join([item['hepburn'] for item in result]).title()
            romaji_parts.append(part2)
            
        final_romaji = "".join(romaji_parts)
        
        return {
            "type": "Japanese",
            "converted": final_romaji
        }
        
    # 3. Phân tích bối cảnh phương Tây (Western/English)
    if len(entity) >= 2:
        match_count = sum(1 for c in entity if c in WESTERN_CHARS)
        ratio = match_count / len(entity)
        
        # Ngưỡng tỷ lệ động dựa trên độ dài để tránh False Positive (như 华国, 喜大普奔)
        threshold = 1.0 if len(entity) <= 2 else (0.66 if len(entity) == 3 else 0.5)
        
        if ratio >= threshold: 
            return {
                "type": "Western",
                "converted": "[Western Phonetic]"
            }
            
    return None

if __name__ == '__main__':
    tests = [
        "宇智波佐助", # Uchiha Sasuke
        "漩涡鸣人", # Uzumaki Naruto
        "金秀贤", # Kim Soo Hyun
        "哈利波特", # Harry Potter
        "亚历山大", # Alexander
        "方元", # Fang Yuan (Chinese)
        "佐藤健", # Sato Takeru
        "朴智星" # Park Ji Sung
    ]
    
    for t in tests:
        print(f"{t}: {analyze_and_convert_entity(t)}")
