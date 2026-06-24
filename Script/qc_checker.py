class QCChecker:
    def __init__(self, context_pack: dict, ai_output: dict):
        self.context_pack = context_pack
        self.ai_output = ai_output
        self.errors = []
        self.warnings = []

    def check(self):
        self._check_segments_count()
        self._check_locked_dictionary()
        self._check_length()
        self._check_chinese_residue()
        
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
        raw_text = " ".join([seg.get("text", "") for seg in self.context_pack.get("raw_segments", []) if isinstance(seg, dict)])
        translated_text = " ".join([seg.get("refined_translation", "") for seg in self.ai_output.get("refined_segments", []) if isinstance(seg, dict)])

        for group_name in ("characters", "glossary"):
            entries = locked_dict.get(group_name, {})
            if not isinstance(entries, dict):
                self.errors.append(f"Locked Dictionary '{group_name}' sai kiểu")
                continue
            for key, target in entries.items():
                if not key or key not in raw_text:
                    continue
                target_text = str(target).split(" (", 1)[0].strip()
                if target_text and target_text not in translated_text:
                    self.warnings.append(f"Thiếu term đã khóa: '{target_text}' (Gốc: '{key}', nhóm: {group_name})")

    def _check_length(self):
        ai_segs = self.ai_output.get("refined_segments", [])
        translated_text = " ".join([seg.get("refined_translation", "") for seg in ai_segs if isinstance(seg, dict)])
        if not translated_text.strip():
            self.errors.append("Bản dịch hoàn toàn trống.")
            return
        if len(translated_text) < 10 and len(self.context_pack.get("raw_segments", [])) > 0:
            self.errors.append("Bản dịch quá ngắn (dưới 10 ký tự).")

    def _check_chinese_residue(self):
        import re
        ai_segs = self.ai_output.get("refined_segments", [])
        translated_text = " ".join([seg.get("refined_translation", "") for seg in ai_segs if isinstance(seg, dict)])
        
        cn_chars = re.findall(r'[\u4e00-\u9fff]', translated_text)
        cn_count = len(cn_chars)
        total_len = len(translated_text.strip())
        if total_len == 0:
            return
            
        ratio = cn_count / total_len
        if cn_count > 0:
            self.errors.append(f"Còn sót Hán tự ({cn_count} ký tự, tỷ lệ {ratio*100:.1f}%).")
