import sqlite3
import os
import threading
from pathlib import Path

_GLOBAL_DICT_CACHE = None
_UNIVERSE_DICT_CACHE = {}
_PREFIX_CACHE = None
_T2S_CACHE = None
_HANVIET_CACHE = None
_MAX_LEN_CACHE = 0
_CACHE_LOCK = threading.Lock()

class DictManager:
    def __init__(self, dict_dir="/sdcard/My Agent/Translator Engine/Dict"):
        self.dict_dir = Path(dict_dir)
        
        # 4 Tầng từ điển
        self.global_dict = {}
        self.style_dict = {}
        self.universe_dicts = {} # dict of dicts: {'naruto': {}, 'marvel': {}}
        self.project_dict = {}
        
        self.prefix = {} # Map ký tự đầu -> chiều dài tối đa
        self.t2s = {}    # Bộ chuyển đổi Phồn -> Giản
        self.hanviet_dict = {} # Lưu Hán Việt đơn âm
        
        self.max_len = 0
        
        # Mapping Context Markers -> Universe ID
        self.context_markers = {
            "木叶": "naruto", "火影": "naruto", "宇智波": "naruto", "查克拉": "naruto",
            "斯塔克": "marvel", "神盾局": "marvel", "复仇者": "marvel",
            "霍格沃茨": "harry_potter", "伏地魔": "harry_potter",
            "恶魔果实": "one_piece", "海贼王": "one_piece"
        }
        
    def load_global(self, db_name="translator_knowledge.db"):
        """Tải từ điển Global (mặc định)"""
        global _GLOBAL_DICT_CACHE, _UNIVERSE_DICT_CACHE, _PREFIX_CACHE, _T2S_CACHE, _HANVIET_CACHE, _MAX_LEN_CACHE, _CACHE_LOCK
        
        with _CACHE_LOCK:
            if _GLOBAL_DICT_CACHE is not None:
                self.global_dict = _GLOBAL_DICT_CACHE
                self.universe_dicts = _UNIVERSE_DICT_CACHE
                self.prefix = _PREFIX_CACHE
                self.t2s = _T2S_CACHE
                self.hanviet_dict = _HANVIET_CACHE
                self.max_len = _MAX_LEN_CACHE
                return

            db_path = self.dict_dir / db_name
            if not db_path.exists():
                print(f"[DictManager] Không tìm thấy Global DB: {db_path}")
                return
                
            print("[DictManager] Đang tải Global DB...")
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        
            # Tải Hán Việt Fallback
            for r in conn.execute("SELECT han, viet FROM kb_hanviet_char"):
                self.hanviet_dict[r['han']] = r['viet']
            for r in conn.execute("SELECT simp, hanviet FROM kb_han_char WHERE hanviet IS NOT NULL AND hanviet != ''"):
                self.hanviet_dict[r['simp']] = r['hanviet']
            
            # Tải Prefix
            for r in conn.execute('SELECT head, max_len FROM kb_term_prefix'):
                self.prefix[r['head']] = r['max_len']
            
            # Tải Charmap (Phồn -> Giản)
            for r in conn.execute('SELECT trad, simp FROM kb_charmap'):
                self.t2s[r['trad']] = r['simp']
            
            # Tải Từ vựng (Bóc tách Tiers)
            query = """
            SELECT n.key, t.vietnamese, n.type, t.pos, t.priority, t.source_dict, n.tier, n.scope
            FROM kb_node n
            JOIN kb_node_translation t ON n.id = t.node_id
            WHERE t.is_active = 1 AND t.source_dict NOT IN ('cedict', 'babylon')
            ORDER BY n.tier DESC, t.priority ASC
        """
            for r in conn.execute(query):
                key = r['key']
                tier = r['tier']
                scope = r['scope']
                tgt = r['vietnamese']
                if tgt:
                    if '=' in tgt: tgt = tgt.split('=')[0]
                    if '/' in tgt: tgt = tgt.split('/')[0]
                    tgt = tgt.strip()
                data = (tgt, r['type'], r['pos'], tier, r['priority'], r['source_dict'])
                length = len(key)
                if length > self.max_len:
                    self.max_len = length
                    
                if tier == 2:
                    if key not in self.project_dict:
                        self.project_dict[key] = data
                        self._inject_to_jieba(key, r['type'])
                elif tier == 1:
                    if scope not in self.universe_dicts:
                        self.universe_dicts[scope] = {}
                    if key not in self.universe_dicts[scope]:
                        self.universe_dicts[scope][key] = data
                        self._inject_to_jieba(key, r['type'])
                else:
                    if key not in self.global_dict:
                        self.global_dict[key] = data
                        if tier == 0: # Chỉ đưa Global core vào Jieba để tránh phình to
                            self._inject_to_jieba(key, r['type'])
            
            _GLOBAL_DICT_CACHE = self.global_dict
            _UNIVERSE_DICT_CACHE = self.universe_dicts
            _PREFIX_CACHE = self.prefix
            _T2S_CACHE = self.t2s
            _HANVIET_CACHE = self.hanviet_dict
            _MAX_LEN_CACHE = self.max_len
            
            conn.close()
        print(f"[DictManager] DB tải xong: {len(self.global_dict)} Global, {len(self.universe_dicts)} Universes, {len(self.project_dict)} Project.")

    def load_style(self, style_name):
        """Tải từ điển Văn Phong (Cổ trang, Hiện đại, Kinh dị...)"""
        db_path = self.dict_dir / f"style_{style_name}.db"
        self._load_simple_db(db_path, self.style_dict, tier=1)
        print(f"[DictManager] Đã tải Style DB ({style_name}): {len(self.style_dict)} từ.")

    def load_universe(self, universe_id):
        """Tải từ điển Vũ Trụ (Đa thế giới, Xuyên không)"""
        if universe_id in self.universe_dicts:
            return # Đã tải
            
        db_path = self.dict_dir / f"universe_{universe_id}.db"
        target_dict = {}
        self._load_simple_db(db_path, target_dict, tier=1)
        self.universe_dicts[universe_id] = target_dict
        print(f"[DictManager] Đã tải Universe DB ({universe_id}): {len(target_dict)} từ.")

    def load_project(self, project_id):
        """Tải từ điển Project (Truyện đang dịch) - Ưu tiên cao nhất"""
        db_path = self.dict_dir / f"project_{project_id}.db"
        keys_to_remove = [k for k, v in self.project_dict.items() if v[5] == 'custom']
        for k in keys_to_remove:
            del self.project_dict[k]
        self._load_simple_db(db_path, self.project_dict, tier=2)
        print(f"[DictManager] Đã tải Project DB ({project_id}): {len(self.project_dict)} từ.")

    def _create_empty_db(self, db_path):
        """Tự động sinh Database rỗng nếu chưa tồn tại"""
        print(f"[DictManager] Đang khởi tạo Database mới: {db_path.name}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE dict_entries (
                key TEXT PRIMARY KEY,
                target TEXT,
                pos TEXT,
                type TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def _load_simple_db(self, db_path, target_dict, tier=1):
        """Tải DB dạng schema đơn giản (key, target, pos, type)"""
        if not db_path.exists():
            self._create_empty_db(db_path)
            return
            
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for r in conn.execute("SELECT key, target, pos, type FROM dict_entries"):
                key = r['key']
                length = len(key)
                if length > self.max_len:
                    self.max_len = length
                target = r['target']
                if '=' in target:
                    target = target.split('=')[0]
                if '/' in target:
                    target = target.split('/')[0]
                target = target.strip()
                # Tuple: (target, type, pos, tier, priority, source_dict)
                target_dict[key] = (target, r['type'], r['pos'], tier, 1, 'custom')
                self._inject_to_jieba(key, r['type'])
        except sqlite3.OperationalError:
            pass # Table không tồn tại
        conn.close()

    def _inject_to_jieba(self, key, type_val):
        """Tự động nạp danh từ riêng (Entity) vào bộ token của Jieba"""
        import jieba
        if type_val in ('character', 'name', 'entity'):
            jieba.add_word(key, freq=10000, tag='nr')
        elif type_val == 'sect':
            jieba.add_word(key, freq=10000, tag='nt')
        elif type_val == 'location':
            jieba.add_word(key, freq=10000, tag='ns')

    def scan_active_universes(self, text: str) -> list:
        """Quét Context Markers trong văn bản để tự động kích hoạt Universe"""
        active = set()
        for marker, universe_id in self.context_markers.items():
            if marker in text:
                active.add(universe_id)
                self.load_universe(universe_id) # Tự động tải nếu chưa có
        return list(active)

    def lookup(self, key: str, active_universes: list = None):
        """
        Tra cứu theo thứ tự ưu tiên:
        Project > Universe (Active) > Style > Global
        """
        with _CACHE_LOCK:
            if key in self.project_dict:
                return self.project_dict[key]
                
            if active_universes:
                for u in active_universes:
                    if u in self.universe_dicts and key in self.universe_dicts[u]:
                        return self.universe_dicts[u][key]
                        
            if key in self.style_dict:
                return self.style_dict[key]
                
            if key in self.global_dict:
                return self.global_dict[key]
                
            return None
        
    def get_hv(self, char: str):
        with _CACHE_LOCK:
            return self.hanviet_dict.get(char)
