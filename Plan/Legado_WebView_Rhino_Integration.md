# Legado WebView/Rhino Integration Deep Dive

Date: 2026-06-21

## Goal

Integrate Legado book sources into Translator Engine while keeping the current JSON/Python crawler stable. The target is compatibility with Legado-style source packs, not just adding a JavaScript evaluator. Legado rules combine URL templating, CSS/XPath/JSONPath extraction, regex transforms, Rhino JavaScript, app-provided `java.*` APIs, cookies, source/book/chapter variables, and Android WebView flows.

The current plugin API is intentionally small:

- `search(keyword)`
- `get_metadata(novel_url)`
- `get_toc(novel_url)`
- `get_chapter(chapter_url)`

The Legado integration should be an adapter behind that API. Existing `JsonPlugin`, Python site plugins, `crawl_sites.json`, and the already fixed crawl pipeline should remain the default path for current sources.

## Verified Local Inputs

Local Legado source is available at:

- `/sdcard/My Agent/Translator Engine/temp/legado-qt-main/legado-qt-main`

Important files studied:

- `modules/rhino/src/main/java/com/script/rhino/RhinoScriptEngine.kt`
- `modules/rhino/src/main/java/com/script/rhino/RhinoClassShutter.kt`
- `modules/rhino/src/main/java/com/script/rhino/RhinoWrapFactory.kt`
- `modules/rhino/src/main/java/com/script/rhino/RhinoContext.kt`
- `modules/rhino/lib/rhino-1.7.14.jar`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/RuleAnalyzer.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSoup.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSonPath.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByXPath.kt`
- `app/src/main/java/io/legado/app/help/JsExtensions.kt`
- `app/src/main/java/io/legado/app/help/http/BackstageWebView.kt`
- `app/src/main/java/io/legado/app/help/webView/WebJsExtensions.kt`
- `app/src/main/java/io/legado/app/model/SharedJsScope.kt`
- `app/src/main/java/io/legado/app/data/entities/BaseSource.kt`
- `app/src/main/java/io/legado/app/data/entities/BookSource.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/SearchRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/BookInfoRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/TocRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/ContentRule.kt`

Local environment checked:

- Chromium exists: `Chromium 147.0.7727.137`.
- Node.js exists: `v22.22.3`.
- Java is not installed yet: `java: command not found`.
- OpenJDK 17 and 21 packages are available from apt.
- Rhino jar already exists in the Legado source tree: `modules/rhino/lib/rhino-1.7.14.jar`.

Conclusion: do not use Node.js as the JS runtime for Legado compatibility. Use the same Rhino jar after installing OpenJDK. Node/V8 semantics and Legado's host object model are not the same.

## What Legado Actually Does

### Book Source Schema

`BookSource.kt` defines a source with these important fields:

- identity: `bookSourceUrl`, `bookSourceName`, `bookSourceGroup`, `bookSourceType`
- HTTP/runtime: `header`, `enabledCookieJar`, `concurrentRate`, `jsLib`
- login: `loginUrl`, `loginUi`, `loginCheckJs`
- source rules: `searchUrl`, `ruleSearch`, `ruleBookInfo`, `ruleToc`, `ruleContent`, `ruleExplore`
- cover/content extras: `coverDecodeJs`, `imageDecode`, `webJs`, `sourceRegex`, `replaceRegex`

`BaseSource.kt` exposes source state and APIs to JavaScript:

- dynamic header parsing via plain JSON or `@js:`/`<js>`
- login information and login headers
- persisted source variable via `putVariable/getVariable`
- key-value storage via `source.put/source.get`
- `jsLib` shared scope refresh
- `evalJS` with bindings: `java`, `source`, `baseUrl`, `cookie`, `cache`

Translator Engine must store imported source records separately from `crawl_sites.json`, for example under `Dashboard/data/legado/`, because Legado source records are richer and should not be flattened into simple CSS selector configs.

### Rule Models

Legado source rule classes map directly to plugin methods:

- `SearchRule`: `bookList`, `name`, `author`, `intro`, `kind`, `lastChapter`, `updateTime`, `bookUrl`, `coverUrl`, `wordCount`, `checkKeyWord`
- `BookInfoRule`: `init`, `name`, `author`, `intro`, `kind`, `lastChapter`, `updateTime`, `coverUrl`, `tocUrl`, `wordCount`, `downloadUrls`
- `TocRule`: `preUpdateJs`, `chapterList`, `chapterName`, `chapterUrl`, `formatJs`, `isVolume`, `isVip`, `isPay`, `updateTime`, `nextTocUrl`
- `ContentRule`: `content`, `subContent`, `title`, `nextContentUrl`, `webJs`, `sourceRegex`, `replaceRegex`, `imageStyle`, `imageDecode`, `payAction`, `callBackJs`

Minimum useful adapter behavior:

- `search(keyword)`: evaluate `searchUrl`, fetch result, apply `ruleSearch.bookList`, map each item with `name/author/bookUrl/coverUrl/...`.
- `get_metadata(novel_url)`: fetch detail page, optionally run `ruleBookInfo.init`, map metadata and cover.
- `get_toc(novel_url)`: resolve `tocUrl`, fetch it, apply `chapterList/chapterName/chapterUrl`, support `nextTocUrl`, then normalize chapter order.
- `get_chapter(chapter_url)`: fetch chapter, optionally WebView, apply `content/subContent/title/nextContentUrl/replaceRegex`, return text.

### AnalyzeUrl Flow

`AnalyzeUrl.kt` is not a plain HTTP wrapper. Its order matters:

1. Execute leading/interleaved `@js:` or `<js>` blocks. Later URL text can reference `@result`.
2. Replace templates such as `{{...}}`, page variables, key variables.
3. Parse URL options after the first JSON option comma.
4. Execute option `js`, whose return value can rewrite the final URL.
5. Fetch by HTTP or WebView depending on `webView`.
6. Execute `bodyJs` on the response body.

Supported URL options include:

- `method`
- `headers`
- `body`
- `charset`
- `retry`
- `type`
- `webView`
- `webJs`
- `bodyJs`
- `dnsIp`
- `js`
- `serverID`
- `webViewDelayTime`

For HTTP, Legado merges source headers, login headers, temporary option headers, and cookies. For `enabledCookieJar`, response cookies are stored back into the source cookie jar. For WebView, Legado can either load a URL directly or first POST with HTTP and then load the returned HTML into WebView.

Translator Engine needs a `LegadoAnalyzeUrl` layer instead of calling `requests.get()` directly from each method.

### AnalyzeRule Flow

`AnalyzeRule.kt` is the core rule pipeline. Rules are split into `SourceRule` segments and each segment can run in a different mode:

- Default/JSoup-like selector mode
- `@CSS:` selector mode
- XPath mode via `@XPath:` or leading `/`
- JSONPath mode via `@Json:` or JSON content / `$.` / `$[` rules
- Regex mode through `##pattern##replacement`
- Rhino JS mode through `@js:` or `<js>`
- WebJS mode through WebView-specific patterns

Important behavior that must be preserved:

- Rule splitting must ignore separators inside strings, brackets, parentheses, regex bodies, and `{{...}}`. `RuleAnalyzer.kt` must be ported; naive `.split('@')`, `.split('&&')`, or `.split('||')` will break real sources.
- `@put:{...}` writes variables and `@get:{...}` reads them.
- `{{...}}` inline expressions can evaluate JS or nested rules.
- `##...##...` regex replacement supports group references `$1` to `$99`; `###` means first-match/replace-first style behavior.
- Results can be plain strings, lists, DOM elements, JSON objects, Rhino `NativeObject`, or Java/Kotlin maps.
- URL extraction must normalize against the current `redirectUrl`, not always the original URL.

### JSoup/CSS/XPath/JSONPath

`AnalyzeByJSoup.kt` supports more than CSS selectors:

- Chain mode: `class.foo@tag.a@href`, `id.xxx`, `tag.xxx`, `text.xxx`, `children`, `text`, `ownText`, `html`, `all`.
- CSS mode: `@CSS:selector@attr`.
- Indexing: `[0]`, `[-1]`, ranges, reverse ranges, negation, old style `.0:10:2` forms.
- Multi-rule operators: `&&`, `||`, `%%`.

`AnalyzeByJSonPath.kt` uses Jayway JsonPath semantics, not a tiny ad hoc subset. Python should eventually use a real JSONPath implementation or delegate JSONPath to Java. `jsonpath_ng` is not currently installed.

`AnalyzeByXPath.kt` uses JXDocument/JXNode style behavior. Python can use `lxml`, but output coercion should match Legado: element text, html, attributes, and list/object returns.

### Rhino Runtime

`RhinoScriptEngine.kt` configures Rhino this way:

- language version: ES6
- interpreted mode enabled
- `RhinoClassShutter` installed
- `RhinoWrapFactory` installed
- instruction observer threshold: 10000
- maximum interpreter stack depth: 1000
- script run permission checked through `allowScriptRun`
- continuation support for suspend-like host calls
- unwrap support for `Wrapper`, `ConsString`, `Undefined`

`RhinoContext.kt` adds:

- cancellation checks
- recursion guard at 10 nested levels

`RhinoClassShutter.kt` and `RhinoWrapFactory.kt` are security-critical. They block or refuse wrapping dangerous Java classes and packages including process, runtime, file, nio file, reflection, `sun`, `org.mozilla`, internal script classes, Android sensitive classes, and database classes.

Translator Engine should not expose a generic Java class bridge. The Java subprocess must expose only explicit host objects and functions required by Legado rules.

### Shared JS Scope

`SharedJsScope.kt` implements `jsLib` caching:

- If `jsLib` is JSON object, each URL/script value is fetched/cached and evaluated into a shared scope.
- Else raw `jsLib` text is evaluated directly.
- Shared scopes are LRU-cached by md5 of `jsLib`.
- Scope is prevented from implicit extension.

Translator Engine needs one shared Rhino scope per source/jsLib hash, then per-call bindings should use that shared scope as prototype.

### JavaScript Bindings

`AnalyzeRule.evalJS` exposes:

- `java`: current `AnalyzeRule` object implementing `JsExtensions`
- `cookie`: `CookieStore`
- `cache`: `CacheManager`
- `source`
- `book`
- `chapter`
- `result`
- `baseUrl`
- `title`
- `src`
- `nextChapterUrl`
- `rssArticle`
- `fromBookInfo`

`AnalyzeUrl.evalJS` exposes:

- `java`: current `AnalyzeUrl`
- `baseUrl`
- `cookie`
- `cache`
- `page`
- `key`
- `speakText`
- `speakSpeed`
- `book`
- `source`
- `result`
- `infoMap`

`JsExtensions.kt` exposes many host APIs. Phase 1 does not need every method, but the bridge should be designed to add them without changing JS semantics.

High-priority APIs:

- `ajax(url, timeout?)`
- `ajaxAll`, `ajaxTestAll`
- `connect(url, header?, timeout?)`
- `get`, `head`, `post`
- `webView`, `webViewGetSource`, `webViewGetOverrideUrl`
- `getCookie(tag, key?)`
- `importScript(path)`
- `cacheFile(url, saveTime)`
- `base64Encode/base64Decode`
- `hexEncode/hexDecode`
- `md5Encode`, sha helpers if present in source rules
- `timeFormat/timeFormatUTC`
- `encodeURI`
- `htmlFormat`
- `t2s/s2t`
- `getWebViewUA`
- `toast/log/logType/randomUUID`
- `source.put/source.get/source.putVariable/source.getVariable`

Lower-priority but needed for full compatibility:

- AES/symmetric crypto helpers
- sign/encrypt/decrypt wrappers
- zip/rar/7z helpers
- font obfuscation helpers
- manual browser/login flows
- image/content byte decode functions

### Android WebView Replacement

`BackstageWebView.kt` gives the exact behavior to emulate:

- Default JS when no script is supplied: `document.documentElement.outerHTML`.
- If no JS and delay is zero, default delay is 900 ms.
- `blockNetworkImage = true` in Android WebView.
- User-Agent comes from headers or app config.
- Can use cache-first mode.
- Saves cookies on page finish.
- Runs injected JS and retries evaluation up to 30 times when result is null/empty.
- Can sniff resource URL by `sourceRegex` or override URL by `overrideUrlRegex`.
- SSL errors are ignored by Android implementation.

Translator Engine replacement:

- Use Playwright Chromium, not Android WebView.
- Use persistent contexts per source/domain to preserve cookies/localStorage/sessionStorage.
- Use mobile Chromium profile by default for Legado sources.
- Pass `--no-sandbox --disable-setuid-sandbox` in Termux/PRoot.
- Block images only for text sources, matching the existing user requirement; do not globally block CSS/scripts/fonts because image/HTML comic sources may be added later.
- Implement default result as `document.documentElement.outerHTML`.
- Implement `webViewDelayTime` and the default 900 ms wait.
- Implement retry loop for JS evaluation.
- Implement `sourceRegex` by observing network responses/requests and matching resource URLs.
- Implement `overrideUrlRegex` by observing navigation/request URLs.
- Synchronize cookies both ways between Python HTTP cookie jar and Playwright context.

`WebJsExtensions.kt` injects async wrappers into WebView:

- `run`
- `ajaxAwait`
- `connectAwait`
- `getAwait`
- `headAwait`
- `postAwait`
- `webViewAwait`
- `webViewGetSourceAwait`
- crypto await helpers
- `downloadFileAwait`
- `readTxtFileAwait`
- `importScriptAwait`
- `getStringAwait`

Playwright can emulate this with `page.expose_function()` plus an injected JS bridge that returns Promises. Native calls should go back to the same `LegadoRuntimeContext` so cookies/cache/source variables remain consistent.

## Proposed Module Design

Add a package:

- `Script/legado/__init__.py`
- `Script/legado/models.py`
- `Script/legado/source_importer.py`
- `Script/legado/runtime.py`
- `Script/legado/analyze_url.py`
- `Script/legado/rule_analyzer.py`
- `Script/legado/rule_engine.py`
- `Script/legado/selectors.py`
- `Script/legado/webview.py`
- `Script/legado/rhino_bridge.py`
- `Script/legado/state_store.py`
- `Script/plugins/legado_plugin.py`
- `Script/legado/rhino/LegadoRhinoBridge.java`

### `LegadoPlugin`

One instance per imported source. It implements the current `BasePlugin` API:

- `source_id`: stable id, for example `legado:<hash(bookSourceUrl)>`
- `source_name`: `bookSourceName`
- `search(keyword)`: Legado search flow
- `get_metadata(novel_url)`: Legado book info flow
- `get_toc(novel_url)`: Legado toc flow
- `get_chapter(chapter_url)`: Legado content flow

`PluginManager` should load these after JSON configs and before/after Python overrides depending on priority. Recommended priority:

1. JSON plugins from `crawl_sites.json`
2. Imported Legado plugins
3. Python `site_*.py` plugins as explicit overrides

### `LegadoRuntimeContext`

Holds all mutable state for one operation:

- source record
- book metadata object
- chapter object
- current URL, base URL, redirect URL
- page/key variables
- cookies
- cache
- source/book/chapter variable maps
- Playwright profile id
- Rhino shared scope key
- debug artifact directory

This context is passed to `AnalyzeUrl`, `AnalyzeRule`, WebView, and Rhino. Avoid global state except persistent stores.

### `LegadoStateStore`

Persist under `Dashboard/data/legado/state/`:

- `sources/<source_hash>.json`: source variables, login headers, misc source cache
- `cookies/<source_hash>.json`: source cookie jar
- `books/<book_hash>.json`: book variable map and metadata cache
- `profiles/<source_hash>/`: Playwright persistent browser profile
- `debug/<timestamp-source>/`: screenshots/html on failures

Rules from `RuleDataInterface.kt`:

- small variables under 10000 characters can live in JSON maps
- large variables should be stored separately, addressed by key

### `LegadoRhinoBridge`

A long-lived Java subprocess is preferred over spawning Java per script. Protocol: JSON Lines over stdin/stdout.

Request shape:

```json
{"id":"...","op":"eval","sourceId":"...","scopeKey":"...","bindings":{},"script":"...","timeoutMs":8000}
```

Response shape:

```json
{"id":"...","ok":true,"result":{},"logs":[],"statePatch":{}}
```

Required Java-side behavior:

- use Rhino 1.7.14 jar from local Legado source or vendored copy
- set ES6/interpreted mode
- install class shutter/wrap restrictions equivalent to Legado
- keep LRU shared scopes for `jsLib`
- expose explicit host objects only
- timeout scripts and fail closed
- serialize Rhino values into JSON-compatible values

Host API calls that require Python HTTP/WebView should either:

- be implemented in Java by making callback requests over the same JSON-RPC channel, or
- be exposed as synchronous Java methods backed by a local request dispatcher thread.

Do not expose `Packages`, arbitrary Java class access, filesystem, process, or reflection.

### `PlaywrightWebView`

Use Python Playwright sync API initially because the current crawler is sync.

Behavior:

- context key: source id or domain id
- launch persistent context with Chromium executable detection already used in `source_manager.py`
- args: `--no-sandbox`, `--disable-setuid-sandbox`
- default mobile viewport and UA if no source header overrides it
- route images only when `source.bookSourceType == 0` or imported support flag says text source
- `goto(..., wait_until="domcontentloaded")`, then controlled delay/wait
- default JS: `document.documentElement.outerHTML`
- evaluate custom `webJs`
- inject WebJS bridge before custom JS when needed
- save screenshot/html to debug folder on selector miss or JS failure

Keep browser lifecycle reusable. Creating a new browser for every chapter will be too slow.

### `LegadoRuleAnalyzer`

Port `RuleAnalyzer.kt` logic, not a naive parser. Required split behavior:

- separators: `@`, `&&`, `||`, `%%`, `##`
- ignore separators inside JS strings, regexes, brackets, parentheses, braces, and `{{...}}`
- detect `@js:` and `<js>...</js>` blocks
- detect WebJS blocks
- parse `@put:{...}` and `@get:{...}`
- parse source rule mode: default/CSS/XPath/JSON/Regex/JS/WebJS

This module is the foundation for reliable TOC and chapter ordering. Incorrect splitting is the main reason Legado source compatibility collapses.

## Execution Flows

### Search

1. Load source by id.
2. Build context with `key=keyword`, `page=1`.
3. `AnalyzeUrl(searchUrl).getStrResponse()`.
4. `AnalyzeRule(body, baseUrl=response.url).getElements(ruleSearch.bookList)`.
5. For each result element, evaluate fields through `AnalyzeRule` with that element as content.
6. Normalize `bookUrl` against response redirect URL.
7. Return list compatible with current dashboard/search usage.

### Metadata and Cover

1. Fetch novel URL through `AnalyzeUrl`.
2. If `ruleBookInfo.init`, evaluate it first and use its output as new content/context.
3. Extract `name`, `author`, `intro`, `kind`, `lastChapter`, `updateTime`, `wordCount`, `coverUrl`, `tocUrl`.
4. If `coverDecodeJs` exists, pass cover bytes/url through Rhino before saving.
5. Return metadata with `cover_url` so existing `_save_crawl_metadata()` can download it.

### TOC

1. Resolve detail page first if needed.
2. Resolve `ruleBookInfo.tocUrl`; fallback to novel URL.
3. Execute `ruleToc.preUpdateJs` if present.
4. Fetch TOC through `AnalyzeUrl`.
5. Extract `chapterList`.
6. For each chapter element, extract `chapterName`, `chapterUrl`, `isVolume`, `isVip`, `isPay`, `updateTime`.
7. Execute `formatJs` if present.
8. Follow `nextTocUrl` until empty, repeated, or max pages reached.
9. Deduplicate by normalized URL.
10. Use existing `normalize_chapter_order()` as a final safety net, but prefer preserving Legado extraction order unless clearly reversed.

### Chapter Content

1. Fetch chapter via `AnalyzeUrl`; use WebView if source/rule says so.
2. If `ContentRule.webJs` exists, run rendered WebView path.
3. Extract `title`, `content`, `subContent`.
4. Follow `nextContentUrl` for paginated chapters with loop guard.
5. Apply `replaceRegex` after extraction.
6. If image source/content, preserve image URLs and do not block images.
7. Return text for text source; later add structured image chapters for comic/image source.

## Compatibility Levels

Each imported source should be classified. This allows the UI/crawler to skip unsupported sources instead of failing during crawl.

- `native`: CSS/XPath/basic JSON/regex only, no Rhino/WebView required.
- `rhino`: uses `@js:`, `<js>`, `{{JS}}`, `jsLib`, `java.*`, or dynamic headers.
- `webview`: requires `webView`, `webJs`, `sourceRegex`, `overrideUrlRegex`, or browser login.
- `partial`: mostly supported but uses lower-priority APIs such as AES/zip/font helpers.
- `unsupported`: requires Android-only UI, manual verification, app callbacks, payment, or APIs not implemented.

Initial UI should default to `native`, `rhino`, and `webview` only after the corresponding runtime is enabled.

## Security Rules

Required from day one:

- No generic Java class access.
- No filesystem writes except controlled cache/debug directories.
- No process execution from JS.
- No reflection.
- Script timeout per eval.
- Recursion limit matching Legado's 10 nested runtime calls.
- Network calls go through `AnalyzeUrl` only, so headers/cookies/rate limits are applied.
- Log JS source id and operation when a script fails, but avoid dumping cookies or login info.

## Implementation Phases

### Phase 1: Importer and Native Rule Engine

Deliverables:

- `source_importer.py` for Legado JSON packs and `yuedu://booksource/importonline?src=...` links.
- `models.py` dataclasses for `BookSource`, `SearchRule`, `BookInfoRule`, `TocRule`, `ContentRule`.
- `rule_analyzer.py` port of Legado splitting semantics.
- `rule_engine.py` with JSoup-like chain mode, CSS mode, XPath via `lxml`, regex, URL normalization.
- `LegadoPlugin` for `native` sources.
- Tests with local HTML/JSON fixtures.

Do not install Java for this phase.

### Phase 2: Playwright WebView

Deliverables:

- `webview.py` persistent Chromium context manager.
- rendered HTML fetch for URL option `webView`.
- custom `webJs` evaluation.
- image blocking only for text sources.
- debug artifacts: screenshot + HTML on miss/failure.
- cookie sync HTTP <-> Playwright.

This can reuse the Chromium launch logic already present in `source_manager.py`.

### Phase 3: Rhino Bridge

Prerequisite:

- Install OpenJDK 17 or 21.
- Use local `rhino-1.7.14.jar` from Legado source or copy it into a controlled vendor path.

Deliverables:

- `LegadoRhinoBridge.java` subprocess.
- Python `rhino_bridge.py` JSON-RPC client.
- ES6/interpreted Rhino setup.
- class shutter/wrap restrictions.
- bindings for AnalyzeRule and AnalyzeUrl contexts.
- high-priority `java.*`, `source.*`, `cache.*`, `cookie.*` APIs.
- tests for `@js:result.replace(...)`, `{{...}}`, `java.ajax`, `source.put/get`, `jsLib` shared scope.

### Phase 4: Full Legado Expansion

Deliverables:

- JSONPath parity, either Java delegated or Python package.
- AES/sign/crypto APIs.
- login flows and `startBrowserAwait` debug/manual mode.
- `nextTocUrl`/`nextContentUrl` hardening.
- source concurrency/rate limiter from `concurrentRate`.
- image/comic content support.
- wider live-source test matrix.

## Testing Plan

Unit tests:

- Rule splitting: `@`, `&&`, `||`, `%%`, `##`, nested `{{...}}`, JS strings, regex literals.
- JSoup-like chain selectors and index/range forms.
- Regex replacement and group interpolation.
- URL option parsing and `{{...}}` replacement.
- Variable store precedence: chapter -> book -> rule data -> source.

Integration tests with fixtures:

- Search result HTML.
- Book info + cover URL.
- Reversed/newest-first TOC.
- Multi-page TOC through `nextTocUrl`.
- Chapter with `nextContentUrl`.
- WebView-rendered fixture page.
- Rhino JS fixture with `jsLib`.

Live smoke tests:

- Run only a small selected set of currently valid sources.
- Save debug HTML/screenshot on failure.
- Avoid treating anti-bot failures as parser failures.

## Immediate Next Step

Start with Phase 1. It gives useful compatibility without installing Java and creates the parser/runtime shape that Phase 2 and Phase 3 need.

Recommended first code changes:

1. Add `Script/legado/models.py` and `source_importer.py`.
2. Add `rule_analyzer.py` with tests ported from observed Legado parser behavior.
3. Add `rule_engine.py` for native selectors and regex.
4. Add `Script/plugins/legado_plugin.py` but keep it disabled unless a source is classified `native`.
5. Extend `PluginManager` to load `Dashboard/data/legado/sources.json` when present.

Only after these pass should Java/Rhino be installed and wired in. Rhino depends on the same parser/state model, so implementing it first would produce a runtime that still cannot interpret real Legado rules correctly.
