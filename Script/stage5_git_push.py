import subprocess
from pathlib import Path

def run(out_dir: Path, chapter_filename: str):
    """BƯỚC 5: Push Git
    - Nếu mọi thứ pass, push lên Git
    """
    print(f"[Stage 5] Đang push Git cho chương: {chapter_filename}")
    
    try:
        # Khởi tạo git nếu chưa có
        if not (out_dir / ".git").exists():
            subprocess.run(["git", "init"], cwd=out_dir, check=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=out_dir, check=False)
            
        # Thêm file (force include large ignored outputs + final artifacts)
        subprocess.run(["git", "config", "user.name", "Translator Engine Bot"], cwd=out_dir, check=False)
        subprocess.run(["git", "config", "user.email", "translator-engine-bot@localhost"], cwd=out_dir, check=False)
        tracked = [
            "README.md", "toc.json", "story_timeline.json", "State/", "Final_Translated/",
            "State/toc.json", "State/metadata.json", "State/prompt_cover.txt", "State/story_timeline.json",
            "State/cover_generation.json",
        ]
        for path in tracked:
            subprocess.run(["git", "add", "-f", path], cwd=out_dir, check=False)
        subprocess.run(["git", "add", "."], cwd=out_dir, check=True)
        
        # Commit
        commit_msg = f"Auto-translate: {chapter_filename}" if chapter_filename != "Initialization" else "Initialize Translation Project"
        res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=out_dir, capture_output=True, text=True)
        commit_output = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0:
            if "nothing to commit" in commit_output.lower() or "no changes added" in commit_output.lower():
                print("[Stage 5] Không có thay đổi mới để commit.")
            else:
                raise ValueError(f"git commit failed: {commit_output.strip()[:500]}")
        
        # Push (Chỉ push nếu có remote)
        remote_check = subprocess.run(["git", "remote"], cwd=out_dir, capture_output=True, text=True)
        if remote_check.stdout.strip():
            # Push ngầm (không in lỗi ra ngoài nếu đứt mạng, có thể retry sau)
            try:
                subprocess.run(["git", "push", "origin", "main"], cwd=out_dir, check=True, capture_output=True)
            except subprocess.CalledProcessError as push_e:
                print(f"[Stage 5 Warning] Commit thành công nhưng không thể Push: {push_e}")
    except Exception as e:
        raise ValueError(f"[Stage 5 FAILED] Lỗi Git: {e}")
        
    print("✅ [Stage 5 PASS] Git checkpoint hoàn tất.")
    return True
