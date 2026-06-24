import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR / "Script"))


def test_pipeline_stage_artifacts_are_grouped_by_chapter(tmp_path):
    from pipeline_manager import PipelineManager

    raw_dir = tmp_path / "Source_Split" / "demo"
    out_dir = tmp_path / "Output" / "demo"
    raw_dir.mkdir(parents=True)
    pm = PipelineManager("demo", str(raw_dir), str(out_dir))

    chapter = "Chapter 0001 第一章.md"
    pretrans = pm._chapter_pretrans_dir(chapter)

    assert pretrans == out_dir / "Intermediate" / "Chapter 0001 第一章" / "pre-trans"
    assert pm._stage_artifact_path(chapter, 1) == pretrans / "stage1_entity_review.json"
    assert pm._stage_artifact_path(chapter, 2) == pretrans / "stage2_context_pack.json"
    assert pm._stage_artifact_path(chapter, 3) == pretrans / "stage3_ai_refiner.json"
    assert pm.final_dir == out_dir / "Final_Translated"
    assert pm.state_dir == out_dir / "State"


def test_stage_artifact_resume_reads_legacy_flat_file(tmp_path):
    from pipeline_manager import PipelineManager

    raw_dir = tmp_path / "Source_Split" / "demo"
    out_dir = tmp_path / "Output" / "demo"
    raw_dir.mkdir(parents=True)
    pm = PipelineManager("demo", str(raw_dir), str(out_dir))
    legacy = out_dir / "Intermediate" / "Stage_1_Chapter 0001.json"
    legacy.write_text('{"characters":{},"glossary":{},"pronouns":{}}', encoding="utf-8")

    data = pm._load_stage_artifact("Chapter 0001.md", 1, "Stage 1")

    assert data["characters"] == {}
