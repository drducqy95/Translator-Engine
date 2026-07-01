import os
import json
import shutil
import subprocess
from pathlib import Path
import re

def _atomic_write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

def _is_bad_prompt_value(value: str) -> bool:
    text = str(value or "").strip()
    return not text or text.lower() in {"unknown", "đang cập nhật", "dang cap nhat", "n/a", "na"} or "object object" in text.lower() or "{" in text or "}" in text

def _clean_prompt_text(value: str) -> str:
    text = str(value or "").replace("\uFFFD", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text

def _normalize_cover_metadata(novel_id: str, metadata: dict | None, ai_response: dict | None = None):
    metadata = dict(metadata or {})
    ai_response = ai_response or {}
    canonical_title = novel_id.split("_", 1)[0].strip() or novel_id
    canonical_author = novel_id.split("_", 1)[1].strip() if "_" in novel_id else "Unknown"
    title_vi = canonical_title
    author = canonical_author if not _is_bad_prompt_value(canonical_author) else "Unknown"
    if _is_bad_prompt_value(title_vi):
        title_vi = canonical_title
    if _is_bad_prompt_value(author):
        author = "Unknown"
    # Only accept AI title/author if they are clean and clearly non-placeholder; otherwise keep canonical project title.
    ai_title = _clean_prompt_text(ai_response.get("title_vi") or metadata.get("title_vi") or "")
    ai_author = _clean_prompt_text(ai_response.get("author") or metadata.get("author") or "")
    if ai_title and not _is_bad_prompt_value(ai_title) and len(ai_title) <= max(50, len(canonical_title) * 2) and ai_title != title_vi:
        # still prefer canonical title for cover consistency; keep AI title only in synopsis/extra metadata elsewhere
        pass
    if ai_author and not _is_bad_prompt_value(ai_author) and len(ai_author) <= 80 and ai_author != author:
        # keep canonical author for cover consistency
        pass
    genres = metadata.get("genres") or ai_response.get("genres") or []
    if isinstance(genres, dict):
        genres = list(genres.values())
    if not isinstance(genres, list):
        genres = [genres] if genres else []
    genres = [_clean_prompt_text(g) for g in genres if _clean_prompt_text(g) and not _is_bad_prompt_value(g)]
    synopsis = _clean_prompt_text(ai_response.get("synopsis") or metadata.get("synopsis") or "")
    cover_prompt = _clean_prompt_text(ai_response.get("cover_prompt") or metadata.get("cover_prompt") or "")
    return {
        "title_vi": title_vi,
        "author": author,
        "genres": genres,
        "synopsis": synopsis,
        "cover_prompt": cover_prompt,
    }

def _build_cover_prompt(novel_id: str, title_vi: str, author: str, genres: list[str], synopsis: str, cover_prompt: str = "") -> str:
    title_vi = _clean_prompt_text(title_vi)
    author = _clean_prompt_text(author)
    if _is_bad_prompt_value(title_vi):
        title_vi = novel_id.split("_", 1)[0].strip() or novel_id
    if _is_bad_prompt_value(author):
        author = novel_id.split("_", 1)[1].strip() if "_" in novel_id else "Unknown"
        if _is_bad_prompt_value(author):
            author = "Unknown"
    genres = [_clean_prompt_text(g) for g in (genres or []) if _clean_prompt_text(g) and not _is_bad_prompt_value(g)]
    synopsis = _clean_prompt_text(synopsis)
    extra = _clean_prompt_text(cover_prompt)
    if not extra:
        extra = f"Visual mood derived from genres: {', '.join(genres) if genres else 'literary fiction'}"
    return (
        f"Vertical book cover ratio 6:9. Cinematic composition, hyper-detailed, 8k resolution. "
        f"[TITLE]: '{title_vi}' centered, large, legible, premium Vietnamese web novel typography. "
        f"[AUTHOR]: '{author}' smaller near the title. "
        f"[FOCUS]: A single protagonist, emblem, or symbolic object that strongly represents the story; avoid generic placeholders. "
        f"[WORLD]: {synopsis[:500] if synopsis else 'Use the story premise to define world, era, and key visual motifs.'} "
        f"[GENRE]: {', '.join(genres) if genres else 'novelistic drama, adventure'}; reflect the genre with scene, costume, lighting, and props. "
        f"[STYLE]: high contrast, clear composition, polished, premium cover art. "
        f"[TEXT RULES]: Only the exact title and author may be readable; no random text, no subtitles, no watermarks. "
        f"[EXTRA]: {extra}"
    )


class PipelineManager:
    FULL_INIT_SCAN_CHAPTERS = 50
    CRAWL_INIT_SCAN_CHAPTERS = 5

    def __init__(self, novel_id: str, raw_dir: str, output_dir: str, source_type: str = "full"):
        self.novel_id = novel_id
        self.raw_dir = Path(raw_dir)
        self.out_dir = Path(output_dir)
        self.source_type = source_type

        self.state_dir = self.out_dir / "State"
        self.intermediate_dir = self.out_dir / "Intermediate"
        self.final_dir = self.out_dir / "Final_Translated"

        for d in [self.out_dir, self.state_dir, self.intermediate_dir, self.final_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.toc_file = self.state_dir / "toc.json"

        self._qt = None

        self.readme_file = self.out_dir / "README.md"
        self.timeline_file = self.state_dir / "story_timeline.json"
        self.config_file = self.state_dir / "translation_config.json"


    def _stage_fail(self, stage: str, message: str):
        raise ValueError(f"[{stage} FAILED] {message}")

    def _get_qt(self):
        if self._qt is None:
            import qt_engine
            self._qt = qt_engine.QTEngine()
            self._qt.dict_mgr.load_project(self.novel_id)
        return self._qt

    def _load_json_required(self, path: Path, stage: str):
        if not path.exists():
            self._stage_fail(stage, f"Không tìm thấy artifact resume: {path}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            self._stage_fail(stage, f"Artifact JSON lỗi: {path} ({exc})")

    def _validate_stage1(self, data, raw_content: str):
        if not raw_content or not raw_content.strip():
            self._stage_fail("Stage 1", "Nội dung chương rỗng")
        if not isinstance(data, dict):
            self._stage_fail("Stage 1", "Output phải là JSON object")
        for key in ("characters", "glossary", "pronouns"):
            if not isinstance(data.get(key), dict):
                self._stage_fail("Stage 1", f"Thiếu hoặc sai kiểu '{key}'")
        print("✅ [Stage 1 PASS] Entity review output hợp lệ.")

    def _validate_stage2(self, context_pack):
        if not isinstance(context_pack, dict):
            self._stage_fail("Stage 2", "Context Pack phải là JSON object")
        required = [
            "translation_config",
            "story_timeline",
            "source_manifest",
            "locked_dictionary",
            "suggested_dictionary",
            "relationships_graph",
            "pronouns_addressing",
            "translation_memory_hits",
            "raw_segments",
        ]
        missing = [key for key in required if key not in context_pack]
        if missing:
            self._stage_fail("Stage 2", f"Context Pack thiếu trường: {missing}")
        if not isinstance(context_pack.get("translation_config"), dict) or not context_pack["translation_config"]:
            self._stage_fail("Stage 2", "translation_config rỗng hoặc sai kiểu")
        manifest = context_pack.get("source_manifest")
        if not isinstance(manifest, dict):
            self._stage_fail("Stage 2", "source_manifest phải là object")
        raw_segments = context_pack.get("raw_segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            self._stage_fail("Stage 2", "raw_segments rỗng hoặc sai kiểu")
        seen_ids = set()
        for idx, seg in enumerate(raw_segments, 1):
            if not isinstance(seg, dict):
                self._stage_fail("Stage 2", f"segment #{idx} không phải object")
            sid = seg.get("id")
            if not isinstance(sid, int) or sid in seen_ids:
                self._stage_fail("Stage 2", f"segment id sai hoặc trùng: {sid}")
            if not isinstance(seg.get("text"), str) or not seg["text"].strip():
                self._stage_fail("Stage 2", f"segment id {sid} thiếu text")
            if not isinstance(seg.get("qt"), str):
                self._stage_fail("Stage 2", f"segment id {sid} thiếu qt")
            seen_ids.add(sid)
        if manifest.get("segment_count") != len(raw_segments):
            self._stage_fail("Stage 2", "source_manifest.segment_count lệch raw_segments")
        manifest_segments = manifest.get("segments")
        if not isinstance(manifest_segments, list):
            self._stage_fail("Stage 2", "source_manifest.segments phải là list")
        if len(manifest_segments) != len(raw_segments):
            self._stage_fail("Stage 2", "source_manifest.segments lệch raw_segments")
        try:
            import hashlib
            for raw_seg, manifest_seg in zip(raw_segments, manifest_segments):
                if manifest_seg.get("id") != raw_seg.get("id"):
                    self._stage_fail("Stage 2", f"manifest id lệch raw segment: {manifest_seg.get('id')} vs {raw_seg.get('id')}")
                if manifest_seg.get("segment_id") != raw_seg.get("segment_id"):
                    self._stage_fail("Stage 2", f"manifest segment_id lệch id {raw_seg.get('id')}")
                source_hash = hashlib.sha256(str(raw_seg.get("text") or "").encode("utf-8")).hexdigest()
                if manifest_seg.get("source_hash") != source_hash:
                    self._stage_fail("Stage 2", f"source_hash lệch segment id {raw_seg.get('id')}")
        except Exception as exc:
            self._stage_fail("Stage 2", f"source_manifest validation lỗi: {exc}")
        for key in ("locked_dictionary", "suggested_dictionary", "pronouns_addressing"):
            if not isinstance(context_pack.get(key), dict):
                self._stage_fail("Stage 2", f"{key} phải là object")
        for key in ("locked_dictionary", "suggested_dictionary"):
            payload = context_pack.get(key, {})
            if isinstance(payload, dict):
                for group_name in ("characters", "glossary"):
                    if group_name in payload and not isinstance(payload.get(group_name), dict):
                        self._stage_fail("Stage 2", f"{key}.{group_name} phải là object")
        for key in ("story_timeline", "relationships_graph", "translation_memory_hits"):
            if not isinstance(context_pack.get(key), list):
                self._stage_fail("Stage 2", f"{key} phải là list")
        print("✅ [Stage 2 PASS] Context Pack đạt schema workflow.")

    def _validate_stage3(self, stage3_data, context_pack):
        if not isinstance(stage3_data, dict):
            self._stage_fail("Stage 3", "AI output phải là JSON object")
        refined = stage3_data.get("refined_segments")
        raw_segments = context_pack.get("raw_segments", []) if isinstance(context_pack, dict) else []
        expected_ids = [seg.get("id") for seg in raw_segments if isinstance(seg, dict)]
        expected_segment_ids = [seg.get("segment_id") for seg in raw_segments if isinstance(seg, dict)]
        if not isinstance(refined, list):
            self._stage_fail("Stage 3", "refined_segments phải là list")
        got_ids = []
        got_segment_ids = []
        for idx, seg in enumerate(refined, 1):
            if not isinstance(seg, dict):
                self._stage_fail("Stage 3", f"refined segment #{idx} không phải object")
            sid = seg.get("id")
            if not isinstance(sid, int):
                self._stage_fail("Stage 3", f"refined segment #{idx} thiếu id int")
            text = seg.get("refined_translation")
            if not isinstance(text, str) or not text.strip():
                self._stage_fail("Stage 3", f"refined segment id {sid} thiếu bản dịch")
            got_ids.append(sid)
            if seg.get("segment_id"):
                got_segment_ids.append(seg.get("segment_id"))
        if got_ids != expected_ids:
            self._stage_fail("Stage 3", f"Segment ids không khớp workflow: expected={expected_ids}, got={got_ids}")
        if got_segment_ids and got_segment_ids != expected_segment_ids:
            self._stage_fail("Stage 3", f"segment_id không khớp workflow: expected={expected_segment_ids}, got={got_segment_ids}")
        if not isinstance(stage3_data.get("story_timeline", {}), dict):
            self._stage_fail("Stage 3", "story_timeline phải là object")
        for key in ("new_entities", "relationships"):
            if not isinstance(stage3_data.get(key, []), list):
                self._stage_fail("Stage 3", f"{key} phải là list")
        try:
            from qc_checker import QCChecker
            qc = QCChecker(context_pack, stage3_data).check()
        except Exception as exc:
            self._stage_fail("Stage 3", f"QC checker lỗi: {exc}")
        if not qc.get("passed"):
            self._stage_fail("Stage 3", f"QC fail: {qc.get('errors', [])}")
        print("✅ [Stage 3 PASS] AI output đạt schema workflow.")

    def _validate_stage4(self, chapter_filename: str):
        toc = self._load_json_required(self.toc_file, "Stage 4")
        chapter_row = None
        for row in toc.get("chapters", []):
            if row.get("file", row.get("name")) == chapter_filename:
                chapter_row = row
                break
        if not chapter_row:
            self._stage_fail("Stage 4", f"TOC không có chương: {chapter_filename}")
        if chapter_row.get("status") != "done":
            self._stage_fail("Stage 4", f"TOC chưa đánh dấu done: {chapter_filename}")
        translated_file = chapter_row.get("translated_file")
        if not translated_file:
            self._stage_fail("Stage 4", "TOC thiếu translated_file")
        final_path = self.final_dir / translated_file
        if not final_path.exists() or not final_path.read_text(encoding="utf-8", errors="ignore").strip():
            self._stage_fail("Stage 4", f"File dịch không tồn tại hoặc rỗng: {final_path}")
        if not self.timeline_file.exists():
            self._stage_fail("Stage 4", "Thiếu story_timeline.json")
        print("✅ [Stage 4 PASS] Artifact hậu xử lý hợp lệ.")

    def _validate_stage5(self, result):
        if result is not True:
            self._stage_fail("Stage 5", "stage5_git_push.run phải trả True")
        if not (self.out_dir / ".git").exists():
            self._stage_fail("Stage 5", "Thiếu git repository sau checkpoint")
        print("✅ [Stage 5 PASS] Git checkpoint hợp lệ.")

    def _chapter_artifact_key(self, chapter_filename: str) -> str:
        base = Path(chapter_filename).stem
        base = re.sub(r'[\/:*?"<>|]', '', base)
        base = re.sub(r'\s+', ' ', base).strip()
        return base[:120] or "chapter"

    def _chapter_pretrans_dir(self, chapter_filename: str) -> Path:
        path = self.intermediate_dir / self._chapter_artifact_key(chapter_filename) / "pre-trans"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _stage_artifact_path(self, chapter_filename: str, stage: int) -> Path:
        names = {
            1: "stage1_entity_review.json",
            2: "stage2_context_pack.json",
            3: "stage3_ai_refiner.json",
        }
        return self._chapter_pretrans_dir(chapter_filename) / names[stage]

    def _legacy_stage_artifact_path(self, chapter_filename: str, stage: int) -> Path:
        return self.intermediate_dir / f"Stage_{stage}_{chapter_filename.replace('.md', '.json')}"

    def _load_stage_artifact(self, chapter_filename: str, stage: int, label: str):
        path = self._stage_artifact_path(chapter_filename, stage)
        if path.exists():
            return self._load_json_required(path, label)
        legacy = self._legacy_stage_artifact_path(chapter_filename, stage)
        if legacy.exists():
            return self._load_json_required(legacy, label)
        return self._load_json_required(path, label)

    def _chapter_index_from_name(self, name: str):
        match = re.search(r"\b(?:Chapter|Chương)\s*0*([0-9]+)", name, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _chapter_sort_key(self, path: Path):
        index = self._chapter_index_from_name(path.name)
        return (0, index, path.name) if index is not None else (1, path.name)

    def _chapter_files(self):
        chapter_files = [p for p in self.raw_dir.glob("Chapter *.md") if p.is_file()]
        if not chapter_files:
            chapter_files = [
                p for p in self.raw_dir.glob("*.md")
                if p.is_file() and p.name not in {"Intro.md", "README.md"}
            ]
        return sorted(chapter_files, key=self._chapter_sort_key)

    def _ensure_stage2_qt(self, context_pack):
        if not isinstance(context_pack, dict):
            return context_pack
        raw_segments = context_pack.get("raw_segments")
        if isinstance(raw_segments, list):
            for seg in raw_segments:
                if isinstance(seg, dict) and not isinstance(seg.get("qt"), str):
                    seg["qt"] = seg.get("text", "")
        return context_pack

    def _hydrate_stage2_manifest(self, chapter_filename: str, raw_content: str, context_pack: dict):
        if not isinstance(context_pack, dict) or context_pack.get("source_manifest"):
            return context_pack
        raw_segments = context_pack.get("raw_segments")
        if not isinstance(raw_segments, list):
            return context_pack
        import hashlib
        chapter_id = self._chapter_artifact_key(chapter_filename)
        manifest_segments = []
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue
            sid = seg.get("id")
            text = str(seg.get("text") or "")
            segment_id = f"{chapter_id}:seg_{int(sid):04d}" if isinstance(sid, int) else None
            if segment_id:
                seg["segment_id"] = segment_id
            manifest_segments.append({
                "id": sid,
                "segment_id": segment_id,
                "source_hash": hashlib.sha256(text.encode('utf-8')).hexdigest(),
                "source": text,
            })
        context_pack["source_manifest"] = {
            "schema_version": "legacy-compatible-v2",
            "chapter_id": chapter_id,
            "chapter_file": chapter_filename,
            "source_hash": hashlib.sha256((raw_content or "").encode('utf-8')).hexdigest(),
            "segment_count": len(manifest_segments),
            "segments": manifest_segments,
        }
        return context_pack

    def _read_text_sample(self, chapter_files, limit_chars=8000):
        all_text = ""
        for cf in chapter_files:
            with open(cf, 'r', encoding='utf-8') as f:
                all_text += f.read() + "\n"
            if len(all_text) >= limit_chars:
                break
        return all_text[:limit_chars]

    def _copy_master_config(self):
        import shutil
        candidates = [
            Path("/sdcard/My Agent/Translator Engine/Temp/translation_config.json"),
            Path(__file__).parent.parent / "Temp" / "translation_config.json",
        ]
        for master_config in candidates:
            if master_config.exists() and not self.config_file.exists():
                shutil.copy(master_config, self.config_file)
                return

    def _load_crawl_metadata(self):
        metadata_file = self.raw_dir / "metadata.json"
        if not metadata_file.exists():
            return {}
        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _normalize_genres(self, value):
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            return [x.strip() for x in re.split(r"[,，/|;；]", value) if x.strip()]
        return []

    def _novel_id_title_author(self):
        parts = self.novel_id.split("_", 1)
        title = parts[0].strip() if parts else self.novel_id.strip()
        author = parts[1].strip() if len(parts) > 1 else ""
        return title or self.novel_id, author

    def _pick_crawl_title_author(self, metadata: dict):
        nid_title, nid_author = self._novel_id_title_author()
        title = metadata.get("title_vi") or metadata.get("title") or nid_title
        author = metadata.get("author") or nid_author or "Unknown"
        if not isinstance(title, str) or not title.strip():
            title = nid_title
        if not isinstance(author, str) or not author.strip():
            author = nid_author or "Unknown"
        return title.strip(), author.strip()

    def _build_initial_entity_seed(self, chapter_files):
        content = "\n".join(cf.read_text(encoding="utf-8", errors="ignore") for cf in chapter_files)
        if not content.strip():
            return {"characters": {}, "glossary": {}, "pronouns": {}}
        import stage1_entity_review
        return stage1_entity_review.extract_entities_and_pronouns_offline(self.novel_id, content)

    def _write_init_entity_seed(self, chapter_files, source_type, scan_limit):
        seed_files = chapter_files[:scan_limit]
        data = self._build_initial_entity_seed(seed_files)
        data["source_type"] = source_type
        data["scan_chapter_count"] = len(seed_files)
        data["scan_limit"] = scan_limit
        data["files"] = [p.name for p in seed_files]
        _atomic_write_json(self.state_dir / "init_entity_review.json", data)
        return data

    def _write_common_project_files(self, chapter_files, readme_content, source_type, metadata=None, cover_prompt=""):
        metadata = metadata or {}
        self.readme_file.write_text(readme_content.rstrip() + "\n", encoding="utf-8")
        norm = _normalize_cover_metadata(self.novel_id, metadata, {"cover_prompt": cover_prompt})
        prompt_text = _build_cover_prompt(
            self.novel_id,
            norm["title_vi"],
            norm["author"],
            norm["genres"],
            norm["synopsis"],
            norm["cover_prompt"],
        )
        (self.state_dir / "prompt_cover.txt").write_text(prompt_text + "\n", encoding="utf-8")
        _atomic_write_json(self.state_dir / "metadata.json", metadata)

        toc = {
            "novel_id": self.novel_id,
            "source_type": source_type,
            "metadata": metadata,
            "chapters": [
                {"index": idx, "file": cf.name, "title": self._chapter_title_from_file(cf.name), "status": "pending"}
                for idx, cf in enumerate(chapter_files, 1)
            ],
        }
        _atomic_write_json(self.toc_file, toc)
        _atomic_write_json(self.out_dir / "toc.json", toc)

        _atomic_write_json(self.timeline_file, [])

        self._copy_master_config()

    def _chapter_title_from_file(self, filename: str) -> str:
        stem = Path(filename).stem
        title = re.sub(r"^Chapter\s*\d+\s*", "", stem, flags=re.IGNORECASE).strip()
        return title or stem

    def _copy_source_cover(self, metadata: dict):
        cover_file = (metadata or {}).get("cover_file")
        if not cover_file:
            return ""
        src = self.raw_dir / cover_file
        if not src.exists():
            return ""
        dst = self.out_dir / ("cover" + src.suffix.lower())
        try:
            shutil.copy2(src, dst)
            return dst.name
        except Exception as exc:
            print(f"⚠️ Copy cover failed: {exc}")
            return ""

    def _generate_cover_from_prompt(self, metadata: dict | None = None):
        metadata = metadata or {}
        copied = self._copy_source_cover(metadata)
        prompt_file = self.state_dir / "prompt_cover.txt"
        prompt = prompt_file.read_text(encoding="utf-8").strip() if prompt_file.exists() else ""
        report = {"prompt": prompt, "copied_cover": copied, "generated": False, "output": copied}
        if copied:
            _atomic_write_json(self.state_dir / "cover_generation.json", report)
            return True
        if not prompt:
            _atomic_write_json(self.state_dir / "cover_generation.json", report)
            return False
        cmd = ["agy", "-p", f"Generate a vertical 6:9 book cover image and save it as cover.png in current directory. Prompt: {prompt}"]
        try:
            proc = subprocess.run(cmd, cwd=str(self.out_dir), timeout=180, capture_output=True, text=True)
            report.update({"returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]})
        except Exception as exc:
            report["error"] = str(exc)
        for name in ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp"):
            if (self.out_dir / name).exists():
                report.update({"generated": True, "output": name})
                break
        _atomic_write_json(self.state_dir / "cover_generation.json", report)
        return bool(report.get("output"))

    def _run_init_git_push(self):
        import stage5_git_push
        stage5_git_push.run(self.out_dir, "Initialization")

    def init_new_novel(self):
        """Pipeline init cho truyện tách từ Source_Full: quét 50 chương đầu + AI overview."""
        print(f"\n=== KHỞI TẠO TRUYỆN MỚI (Source_Full Pipeline): {self.novel_id} ===")
        try:
            chapter_files = self._chapter_files()
            scan_files = chapter_files[:self.FULL_INIT_SCAN_CHAPTERS]
            if not scan_files:
                raise ValueError("[Init Stage 1 FAILED] Không tìm thấy file chương nào để khởi tạo.")

            all_text = self._read_text_sample(scan_files, limit_chars=8000)
            print(f"✅ [Init Stage 1 PASS] Đã gom {len(scan_files)} chương để phân tích.")

            print("[Init Stage 1b] Đang quét entity seed 50 chương đầu...")
            self._write_init_entity_seed(chapter_files, "source_full", self.FULL_INIT_SCAN_CHAPTERS)

            print("[Init Stage 2] Đang gọi AI phân tích tổng quan...")
            import ai_client
            import re

            prompt = f"""Bạn là một chuyên gia phân tích tiểu thuyết Trung Quốc.
Phân tích trích đoạn bên dưới rồi trả về DUY NHẤT một JSON object hợp lệ. Không markdown, không giải thích.
Schema bắt buộc:
{{
  "title_vi": "Tên truyện dịch sang tiếng Việt",
  "author": "Tên tác giả, hoặc Unknown nếu không rõ",
  "genres": ["Thể loại 1", "Thể loại 2"],
  "synopsis": "Tóm tắt cốt truyện 1-2 đoạn, tiếng Việt tự nhiên",
  "cover_prompt": "English prompt chi tiết để vẽ bìa truyện"
}}

Yêu cầu lỗi chuẩn:
- Nếu thiếu dữ kiện, dùng Unknown hoặc [] thay vì bịa.
- JSON phải parse được bằng json.loads.
- Không đặt JSON trong ```.

Nội dung trích xuất:
{all_text}
"""
            ai_text, ai_err = ai_client.call_ai_checked(prompt, temperature=0.7)
            if ai_err or not ai_text:
                raise ValueError(f"[Init Stage 2 FAILED] Lỗi gọi AI: {ai_err}")

            try:
                match = re.search(r'\{.*\}', ai_text, re.DOTALL)
                ai_response = json.loads(match.group(0) if match else ai_text)
            except Exception as e:
                raise ValueError(f"[Init Stage 2 FAILED] AI trả về JSON lỗi: {e}\nRaw output: {ai_text[:200]}")

            required_keys = ['title_vi', 'author', 'genres', 'synopsis', 'cover_prompt']
            if not isinstance(ai_response, dict) or not all(k in ai_response for k in required_keys):
                raise ValueError("[Init Stage 2 FAILED] AI trả về thiếu các trường dữ liệu khởi tạo bắt buộc.")
            ai_response = _normalize_cover_metadata(self.novel_id, ai_response, ai_response)
            print("✅ [Init Stage 2 PASS] Dữ liệu tổng quan từ AI đạt chuẩn.")

            print("[Init Stage 3] Đang tạo README, TOC, Config...")
            readme_content = f"# {ai_response['title_vi']}\n\n"
            readme_content += f"**Tác giả:** {ai_response['author']}\n"
            readme_content += f"**Thể loại:** {', '.join(self._normalize_genres(ai_response.get('genres')))}\n"
            readme_content += f"**Nguồn:** Source_Full\n"
            readme_content += f"**Tiến độ:** 0 / {len(chapter_files)} chương\n\n"
            readme_content += f"## Giới Thiệu\n{ai_response['synopsis']}\n"
            self._write_common_project_files(
                chapter_files,
                readme_content,
                source_type="source_full",
                metadata=ai_response,
                cover_prompt=ai_response.get('cover_prompt', ''),
            )
            print("✅ [Init Stage 3 PASS] Đã tạo file hệ thống.")

            print("[Init Stage 4] Sinh cover từ prompt...")
            if self._generate_cover_from_prompt({"cover_file": ""}):
                print("✅ Cover generation flow completed.")
            else:
                print("⚠️ Không sinh được cover; kiểm tra prompt_cover.txt / agy backend.")

            print("[Init Stage 5] Push lên Git...")
            self._run_init_git_push()
            print("✅ [Init Stage 5 PASS] Khởi tạo Git thành công.")

        except Exception as e:
            print(f"\n❌ [INIT PIPELINE ABORTED] Khởi tạo thất bại: {e}")
            return False

        print(f"\n🎉 HOÀN TẤT KHỞI TẠO TRUYỆN MỚI: {self.novel_id}")
        return True

    def init_crawled_novel(self):
        """Pipeline init riêng cho truyện crawl: dùng metadata, không gọi AI overview, entity seed 5 chương đầu."""
        print(f"\n=== KHỞI TẠO TRUYỆN CRAWL (Crawl Pipeline): {self.novel_id} ===")
        try:
            chapter_files = self._chapter_files()
            if not chapter_files:
                raise ValueError("[Crawl Init FAILED] Không tìm thấy file chương nào để khởi tạo.")

            metadata = self._load_crawl_metadata()
            title, author = self._pick_crawl_title_author(metadata)
            genres = self._normalize_genres(metadata.get("genres") or metadata.get("genre") or metadata.get("kind") or metadata.get("category"))
            synopsis = metadata.get("description") or metadata.get("intro") or metadata.get("summary") or ""
            source_name = metadata.get("source_name") or metadata.get("source_id") or "crawl"
            source_url = metadata.get("source_url") or ""
            cover_file = metadata.get("cover_file") or ""

            print("[Crawl Init Stage 1] Đang quét entity seed 5 chương đầu...")
            self._write_init_entity_seed(chapter_files, "crawl", self.CRAWL_INIT_SCAN_CHAPTERS)

            print("[Crawl Init Stage 2] Đang tạo README từ metadata crawl...")
            readme = [f"# {title}", ""]
            readme.append(f"**Tác giả:** {author}")
            if genres:
                readme.append(f"**Thể loại:** {', '.join(genres)}")
            readme.append(f"**Nguồn:** {source_name}")
            if source_url:
                readme.append(f"**URL nguồn:** {source_url}")
            readme.append(f"**Tiến độ:** 0 / {len(chapter_files)} chương")
            if cover_file:
                rel_cover = os.path.relpath(self.raw_dir / cover_file, self.out_dir)
                readme.extend(["", f"![Cover]({rel_cover})"])
            readme.extend(["", "## Giới Thiệu", synopsis or "Chưa có mô tả.", ""])

            norm_meta = _normalize_cover_metadata(self.novel_id, metadata, {})
            cover_prompt = norm_meta.get("cover_prompt") or f"Book cover for {title}. Chinese web novel style."
            self._write_common_project_files(
                chapter_files,
                "\n".join(readme),
                source_type="crawl",
                metadata={**metadata, **norm_meta},
                cover_prompt=cover_prompt,
            )
            print("✅ [Crawl Init Stage 2 PASS] Đã tạo README, TOC, Config từ metadata.")

            print("[Crawl Init Stage 3] Sinh cover từ prompt...")
            if self._generate_cover_from_prompt(metadata):
                print("✅ Cover generation flow completed.")
            else:
                print("⚠️ Không sinh được cover; kiểm tra prompt/metadata/backend.")

            print("[Crawl Init Stage 4] Push lên Git...")
            self._run_init_git_push()
            print("✅ [Crawl Init Stage 4 PASS] Khởi tạo Git thành công.")

        except Exception as e:
            print(f"\n❌ [CRAWL INIT PIPELINE ABORTED] Khởi tạo crawl thất bại: {e}")
            return False

        print(f"\n🎉 HOÀN TẤT KHỞI TẠO TRUYỆN CRAWL: {self.novel_id}")
        return True

    def process_chapter(self, chapter_filename: str, start_stage: int = 1):
        """Xử lý một chương qua 5 bước nghiêm ngặt. Hỗ trợ resume từ stage bị lỗi."""
        # Kiểm tra TOC trước (chỉ skip nếu chạy mới từ stage 1)
        toc_path = self.state_dir / "toc.json"
        if toc_path.exists() and start_stage == 1:
            try:
                with open(toc_path, 'r', encoding='utf-8') as f:
                    toc = json.load(f)
                for ch in toc.get('chapters', []):
                    if ch.get('file', ch.get('name')) == chapter_filename and ch.get('status') == 'done':
                        print(f"⏭️ Bỏ qua {chapter_filename} — đã dịch xong.")
                        return True, "Already done"
            except: pass

        print(f"\n{'='*50}\n[Pipeline] Bắt đầu xử lý: {chapter_filename} (Từ Stage {start_stage})\n{'='*50}")
        raw_filepath = self.raw_dir / chapter_filename
        if not raw_filepath.exists():
            print(f"❌ Không tìm thấy file gốc: {raw_filepath}")
            return False, "File not found"

        with open(raw_filepath, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        if not raw_content.strip():
            return False, "[Stage 0 FAILED] Nội dung chương rỗng"

        # Artifact trung gian được nhóm theo chương:
        # Intermediate/<chapter-key>/pre-trans/{stage1,stage2,stage3}.json
        stage1_out_path = self._stage_artifact_path(chapter_filename, 1)
        stage2_out_path = self._stage_artifact_path(chapter_filename, 2)
        stage3_out_path = self._stage_artifact_path(chapter_filename, 3)

        # Khởi tạo biến lưu trữ dữ liệu truyền giữa các stage
        stage1_data = None
        context_pack = None
        stage3_data = None

        import stage1_entity_review
        import stage2_context_pack
        import stage3_ai_refiner
        import stage4_post_process
        import stage5_git_push

        try:
            # --- STAGE 1: ENTITY REVIEW (100% Offline) ---
            if start_stage <= 1:
                stage1_data = stage1_entity_review.run(
                    novel_id=self.novel_id,
                    chapter_content=raw_content,
                    output_dir=str(self.out_dir)
                )
                self._validate_stage1(stage1_data, raw_content)
                with open(stage1_out_path, 'w', encoding='utf-8') as f:
                    json.dump(stage1_data, f, ensure_ascii=False, indent=2)
            else:
                stage1_data = self._load_stage_artifact(chapter_filename, 1, "Stage 1")
                self._validate_stage1(stage1_data, raw_content)

            # --- STAGE 2: CONTEXT PACK ---
            if start_stage <= 2:
                context_pack = stage2_context_pack.run(
                    novel_id=self.novel_id,
                    chapter_content=raw_content,
                    stage1_data=stage1_data,
                    output_dir=str(self.out_dir),
                    chapter_filename=chapter_filename,
                )
                context_pack = self._ensure_stage2_qt(context_pack)
                self._validate_stage2(context_pack)
                with open(stage2_out_path, 'w', encoding='utf-8') as f:
                    json.dump(context_pack, f, ensure_ascii=False, indent=2)
            else:
                context_pack = self._load_stage_artifact(chapter_filename, 2, "Stage 2")
                context_pack = self._ensure_stage2_qt(context_pack)
                context_pack = self._hydrate_stage2_manifest(chapter_filename, raw_content, context_pack)
                self._validate_stage2(context_pack)

            # --- STAGE 3: AI REFINER ---
            if start_stage <= 3:
                import time
                for attempt in range(3):
                    try:
                        stage3_data = stage3_ai_refiner.run(
                            novel_id=self.novel_id,
                            context_pack=context_pack,
                            output_dir=str(self.out_dir)
                        )
                        self._validate_stage3(stage3_data, context_pack)
                        break
                    except Exception as e:
                        if attempt < 2:
                            print(f"[Stage 3] Thất bại lần {attempt+1}/3. Đang thử lại sau 5s... Lỗi: {e}")
                            time.sleep(5)
                        else:
                            raise e
                with open(stage3_out_path, 'w', encoding='utf-8') as f:
                    json.dump(stage3_data, f, ensure_ascii=False, indent=2)
                
                # --- STAGE 3.5: QC CHECK ---
                from qc_checker import QCChecker
                qc = QCChecker(context_pack, stage3_data)
                qc_res = qc.check()
                if not qc_res['passed']:
                    print(f"[QC] Errors: {qc_res['errors']}")
                    raise ValueError(f"[Stage 3.5 FAILED] QC failed: {qc_res['errors']}")
                if qc_res['warnings']:
                    print(f"[QC] Warnings: {qc_res['warnings']}")
            else:
                stage3_data = self._load_stage_artifact(chapter_filename, 3, "Stage 3")
                self._validate_stage3(stage3_data, context_pack)

            if start_stage <= 4:
                stage4_result = stage4_post_process.run(
                    novel_id=self.novel_id,
                    out_dir=self.out_dir,
                    chapter_filename=chapter_filename,
                    ai_output=stage3_data,
                    context_pack=context_pack
                )
                if stage4_result is not True:
                    self._stage_fail("Stage 4", "stage4_post_process.run phải trả True")
                self._validate_stage4(chapter_filename)

            # --- STAGE 5: GIT PUSH ---
            if start_stage <= 5:
                stage5_result = stage5_git_push.run(
                    out_dir=self.out_dir,
                    chapter_filename=chapter_filename
                )
                self._validate_stage5(stage5_result)

            print(f"🎉 Hoàn tất toàn bộ Pipeline cho {chapter_filename}")
            return True, ""

        except Exception as e:
            import traceback
            error_msg = str(e) + "\n" + traceback.format_exc()
            print(f"❌ Pipeline bị vỡ ở chương {chapter_filename}: {e}")
            return False, error_msg


if __name__ == '__main__':
    mgr = PipelineManager("truyen_test", "/sdcard/My Agent/Translator Engine/Test", "/sdcard/My Agent/Translator Engine/Output")
    mgr.init_new_novel()
    mgr.process_chapter("Chapter 0008 喜大普奔，恭喜无限游戏正式开服！.md")
