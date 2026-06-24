#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import json
import shutil
from unittest.mock import patch

# Adjust sys.path to include Script directory
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "Script"))

import ai_client
from pipeline_manager import PipelineManager
import stage3_offline_hymt
import stage5_git_push

def test_quota_fallback():
    print("\n--- Testing Cloud Quota to Local Fallback ---")
    
    cooldown_file = ROOT / "Dashboard" / "data" / "ai_cooldown.json"
    if cooldown_file.exists():
        cooldown_file.unlink()

    def mock_call_provider(prov, prompt, stream, temperature, timeout, system_prompt=None):
        role = prov.get("role", "primary")
        if role == "primary":
            raise ai_client._RateLimited("429 Too Many Requests")
        elif role == "offline_fallback":
            return "[1] Bản dịch 1\n[2] Bản dịch 2\n[3] Bản dịch 3"
        return ""
        
    with patch("ai_client._call_provider", side_effect=mock_call_provider):
        text, err, meta = ai_client.call_ai_checked_with_meta("test prompt")
        assert err is None, f"Expected no error, got {err}"
        assert meta["mode"] == "offline_fallback", f"Expected offline_fallback, got {meta['mode']}"
        assert "[1] Bản dịch 1" in text
        print("OK: Quota fallback works!")

def test_cli_fallback_keeps_json_contract():
    print("\n--- Testing CLI fallback metadata contract ---")

    def mock_call_provider(prov, prompt, stream, temperature, timeout, system_prompt=None):
        raise Exception("network down")

    with patch("ai_client._call_provider", side_effect=mock_call_provider), \
         patch("ai_client._call_cli", return_value='{"refined_segments":[],"story_timeline":{},"new_entities":[],"relationships":[]}') as cli_mock:
        text, err, meta = ai_client.call_ai_checked_with_meta(
            "user payload",
            system_prompt="SYSTEM RULES: return JSON",
            max_retries=1,
        )

    sent_prompt = cli_mock.call_args.args[1]
    assert "SYSTEM RULES: return JSON" in sent_prompt
    assert "user payload" in sent_prompt
    assert err is None
    assert text.startswith("{")
    assert meta["role"] == "cli_fallback"
    assert meta["mode"] == "cli_fallback"

def test_segment_preservation():
    print("\n--- Testing Segment Preservation ---")
    context_pack = {
        "raw_segments": [
            {"id": 1, "text": "Raw 1"},
            {"id": 2, "text": "Raw 2"},
            {"id": 3, "text": "Raw 3"}
        ]
    }
    response_text = "[1] Bản dịch 1\n[2] Bản dịch 2" # Missing segment 3
    
    # Mock call_one_checked for the missing segment 3
    def mock_call_one_checked(provider, prompt, **kwargs):
        if "Raw 3" in prompt:
            return "Bản dịch 3 (batch)", None
        return "", "Error"
        
    with patch("stage3_offline_hymt.call_one_checked", side_effect=mock_call_one_checked):
        result = stage3_offline_hymt.run_fallback(
            novel_id="test", 
            context_pack=context_pack, 
            output_dir="/tmp", 
            response_text=response_text, 
            meta={"provider": "local_hymt", "mode": "offline_fallback"}
        )
        
        segments = result.get("refined_segments", [])
        assert len(segments) == 3, f"Expected 3 segments, got {len(segments)}"
        assert segments[0]["id"] == 1
        assert segments[1]["id"] == 2
        assert segments[2]["id"] == 3
        assert segments[2]["refined_translation"] == "Bản dịch 3 (batch)"
        assert result["provider_meta"]["provider"] == "local_hymt"
        assert result["provider_meta"]["mode"] == "offline_fallback"
        print("OK: Segment preservation works!")

