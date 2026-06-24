import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR / "Script"))


def test_daemons_do_not_autostart_on_import():
    import Bot.daemons as daemons

    assert daemons._daemon_threads == []
    assert callable(daemons.start_daemons)


def test_recover_stale_processing_resets_missing_timestamp():
    import Bot.daemons as daemons

    toc = {"chapters": [{"file": "Chapter 0001.md", "status": "processing"}]}

    changed = daemons._recover_stale_processing(toc)

    assert changed is True
    assert toc["chapters"][0]["status"] == "pending"
    assert "processing_started_at" not in toc["chapters"][0]


def test_recover_stale_processing_keeps_recent_task():
    import Bot.daemons as daemons

    toc = {
        "chapters": [
            {
                "file": "Chapter 0001.md",
                "status": "processing",
                "processing_started_at": time.time(),
            }
        ]
    }

    changed = daemons._recover_stale_processing(toc)

    assert changed is False
    assert toc["chapters"][0]["status"] == "processing"


def test_ai_provider_legacy_list_migrates_to_provider_schema(tmp_path, monkeypatch):
    import json
    import ai_client

    providers_path = tmp_path / "ai_providers.json"
    providers_path.write_text(
        json.dumps([{"name": "old", "base_url": "https://example.test", "model_name": "legacy-model"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_client, "PROVIDERS_JSON", providers_path)
    monkeypatch.delenv("AI_API_KEY", raising=False)

    cfg = ai_client.load_providers()

    assert isinstance(cfg, dict)
    assert cfg["providers"][0]["model"] == "legacy-model"
    assert "model_name" not in cfg["providers"][0]
    assert cfg["providers"][0]["enabled"] is True
    assert cfg["providers"][0]["priority"] == 1


def test_dashboard_api_requires_auth():
    import importlib.util

    app_path = ENGINE_DIR / "Dashboard" / "app.py"
    spec = importlib.util.spec_from_file_location("dashboard_app_for_test", app_path)
    dashboard_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard_app)

    client = dashboard_app.app.test_client()

    assert client.get("/api/novels").status_code == 401
    assert client.post("/api/scan").status_code == 401
    assert client.post("/api/crawl", json={}).status_code == 401


def test_69shuba_relative_urls_are_normalized():
    from plugins.site_69shuba import Plugin69Shuba

    plugin = Plugin69Shuba()

    assert plugin._normalize_url(
        "/txt/48360/12345",
        "https://www.69shuba.cx/book/48360/",
    ) == "https://www.69shuba.com/txt/48360/12345"



def test_chapter_order_normalizes_newest_first():
    from plugins.base_plugin import normalize_chapter_order

    chapters = [
        {"title": "第1072章 搜刮", "url": "https://example.test/txt/1072"},
        {"title": "第1071章 巡查", "url": "https://example.test/txt/1071"},
        {"title": "第1070章 差一点", "url": "https://example.test/txt/1070"},
    ]

    ordered = normalize_chapter_order(chapters)

    assert [c["title"] for c in ordered] == ["第1070章 差一点", "第1071章 巡查", "第1072章 搜刮"]


def test_text_site_route_blocks_only_images(tmp_path):
    from source_manager import SourceManager

    config_dir = tmp_path / "Dashboard" / "data"
    config_dir.mkdir(parents=True)
    (config_dir / "crawl_sites.json").write_text(
        '{"sites":[{"id":"textsite","catalog_url":"https://novel.example/top/","content_type":"text"}]}',
        encoding="utf-8",
    )
    manager = SourceManager(str(tmp_path))
    captured = {}

    class FakePage:
        def route(self, pattern, handler):
            captured["pattern"] = pattern
            captured["handler"] = handler

    class FakeRequest:
        def __init__(self, resource_type):
            self.resource_type = resource_type

    class FakeRoute:
        def __init__(self, resource_type):
            self.request = FakeRequest(resource_type)
            self.action = None

        def abort(self):
            self.action = "abort"

        def continue_(self):
            self.action = "continue"

    manager._route_text_site_images(FakePage(), "https://novel.example/book/1", "textsite")

    assert captured["pattern"] == "**/*"
    for resource_type, expected in [("image", "abort"), ("stylesheet", "continue"), ("font", "continue"), ("script", "continue")]:
        route = FakeRoute(resource_type)
        captured["handler"](route)
        assert route.action == expected



def test_json_plugin_extracts_metadata_and_cover_url():
    from plugins.json_plugin import JsonPlugin

    plugin = JsonPlugin({"id": "demo", "name": "Demo Source"})
    plugin._fetch = lambda url: """
    <html><head>
      <meta property="og:title" content="Demo Novel - Demo Site" />
      <meta name="description" content="A long enough demo description for the crawler metadata parser." />
      <meta property="og:image" content="/covers/demo.jpg" />
    </head><body><span class="author">作者：Demo Author</span></body></html>
    """

    metadata = plugin.get_metadata("https://example.test/book/1/")

    assert metadata["title"] == "Demo Novel"
    assert metadata["author"] == "Demo Author"
    assert metadata["description"].startswith("A long enough demo")
    assert metadata["cover_url"] == "https://example.test/covers/demo.jpg"
    assert metadata["source_id"] == "demo"


def test_uukanshu_plugin_parses_metadata_toc_chapter_and_detects_cloudflare():
    import pytest
    from plugins.site_uukanshu import CloudflareBlocked, PluginUUKanshu

    plugin = PluginUUKanshu()
    pages = {
        "https://uukanshu.cc/book/1/": """
        <html><head>
          <meta property="og:title" content="Demo Book - UU看书" />
          <meta name="description" content="这是一本用于测试的小说简介，长度足够用于元数据解析。" />
          <meta property="og:image" content="/cover/demo.jpg" />
        </head><body>
          <div class="info"><p>作者：Demo Author</p></div>
          <ul id="chapterList">
            <li><a href="/book/1/2.html">第2章 后来</a></li>
            <li><a href="/book/1/1.html">第1章 开始</a></li>
          </ul>
        </body></html>
        """,
        "https://uukanshu.cc/book/1/1.html": """
        <html><body><div id="contentbox">
          <p>第一章正文开始，这里是一段足够长的正文内容，用来确认章节解析器能够提取正文。</p>
          <script>bad()</script><a href="/book/1/2.html">下一章</a>
        </div></body></html>
        """,
    }
    plugin._fetch = lambda url: pages[plugin._normalize_url(url)]

    metadata = plugin.get_metadata("https://www.uukanshu.cc/book/1/")
    toc = plugin.get_toc("https://uukanshu.cc/book/1/")
    chapter = plugin.get_chapter(toc[0]["url"])

    assert metadata["title"] == "Demo Book"
    assert metadata["author"] == "Demo Author"
    assert metadata["cover_url"] == "https://uukanshu.cc/cover/demo.jpg"
    assert [item["title"] for item in toc] == ["第1章 开始", "第2章 后来"]
    assert "第一章正文开始" in chapter
    assert "下一章" not in chapter
    with pytest.raises(CloudflareBlocked):
        if plugin._is_cloudflare_challenge("<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>"):
            raise CloudflareBlocked("blocked")

def test_exporter_ebook_convert_env_prefers_distro_python_packages(monkeypatch, tmp_path):
    import novel_exporter

    captured = {}
    monkeypatch.setattr(novel_exporter.shutil, "which", lambda name: "/usr/bin/ebook-convert")

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}

    monkeypatch.setattr(novel_exporter.subprocess, "run", fake_run)

    novel_exporter._run_ebook_convert(tmp_path / "in.epub", tmp_path / "out.pdf")

    assert captured["cmd"] == ["ebook-convert", str(tmp_path / "in.epub"), str(tmp_path / "out.pdf")]
    assert captured["env"]["PYTHONPATH"].split(":")[0] == "/usr/lib/python3/dist-packages"
    assert captured["env"]["QTWEBENGINE_DISABLE_SANDBOX"] == "1"

def test_save_crawl_metadata_writes_json_and_cover_file(tmp_path, monkeypatch):
    import json
    from source_manager import SourceManager

    manager = SourceManager(str(tmp_path))
    monkeypatch.setattr(manager, "_download_cover", lambda cover_url, novel_dir: "cover.jpg")
    novel_dir = tmp_path / "Source_Split" / "demo"
    novel_dir.mkdir(parents=True)

    manager._save_crawl_metadata(
        novel_dir,
        {"title": "Demo", "cover_url": "https://example.test/cover.jpg"},
        "https://example.test/book/1/",
        "demo-site",
    )

    metadata = json.loads((novel_dir / "metadata.json").read_text(encoding="utf-8"))

    assert metadata["title"] == "Demo"
    assert metadata["cover_file"] == "cover.jpg"
    assert metadata["source_url"] == "https://example.test/book/1/"
    assert metadata["source_id"] == "demo-site"
    assert "crawled_at" in metadata

def test_exporter_rich_markdown_embeds_assets_and_styles(tmp_path):
    import io
    import zipfile
    from PIL import Image
    from novel_exporter import create_cbz, create_epub

    novel_dir = tmp_path / "rich_novel"
    image_dir = novel_dir / "images"
    image_dir.mkdir(parents=True)
    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(image_buffer, format="PNG")
    png_bytes = image_buffer.getvalue()
    figure = image_dir / "figure.png"
    cover = novel_dir / "cover.png"
    figure.write_bytes(png_bytes)
    cover.write_bytes(png_bytes)
    chapter = novel_dir / "Chapter 0001_vi.md"
    chapter.write_text(
        """# Chương 1

![Hình minh họa](images/figure.png)

| Chất | Công thức |
|---|---|
| Nước | H₂O |
| Glucose | C₆H₁₂O₆ |

Inline math: $E=mc^2$

$$\\frac{a}{b}$$
""",
        encoding="utf-8",
    )

    epub_path = tmp_path / "rich.epub"
    cbz_path = tmp_path / "rich.cbz"
    create_epub("rich", "Rich", "Tester", cover, [chapter], epub_path)
    create_cbz("rich", [chapter], cbz_path)

    with zipfile.ZipFile(epub_path) as zf:
        names = zf.namelist()
        chapter_html = zf.read("EPUB/chap_0000.xhtml").decode("utf-8")
        css = zf.read("EPUB/style/nav.css").decode("utf-8")

    assert "EPUB/images/figure.png" in names
    assert "EPUB/cover.png" in names
    assert "<table>" in chapter_html
    assert "arithmatex" in chapter_html
    assert "images/figure.png" in chapter_html
    assert "Noto Serif CJK" in css
    assert "border-collapse" in css
    assert "max-width: 100%" in css

    with zipfile.ZipFile(cbz_path) as zf:
        assert "images/0001_figure.png" in zf.namelist()

def test_crawl_pipeline_init_uses_metadata_and_scans_five_chapters(tmp_path, monkeypatch):
    import json
    import stage5_git_push
    from pipeline_manager import PipelineManager
    from source_manager import SourceManager

    split_dir = tmp_path / "Source_Split" / "crawl_demo"
    split_dir.mkdir(parents=True)
    (tmp_path / "Output").mkdir()
    (split_dir / "cover.jpg").write_bytes(b"fake-cover")
    (split_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Demo Crawl",
                "author": "Demo Author",
                "description": "Metadata synopsis",
                "source_name": "Demo Source",
                "source_url": "https://example.test/book/1",
                "cover_file": "cover.jpg",
                "kind": "Fantasy,Action",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for idx in range(1, 8):
        (split_dir / f"Chapter {idx:04d}.md").write_text(f"# 第{idx}章\n\n内容{idx}", encoding="utf-8")

    monkeypatch.setattr(stage5_git_push, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        PipelineManager,
        "_build_initial_entity_seed",
        lambda self, files: {"characters": {}, "glossary": {}, "pronouns": {}, "seen_files": [p.name for p in files]},
    )

    manager = SourceManager(str(tmp_path))

    assert manager.init_novel_from_split("crawl_demo") is True

    out_dir = tmp_path / "Output" / "crawl_demo"
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    toc = json.loads((out_dir / "State" / "toc.json").read_text(encoding="utf-8"))
    seed = json.loads((out_dir / "State" / "init_entity_review.json").read_text(encoding="utf-8"))

    assert "# Demo Crawl" in readme
    assert "**Tác giả:** Demo Author" in readme
    assert "**Nguồn:** Demo Source" in readme
    assert "https://example.test/book/1" in readme
    assert "Metadata synopsis" in readme
    assert toc["source_type"] == "crawl"
    assert toc["metadata"]["title"] == "Demo Crawl"
    assert len(toc["chapters"]) == 7
    assert seed["source_type"] == "crawl"
    assert seed["scan_limit"] == 5
    assert seed["scan_chapter_count"] == 5
    assert len(seed["seen_files"]) == 5


def test_stage3_refiner_rejects_missing_segment(monkeypatch, tmp_path):
    import pytest
    import stage3_ai_refiner
    import ai_client

    context_pack = {
        "translation_config": {"translation_goal": {"style": "test", "anti_goals": []}},
        "raw_segments": [{"id": 1, "text": "# 第一章"}, {"id": 2, "text": "正文"}],
        "locked_dictionary": {},
        "suggested_dictionary": {},
        "pronouns_addressing": {},
    }
    monkeypatch.setattr(
        ai_client,
        "call_ai_checked_with_meta",
        lambda *args, **kwargs: (
            '{"refined_segments":[{"id":1,"refined_translation":"# Chương 1"}],"story_timeline":{},"new_entities":[],"relationships":[]}',
            None,
            {"provider": "test", "mode": "online"},
        ),
    )

    with pytest.raises(Exception, match="Thiếu segment id"):
        stage3_ai_refiner.run("demo", context_pack, str(tmp_path))

def test_pipeline_stage1_gate_blocks_stage2(monkeypatch, tmp_path):
    from pipeline_manager import PipelineManager
    import stage1_entity_review
    import stage2_context_pack

    raw_dir = tmp_path / "Source_Split" / "gate_demo"
    out_dir = tmp_path / "Output" / "gate_demo"
    raw_dir.mkdir(parents=True)
    (raw_dir / "Chapter 0001.md").write_text("# 第一章\n\n正文", encoding="utf-8")

    called = {"stage2": False}
    monkeypatch.setattr(stage1_entity_review, "run", lambda *args, **kwargs: {"characters": []})

    def fail_if_called(*args, **kwargs):
        called["stage2"] = True
        raise AssertionError("Stage 2 must not run when Stage 1 gate fails")

    monkeypatch.setattr(stage2_context_pack, "run", fail_if_called)

    ok, err = PipelineManager("gate_demo", str(raw_dir), str(out_dir)).process_chapter("Chapter 0001.md")

    assert ok is False
    assert "Stage 1" in err
    assert called["stage2"] is False


def test_pipeline_stage4_gate_blocks_stage5(monkeypatch, tmp_path):
    import json
    from pipeline_manager import PipelineManager
    import stage1_entity_review
    import stage2_context_pack
    import stage3_ai_refiner
    import stage4_post_process
    import stage5_git_push

    raw_dir = tmp_path / "Source_Split" / "gate_demo"
    out_dir = tmp_path / "Output" / "gate_demo"
    state_dir = out_dir / "State"
    raw_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    (raw_dir / "Chapter 0001.md").write_text("# 第一章\n\n正文", encoding="utf-8")
    (state_dir / "translation_config.json").write_text('{"translation_goal":{"style":"test","anti_goals":[]}}', encoding="utf-8")
    (state_dir / "toc.json").write_text(json.dumps({"chapters": [{"file": "Chapter 0001.md", "status": "pending"}]}), encoding="utf-8")
    (state_dir / "story_timeline.json").write_text("[]", encoding="utf-8")

    context_pack = {
        "translation_config": {"translation_goal": {"style": "test", "anti_goals": []}},
        "story_timeline": [],
        "locked_dictionary": {"characters": {}, "glossary": {}},
        "suggested_dictionary": {"characters": {}, "glossary": {}},
        "relationships_graph": [],
        "pronouns_addressing": {},
        "translation_memory_hits": [],
        "raw_segments": [{"id": 1, "text": "# 第一章"}, {"id": 3, "text": "正文"}],
    }
    ai_output = {
        "refined_segments": [{"id": 1, "refined_translation": "# Chương 1"}, {"id": 3, "refined_translation": "Chính văn"}],
        "story_timeline": {},
        "new_entities": [],
        "relationships": [],
    }
    called = {"stage5": False}
    monkeypatch.setattr(stage1_entity_review, "run", lambda *args, **kwargs: {"characters": {}, "glossary": {}, "pronouns": {}})
    monkeypatch.setattr(stage2_context_pack, "run", lambda *args, **kwargs: context_pack)
    monkeypatch.setattr(stage3_ai_refiner, "run", lambda *args, **kwargs: ai_output)
    monkeypatch.setattr(stage4_post_process, "run", lambda *args, **kwargs: True)

    def fail_if_called(*args, **kwargs):
        called["stage5"] = True
        raise AssertionError("Stage 5 must not run when Stage 4 artifact gate fails")

    monkeypatch.setattr(stage5_git_push, "run", fail_if_called)

    ok, err = PipelineManager("gate_demo", str(raw_dir), str(out_dir)).process_chapter("Chapter 0001.md")

    assert ok is False
    assert "Stage 4" in err
    assert called["stage5"] is False


def test_qc_locked_dictionary_is_hard_error():
    from qc_checker import QCChecker

    context_pack = {
        "raw_segments": [{"id": 1, "text": "赵奇来了"}],
        "locked_dictionary": {"characters": {"赵奇": "Triệu Kỳ"}, "glossary": {}},
    }
    ai_output = {"refined_segments": [{"id": 1, "refined_translation": "Triệu Đơn tới."}]}

    result = QCChecker(context_pack, ai_output).check()

    assert result["passed"] is False
    assert any("Triệu Kỳ" in err for err in result["errors"])

