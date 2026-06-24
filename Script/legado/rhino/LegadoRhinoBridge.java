import org.mozilla.javascript.BaseFunction;
import org.mozilla.javascript.ClassShutter;
import org.mozilla.javascript.Context;
import org.mozilla.javascript.ContextFactory;
import org.mozilla.javascript.Scriptable;
import org.mozilla.javascript.ScriptableObject;
import org.mozilla.javascript.Undefined;
import org.mozilla.javascript.Wrapper;

import java.io.BufferedReader;
import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public class LegadoRhinoBridge {
    private static final int MAX_STACK_DEPTH = 1000;
    private static final long DEFAULT_TIMEOUT_MS = 8000L;
    private static final Map<String, Scriptable> SHARED_SCOPES = new HashMap<>();
    private static BufferedReader BRIDGE_IN;
    private static PrintWriter BRIDGE_OUT;

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintWriter out = new PrintWriter(System.out, true, StandardCharsets.UTF_8);
        BRIDGE_IN = in;
        BRIDGE_OUT = out;
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) {
                continue;
            }
            Map<String, Object> response = new LinkedHashMap<>();
            String id = "";
            try {
                Object parsed = Json.parse(line);
                if (!(parsed instanceof Map)) {
                    throw new IllegalArgumentException("Request must be a JSON object");
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> request = (Map<String, Object>) parsed;
                id = str(request.get("id"));
                response.put("id", id);
                Object result = eval(request);
                response.put("ok", true);
                response.put("result", result);
                response.put("state", stateFromRequest(request));
            } catch (Throwable t) {
                response.put("id", id);
                response.put("ok", false);
                response.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
            }
            out.println(Json.stringify(response));
        }
    }

    private static Object eval(Map<String, Object> request) {
        String script = str(request.get("script"));
        String scopeKey = str(request.get("scopeKey"));
        long timeoutMs = longValue(request.get("timeoutMs"), DEFAULT_TIMEOUT_MS);
        @SuppressWarnings("unchecked")
        Map<String, Object> bindings = request.get("bindings") instanceof Map ? (Map<String, Object>) request.get("bindings") : new LinkedHashMap<>();
        String jsLib = str(request.get("jsLib"));
        SandboxFactory factory = new SandboxFactory(System.currentTimeMillis() + timeoutMs);
        Context cx = factory.enterContext();
        try {
            cx.setLanguageVersion(Context.VERSION_ES6);
            cx.setOptimizationLevel(-1);
            cx.setInstructionObserverThreshold(10000);
            cx.setMaximumInterpreterStackDepth(MAX_STACK_DEPTH);
            cx.setClassShutter(new RestrictedClassShutter());
            Scriptable root = sharedScope(cx, scopeKey, jsLib);
            Scriptable scope = cx.newObject(root);
            scope.setPrototype(root);
            scope.setParentScope(null);
            bind(cx, scope, bindings);
            Object value = cx.evaluateString(scope, script, "legado-rule", 1, null);
            return toJsonValue(value);
        } finally {
            Context.exit();
        }
    }


    private static Map<String, Object> stateFromRequest(Map<String, Object> request) {
        Map<String, Object> state = new LinkedHashMap<>();
        @SuppressWarnings("unchecked")
        Map<String, Object> bindings = request.get("bindings") instanceof Map ? (Map<String, Object>) request.get("bindings") : new LinkedHashMap<>();
        state.put("sourceState", asMap(bindings.get("sourceState")));
        state.put("cacheState", asMap(bindings.get("cacheState")));
        state.put("cookieState", asMap(bindings.get("cookieState")));
        state.put("bookState", asMap(bindings.get("bookState")));
        state.put("chapterState", asMap(bindings.get("chapterState")));
        return state;
    }

    private static Scriptable sharedScope(Context cx, String scopeKey, String jsLib) {
        String key = scopeKey == null || scopeKey.isEmpty() ? "default" : scopeKey;
        Scriptable existing = SHARED_SCOPES.get(key);
        if (existing != null) {
            return existing;
        }
        Scriptable scope = cx.initSafeStandardObjects(null, true);
        delete(scope, "Packages");
        delete(scope, "java");
        delete(scope, "javax");
        delete(scope, "org");
        delete(scope, "com");
        delete(scope, "edu");
        if (jsLib != null && !jsLib.isBlank()) {
            cx.evaluateString(scope, jsLib, "legado-jsLib", 1, null);
        }
        SHARED_SCOPES.put(key, scope);
        return scope;
    }

    private static void delete(Scriptable scope, String name) {
        ScriptableObject.deleteProperty(scope, name);
    }

    private static void bind(Context cx, Scriptable scope, Map<String, Object> bindings) {
        String tag = str(bindings.get("tag"));
        HostJava javaHost = new HostJava(tag, bindings, scope);
        MapHost sourceHost = new MapHost(asMap(bindings.get("sourceState")));
        MapHost cacheHost = new MapHost(asMap(bindings.get("cacheState")));
        MapHost cookieHost = new MapHost(asMap(bindings.get("cookieState")));
        MapObject bookHost = new MapObject(asMap(bindings.get("bookState")));
        MapObject chapterHost = new MapObject(asMap(bindings.get("chapterState")));
        bookHost.setParentScope(scope);
        bookHost.setPrototype(ScriptableObject.getObjectPrototype(scope));
        chapterHost.setParentScope(scope);
        chapterHost.setPrototype(ScriptableObject.getObjectPrototype(scope));
        Object wrappedJava = Context.javaToJS(javaHost, scope);
        Object wrappedSource = Context.javaToJS(sourceHost, scope);
        Object wrappedCache = Context.javaToJS(cacheHost, scope);
        Object wrappedCookie = Context.javaToJS(cookieHost, scope);
        ScriptableObject.putProperty(scope, "java", wrappedJava);
        ScriptableObject.putProperty(scope, "source", wrappedSource);
        ScriptableObject.putProperty(scope, "cache", wrappedCache);
        ScriptableObject.putProperty(scope, "cookie", wrappedCookie);
        ScriptableObject.putProperty(scope, "book", bookHost);
        ScriptableObject.putProperty(scope, "chapter", chapterHost);
        installGlobalHelpers(scope, javaHost, bindings);
        for (Map.Entry<String, Object> entry : bindings.entrySet()) {
            String key = entry.getKey();
            if ("sourceState".equals(key) || "cacheState".equals(key) || "cookieState".equals(key) || "bookState".equals(key) || "chapterState".equals(key) || "tag".equals(key)) {
                continue;
            }
            ScriptableObject.putProperty(scope, key, Context.javaToJS(entry.getValue(), scope));
        }
        if (!bindings.containsKey("result")) {
            ScriptableObject.putProperty(scope, "result", "");
        }
        if (!bindings.containsKey("src")) {
            ScriptableObject.putProperty(scope, "src", "");
        }
    }

    private static void installGlobalHelpers(Scriptable scope, HostJava javaHost, Map<String, Object> bindings) {
        BaseFunction mapFn = new BaseFunction() {
            @Override
            public Object call(Context cx, Scriptable callScope, Scriptable thisObj, Object[] args) {
                Map<String, Object> state = javaHost.javaState();
                if (args.length >= 2) {
                    state.put(str(args[0]), toJsonValue(args[1]));
                    return args[1];
                }
                if (args.length == 0) {
                    return "";
                }
                String key = str(args[0]);
                Object value = state.get(key);
                if (value == null) value = asMap(bindings.get("cacheState")).get(key);
                if (value == null) value = asMap(bindings.get("sourceState")).get(key);
                return value == null ? "" : Context.javaToJS(value, callScope);
            }
        };
        BaseFunction sFn = new BaseFunction() {
            @Override
            public Object call(Context cx, Scriptable callScope, Scriptable thisObj, Object[] args) {
                if (args.length == 0) return "";
                try {
                    return javaHost.getString(args[0]);
                } catch (Exception e) {
                    return "";
                }
            }
        };
        ScriptableObject.putProperty(scope, "Map", mapFn);
        ScriptableObject.putProperty(scope, "M", mapFn);
        ScriptableObject.putProperty(scope, "S", sFn);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        if (value instanceof Map) {
            return (Map<String, Object>) value;
        }
        return new LinkedHashMap<>();
    }

    private static Object toJsonValue(Object value) {
        if (value == null || value == Undefined.instance) {
            return null;
        }
        if (value instanceof Wrapper) {
            return toJsonValue(((Wrapper) value).unwrap());
        }
        if (value instanceof CharSequence || value instanceof Number || value instanceof Boolean) {
            return value.toString();
        }
        if (value instanceof Map) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (Object entryObject : ((Map<?, ?>) value).entrySet()) {
                Map.Entry<?, ?> entry = (Map.Entry<?, ?>) entryObject;
                out.put(String.valueOf(entry.getKey()), toJsonValue(entry.getValue()));
            }
            return out;
        }
        if (value instanceof Iterable) {
            List<Object> out = new ArrayList<>();
            for (Object item : (Iterable<?>) value) {
                out.add(toJsonValue(item));
            }
            return out;
        }
        if (value instanceof Scriptable) {
            Scriptable scriptable = (Scriptable) value;
            Object[] ids = scriptable.getIds();
            Map<String, Object> out = new LinkedHashMap<>();
            for (Object key : ids) {
                out.put(String.valueOf(key), toJsonValue(ScriptableObject.getProperty(scriptable, String.valueOf(key))));
            }
            if (!out.isEmpty()) {
                return out;
            }
        }
        return Context.toString(value);
    }

    private static String str(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static long longValue(Object value, long fallback) {
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        try {
            return Long.parseLong(str(value));
        } catch (Exception e) {
            return fallback;
        }
    }

    public static class SandboxFactory extends ContextFactory {
        private final long deadlineMs;

        SandboxFactory(long deadlineMs) {
            this.deadlineMs = deadlineMs;
        }

        @Override
        protected void observeInstructionCount(Context cx, int instructionCount) {
            if (System.currentTimeMillis() > deadlineMs) {
                throw new RuntimeException("Rhino script timed out");
            }
        }
    }

    public static class RestrictedClassShutter implements ClassShutter {
        @Override
        public boolean visibleToScripts(String fullClassName) {
            return fullClassName.startsWith("LegadoRhinoBridge$HostJava")
                    || fullClassName.startsWith("LegadoRhinoBridge$MapHost")
                    || fullClassName.startsWith("LegadoRhinoBridge$HttpResponseHost")
                    || "java.lang.String".equals(fullClassName)
                    || "java.lang.Boolean".equals(fullClassName)
                    || "java.lang.Number".equals(fullClassName)
                    || "java.lang.Integer".equals(fullClassName)
                    || "java.lang.Long".equals(fullClassName)
                    || "java.lang.Double".equals(fullClassName)
                    || "java.util.ArrayList".equals(fullClassName)
                    || "java.util.LinkedHashMap".equals(fullClassName);
        }
    }

    public static class HostJava {
        private final String tag;
        private final Map<String, Object> bindings;
        private final Scriptable scope;

        HostJava(String tag, Map<String, Object> bindings, Scriptable scope) {
            this.tag = tag == null ? "" : tag;
            this.bindings = bindings == null ? new LinkedHashMap<>() : bindings;
            this.scope = scope;
        }

        public String md5Encode(Object value) throws Exception {
            return digest("MD5", str(value));
        }

        public String md5Encode16(Object value) throws Exception {
            String md5 = digest("MD5", str(value));
            return md5.substring(8, 24);
        }

        public String sha1Encode(Object value) throws Exception {
            return digest("SHA-1", str(value));
        }

        public String sha256Encode(Object value) throws Exception {
            return digest("SHA-256", str(value));
        }

        public String sha512Encode(Object value) throws Exception {
            return digest("SHA-512", str(value));
        }

        public String hmacSha1(Object key, Object value) throws Exception {
            return hmac("HmacSHA1", str(key), str(value));
        }

        public String hmacSha256(Object key, Object value) throws Exception {
            return hmac("HmacSHA256", str(key), str(value));
        }

        public String hmacSha512(Object key, Object value) throws Exception {
            return hmac("HmacSHA512", str(key), str(value));
        }

        public String base64Encode(Object value) {
            return Base64.getEncoder().encodeToString(str(value).getBytes(StandardCharsets.UTF_8));
        }

        public String base64Decode(Object value) {
            return new String(Base64.getDecoder().decode(str(value)), StandardCharsets.UTF_8);
        }

        public String encryptBase64(Object algorithm, Object key, Object iv, Object data) throws Exception {
            return Base64.getEncoder().encodeToString(aesCipher(Cipher.ENCRYPT_MODE, str(algorithm), keyBytes(key), ivBytes(iv)).doFinal(str(data).getBytes(StandardCharsets.UTF_8)));
        }

        public String encryptBase64(Object key, Object iv, Object data) throws Exception {
            return encryptBase64("AES/CBC/PKCS5Padding", key, iv, data);
        }

        public String encryptBase64(Object key, Object data) throws Exception {
            return encryptBase64("AES/ECB/PKCS5Padding", key, "", data);
        }

        public String encryptHex(Object algorithm, Object key, Object iv, Object data) throws Exception {
            return bytesToHex(aesCipher(Cipher.ENCRYPT_MODE, str(algorithm), keyBytes(key), ivBytes(iv)).doFinal(str(data).getBytes(StandardCharsets.UTF_8)));
        }

        public String encryptHex(Object key, Object iv, Object data) throws Exception {
            return encryptHex("AES/CBC/PKCS5Padding", key, iv, data);
        }

        public String decryptStr(Object algorithm, Object key, Object iv, Object data) throws Exception {
            byte[] encrypted = looksLikeHex(str(data)) ? hexToBytes(str(data)) : Base64.getDecoder().decode(str(data));
            return new String(aesCipher(Cipher.DECRYPT_MODE, str(algorithm), keyBytes(key), ivBytes(iv)).doFinal(encrypted), StandardCharsets.UTF_8);
        }

        public String decryptStr(Object key, Object iv, Object data) throws Exception {
            return decryptStr("AES/CBC/PKCS5Padding", key, iv, data);
        }

        public String decryptStr(Object key, Object data) throws Exception {
            return decryptStr("AES/ECB/PKCS5Padding", key, "", data);
        }

        public String hexEncode(Object value) {
            return bytesToHex(str(value).getBytes(StandardCharsets.UTF_8));
        }

        public String hexDecode(Object value) {
            return new String(hexToBytes(str(value)), StandardCharsets.UTF_8);
        }

        public String hexDecodeToString(Object value) {
            return hexDecode(value);
        }

        public String timeFormat(Object value) {
            long ms = longValue(value, 0L);
            if (ms <= 0L) return "";
            return java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
                    .withZone(java.time.ZoneId.systemDefault())
                    .format(java.time.Instant.ofEpochMilli(ms));
        }

        public String encodeURI(Object value) throws Exception {
            return URLEncoder.encode(str(value), StandardCharsets.UTF_8).replace("+", "%20");
        }

        public String importScript(Object path) throws Exception {
            String raw = str(path);
            String content = raw.startsWith("http://") || raw.startsWith("https://") ? cacheFile(raw) : readTxtFile(raw);
            if (content.isBlank()) {
                throw new RuntimeException(raw + " returned empty script content");
            }
            Context.getCurrentContext().evaluateString(scope, content, "legado-importScript", 1, null);
            return content;
        }

        public String cacheFile(Object url) throws Exception {
            return cacheFile(url, 0);
        }

        public String cacheFile(Object url, Object saveTime) throws Exception {
            String urlText = str(url);
            String key = "file:" + md5Encode16(urlText);
            Map<String, Object> cacheState = asMap(bindings.get("cacheState"));
            Object cached = cacheState.get(key);
            if (cached != null && !str(cached).isBlank()) {
                return str(cached);
            }
            String body = request("GET", urlText, null, null, 15000).body();
            cacheState.put(key, body);
            return body;
        }

        public String downloadFile(Object url) throws Exception {
            String urlText = str(url);
            String digest = md5Encode16(urlText);
            String key = "file:" + digest;
            Map<String, Object> cacheState = asMap(bindings.get("cacheState"));
            if (!cacheState.containsKey(key)) {
                cacheState.put(key, request("GET", urlText, null, null, 15000).body());
            }
            return "cache://" + digest;
        }

        public String readTxtFile(Object path) throws Exception {
            return readTxtFile(path, "UTF-8");
        }

        public String readTxtFile(Object path, Object charsetName) throws Exception {
            String raw = str(path);
            if (raw.startsWith("cache://")) {
                Object cached = asMap(bindings.get("cacheState")).get("file:" + raw.substring(8));
                return cached == null ? "" : str(cached);
            }
            Path root = new File(System.getProperty("user.dir")).toPath().toAbsolutePath().normalize();
            Path target = root.resolve(raw).normalize();
            if (!target.startsWith(root)) {
                throw new RuntimeException("readTxtFile path is outside base dir");
            }
            if (!Files.exists(target) || !Files.isRegularFile(target)) {
                return "";
            }
            return Files.readString(target, StandardCharsets.UTF_8);
        }

        public Object log(Object value) {
            rememberEvent("log", str(value));
            return value;
        }

        public Object toast(Object value) {
            rememberEvent("toast", str(value));
            return value;
        }

        public Object longToast(Object value) {
            rememberEvent("longToast", str(value));
            return value;
        }

        public Object copyText(Object value) {
            javaState().put("clipboard", str(value));
            rememberEvent("copyText", str(value));
            return value;
        }

        public Object openUrl(Object url) {
            javaState().put("lastOpenUrl", str(url));
            rememberEvent("openUrl", str(url));
            return url;
        }

        public Object startBrowser(Object url) {
            return openUrl(url);
        }

        public Object startBrowser(Object url, Object title) {
            javaState().put("lastOpenTitle", str(title));
            return openUrl(url);
        }

        public Object startBrowserAwait(Object url) {
            return startBrowser(url);
        }

        public Object startBrowserAwait(Object url, Object title) {
            return startBrowser(url, title);
        }

        public Object upLoginData(Object value) {
            Object normalized = normalizeLoginUiData(value);
            if (normalized instanceof Map) {
                javaState().put("loginUiData", normalized);
                mergeLoginInfoMap((Map<?, ?>) normalized);
                rememberEvent("upLoginData", Json.stringify(normalized));
            } else {
                String text = str(value);
                javaState().put("loginData", text);
                mergeCookieHeader(text);
                rememberEvent("upLoginData", text);
            }
            return true;
        }

        public Object upUiData(Object value) {
            return upLoginData(value);
        }

        public Object upLoginData(Object key, Object value) {
            String text = str(value);
            javaState().put("loginData:" + str(key), text);
            Map<String, Object> uiData = new LinkedHashMap<>();
            uiData.put(str(key), text);
            javaState().put("loginUiData", uiData);
            mergeLoginInfoMap(uiData);
            mergeCookieHeader(text);
            rememberEvent("upLoginData", text);
            return true;
        }

        public Object upUiData(Object key, Object value) {
            return upLoginData(key, value);
        }

        public Object reLoginView() {
            return reLoginView(false);
        }

        public Object reLoginView(Object deltaUp) {
            javaState().put("reLoginView", str(deltaUp));
            rememberEvent("reLoginView", str(deltaUp));
            return true;
        }

        public Object setContent(Object value) {
            javaState().put("content", str(value));
            rememberEvent("setContent", str(value));
            return value;
        }

        public Object setContent(Object value, Object baseUrl) {
            javaState().put("content", str(value));
            javaState().put("baseUrl", str(baseUrl));
            rememberEvent("setContent", str(value));
            return value;
        }

        public Object setBaseUrl(Object baseUrl) {
            javaState().put("baseUrl", str(baseUrl));
            rememberEvent("setBaseUrl", str(baseUrl));
            return baseUrl;
        }

        public Object setRedirectUrl(Object url) {
            javaState().put("redirectUrl", str(url));
            rememberEvent("setRedirectUrl", str(url));
            return url;
        }

        public Object getSource() {
            Map<String, Object> source = new LinkedHashMap<>();
            source.put("tag", getTag());
            source.put("state", asMap(bindings.get("sourceState")));
            return source;
        }

        public Object open(Object type, Object url, Object title) {
            Map<String, Object> event = new LinkedHashMap<>();
            event.put("type", str(type));
            event.put("url", str(url));
            event.put("title", str(title));
            javaState().put("lastOpen", event);
            rememberEvent("open", Json.stringify(event));
            return url;
        }

        public Object refreshBookInfo() {
            javaState().put("refreshBookInfo", "true");
            rememberEvent("refreshBookInfo", "true");
            return true;
        }

        public Object refreshExplore() {
            javaState().put("refreshExplore", "true");
            javaState().put("reLoginView", "false");
            rememberEvent("refreshExplore", "true");
            return true;
        }

        public Object searchBook(Object value) {
            javaState().put("lastSearchBook", str(value));
            rememberEvent("searchBook", str(value));
            return value;
        }

        public Object searchBook(Object value, Object scope) {
            javaState().put("lastSearchBook", str(value));
            javaState().put("lastSearchScope", str(scope));
            rememberEvent("searchBook", str(value));
            return value;
        }

        public Object addBook(Object bookUrl) {
            javaState().put("lastAddBook", str(bookUrl));
            rememberEvent("addBook", str(bookUrl));
            return bookUrl;
        }

        public Object showPhoto(Object value) {
            javaState().put("lastPhoto", str(value));
            rememberEvent("showPhoto", str(value));
            return value;
        }

        public Object showBrowser(Object value) {
            return startBrowser(value);
        }

        public String getVerificationCode(Object value) {
            javaState().put("lastVerificationImage", str(value));
            return "";
        }

        public String readBookConfig(Object key) {
            Object value = javaState().get("bookConfig:" + str(key));
            return value == null ? "" : str(value);
        }

        public Object setHeaders(Object value) {
            javaState().put("headers", str(value));
            rememberEvent("setHeaders", str(value));
            return value;
        }

        public String getTag() {
            return tag;
        }

        public String getString(Object rule) throws Exception {
            Object value = callback("getString", List.of(str(rule)));
            return value == null ? "" : String.valueOf(value);
        }

        public Object getStringList(Object rule) throws Exception {
            return toJsArrayIfList(callback("getStringList", List.of(str(rule))));
        }

        public Object getElement(Object rule) throws Exception {
            return callback("getElement", List.of(str(rule)));
        }

        public Object getElements(Object rule) throws Exception {
            return toJsArrayIfList(callback("getElements", List.of(str(rule))));
        }

        private Object toJsArrayIfList(Object value) {
            if (value instanceof List) {
                List<?> list = (List<?>) value;
                return Context.getCurrentContext().newArray(scope, list.toArray(new Object[0]));
            }
            return value;
        }

        private Object callback(String name, List<Object> args) throws Exception {
            if (BRIDGE_IN == null || BRIDGE_OUT == null) {
                throw new RuntimeException("Bridge callback channel is not available");
            }
            Map<String, Object> request = new LinkedHashMap<>();
            request.put("id", "cb_" + System.nanoTime());
            request.put("op", "callback");
            request.put("name", name);
            request.put("args", args);
            request.put("bindings", bindings);
            BRIDGE_OUT.println(Json.stringify(request));
            String line = BRIDGE_IN.readLine();
            if (line == null || line.isBlank()) {
                throw new RuntimeException("No callback response for " + name);
            }
            Object parsed = Json.parse(line);
            if (!(parsed instanceof Map)) {
                throw new RuntimeException("Invalid callback response for " + name);
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> response = (Map<String, Object>) parsed;
            if (!Boolean.TRUE.equals(response.get("ok"))) {
                throw new RuntimeException(str(response.get("error")));
            }
            return response.get("result");
        }

        public String ajax(Object url) throws Exception {
            return request("GET", str(url), null, null, 15000).body();
        }

        public String ajax(Object url, Object timeoutMs) throws Exception {
            return request("GET", str(url), null, null, (int) longValue(timeoutMs, 15000)).body();
        }

        public HttpResponseHost connect(Object url) throws Exception {
            return request("GET", str(url), null, null, 15000);
        }

        public HttpResponseHost connect(Object url, Object headers) throws Exception {
            return request("GET", str(url), parseHeaderMap(headers), null, 15000);
        }

        public HttpResponseHost connect(Object url, Object headers, Object timeoutMs) throws Exception {
            return request("GET", str(url), parseHeaderMap(headers), null, (int) longValue(timeoutMs, 15000));
        }

        public Object get(Object keyOrUrl) throws Exception {
            String key = str(keyOrUrl);
            if (isHttpUrl(key)) {
                return request("GET", key, null, null, 15000);
            }
            Object value = javaState().get(key);
            return value == null ? "" : value;
        }

        public HttpResponseHost get(Object url, Object headers) throws Exception {
            return request("GET", str(url), parseHeaderMap(headers), null, 15000);
        }

        public Object put(Object key, Object value) {
            javaState().put(str(key), value == null || value == Undefined.instance ? "" : toJsonValue(value));
            return value;
        }

        public Object delete(Object key) {
            return javaState().remove(str(key));
        }

        public HttpResponseHost head(Object url) throws Exception {
            return request("HEAD", str(url), null, null, 15000);
        }

        public HttpResponseHost post(Object url, Object body) throws Exception {
            return request("POST", str(url), null, str(body), 15000);
        }

        public HttpResponseHost post(Object url, Object body, Object headers) throws Exception {
            return request("POST", str(url), parseHeaderMap(headers), str(body), 15000);
        }

        private Map<String, Object> parseHeaderMap(Object headers) {
            if (headers == null || headers == Undefined.instance) {
                return null;
            }
            if (headers instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> map = (Map<String, Object>) headers;
                return map;
            }
            String raw = str(headers).trim();
            if (raw.isEmpty()) {
                return null;
            }
            try {
                Object parsed = Json.parse(raw);
                if (parsed instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> map = (Map<String, Object>) parsed;
                    return map;
                }
            } catch (Exception ignored) {
            }
            return null;
        }

        private HttpResponseHost request(String method, String urlText, Map<String, Object> headers, String body, int timeoutMs) throws Exception {
            if (!isHttpUrl(urlText)) {
                throw new RuntimeException("Only http/https URLs are allowed");
            }
            HttpURLConnection conn = (HttpURLConnection) new URL(urlText).openConnection();
            conn.setRequestMethod(method);
            conn.setConnectTimeout(timeoutMs);
            conn.setReadTimeout(timeoutMs);
            conn.setInstanceFollowRedirects(true);
            conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36");
            Map<String, Object> cookieState = asMap(bindings.get("cookieState"));
            if (headers == null || !hasHeader(headers, "Cookie")) {
                String cookieHeader = cookieHeader(cookieState);
                if (!cookieHeader.isEmpty()) {
                    conn.setRequestProperty("Cookie", cookieHeader);
                }
            }
            if (headers != null) {
                for (Map.Entry<String, Object> entry : headers.entrySet()) {
                    conn.setRequestProperty(entry.getKey(), str(entry.getValue()));
                }
            }
            if (body != null && !"HEAD".equals(method)) {
                conn.setDoOutput(true);
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                if (conn.getRequestProperty("Content-Type") == null) {
                    conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
                }
                conn.setRequestProperty("Content-Length", String.valueOf(bytes.length));
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(bytes);
                }
            }
            int code = conn.getResponseCode();
            InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String responseBody = is == null ? "" : readAll(is);
            Map<String, Object> responseHeaders = new LinkedHashMap<>();
            for (Map.Entry<String, List<String>> entry : conn.getHeaderFields().entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    responseHeaders.put(entry.getKey(), String.join(",", entry.getValue()));
                    if ("Set-Cookie".equalsIgnoreCase(entry.getKey())) {
                        storeSetCookies(cookieState, entry.getValue());
                    }
                }
            }
            return new HttpResponseHost(code, responseBody, responseHeaders, conn.getURL().toString());
        }

        private boolean isHttpUrl(String value) {
            return value.startsWith("http://") || value.startsWith("https://");
        }

        public Map<String, Object> javaState() {
            Map<String, Object> cacheState = asMap(bindings.get("cacheState"));
            Object existing = cacheState.get("javaState");
            if (existing instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> map = (Map<String, Object>) existing;
                return map;
            }
            Map<String, Object> map = new LinkedHashMap<>();
            cacheState.put("javaState", map);
            return map;
        }

        private void rememberEvent(String name, String value) {
            Map<String, Object> state = javaState();
            state.put("lastEvent", name);
            state.put("lastEventValue", value);
        }

        private Object normalizeLoginUiData(Object value) {
            if (value instanceof Map) {
                return value;
            }
            if (value instanceof Scriptable) {
                Object json = toJsonValue(value);
                if (json instanceof Map) {
                    return json;
                }
            }
            String text = str(value).trim();
            if (text.startsWith("{") && text.endsWith("}")) {
                try {
                    Object parsed = Json.parse(text);
                    if (parsed instanceof Map) {
                        return parsed;
                    }
                } catch (Exception ignored) {
                }
            }
            return text;
        }

        private void mergeLoginInfoMap(Map<?, ?> data) {
            Map<String, Object> sourceState = asMap(bindings.get("sourceState"));
            Map<String, Object> normalized = new LinkedHashMap<>();
            Object existing = sourceState.get("loginInfo");
            if (existing != null && !str(existing).isBlank()) {
                try {
                    Object parsed = Json.parse(str(existing));
                    if (parsed instanceof Map) {
                        for (Object entryObject : ((Map<?, ?>) parsed).entrySet()) {
                            Map.Entry<?, ?> entry = (Map.Entry<?, ?>) entryObject;
                            normalized.put(String.valueOf(entry.getKey()), entry.getValue());
                        }
                    }
                } catch (Exception ignored) {
                }
            }
            for (Map.Entry<?, ?> entry : data.entrySet()) {
                String key = String.valueOf(entry.getKey());
                Object value = toJsonValue(entry.getValue());
                normalized.put(key, value);
                sourceState.put("loginInfo:" + key, value);
            }
            sourceState.put("loginInfo", Json.stringify(normalized));
        }

        private void mergeCookieHeader(String raw) {
            if (raw == null || raw.isBlank() || !raw.contains("=")) {
                return;
            }
            Map<String, Object> cookies = asMap(bindings.get("cookieState"));
            String[] parts = raw.split(";");
            for (String part : parts) {
                int idx = part.indexOf('=');
                if (idx > 0) {
                    String key = part.substring(0, idx).trim();
                    String value = part.substring(idx + 1).trim();
                    if (!key.isEmpty() && !value.isEmpty()) {
                        cookies.put(key, value);
                    }
                }
            }
        }

        private boolean hasHeader(Map<String, Object> headers, String name) {
            for (String key : headers.keySet()) {
                if (name.equalsIgnoreCase(key)) {
                    return true;
                }
            }
            return false;
        }

        private String cookieHeader(Map<String, Object> cookies) {
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, Object> entry : cookies.entrySet()) {
                String value = str(entry.getValue());
                if (entry.getKey() == null || entry.getKey().isBlank() || value.isBlank()) {
                    continue;
                }
                if (sb.length() > 0) sb.append("; ");
                sb.append(entry.getKey()).append("=").append(value);
            }
            return sb.toString();
        }

        private void storeSetCookies(Map<String, Object> cookies, List<String> values) {
            if (values == null) return;
            for (String raw : values) {
                if (raw == null || raw.isBlank()) continue;
                String first = raw.split(";", 2)[0];
                int idx = first.indexOf('=');
                if (idx > 0) {
                    cookies.put(first.substring(0, idx).trim(), first.substring(idx + 1).trim());
                }
            }
        }

        private String readAll(InputStream is) throws Exception {
            try (InputStream input = is; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int n;
                while ((n = input.read(buffer)) != -1) {
                    out.write(buffer, 0, n);
                }
                return out.toString(StandardCharsets.UTF_8);
            }
        }

        private String digest(String algorithm, String value) throws Exception {
            MessageDigest digest = MessageDigest.getInstance(algorithm);
            return bytesToHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        }

        private String hmac(String algorithm, String key, String value) throws Exception {
            Mac mac = Mac.getInstance(algorithm);
            mac.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), algorithm));
            return bytesToHex(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
        }

        private Cipher aesCipher(int mode, String algorithm, byte[] key, byte[] iv) throws Exception {
            String algo = algorithm == null || algorithm.isBlank() ? (iv.length > 0 ? "AES/CBC/PKCS5Padding" : "AES/ECB/PKCS5Padding") : algorithm;
            Cipher cipher = Cipher.getInstance(algo);
            SecretKeySpec keySpec = new SecretKeySpec(normalizeAesKey(key), "AES");
            if (algo.contains("/CBC/") || algo.contains("/CTR/") || algo.contains("/CFB/") || algo.contains("/OFB/")) {
                cipher.init(mode, keySpec, new IvParameterSpec(normalizeIv(iv)));
            } else {
                cipher.init(mode, keySpec);
            }
            return cipher;
        }

        private byte[] keyBytes(Object value) {
            return decodeMaybeBase64OrHex(str(value));
        }

        private byte[] ivBytes(Object value) {
            String raw = str(value);
            return raw.isEmpty() ? new byte[0] : decodeMaybeBase64OrHex(raw);
        }

        private byte[] normalizeAesKey(byte[] key) {
            int size = key.length <= 16 ? 16 : key.length <= 24 ? 24 : 32;
            byte[] out = new byte[size];
            System.arraycopy(key, 0, out, 0, Math.min(key.length, size));
            return out;
        }

        private byte[] normalizeIv(byte[] iv) {
            byte[] out = new byte[16];
            System.arraycopy(iv, 0, out, 0, Math.min(iv.length, 16));
            return out;
        }

        private byte[] decodeMaybeBase64OrHex(String value) {
            if (looksLikeHex(value) && value.length() >= 16) {
                return hexToBytes(value);
            }
            try {
                byte[] decoded = Base64.getDecoder().decode(value);
                if (decoded.length == 16 || decoded.length == 24 || decoded.length == 32) {
                    return decoded;
                }
            } catch (Exception ignored) {
            }
            return value.getBytes(StandardCharsets.UTF_8);
        }

        private boolean looksLikeHex(String value) {
            return value.length() % 2 == 0 && value.matches("[0-9a-fA-F]+");
        }

        private byte[] hexToBytes(String value) {
            int len = value.length();
            byte[] out = new byte[len / 2];
            for (int i = 0; i < len; i += 2) {
                out[i / 2] = (byte) Integer.parseInt(value.substring(i, i + 2), 16);
            }
            return out;
        }

        private String bytesToHex(byte[] bytes) {
            StringBuilder sb = new StringBuilder();
            for (byte b : bytes) {
                sb.append(String.format("%02x", b & 0xff));
            }
            return sb.toString();
        }
    }


    public static class HttpResponseHost {
        private final int code;
        private final String body;
        private final Map<String, Object> headers;
        private final String url;

        HttpResponseHost(int code, String body, Map<String, Object> headers, String url) {
            this.code = code;
            this.body = body == null ? "" : body;
            this.headers = headers == null ? new LinkedHashMap<>() : headers;
            this.url = url == null ? "" : url;
        }

        public int code() {
            return code;
        }

        public int statusCode() {
            return code;
        }

        public String body() {
            return body;
        }

        public String bodyString() {
            return body;
        }

        public String header(String key) {
            Object value = headers.get(key);
            return value == null ? "" : String.valueOf(value);
        }

        public String headers() {
            return Json.stringify(headers);
        }

        public String url() {
            return url;
        }

        @Override
        public String toString() {
            return body;
        }
    }

    public static class MapObject extends ScriptableObject {
        private final Map<String, Object> values;

        MapObject(Map<String, Object> values) {
            this.values = values == null ? new LinkedHashMap<>() : values;
            super.put("putVariable", this, new BaseFunction() {
                @Override
                public Object call(Context cx, Scriptable scope, Scriptable thisObj, Object[] args) {
                    if (args.length >= 2) {
                        MapObject.this.values.put(str(args[0]), toJsonValue(args[1]));
                        return args[1];
                    }
                    if (args.length == 1) {
                        MapObject.this.values.put("variable", toJsonValue(args[0]));
                        return args[0];
                    }
                    return "";
                }
            });
            super.put("getVariable", this, new BaseFunction() {
                @Override
                public Object call(Context cx, Scriptable scope, Scriptable thisObj, Object[] args) {
                    String key = args.length >= 1 ? str(args[0]) : "variable";
                    Object value = MapObject.this.values.get(key);
                    return value == null ? "" : Context.javaToJS(value, scope);
                }
            });
        }

        @Override
        public String getClassName() {
            return "LegadoMapObject";
        }

        @Override
        public Object get(String name, Scriptable start) {
            if (super.has(name, start)) {
                return super.get(name, start);
            }
            Object value = values.get(name);
            return value == null ? "" : Context.javaToJS(value, start);
        }

        @Override
        public void put(String name, Scriptable start, Object value) {
            if (super.has(name, start)) {
                super.put(name, start, value);
                return;
            }
            values.put(name, value == null || value == Undefined.instance ? "" : toJsonValue(value));
        }

        @Override
        public boolean has(String name, Scriptable start) {
            return super.has(name, start) || values.containsKey(name);
        }

        @Override
        public Object[] getIds() {
            List<Object> ids = new ArrayList<>();
            for (Object id : super.getIds()) ids.add(id);
            ids.addAll(values.keySet());
            return ids.toArray();
        }
    }

    public static class MapHost {
        private final Map<String, Object> values;

        MapHost(Map<String, Object> values) {
            this.values = values == null ? new LinkedHashMap<>() : values;
        }

        public String put(String key, Object value) {
            String text = str(value);
            values.put(key, text);
            return text;
        }

        public String get(String key) {
            Object value = values.get(key);
            return value == null ? "" : String.valueOf(value);
        }

        public String getCookie(String key) {
            if (values.containsKey(key)) {
                return get(key);
            }
            return get(cookieKey(key));
        }

        public String setCookie(String key, Object value) {
            return put(cookieKey(key), value);
        }

        public String getKey(String key) {
            return get(key);
        }

        public String getLoginHeader() {
            return get("loginHeader");
        }

        public String putLoginHeader(Object value) {
            return put("loginHeader", value);
        }

        public String putLoginInfo(Object value) {
            String text = str(value);
            values.put("loginInfo", text);
            try {
                Object parsed = Json.parse(text);
                if (parsed instanceof Map) {
                    for (Object entryObject : ((Map<?, ?>) parsed).entrySet()) {
                        Map.Entry<?, ?> entry = (Map.Entry<?, ?>) entryObject;
                        values.put("loginInfo:" + String.valueOf(entry.getKey()), entry.getValue());
                    }
                }
            } catch (Exception ignored) {
            }
            return text;
        }

        public String putLoginInfo(Object key, Object value) {
            return put("loginInfo:" + str(key), value);
        }

        public String getLoginInfoMap() {
            Object raw = values.get("loginInfo");
            if (raw != null && !str(raw).isBlank()) {
                return str(raw);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : values.entrySet()) {
                if (entry.getKey().startsWith("loginInfo:")) {
                    out.put(entry.getKey().substring(10), entry.getValue());
                }
            }
            return Json.stringify(out);
        }

        public String refreshExplore() {
            values.put("refreshExplore", "true");
            return "true";
        }

        private String cookieKey(String key) {
            return key.startsWith("http://") || key.startsWith("https://") ? key : "cookie:" + key;
        }

        public String getFromMemory(String key) {
            return get(key);
        }

        public void delete(String key) {
            values.remove(key);
        }

        public void deleteMemory(String key) {
            values.remove(key);
        }

        public String putVariable(Object value) {
            values.put("variable", str(value));
            return str(value);
        }

        public String putVariable(Object key, Object value) {
            values.put(str(key), str(value));
            return str(value);
        }

        public String getVariable() {
            Object value = values.get("variable");
            return value == null ? "" : String.valueOf(value);
        }

        public String getVariable(Object key) {
            Object value = values.get(str(key));
            return value == null ? "" : String.valueOf(value);
        }
    }

    public static class Json {
        public static Object parse(String text) {
            return new Parser(text).parseValue();
        }

        public static String stringify(Object value) {
            StringBuilder sb = new StringBuilder();
            write(sb, value);
            return sb.toString();
        }

        private static void write(StringBuilder sb, Object value) {
            if (value == null) {
                sb.append("null");
            } else if (value instanceof Boolean || value instanceof Number) {
                sb.append(value);
            } else if (value instanceof Map) {
                sb.append('{');
                boolean first = true;
                for (Object entryObject : ((Map<?, ?>) value).entrySet()) {
                    Map.Entry<?, ?> entry = (Map.Entry<?, ?>) entryObject;
                    if (!first) sb.append(',');
                    first = false;
                    write(sb, String.valueOf(entry.getKey()));
                    sb.append(':');
                    write(sb, entry.getValue());
                }
                sb.append('}');
            } else if (value instanceof Iterable) {
                sb.append('[');
                boolean first = true;
                for (Object item : (Iterable<?>) value) {
                    if (!first) sb.append(',');
                    first = false;
                    write(sb, item);
                }
                sb.append(']');
            } else {
                sb.append('"');
                String text = String.valueOf(value);
                for (int i = 0; i < text.length(); i++) {
                    char c = text.charAt(i);
                    switch (c) {
                        case '"': sb.append("\\\""); break;
                        case '\\': sb.append("\\\\"); break;
                        case '\b': sb.append("\\b"); break;
                        case '\f': sb.append("\\f"); break;
                        case '\n': sb.append("\\n"); break;
                        case '\r': sb.append("\\r"); break;
                        case '\t': sb.append("\\t"); break;
                        default:
                            if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                            else sb.append(c);
                    }
                }
                sb.append('"');
            }
        }
    }

    private static class Parser {
        private final String text;
        private int pos = 0;

        Parser(String text) {
            this.text = text == null ? "" : text;
        }

        Object parseValue() {
            skipWs();
            if (pos >= text.length()) return null;
            char c = text.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (text.startsWith("true", pos)) { pos += 4; return true; }
            if (text.startsWith("false", pos)) { pos += 5; return false; }
            if (text.startsWith("null", pos)) { pos += 4; return null; }
            return parseNumber();
        }

        Map<String, Object> parseObject() {
            Map<String, Object> out = new LinkedHashMap<>();
            pos++;
            skipWs();
            if (peek('}')) { pos++; return out; }
            while (pos < text.length()) {
                skipWs();
                String key = parseString();
                skipWs();
                expect(':');
                Object value = parseValue();
                out.put(key, value);
                skipWs();
                if (peek('}')) { pos++; break; }
                expect(',');
            }
            return out;
        }

        List<Object> parseArray() {
            List<Object> out = new ArrayList<>();
            pos++;
            skipWs();
            if (peek(']')) { pos++; return out; }
            while (pos < text.length()) {
                out.add(parseValue());
                skipWs();
                if (peek(']')) { pos++; break; }
                expect(',');
            }
            return out;
        }

        String parseString() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < text.length()) {
                char c = text.charAt(pos++);
                if (c == '"') break;
                if (c == '\\') {
                    char e = text.charAt(pos++);
                    switch (e) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'u':
                            String hex = text.substring(pos, pos + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            pos += 4;
                            break;
                        default: sb.append(e);
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        Number parseNumber() {
            int start = pos;
            while (pos < text.length() && "-+0123456789.eE".indexOf(text.charAt(pos)) >= 0) pos++;
            String raw = text.substring(start, pos);
            if (raw.contains(".") || raw.contains("e") || raw.contains("E")) {
                return Double.parseDouble(raw);
            }
            return Long.parseLong(raw);
        }

        void skipWs() {
            while (pos < text.length() && Character.isWhitespace(text.charAt(pos))) pos++;
        }

        boolean peek(char c) {
            return pos < text.length() && text.charAt(pos) == c;
        }

        void expect(char c) {
            if (!peek(c)) {
                throw new IllegalArgumentException("Expected '" + c + "' at " + pos);
            }
            pos++;
        }
    }
}
