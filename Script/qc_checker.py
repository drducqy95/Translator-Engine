class QCChecker:
    def __init__(self, context_pack: dict, ai_output: dict):
        self.context_pack = context_pack
        self.ai_output = ai_output
        self.errors = []
        self.warnings = []

    def check(self):
        self._check_segments_count()
        self._check_locked_dictionary()
        
        return {
            "passed": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings
        }

    def _check_segments_count(self):
        raw_segs = self.context_pack.get("raw_segments", [])
        ai_segs = self.ai_output.get("refined_segments", [])
        
        if len(raw_segs) != len(ai_segs):
            self.errors.append(f"Số lượng đoạn không khớp: Gốc {len(raw_segs)} vs Dịch {len(ai_segs)}")

    def _check_locked_dictionary(self):
        locked_dict = self.context_pack.get("locked_dictionary", {})
        chars = locked_dict.get("characters", {})
        
        # Kiểm tra xem bản dịch có chứa tên đã khóa không
        translated_text = " ".join([seg.get("refined_translation", "") for seg in self.ai_output.get("refined_segments", []) if isinstance(seg, dict)])
        
        for key, target in chars.items():
            # Nếu bản gốc có chứa key, bản dịch BẮT BUỘC phải chứa target
            raw_text = " ".join([seg.get("text", "") for seg in self.context_pack.get("raw_segments", [])])
            if key in raw_text and target not in translated_text:
                self.warnings.append(f"Thiếu tên nhân vật đã khóa: '{target}' (Gốc: '{key}')")
