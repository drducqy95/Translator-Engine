import json
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR / "Script"))


def test_legado_rule_split_ignores_js_strings_and_templates():
    from legado.rule_analyzer import split_text

    rule = "class.book@text##A@B##C&&@CSS:.x[data='a&&b']@href||tag.a@href"

    assert split_text(rule, ["||"]) == ["class.book@text##A@B##C&&@CSS:.x[data='a&&b']@href", "tag.a@href"]
    assert split_text("tag.a@href@text", ["@"]) == ["tag.a", "href", "text"]
    assert split_text("{{java.ajax('a@b')}}@text", ["@"]) == ["{{java.ajax('a@b')}}", "text"]


def test_legado_rule_engine_extracts_css_chain_and_urls():
    from legado.rule_engine import LegadoRuleEngine

    html = """
    <div class="book"><a href="/book/1"><span class="name">Demo</span></a><span class="author">Alice</span></div>
    <div class="book"><a href="/book/2"><span class="name">Other</span></a><span class="author">Bob</span></div>
    """
    engine = LegadoRuleEngine("https://example.test/top/")
    items = engine.get_elements(html, "class.book")

    assert len(items) == 2
    assert engine.get_string(items[0], "class.name@text") == "Demo"
    assert engine.get_string(items[0], "tag.a@href") == "https://example.test/book/1"
    assert engine.get_string(html, "@CSS:.book:nth-of-type(2) .author@text") == "Bob"


def test_legado_rule_engine_jsonpath_subset():
    from legado.rule_engine import LegadoRuleEngine

    data = {"data": [{"name": "A"}, {"name": "B"}]}
    engine = LegadoRuleEngine()

    assert engine.get_string_list(data, "$.data[*].name") == ["A", "B"]
    assert engine.get_string(data, "$.data[1].name") == "B"


def test_legado_importer_classifies_native_and_rhino_sources(tmp_path):
    from legado.source_importer import parse_sources_text, write_sources_cache

    sources = parse_sources_text(json.dumps([
        {
            "bookSourceUrl": "https://example.test",
            "bookSourceName": "Native",
            "searchUrl": "https://example.test/search/{{key}}",
            "ruleSearch": {"bookList": "class.book", "name": "class.name@text"},
        },
        {
            "bookSourceUrl": "https://js.example.test",
            "bookSourceName": "JS",
            "searchUrl": "@js:'https://js.example.test'",
        },
    ]))
    records = write_sources_cache(sources, tmp_path / "sources.json")

    assert len(records) == 2
    assert records[0]["_plugin_id"].startswith("legado:")
    assert records[0]["_classification"]["support_level"] == "native"
    assert records[1]["_classification"]["support_level"] == "rhino"


def test_plugin_manager_loads_legado_source_cache(tmp_path):
    from legado.source_importer import parse_sources_text, write_sources_cache
    from plugin_manager import PluginManager

    script_plugins = tmp_path / "Script" / "plugins"
    script_plugins.mkdir(parents=True)
    data_dir = tmp_path / "Dashboard" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "crawl_sites.json").write_text('{"sites":[]}', encoding="utf-8")

    sources = parse_sources_text(json.dumps([
        {
            "bookSourceUrl": "https://example.test",
            "bookSourceName": "Native Legado",
            "searchUrl": "https://example.test/search/{{key}}",
            "ruleSearch": {"bookList": "class.book", "name": "class.name@text", "bookUrl": "tag.a@href"},
        }
    ]))
    write_sources_cache(sources, data_dir / "legado" / "sources.json")

    manager = PluginManager(str(tmp_path))
    plugins = manager.list_plugins()

    assert len(plugins) == 1
    assert plugins[0]["id"].startswith("legado:")
    assert plugins[0]["name"] == "Native Legado"



