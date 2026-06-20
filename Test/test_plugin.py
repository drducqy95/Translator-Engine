import os
import sys
sys.path.append("/sdcard/My Agent/Translator Engine/Script")
from source_manager import SourceManager

def test_69shuba():
    base_dir = "/sdcard/My Agent/Translator Engine"
    sm = SourceManager(base_dir)
    
    # 69shuba url
    url = "https://www.69shuba.cx/book/48360.htm"
    novel_id = "test_plugin_69shuba"
    
    # crawl 3 chapters for testing
    sm.crawl_novel_via_plugin(url=url, novel_id=novel_id, site_id="69shuba", max_chapters=3)

if __name__ == "__main__":
    test_69shuba()
