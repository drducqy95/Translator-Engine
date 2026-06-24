import re
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR / "Script"))


def test_chapter_splitter_keeps_author_notice_headings():
    import chapter_splitter

    samples = [
        "明天就要上架了，在此求订阅",
        "今天请假一天",
        "今日请假",
        "完本感言",
        "第十卷 尼特莱尔家族III复活 第十三卷 斯特拉斯堡",
    ]

    for sample in samples:
        assert chapter_splitter.detect_chapter_heading(sample) is not None

    assert chapter_splitter.detect_chapter_heading("这里需要说明一下剧情，并不是章节标题。") is None


def test_hell_cinema_source_splits_to_1887_chapters_when_available():
    import chapter_splitter

    source = ENGINE_DIR / "Source_Full" / "Rạp Chiếu Phim Địa Ngục.html"
    if not source.exists():
        pytest.skip("local source fixture not present")

    html = source.read_text(encoding="utf-8", errors="replace")
    assert len(re.findall(r"<h1\b[^>]*>.*?</h1>", html, flags=re.I | re.S)) == 1887

    lines = chapter_splitter.extract_lines(source)
    headings = [line for line in lines if chapter_splitter.detect_chapter_heading(line)]

    assert len(headings) == 1887