def test_smoke_5_chapters():
    print("\n--- Testing Smoke 5 Real Chapters ---")
    
    novel_id = "Rạp Chiếu Phim Địa Ngục"
    source_dir = ROOT / "Source_Split" / novel_id
    temp_output_dir = Path("/tmp/hymt-5chap-output")
    
    if not source_dir.exists():
        print(f"Skipping smoke test: {source_dir} not found.")
        return
        
    chapters = sorted([f for f in os.listdir(source_dir) if f.startswith("Chapter ") and f.endswith(".md")])[:5]
    if not chapters:
        print("Skipping smoke test: No chapters found.")
        return
        
    print(f"Found 5 chapters: {chapters}")
    
    # We mock _call_provider to always act as local_hymt doing a fake translation
    def mock_call_provider(prov, prompt, stream, temperature, timeout, system_prompt=None):
        if prov.get("role", "primary") == "primary":
            raise ai_client._RateLimited("429 Too Many Requests")
            
        # It's offline fallback!
        # Return a fake translation block that matches whatever segments were asked
        import re
        ids = re.findall(r'\[(\d+)\]', prompt)
        lines = []
        for i in ids:
            lines.append(f"[{i}] Bản dịch fake cho segment {i}")
        return "\n".join(lines)
        
    # We also mock stage3_offline_hymt.call_one_checked in case any segments are missing
    def mock_call_one_checked(provider, prompt, **kwargs):
        return "Bản dịch fake từng đoạn", None

    # Clear old ai cooldown state to avoid hitting cache instead of our mock
    cooldown_file = ROOT / "Dashboard" / "data" / "ai_cooldown.json"
    if cooldown_file.exists():
        cooldown_file.unlink()

    if temp_output_dir.exists():
        shutil.rmtree(temp_output_dir)
    novel_source = temp_output_dir / "Source_Split" / novel_id
    novel_source.mkdir(parents=True, exist_ok=True)
    
    for chapter in chapters:
        chapter_path = source_dir / chapter
        with open(chapter_path, "r", encoding="utf-8") as f:
            text = f.read()
        with open(novel_source / chapter, "w", encoding="utf-8") as f:
            f.write(text)
    
    mgr = PipelineManager(novel_id, str(novel_source), str(temp_output_dir))
    
    with patch("ai_client._call_provider", side_effect=mock_call_provider), \
         patch("stage3_offline_hymt.call_one_checked", side_effect=mock_call_one_checked), \
         patch("stage5_git_push.run", return_value=True):
        assert mgr.init_crawled_novel() is True
         
        for chapter in chapters:
            print(f"Processing {chapter}...")
            
            try:
                res = mgr.process_chapter(chapter)
                assert res[0], f"Chapter {chapter} failed processing: {res[1]}"
            except Exception as e:
                print(f"Error processing {chapter}: {e}")
                import traceback
                traceback.print_exc()
                
    # Verify artifacts
    toc_path = temp_output_dir / "State" / "toc.json"
    assert toc_path.exists(), "toc.json not found"
    with open(toc_path, "r", encoding="utf-8") as f:
        toc = json.load(f)
        
    for chapter in chapters:
        import re
        base = Path(chapter).stem
        base = re.sub(r'[\/:*?"<>|]', '', base)
        base = re.sub(r'\s+', ' ', base).strip()
        base_name = base[:120] or "chapter"
        
        pre_trans = temp_output_dir / "Intermediate" / base_name / "pre-trans"
        
        assert pre_trans.exists(), f"pre-trans missing for {chapter}"
        assert (pre_trans / "stage1_entity_review.json").exists(), f"stage1 missing for {chapter}"
        assert (pre_trans / "stage2_context_pack.json").exists(), f"stage2 missing for {chapter}"
        assert (pre_trans / "stage3_ai_refiner.json").exists(), f"stage3 missing for {chapter}"
        
        ch_info = next((row for row in toc.get("chapters", []) if row.get("file") == chapter), None)
        assert ch_info is not None, f"{chapter} missing from toc.json"
        assert ch_info.get("status") == "done", f"{chapter} status is not done"

        translated_file = ch_info.get("translated_file")
        assert translated_file, f"translated_file missing for {chapter}"

        final_file = temp_output_dir / "Final_Translated" / translated_file
        assert final_file.exists(), f"Final output missing for {chapter}: {final_file}"
        assert final_file.read_text(encoding="utf-8").strip(), f"Final output empty for {chapter}"
        
    print("OK: Smoke test artifacts verified!")

if __name__ == "__main__":
    test_quota_fallback()
    test_segment_preservation()
    test_smoke_5_chapters()
    print("\nALL TESTS PASSED!")
