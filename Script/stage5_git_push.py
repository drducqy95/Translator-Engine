import subprocess
from pathlib import Path


def _find_git_root(start: Path) -> Path:
    engine_root = Path(__file__).resolve().parents[1]
    if (engine_root / ".git").exists():
        return engine_root
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start


def _git_add_force(cwd: Path, paths: list[str]) -> None:
    for path in paths:
        subprocess.run(["git", "add", "-f", path], cwd=cwd, check=False)


def _git_reset_paths(cwd: Path, paths: list[str]) -> None:
    for path in paths:
        subprocess.run(["git", "reset", "--", path], cwd=cwd, check=False, capture_output=True)


def _rel_to_git_root(git_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(git_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _current_branch(git_root: Path) -> str:
    res = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )
    branch = (res.stdout or "").strip()
    return branch or "main"


def _refresh_final_output_indexes(git_root: Path) -> None:
    try:
        from final_output_indexer import refresh
    except ImportError:
        from Script.final_output_indexer import refresh
    refresh(git_root / "Final_Output_ASCII")

def run(out_dir: Path, chapter_filename: str):
    """BƯỚC 5: Push Git
    - Nếu mọi thứ pass, push lên Git
    """
    print(f"[Stage 5] Đang push Git cho chương: {chapter_filename}")
    
    try:
        # Khởi tạo git nếu chưa có
        git_root = _find_git_root(out_dir)
        if not (git_root / ".git").exists():
            subprocess.run(["git", "init"], cwd=git_root, check=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=git_root, check=False)
            
        # Thêm file (force include large ignored outputs + final artifacts)
        subprocess.run(["git", "config", "user.name", "Translator Engine Bot"], cwd=git_root, check=False)
        subprocess.run(["git", "config", "user.email", "translator-engine-bot@localhost"], cwd=git_root, check=False)
        _refresh_final_output_indexes(git_root)
        out_dir = Path(out_dir)
        tracked = [_rel_to_git_root(git_root, out_dir), _rel_to_git_root(git_root, git_root / "Final_Output_ASCII")]
        _git_add_force(git_root, tracked)
        _git_reset_paths(git_root, [_rel_to_git_root(git_root, out_dir / "Intermediate")])
        subprocess.run(["git", "add", "."], cwd=git_root, check=True)
        _git_reset_paths(git_root, [_rel_to_git_root(git_root, out_dir / "Intermediate")])
        
        # Commit
        commit_msg = f"Auto-translate: {chapter_filename}" if chapter_filename != "Initialization" else "Initialize Translation Project"
        res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=git_root, capture_output=True, text=True)
        commit_output = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0:
            if "nothing to commit" in commit_output.lower() or "no changes added" in commit_output.lower():
                print("[Stage 5] Không có thay đổi mới để commit.")
            else:
                raise ValueError(f"git commit failed: {commit_output.strip()[:500]}")
        
        # Push (Chỉ push nếu có remote)
        remote_check = subprocess.run(["git", "remote"], cwd=git_root, capture_output=True, text=True)
        if remote_check.stdout.strip():
            # Push ngầm (không in lỗi ra ngoài nếu đứt mạng, có thể retry sau)
            try:
                branch = _current_branch(git_root)
                subprocess.run(["git", "push", "origin", branch], cwd=git_root, check=True, capture_output=True)
            except subprocess.CalledProcessError as push_e:
                print(f"[Stage 5 Warning] Commit thành công nhưng không thể Push: {push_e}")
    except Exception as e:
        raise ValueError(f"[Stage 5 FAILED] Lỗi Git: {e}")
        
    print("✅ [Stage 5 PASS] Git checkpoint hoàn tất.")
    return True