def test_legado_plugin_uses_playwright_webview_for_webview_url(monkeypatch, tmp_path):
    import plugins.legado_plugin as legado_plugin

    captured = {}

    class FakeWebView:
        def __init__(self, base_dir, source_id, text_source=True):
            captured["base_dir"] = str(base_dir)
            captured["source_id"] = source_id
            captured["text_source"] = text_source

        def fetch(self, url, headers=None, script=None, delay_ms=900, bridge_handlers=None, cookie_state=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["script"] = script
            captured["delay_ms"] = delay_ms
            captured["bridge_handlers"] = bridge_handlers
            captured["cookie_state"] = cookie_state
            return '<div id="content">Rendered</div>'

    monkeypatch.setattr(legado_plugin, "PlaywrightWebView", FakeWebView)
    plugin = legado_plugin.LegadoPlugin({
        "bookSourceUrl": "https://example.test",
        "bookSourceName": "WebView Source",
        "bookSourceType": 0,
        "header": '{"User-Agent":"Demo UA"}',
        "ruleContent": {"content": "@CSS:#content@text"},
    }, base_dir=str(tmp_path))

    body = plugin.get_chapter('https://example.test/ch/1,{"webView":true,"webJs":"document.body.innerHTML","webViewDelayTime":123}')

    assert body == "Rendered"
    assert captured["url"] == "https://example.test/ch/1"
    assert captured["headers"]["User-Agent"] == "Demo UA"
    assert captured["script"] == "document.body.innerHTML"
    assert captured["delay_ms"] == 123
    assert captured["text_source"] is True
    assert "getStringAwait" in captured["bridge_handlers"]
    assert captured["cookie_state"] == {}



def _rhino_bridge_or_skip():
    import pytest
    from legado.rhino_bridge import RhinoBridge

    bridge = RhinoBridge(ENGINE_DIR)
    if not bridge.available:
        pytest.skip("Java/Javac/Rhino jar is not available")
    return bridge


def test_rhino_bridge_executes_js_and_blocks_runtime_access():
    from legado.rhino_bridge import RhinoBridgeError

    bridge = _rhino_bridge_or_skip()
    try:
        assert bridge.eval("java.md5Encode(result)", bindings={"result": "abc"}, scope_key="pytest") == "900150983cd24fb0d6963f7d28e17f72"
        assert bridge.eval("source.put('k','v'); source.get('k')", scope_key="pytest") == "v"
        try:
            bridge.eval("Packages.java.lang.Runtime.getRuntime().exec('id')", scope_key="pytest", timeout_ms=1000)
        except RhinoBridgeError:
            pass
        else:
            raise AssertionError("Rhino bridge allowed Runtime access")
    finally:
        bridge.close()


def test_rule_engine_uses_rhino_for_js_rule():
    from legado.rule_engine import LegadoRuleEngine

    bridge = _rhino_bridge_or_skip()
    try:
        engine = LegadoRuleEngine("https://example.test", rhino=bridge, bindings={"tag": "pytest"}, scope_key="pytest-rule")
        assert engine.get_string("<p>Demo</p>", "@js:result.replace(/<[^>]+>/g,'').trim()") == "Demo"
        assert engine.get_string("ignored", "@CSS:{{'.name'}}@text") == ""
    finally:
        bridge.close()


def test_legado_plugin_supports_rhino_content_rule(monkeypatch):
    import plugins.legado_plugin as legado_plugin

    plugin = legado_plugin.LegadoPlugin({
        "bookSourceUrl": "https://rhino.example.test",
        "bookSourceName": "Rhino Source",
        "ruleContent": {"content": "@js:result.replace(/<[^>]+>/g,'').trim()"},
    }, base_dir=str(ENGINE_DIR))
    if not plugin.supported_now:
        import pytest
        pytest.skip("Rhino runtime unavailable")
    monkeypatch.setattr(plugin, "_fetch", lambda request: "<div>Demo Rhino</div>")

    assert plugin.get_chapter("https://rhino.example.test/ch/1") == "Demo Rhino"
    if plugin.rhino:
        plugin.rhino.close()



def test_rhino_bridge_persists_source_state_between_evals():
    bridge = _rhino_bridge_or_skip()
    try:
        assert bridge.eval("source.put('persist','ok')", scope_key="pytest-state") == "ok"
        assert bridge.eval("source.get('persist')", scope_key="pytest-state") == "ok"
        assert bridge.source_state["persist"] == "ok"
    finally:
        bridge.close()


def test_rhino_bridge_java_ajax_against_local_http_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    bridge = _rhino_bridge_or_skip()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ajax-ok")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/demo"
    try:
        assert bridge.eval(f"java.ajax('{url}')", scope_key="pytest-http") == "ajax-ok"
        assert bridge.eval(f"java.get('{url}').body()", scope_key="pytest-http") == "ajax-ok"
    finally:
        server.shutdown()
        bridge.close()



def test_rhino_java_get_string_callbacks_into_rule_engine():
    from legado.rule_engine import LegadoRuleEngine

    bridge = _rhino_bridge_or_skip()
    try:
        html = '<div class="book"><span class="name">Demo</span><span class="name">Other</span></div>'
        engine = LegadoRuleEngine("https://example.test", rhino=bridge, bindings={"tag": "pytest"}, scope_key="pytest-callback")
        assert engine.get_string(html, "@js:java.getString('class.name@text')") == "Demo"
        assert engine.get_string(html, "@js:java.getStringList('class.name@text').join('|')") == "Demo|Other"
    finally:
        bridge.close()



def test_playwright_webview_bridge_script_exposes_legado_await_helpers():
    from legado.webview import PlaywrightWebView

    script = PlaywrightWebView.bridge_script()

    assert "ajaxAwait" in script
    assert "getStringAwait" in script
    assert "startBrowserAwait" in script
    assert "upLoginData" in script
    assert "setContent" in script
    assert "__legadoBridgeRequest" in script
    assert "document.documentElement.outerHTML" in script


def test_playwright_webview_fetch_preserves_empty_cookie_state(monkeypatch, tmp_path):
    import sys
    import types
    from legado.webview import PlaywrightWebView

    class FakeManager:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakePage:
        def route(self, *args, **kwargs):
            pass

        def goto(self, *args, **kwargs):
            pass

        def wait_for_timeout(self, *args, **kwargs):
            pass

        def evaluate(self, script):
            return "ok"

    class FakeContext:
        def new_page(self):
            return FakePage()

        def cookies(self):
            return [{"name": "sid", "value": "stored"}]

        def close(self):
            pass

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: FakeManager()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(PlaywrightWebView, "_launch_context", lambda self, playwright, headers: FakeContext())

    cookies = {}
    body = PlaywrightWebView(tmp_path, "cookie-ref").fetch("https://example.test", cookie_state=cookies, delay_ms=0)

    assert body == "ok"
    assert cookies == {"sid": "stored"}

def test_legado_plugin_webjs_get_string_handler_uses_rule_engine(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://webjs.example.test",
        "bookSourceName": "WebJS Source",
        "ruleContent": {"content": "@CSS:#content@text"},
    }, base_dir=str(tmp_path))
    handlers = plugin._webjs_handlers("https://webjs.example.test/ch/1")

    assert handlers["getStringAwait"]("#content@text", '<div id="content">Rendered Text</div>') == "Rendered Text"



