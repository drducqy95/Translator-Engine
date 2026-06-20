import os
import json
from pathlib import Path
from qt_engine import QTEngine
import re

class PipelineManager:
    def __init__(self, novel_id: str, raw_dir: str, output_dir: str):
        self.novel_id = novel_id
        self.raw_dir = Path(raw_dir)
        self.out_dir = Path(output_dir)
        
        self.state_dir = self.out_dir / "State"
        self.intermediate_dir = self.out_dir / "Intermediate"
        self.final_dir = self.out_dir / "Final_Translated"
        
        for d in [self.out_dir, self.state_dir, self.intermediate_dir, self.final_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
        self.toc_file = self.state_dir / "toc.json"
        
        # Liên kết với QT Engine
        import qt_engine
        self.qt = qt_engine.QTEngine()
        
        # Đảm bảo Project DB tồn tại và được load
        self.qt.dict_mgr.load_project(self.novel_id)
        
        self.readme_file = self.out_dir / "README.md"
        self.timeline_file = self.state_dir / "story_timeline.json"
        self.config_file = self.state_dir / "translation_config.json"

    def init_new_novel(self):
        """Pipeline 1: Khởi tạo truyện mới (Quét 50 chương đầu, AI phân tích tổng quan) có check Pass/Fail"""
        print(f"\n=== KHỞI TẠO TRUYỆN MỚI (Strict Pipeline): {self.novel_id} ===")
        try:
            # BƯỚC 1: Quét nội dung 50 chương đầu
            chapter_files = sorted(list(self.raw_dir.glob("*.md")))[:50]
            if not chapter_files:
                raise ValueError("[Init Stage 1 FAILED] Không tìm thấy file chương nào để khởi tạo.")
                
            all_text = ""
            for cf in chapter_files:
                with open(cf, 'r', encoding='utf-8') as f:
                    all_text += f.read() + "\n"
            print(f"✅ [Init Stage 1 PASS] Đã gom {len(chapter_files)} chương để phân tích.")

            # BƯỚC 2: Gọi AI phân tích tổng quan
            print("[Init Stage 2] Đang gọi AI phân tích tổng quan...")
            import ai_client
            import re
            
            prompt = f"""Bạn là một chuyên gia phân tích tiểu thuyết.
Dưới đây là một phần nội dung từ tiểu thuyết mới. Hãy phân tích và xuất ra thông tin bằng JSON với định dạng sau:
{{
  "title_vi": "Tên truyện dịch sang tiếng Việt",
  "author": "Tên Tác giả",
  "genres": ["Thể loại 1", "Thể loại 2"],
  "synopsis": "Tóm tắt cốt truyện ngắn gọn gọn gàng (1-2 đoạn)",
  "cover_prompt": "Prompt tiếng Anh cực kỳ chi tiết, miêu tả khung cảnh, nhân vật để vẽ bìa truyện (Digital art, 8k, masterpiece)"
}}

CHỈ XUẤT JSON HỢP LỆ, KHÔNG CÓ BẤT KỲ VĂN BẢN NÀO KHÁC BÊN NGOÀI.

Nội dung trích xuất để phân tích:
{all_text[:8000]}
"""
            ai_text, ai_err = ai_client.call_ai_checked(prompt, temperature=0.7)
            if ai_err or not ai_text:
                raise ValueError(f"[Init Stage 2 FAILED] Lỗi gọi AI: {ai_err}")
                
            try:
                match = re.search(r'\{.*\}', ai_text, re.DOTALL)
                if match:
                    ai_response = json.loads(match.group(0))
                else:
                    ai_response = json.loads(ai_text)
            except Exception as e:
                raise ValueError(f"[Init Stage 2 FAILED] AI trả về JSON lỗi: {e}\nRaw output: {ai_text[:200]}")
            
            required_keys = ['title_vi', 'author', 'genres', 'synopsis', 'cover_prompt']
            if not isinstance(ai_response, dict) or not all(k in ai_response for k in required_keys):
                raise ValueError("[Init Stage 2 FAILED] AI trả về thiếu các trường dữ liệu khởi tạo bắt buộc.")
            print("✅ [Init Stage 2 PASS] Dữ liệu tổng quan từ AI đạt chuẩn.")

            # BƯỚC 3: Tạo File Hệ thống
            print("[Init Stage 3] Đang tạo các file hệ thống (README, TOC, Config)...")
            readme_content = f"# {ai_response['title_vi']}\n\n"
            readme_content += f"**Tác giả:** {ai_response['author']}\n"
            readme_content += f"**Thể loại:** {', '.join(ai_response['genres'])}\n"
            readme_content += f"**Tiến độ:** 0 / {len(list(self.raw_dir.glob('*.md')))} chương\n\n"
            readme_content += f"## Giới Thiệu\n{ai_response['synopsis']}\n"
            
            with open(self.readme_file, 'w', encoding='utf-8') as f:
                f.write(readme_content)
                
            with open(self.state_dir / "prompt_cover.txt", 'w', encoding='utf-8') as f:
                f.write(ai_response['cover_prompt'])
                
            toc = {"novel_id": self.novel_id, "chapters": [{"file": cf.name, "status": "pending"} for cf in self.raw_dir.glob("*.md")]}
            with open(self.toc_file, 'w', encoding='utf-8') as f:
                json.dump(toc, f, ensure_ascii=False, indent=2)
                
            with open(self.timeline_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
                
            import shutil
            master_config = Path("/sdcard/My Agent/Translator Engine/Temp/translation_config.json")
            if master_config.exists() and not self.config_file.exists():
                shutil.copy(master_config, self.config_file)
            print("✅ [Init Stage 3 PASS] Đã tạo thành công toàn bộ file hệ thống.")

            # BƯỚC 4: Git Push cho init
            print("[Init Stage 4] Push lên Git...")
            import stage5_git_push
            stage5_git_push.run(self.out_dir, "Initialization")
            print("✅ [Init Stage 4 PASS] Khởi tạo Git thành công.")
            
        except Exception as e:
            print(f"\n❌ [INIT PIPELINE ABORTED] Khởi tạo thất bại: {e}")
            return False
            
        print(f"\n🎉 HOÀN TẤT KHỞI TẠO TRUYỆN MỚI: {self.novel_id}")
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
            
        # Tạo thư mục lưu output trung gian cho từng stage
        for stage_dir in ["Stage_1_Output", "Stage_2_Output", "Stage_3_Output"]:
            (self.out_dir / stage_dir).mkdir(parents=True, exist_ok=True)

        stage1_out_path = self.intermediate_dir / f"Stage_1_{chapter_filename.replace('.md', '.json')}"
        stage2_out_path = self.intermediate_dir / f"Stage_2_{chapter_filename.replace('.md', '.json')}"
        stage3_out_path = self.intermediate_dir / f"Stage_3_{chapter_filename.replace('.md', '.json')}"

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
                with open(stage1_out_path, 'w', encoding='utf-8') as f:
                    json.dump(stage1_data, f, ensure_ascii=False, indent=2)
            else:
                if stage1_out_path.exists():
                    with open(stage1_out_path, 'r', encoding='utf-8') as f:
                        stage1_data = json.load(f)
                else:
                    raise Exception(f"Không tìm thấy dữ liệu Stage 1 để resume: {stage1_out_path}")

            # --- STAGE 2: CONTEXT PACK ---
            if start_stage <= 2:
                context_pack = stage2_context_pack.run(
                    novel_id=self.novel_id,
                    chapter_content=raw_content,
                    stage1_data=stage1_data,
                    output_dir=str(self.out_dir)
                )
                with open(stage2_out_path, 'w', encoding='utf-8') as f:
                    json.dump(context_pack, f, ensure_ascii=False, indent=2)
            else:
                if stage2_out_path.exists():
                    with open(stage2_out_path, 'r', encoding='utf-8') as f:
                        context_pack = json.load(f)
                else:
                    raise Exception(f"Không tìm thấy dữ liệu Stage 2 để resume: {stage2_out_path}")

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
                if qc_res['warnings']:
                    print(f"[QC] Warnings: {qc_res['warnings']}")
            else:
                if stage3_out_path.exists():
                    with open(stage3_out_path, 'r', encoding='utf-8') as f:
                        stage3_data = json.load(f)
                else:
                    raise Exception(f"Không tìm thấy dữ liệu Stage 3 để resume: {stage3_out_path}")

            if start_stage <= 4:
                stage4_post_process.run(
                    novel_id=self.novel_id,
                    out_dir=self.out_dir,
                    chapter_filename=chapter_filename,
                    ai_output=stage3_data,
                    context_pack=context_pack
                )
            
            # --- STAGE 5: GIT PUSH ---
            if start_stage <= 5:
                stage5_git_push.run(
                    out_dir=self.out_dir,
                    chapter_filename=chapter_filename
                )

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
