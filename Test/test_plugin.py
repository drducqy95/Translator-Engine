import os
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
sys.path.append(str(ENGINE_DIR / "Script"))
from source_manager import SourceManager


@pytest.mark.skipif(os.getenv("RUN_NETWORK_TESTS") != "1", reason="network integration test disabled")
def test_69shuba_crawl_integration():
    sm = SourceManager(str(ENGINE_DIR))
    novel_id = "test_plugin_69shuba"
    out_dir = ENGINE_DIR / "Source_Split" / novel_id

    sm.crawl_novel_via_plugin(
        url="https://www.69shuba.cx/book/48360.htm",
        novel_id=novel_id,
        site_id="69shuba",
        max_chapters=3,
    )

    assert out_dir.exists()
    assert len(list(out_dir.glob("Chapter *.md"))) >= 1