def test_legado_plugin_http_fetch_persists_cookies_between_requests(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from types import SimpleNamespace
    from plugins.legado_plugin import LegadoPlugin

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Cookie", ""))
            self.send_response(200)
            if self.path == "/set":
                self.send_header("Set-Cookie", "sid=pycookie; Path=/")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    plugin = LegadoPlugin({"bookSourceUrl": "http://127.0.0.1", "bookSourceName": "Cookie Source"}, base_dir=str(tmp_path))
    try:
        plugin._fetch(SimpleNamespace(method="GET", url=f"http://127.0.0.1:{server.server_port}/set", headers={}, body=None, charset=None, webview=False, web_js=None))
        plugin._fetch(SimpleNamespace(method="GET", url=f"http://127.0.0.1:{server.server_port}/check", headers={}, body=None, charset=None, webview=False, web_js=None))
    finally:
        server.shutdown()

    assert plugin.cookie_state["sid"] == "pycookie"
    assert any("sid=pycookie" in cookie for cookie in seen[1:])


def test_rhino_java_ajax_persists_cookie_state_between_requests():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    bridge = _rhino_bridge_or_skip()
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Cookie", ""))
            self.send_response(200)
            if self.path == "/set":
                self.send_header("Set-Cookie", "rsid=rhino; Path=/")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bridge.eval(f"java.ajax('http://127.0.0.1:{server.server_port}/set')", scope_key="pytest-cookie")
        bridge.eval(f"java.ajax('http://127.0.0.1:{server.server_port}/check')", scope_key="pytest-cookie")
    finally:
        server.shutdown()
        bridge.close()

    assert bridge.cookie_state["rsid"] == "rhino"
    assert any("rsid=rhino" in cookie for cookie in seen[1:])



def test_rhino_bridge_crypto_helpers_sha_hmac_aes():
    bridge = _rhino_bridge_or_skip()
    try:
        assert bridge.eval("java.sha1Encode('abc')", scope_key="pytest-crypto") == "a9993e364706816aba3e25717850c26c9cd0d89d"
        assert bridge.eval("java.sha256Encode('abc')", scope_key="pytest-crypto") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assert bridge.eval("java.md5Encode16('abc')", scope_key="pytest-crypto") == "3cd24fb0d6963f7d"
        assert bridge.eval("java.hmacSha256('key','abc')", scope_key="pytest-crypto") == "9c196e32dc0175f86f4b1cb89289d6619de6bee699e4c378e68309ed97a1a6ab"
        encrypted = bridge.eval("java.encryptBase64('1234567890123456','abcdef1234567890','hello')", scope_key="pytest-crypto")
        assert encrypted
        assert bridge.eval(f"java.decryptStr('1234567890123456','abcdef1234567890','{encrypted}')", scope_key="pytest-crypto") == "hello"
        encrypted_hex = bridge.eval("java.encryptHex('1234567890123456','abcdef1234567890','hello')", scope_key="pytest-crypto")
        assert bridge.eval(f"java.decryptStr('1234567890123456','abcdef1234567890','{encrypted_hex}')", scope_key="pytest-crypto") == "hello"
    finally:
        bridge.close()




def test_legado_plugin_seeds_book_and_chapter_state_for_rhino_rules(monkeypatch, tmp_path):
    import pytest
    from plugins.legado_plugin import LegadoPlugin

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "https://state-source.example.test",
        "bookSourceName": "State Source",
        "ruleBookInfo": {
            "name": "class.name@text",
            "author": "class.author@text",
            "intro": "class.intro@text",
        },
        "ruleContent": {
            "content": "@js:book.name + '|' + book.author + '|' + chapter.url",
        },
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    monkeypatch.setattr(
        plugin,
        "_fetch_url",
        lambda url: '<div class="name">Seed Book</div><div class="author">Seed Author</div><p class="intro">Intro</p>',
    )
    monkeypatch.setattr(plugin, "_fetch_content_url", lambda url: "<div>ignored</div>")
    try:
        metadata = plugin.get_metadata("https://state-source.example.test/book/1")
        assert metadata["title"] == "Seed Book"
        assert plugin.book_state["name"] == "Seed Book"
        assert plugin.book_state["author"] == "Seed Author"
        text = plugin.get_chapter("https://state-source.example.test/ch/1")
        assert text == "Seed Book|Seed Author|https://state-source.example.test/ch/1"
        assert plugin.chapter_state["url"] == "https://state-source.example.test/ch/1"
    finally:
        if plugin.rhino:
            plugin.rhino.close()

    second = LegadoPlugin(record, base_dir=str(tmp_path))
    try:
        assert second.book_state["name"] == "Seed Book"
        assert second.chapter_state["url"] == "https://state-source.example.test/ch/1"
    finally:
        if second.rhino:
            second.rhino.close()

def test_legado_plugin_persists_cookie_state_to_disk(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    record = {"bookSourceUrl": "https://persist.example.test", "bookSourceName": "Persist Source"}
    first = LegadoPlugin(record, base_dir=str(tmp_path))
    first._store_cookie_header("sid=persisted; Path=/")

    second = LegadoPlugin(record, base_dir=str(tmp_path))

    assert second.cookie_state["sid"] == "persisted"
    assert second._headers_with_cookies({})["Cookie"] == "sid=persisted"



def _prepare_tmp_rhino_base(tmp_path):
    import shutil
    java_src = ENGINE_DIR / "Script" / "legado" / "rhino" / "LegadoRhinoBridge.java"
    rhino_jar = ENGINE_DIR / "temp" / "legado-qt-main" / "legado-qt-main" / "modules" / "rhino" / "lib" / "rhino-1.7.14.jar"
    target_dir = tmp_path / "Script" / "legado" / "rhino"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(java_src, target_dir / "LegadoRhinoBridge.java")
    if rhino_jar.exists():
        shutil.copy(rhino_jar, target_dir / "rhino-1.7.14.jar")


def test_legado_plugin_persists_rhino_source_state_to_disk(monkeypatch, tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    record = {
        "bookSourceUrl": "https://rhino-persist.example.test",
        "bookSourceName": "Rhino Persist Source",
        "ruleContent": {"content": "@js:source.put('persist','ok'); source.get('persist')"},
    }
    _prepare_tmp_rhino_base(tmp_path)
    first = LegadoPlugin(record, base_dir=str(tmp_path))
    if not first.supported_now:
        import pytest
        pytest.skip("Rhino runtime unavailable")
    monkeypatch.setattr(first, "_fetch", lambda request: "ignored")

    assert first.get_chapter("https://rhino-persist.example.test/ch/1") == "ok"
    if first.rhino:
        first.rhino.close()

    second = LegadoPlugin(record, base_dir=str(tmp_path))
    if not second.supported_now:
        import pytest
        pytest.skip("Rhino runtime unavailable")
    try:
        assert second.rhino.source_state["persist"] == "ok"
        assert second.rhino.eval("source.get('persist')", scope_key=second.source_id) == "ok"
    finally:
        if second.rhino:
            second.rhino.close()



def test_legado_rule_engine_jsonpath_deep_filter_slice_and_quoted_keys():
    from legado.rule_engine import LegadoRuleEngine

    data = {
        "store": {
            "book": [
                {"title": "A", "price": 5, "kind-name": "x"},
                {"title": "B", "price": 12, "kind-name": "y"},
                {"title": "C", "price": 20, "kind-name": "x"},
            ],
            "nested": {"book": [{"title": "D", "price": 1}]},
        }
    }
    engine = LegadoRuleEngine()

    assert engine.get_string_list(data, "$..title") == ["A", "B", "C", "D"]
    assert engine.get_string_list(data, "$.store.book[1:].title") == ["B", "C"]
    assert engine.get_string_list(data, "$.store.book[?(@.price >= 10)].title") == ["B", "C"]
    assert engine.get_string_list(data, "$.store.book[?(@['kind-name'] == 'x')].title") == ["A", "C"]
    assert engine.get_string_list(data, "$.store['book'][0]['kind-name']") == ["x"]



def test_legado_plugin_webjs_http_handlers_return_response_objects(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(201)
            self.send_header("X-Demo", "yes")
            self.end_headers()
            self.wfile.write(b"get-body")

        def do_HEAD(self):
            self.send_response(204)
            self.send_header("X-Demo", "head")
            self.end_headers()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(202)
            self.send_header("X-Demo", "post")
            self.end_headers()
            self.wfile.write(b"post:" + body)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    plugin = LegadoPlugin({"bookSourceUrl": "http://127.0.0.1", "bookSourceName": "WebJS HTTP"}, base_dir=str(tmp_path))
    handlers = plugin._webjs_handlers(f"http://127.0.0.1:{server.server_port}/page")
    try:
        url = f"http://127.0.0.1:{server.server_port}/demo"
        assert handlers["ajaxAwait"](url) == "get-body"
        response = handlers["getAwait"](url)
        assert response.body == "get-body"
        assert response["statusCode"] == 201
        assert response.header("X-Demo") == "yes"
        assert str(response) == "get-body"
        head = handlers["headAwait"](url)
        assert head.statusCode == 204
        assert head.body == ""
        post = handlers["postAwait"](url, "payload")
        assert post.statusCode == 202
        assert post.body == "post:payload"
    finally:
        server.shutdown()



def test_legado_classifier_marks_dynamic_js_fields_as_rhino():
    from legado.models import classify_source

    classified = classify_source({
        "bookSourceUrl": "https://dynamic.example.test",
        "bookSourceName": "Dynamic JS",
        "searchUrl": "/search,{'js':'url'}".replace("'", '"'),
        "ruleToc": {"formatJs": "result"},
        "ruleContent": {"imageDecode": "result"},
        "jsLib": "var token = 1;",
    })

    assert classified["needs_js"] is True
    assert classified["support_level"] == "rhino"


def test_analyze_url_executes_option_js(tmp_path):
    import pytest
    from legado.analyze_url import AnalyzeUrl
    from legado.models import BookSource
    from legado.rhino_bridge import RhinoBridge

    _prepare_tmp_rhino_base(tmp_path)
    bridge = RhinoBridge(str(tmp_path))
    if not bridge.available:
        pytest.skip("Rhino runtime unavailable")
    try:
        source = BookSource.from_dict({"bookSourceUrl": "https://example.test/root/"})
        request = AnalyzeUrl(source, source.bookSourceUrl, rhino=bridge, scope_key="pytest-url").build(
            "chapter/old,{'js':'url.replace(\\\"old\\\",\\\"new\\\")'}".replace("'", '"')
        )
        assert request.url == "https://example.test/root/chapter/new"
        assert request.option_js
    finally:
        bridge.close()


def test_legado_plugin_applies_body_js_before_content_rules(tmp_path):
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<html><body><div id="content">raw</div></body></html>')

        def log_message(self, format, *args):
            return

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "http://127.0.0.1",
        "bookSourceName": "Body JS",
        "jsLib": "var enabled = true;",
        "ruleContent": {"content": "@CSS:#content@text"},
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/chapter,{{\"bodyJs\":\"result.replace('raw','changed')\"}}"
        assert plugin.get_chapter(url) == "changed"
    finally:
        server.shutdown()
        if plugin.rhino:
            plugin.rhino.close()


def test_legado_plugin_applies_cover_decode_js_in_metadata(tmp_path):
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b'<html><head><title>Cover Demo</title></head>'
                b'<body><h1>Cover Demo</h1><img class="cover" src="/cover-raw.jpg"></body></html>'
            )

        def log_message(self, format, *args):
            return

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "http://127.0.0.1",
        "bookSourceName": "Cover Decode",
        "coverDecodeJs": "result.replace('raw','decoded')",
        "ruleBookInfo": {
            "name": "tag.h1@text",
            "coverUrl": "class.cover@src",
        },
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/book"
        metadata = plugin.get_metadata(url)
        assert metadata["title"] == "Cover Demo"
        assert metadata["cover_url"] == f"http://127.0.0.1:{server.server_port}/cover-decoded.jpg"
    finally:
        server.shutdown()
        if plugin.rhino:
            plugin.rhino.close()



def test_legado_plugin_applies_book_info_init_rule(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://init.example.test",
        "bookSourceName": "Init Rule",
        "ruleBookInfo": {
            "init": "class.detail",
            "name": "class.name@text",
            "author": "class.author@text",
            "kind": "class.kind@text",
        },
    }, base_dir=str(tmp_path))
    html = """
    <html><body>
      <div class="outside"><span class="name">Wrong</span></div>
      <section class="detail">
        <h1 class="name">Right Name</h1>
        <span class="author">Right Author</span>
        <span class="kind">Fantasy</span><span class="kind">Action</span>
      </section>
    </body></html>
    """
    plugin._fetch_url = lambda url: html

    metadata = plugin.get_metadata("https://init.example.test/book/1")

    assert metadata["title"] == "Right Name"
    assert metadata["author"] == "Right Author"
    assert metadata["kind"] == "Fantasy,Action"


def test_legado_plugin_follows_next_toc_url_and_formats_titles(tmp_path):
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            pages = {
                "/toc1": b'<div class="ch"><a href="/c1">One</a></div><a class="next" href="/toc2">next</a>',
                "/toc2": b'<div class="ch"><a href="/c2">Two</a></div>',
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(pages.get(self.path, pages["/toc1"]))

        def log_message(self, format, *args):
            return

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "http://127.0.0.1",
        "bookSourceName": "Paged Toc",
        "ruleToc": {
            "chapterList": "class.ch",
            "chapterName": "tag.a@text",
            "chapterUrl": "tag.a@href",
            "nextTocUrl": "class.next@href",
            "formatJs": "index + '. ' + title",
        },
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        chapters = plugin.get_toc(f"http://127.0.0.1:{server.server_port}/toc1")
        assert chapters == [
            {"title": "1. One", "url": f"http://127.0.0.1:{server.server_port}/c1"},
            {"title": "2. Two", "url": f"http://127.0.0.1:{server.server_port}/c2"},
        ]
    finally:
        server.shutdown()
        if plugin.rhino:
            plugin.rhino.close()


def test_legado_plugin_follows_next_content_url_and_appends_subcontent_title(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            pages = {
                "/c1": b'<h1>Chapter A</h1><div class="content">part one</div><div class="note">note one</div><a class="next" href="/c1p2">next</a>',
                "/c1p2": b'<h1>Chapter A Continued</h1><div class="content">part two</div><div class="note">note two</div>',
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(pages.get(self.path, pages["/c1"]))

        def log_message(self, format, *args):
            return

    plugin = LegadoPlugin({
        "bookSourceUrl": "http://127.0.0.1",
        "bookSourceName": "Paged Content",
        "ruleContent": {
            "title": "tag.h1@text",
            "content": "class.content@text",
            "subContent": "class.note@text",
            "nextContentUrl": "class.next@href",
        },
    }, base_dir=str(tmp_path))
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        text = plugin.get_chapter(f"http://127.0.0.1:{server.server_port}/c1")
        assert text == (
            "Chapter A\n\npart one\n\nnote one\n\n"
            "Chapter A Continued\n\npart two\n\nnote two"
        )
    finally:
        server.shutdown()



def test_legado_rule_engine_supports_put_get_variables():
    from legado.rule_engine import LegadoRuleEngine

    state = {}
    engine = LegadoRuleEngine("https://vars.example.test", bindings={"sourceState": state})
    html = '<div class="name">Stored Name</div><div class="other">Other</div>'

    assert engine.get_string(html, '@put:{"saved":"class.name@text"}@get:{saved}') == "Stored Name"
    assert state["saved"] == "Stored Name"
    assert engine.get_string(html, '@get:{saved}') == "Stored Name"


def test_legado_plugin_seeds_login_cookies_from_source_header_and_file(tmp_path):
    import json
    from plugins.legado_plugin import LegadoPlugin

    data_dir = tmp_path / "Dashboard" / "data" / "legado"
    data_dir.mkdir(parents=True)
    (data_dir / "cookies.json").write_text(json.dumps({
        "https://cookie.example.test": "file_sid=file; file_token=abc"
    }), encoding="utf-8")

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://cookie.example.test",
        "bookSourceName": "Cookie Source",
        "header": '{"Cookie":"header_sid=header"}',
    }, base_dir=str(tmp_path))

    assert plugin.cookie_state["header_sid"] == "header"
    assert plugin.cookie_state["file_sid"] == "file"
    header = plugin._headers_with_cookies({})["Cookie"]
    assert "header_sid=header" in header
    assert "file_sid=file" in header


def test_legado_plugin_set_login_cookies_persists_to_state(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    record = {"bookSourceUrl": "https://manual-cookie.example.test", "bookSourceName": "Manual Cookie"}
    first = LegadoPlugin(record, base_dir=str(tmp_path))
    first.set_login_cookies("sid=manual; token=xyz")

    second = LegadoPlugin(record, base_dir=str(tmp_path))

    assert second.cookie_state["sid"] == "manual"
    assert second.cookie_state["token"] == "xyz"
    assert "sid=manual" in second._headers_with_cookies({})["Cookie"]



def test_legado_classifier_keeps_login_ui_sources_supported():
    from legado.models import classify_source

    classified = classify_source({
        "bookSourceUrl": "https://login-ui.example.test",
        "bookSourceName": "Login UI",
        "loginUi": "[{\"name\":\"cookie\"}]",
        "loginCheckJs": "cookie.get('sid') == 'ok'",
    })

    assert classified["support_level"] == "partial"
    assert "manual_login" in classified["reasons"]


def test_legado_plugin_login_fetches_url_and_persists_cookies(tmp_path):
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Set-Cookie", "sid=login-ok; Path=/")
            self.end_headers()
            self.wfile.write(b"logged")

        def log_message(self, format, *args):
            return

    _prepare_tmp_rhino_base(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    record = {
        "bookSourceUrl": "http://127.0.0.1",
        "bookSourceName": "Login Fetch",
        "loginUrl": f"http://127.0.0.1:{server.server_port}/login",
        "loginCheckJs": "cookie.get('sid') == 'login-ok'",
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    try:
        assert plugin.login() is True
        assert plugin.cookie_state["sid"] == "login-ok"
    finally:
        server.shutdown()
        if plugin.rhino:
            plugin.rhino.close()

    second = LegadoPlugin(record, base_dir=str(tmp_path))
    try:
        assert second.cookie_state["sid"] == "login-ok"
    finally:
        if second.rhino:
            second.rhino.close()


def test_legado_plugin_webjs_login_handlers_store_cookies_and_content(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://web-login.example.test",
        "bookSourceName": "Web Login",
    }, base_dir=str(tmp_path))
    handlers = plugin._webjs_handlers("https://web-login.example.test/login")

    assert handlers["upLoginData"]("sid=web; token=abc") is True
    assert plugin.cookie_state["sid"] == "web"
    assert plugin.cookie_state["token"] == "abc"
    assert handlers["setContent"]("done") == "done"
    assert plugin.source_state["content"] == "done"
    assert "startBrowserAwait" in handlers


def test_legado_plugin_login_url_webview_updates_login_cookies(monkeypatch, tmp_path):
    import plugins.legado_plugin as legado_plugin

    captured = {}

    class FakeWebView:
        def __init__(self, base_dir, source_id, text_source=True):
            captured["base_dir"] = str(base_dir)
            captured["source_id"] = source_id
            captured["text_source"] = text_source

        def fetch(self, url, headers=None, script=None, delay_ms=900, bridge_handlers=None, cookie_state=None):
            captured["url"] = url
            captured["script"] = script
            captured["delay_ms"] = delay_ms
            bridge_handlers["upLoginData"]("sid=wv; token=123")
            cookie_state["ctx"] = "persisted"
            return "<html>login-ok</html>"

    monkeypatch.setattr(legado_plugin, "PlaywrightWebView", FakeWebView)
    record = {
        "bookSourceUrl": "https://webview-login.example.test",
        "bookSourceName": "WebView Login",
        "bookSourceType": 0,
        "loginUrl": 'https://webview-login.example.test/login,{"webView":true,"webJs":"document.body.innerHTML","webViewDelayTime":42}',
    }
    plugin = legado_plugin.LegadoPlugin(record, base_dir=str(tmp_path))

    assert plugin.login() is True
    assert captured["url"] == "https://webview-login.example.test/login"
    assert captured["script"] == "document.body.innerHTML"
    assert captured["delay_ms"] == 42
    assert captured["text_source"] is True
    assert plugin.cookie_state["sid"] == "wv"
    assert plugin.cookie_state["token"] == "123"
    assert plugin.cookie_state["ctx"] == "persisted"

    second = legado_plugin.LegadoPlugin(record, base_dir=str(tmp_path))

    assert second.cookie_state["sid"] == "wv"
    assert second.cookie_state["ctx"] == "persisted"

def test_legado_plugin_login_ui_defaults_feed_login_url_js(tmp_path):
    import json
    import pytest
    from plugins.legado_plugin import LegadoPlugin

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "https://login-ui-js.example.test",
        "bookSourceName": "Login UI JS",
        "loginUi": json.dumps([
            {"name": "username", "type": "text", "default": "alice"},
            {"name": "password", "type": "password", "default": "secret"},
            {"name": "mode", "type": "select", "chars": ["fast", "slow"]},
            {"name": "submit", "type": "button", "action": "login()"},
        ]),
        "loginUrl": """
        function login(){
          var data = JSON.parse(source.getLoginInfoMap());
          java.upLoginData('sid=' + data.username + '; token=' + data.password + '; mode=' + data.mode);
        }
        """,
        "loginCheckJs": "cookie.get('sid') == 'alice' && cookie.get('token') == 'secret' && cookie.get('mode') == 'fast'",
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    try:
        assert plugin.login() is True
        assert plugin.cookie_state["sid"] == "alice"
        assert plugin.cookie_state["token"] == "secret"
        assert plugin.cookie_state["mode"] == "fast"
        assert json.loads(plugin.source_state["loginInfo"])["username"] == "alice"
    finally:
        if plugin.rhino:
            plugin.rhino.close()

    second = LegadoPlugin(record, base_dir=str(tmp_path))
    try:
        assert json.loads(second.source_state["loginInfo"])["password"] == "secret"
    finally:
        if second.rhino:
            second.rhino.close()



def test_legado_login_ui_dynamic_up_ui_data_updates_login_info(tmp_path):
    import json
    import pytest
    from plugins.legado_plugin import LegadoPlugin

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "https://login-dynamic.example.test",
        "bookSourceName": "Login Dynamic",
        "loginUi": json.dumps([
            {"name": "username", "type": "text", "default": "default-user"},
            {"name": "mode", "type": "toggle", "chars": ["short", "long"], "default": "short"},
        ]),
        "loginUrl": """
        function login(){
          var data = JSON.parse(source.getLoginInfoMap());
          java.upLoginData('sid=' + data.username + '; mode=' + data.mode);
        }
        """,
        "loginCheckJs": "cookie.get('sid') == 'dynamic-user' && cookie.get('mode') == 'long'",
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    try:
        plugin.rhino.eval("java.upUiData({username:'dynamic-user', mode:'long'}); java.reLoginView(true);", scope_key=plugin.source_id)
        plugin._save_state()
        assert plugin.cache_state["javaState"]["reLoginView"] == "true"
        assert json.loads(plugin.source_state["loginInfo"])["username"] == "dynamic-user"
        assert plugin.login() is True
        assert plugin.cookie_state["sid"] == "dynamic-user"
        assert plugin.cookie_state["mode"] == "long"
    finally:
        if plugin.rhino:
            plugin.rhino.close()

def test_legado_plugin_login_ui_button_action_runs_with_login_context(tmp_path):
    import json
    import pytest
    from plugins.legado_plugin import LegadoPlugin

    _prepare_tmp_rhino_base(tmp_path)
    record = {
        "bookSourceUrl": "https://login-action.example.test",
        "bookSourceName": "Login Action",
        "loginUi": json.dumps([
            {"name": "username", "type": "text", "default": "bob"},
            {"name": "action", "type": "button", "action": "setToken()"},
            {"name": "open", "type": "button", "action": "https://login-action.example.test/open"},
        ]),
        "loginUrl": """
        function setToken(){
          var data = JSON.parse(source.getLoginInfoMap());
          java.upLoginData('sid=' + data.username + '; mode=' + (isLongClick ? 'long' : 'short'));
        }
        """,
        "loginCheckJs": "cookie.get('sid') == 'bob' && cookie.get('mode') == 'long'",
    }
    plugin = LegadoPlugin(record, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    try:
        plugin.run_login_action("action")
        assert plugin.cookie_state["mode"] == "short"
        plugin.run_login_action("action", long_click=True)
        assert plugin.check_login() is True
        assert plugin.cookie_state["mode"] == "long"
        assert plugin.run_login_action("open") == "https://login-action.example.test/open"
        assert plugin.source_state["lastBrowserUrl"] == "https://login-action.example.test/open"
    finally:
        if plugin.rhino:
            plugin.rhino.close()

def test_legado_plugin_login_check_js_reads_cookie_state(tmp_path):
    import pytest
    from plugins.legado_plugin import LegadoPlugin

    _prepare_tmp_rhino_base(tmp_path)
    plugin = LegadoPlugin({
        "bookSourceUrl": "https://login-check.example.test",
        "bookSourceName": "Login Check",
        "loginCheckJs": "cookie.get('sid') == 'ok'",
        "loginCookies": "sid=ok",
    }, base_dir=str(tmp_path))
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")
    try:
        assert plugin.check_login() is True
        plugin.set_login_cookies("sid=bad")
        assert plugin.check_login() is False
    finally:
        if plugin.rhino:
            plugin.rhino.close()



def test_rhino_bridge_import_script_from_local_file(tmp_path):
    import pytest
    from legado.rhino_bridge import RhinoBridge

    _prepare_tmp_rhino_base(tmp_path)
    script_dir = tmp_path / "libs"
    script_dir.mkdir()
    (script_dir / "demo.js").write_text("function demoValue(x){ return x + 5; }", encoding="utf-8")
    bridge = RhinoBridge(str(tmp_path))
    if not bridge.available:
        pytest.skip("Rhino runtime unavailable")
    try:
        assert bridge.eval("eval(java.importScript('libs/demo.js')); demoValue(7)", scope_key="pytest-import") == "12.0"
    finally:
        bridge.close()



def test_rhino_bridge_legado_ui_and_memory_helpers_do_not_crash(tmp_path):
    import pytest
    from legado.rhino_bridge import RhinoBridge

    _prepare_tmp_rhino_base(tmp_path)
    bridge = RhinoBridge(str(tmp_path))
    if not bridge.available:
        pytest.skip("Rhino runtime unavailable")
    try:
        script = """
        java.put('token', 'abc');
        java.toast('hi');
        java.longToast('long');
        java.setHeaders('mode=text');
        java.copyText('copied');
        java.open('explore', 'https://example.test/list', 'List');
        java.openUrl('https://example.test/open');
        java.startBrowser('https://example.test/browser', 'Browser');
        java.startBrowserAwait('https://example.test/await', 'Await');
        java.upLoginData('sid=await; token=tok');
        java.setContent('login content', 'https://base.example.test');
        java.setBaseUrl('https://base2.example.test');
        java.setRedirectUrl('https://redirect.example.test');
        java.addBook('https://book.example.test');
        java.searchBook('keyword', 'scope');
        java.refreshBookInfo();
        java.get('token') + '|' + java.getTag();
        """
        assert bridge.eval(script, bindings={"tag": "pytest-tag"}, scope_key="pytest-ui") == "abc|pytest-tag"
        java_state = bridge.cache_state.get("javaState", {})
        assert java_state["token"] == "abc"
        assert java_state["headers"] == "mode=text"
        assert java_state["clipboard"] == "copied"
        assert java_state["lastOpenUrl"] == "https://example.test/await"
        assert java_state["loginData"] == "sid=await; token=tok"
        assert java_state["content"] == "login content"
        assert java_state["baseUrl"] == "https://base2.example.test"
        assert java_state["redirectUrl"] == "https://redirect.example.test"
        assert java_state["lastAddBook"] == "https://book.example.test"
        assert java_state["lastSearchBook"] == "keyword"
        assert java_state["lastSearchScope"] == "scope"
        assert bridge.cookie_state["sid"] == "await"
        assert bridge.cookie_state["token"] == "tok"
        assert java_state["refreshBookInfo"] == "true"
    finally:
        bridge.close()


def test_rhino_bridge_legado_globals_book_chapter_and_cookie_helpers(tmp_path):
    import pytest
    from legado.rhino_bridge import RhinoBridge

    _prepare_tmp_rhino_base(tmp_path)
    bridge = RhinoBridge(str(tmp_path))
    if not bridge.available:
        pytest.skip("Rhino runtime unavailable")
    bridge.rule_callback = lambda name, args, ctx: "Rule Value" if name == "getString" else ""
    try:
        script = """
        Map('mode', 'audio');
        book.name = 'Book Name';
        book.author = 'Author Name';
        book.putVariable('mid', '123');
        chapter.title = 'Chapter One';
        chapter.url = 'https://chapter.test/1';
        cookie.setCookie('https://cookie.test', 'sid=abc');
        source.putLoginHeader('Bearer token');
        source.putLoginInfo('uid', '42');
        source.putLoginInfo('{"name":"alice"}');
        java.upUiData({name:'carol'});
        java.reLoginView(true);
        [M('mode'), S('class.name@text'), book.name, book.getVariable('mid'), chapter.title, cookie.getCookie('https://cookie.test'), source.getLoginHeader(), JSON.parse(source.getLoginInfoMap()).name, java.hexDecodeToString('6869'), java.timeFormat(1700000000000)].join('|')
        """
        value = bridge.eval(script, scope_key="pytest-legado-globals")
        parts = str(value).split("|")
        assert parts[:9] == ["audio", "Rule Value", "Book Name", "123", "Chapter One", "sid=abc", "Bearer token", "carol", "hi"]
        assert parts[9].startswith("2023-")
        assert bridge.book_state["name"] == "Book Name"
        assert bridge.book_state["mid"] == "123"
        assert bridge.chapter_state["url"] == "https://chapter.test/1"
        assert bridge.cookie_state["https://cookie.test"] == "sid=abc"
        assert bridge.cache_state["javaState"]["reLoginView"] == "true"
        assert bridge.eval("java.getSource() != null", scope_key="pytest-legado-globals") == "true"
        assert "uid" in bridge.source_state.get("loginInfo:uid", "42") or bridge.source_state["loginInfo:uid"] == "42"
    finally:
        bridge.close()

def test_rhino_bridge_cache_file_and_download_file_use_cache_state(tmp_path):
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from legado.rhino_bridge import RhinoBridge

    hits = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits["count"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"var remoteValue = 42;")

        def log_message(self, format, *args):
            return

    _prepare_tmp_rhino_base(tmp_path)
    bridge = RhinoBridge(str(tmp_path))
    if not bridge.available:
        pytest.skip("Rhino runtime unavailable")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/lib.js"
        assert bridge.eval(f"java.cacheFile('{url}')", scope_key="pytest-cache") == "var remoteValue = 42;"
        assert bridge.eval(f"java.cacheFile('{url}')", scope_key="pytest-cache") == "var remoteValue = 42;"
        path = bridge.eval(f"java.downloadFile('{url}')", scope_key="pytest-cache")
        assert str(path).startswith("cache://")
        assert bridge.eval(f"java.readTxtFile('{path}')", scope_key="pytest-cache") == "var remoteValue = 42;"
        assert hits["count"] == 1
        assert bridge.cache_state
    finally:
        server.shutdown()
        bridge.close()


def test_legado_plugin_webjs_import_script_handlers_cache_remote_and_read_local(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from plugins.legado_plugin import LegadoPlugin

    hits = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits["count"] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"function remote(){return 9;}")

        def log_message(self, format, *args):
            return

    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "local.js").write_text("function local(){return 3;}", encoding="utf-8")
    plugin = LegadoPlugin({"bookSourceUrl": "http://127.0.0.1", "bookSourceName": "WebJS Import"}, base_dir=str(tmp_path))
    handlers = plugin._webjs_handlers("http://127.0.0.1/page")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/remote.js"
        assert handlers["readTxtFileAwait"]("libs/local.js") == "function local(){return 3;}"
        assert handlers["importScriptAwait"]("libs/local.js") == "function local(){return 3;}"
        assert handlers["importScriptAwait"](url) == "function remote(){return 9;}"
        assert handlers["importScriptAwait"](url) == "function remote(){return 9;}"
        cached_path = handlers["downloadFileAwait"](url)
        assert cached_path.startswith("cache://")
        assert handlers["readTxtFileAwait"](cached_path) == "function remote(){return 9;}"
        assert hits["count"] == 1
    finally:
        server.shutdown()



def test_playwright_webview_bridge_exposes_override_url_helper():
    from legado.webview import PlaywrightWebView

    script = PlaywrightWebView.bridge_script()

    assert "webViewGetOverrideUrlAwait" in script
    assert "webViewGetOverrideUrlAwait', args.map(String)" in script


def test_legado_plugin_webjs_source_and_override_regex_handlers(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://webview-regex.example.test",
        "bookSourceName": "WebView Regex",
    }, base_dir=str(tmp_path))
    handlers = plugin._webjs_handlers("https://webview-regex.example.test/page")
    html = '<html><script>var media="https://cdn.example.test/audio.m4a";</script><a href="https://next.example.test/play">go</a></html>'

    assert handlers["webViewGetSourceAwait"](html, "", "", r'media="([^"]+)"') == "https://cdn.example.test/audio.m4a"
    assert handlers["webViewGetOverrideUrlAwait"](html, "", "", r'href="([^"]+)"') == "https://next.example.test/play"
    assert handlers["webViewGetSourceAwait"](html, "", "", r'not-found="([^"]+)"') == ""



def test_legado_plugin_content_source_regex_uses_webview_and_extracted_body(tmp_path):
    from plugins.legado_plugin import LegadoPlugin

    plugin = LegadoPlugin({
        "bookSourceUrl": "https://source-regex.example.test",
        "bookSourceName": "Content Source Regex",
        "ruleContent": {
            "webJs": "document.documentElement.outerHTML",
            "sourceRegex": r'PAYLOAD:(<div id="content">.*?</div>)',
            "content": "@CSS:#content@text",
        },
    }, base_dir=str(tmp_path))
    captured = {}

    def fake_fetch(request):
        captured["webview"] = request.webview
        captured["web_js"] = request.web_js
        return '<html><body>ignore PAYLOAD:<div id="content">extracted chapter</div></body></html>'

    plugin._fetch = fake_fetch

    assert plugin.get_chapter("https://source-regex.example.test/ch/1") == "extracted chapter"
    assert captured["webview"] is True
    assert captured["web_js"] == "document.documentElement.outerHTML"



def test_legado_plugin_supports_combined_webview_and_rhino_bodyjs(monkeypatch, tmp_path):
    import pytest
    import plugins.legado_plugin as legado_plugin

    _prepare_tmp_rhino_base(tmp_path)
    captured = {}

    class FakeWebView:
        def __init__(self, base_dir, source_id, text_source=True):
            captured["base_dir"] = base_dir
            captured["source_id"] = source_id
            captured["text_source"] = text_source

        def fetch(self, url, headers=None, script=None, delay_ms=900, bridge_handlers=None, cookie_state=None):
            captured["url"] = url
            captured["script"] = script
            captured["delay_ms"] = delay_ms
            return '<div id="content">raw combined</div>'

    monkeypatch.setattr(legado_plugin, "PlaywrightWebView", FakeWebView)
    record = {
        "bookSourceUrl": "https://combined.example.test",
        "bookSourceName": "Combined Runtime",
        "searchUrl": "https://combined.example.test/search,{\"webView\":true,\"bodyJs\":\"result\"}",
        "ruleContent": {"content": "@CSS:#content@text"},
    }
    plugin = legado_plugin.LegadoPlugin(record, base_dir=str(tmp_path))
    assert plugin.classification["support_level"] == "partial"
    assert plugin.classification["needs_js"] is True
    assert plugin.classification["needs_webview"] is True
    if not plugin.supported_now:
        pytest.skip("Rhino runtime unavailable")

    text = plugin.get_chapter(
        'https://combined.example.test/ch/1,{"webView":true,"webJs":"document.body.innerHTML","bodyJs":"result.replace(\'raw\',\'changed\')"}'
    )

    assert text == "changed combined"
    assert captured["script"] == "document.body.innerHTML"
    assert captured["url"] == "https://combined.example.test/ch/1"


def test_legado_importer_decodes_share_links_and_fetches_sources():
    from urllib.parse import quote
    from legado.source_importer import decode_importonline_link, extract_import_links, load_sources_location

    source_url = "https://example.test/bookSources.json"
    share = f'yuedu://booksource/importonline?src={quote(source_url, safe="")}'
    page = f'<html><body><a href="{share}">import</a></body></html>'
    payload = json.dumps({"bookSources": [{"bookSourceUrl": "https://demo.test", "bookSourceName": "Demo"}]})
    fetched = []

    def fetcher(url):
        fetched.append(url)
        return payload

    assert decode_importonline_link(share) == source_url
    assert extract_import_links(page) == [share]
    sources = load_sources_location(page, fetcher=fetcher)

    assert fetched == [source_url]
    assert [source.bookSourceName for source in sources] == ["Demo"]


def test_legado_importer_parses_embedded_json_from_html():
    from legado.source_importer import parse_sources_text

    html = """
    <html><script>
    window.sources = [{"bookSourceUrl":"https://embedded.test","bookSourceName":"Embedded"}];
    </script></html>
    """
    sources = parse_sources_text(html)

    assert len(sources) == 1
    assert sources[0].bookSourceUrl == "https://embedded.test"
    assert sources[0].bookSourceName == "Embedded"


def test_legado_importer_loads_local_legado_sample_pack():
    import pytest
    from legado.source_importer import load_sources_file

    sample = ENGINE_DIR / "temp" / "legado-qt-main" / "legado-qt-main" / "1776604747.json"
    if not sample.exists():
        pytest.skip("local Legado sample pack is unavailable")

    sources = load_sources_file(sample)

    assert sources
    assert any(source.bookSourceName == "哔哩哔哩" for source in sources)
