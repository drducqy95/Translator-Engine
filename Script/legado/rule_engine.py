from __future__ import annotations

import ast
import json
import re
from typing import Any, Iterable, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from .rule_analyzer import has_js_rule, split_fallback_rules, split_rule_chain, split_text, strip_js_wrapper


_INDEX_RE = re.compile(r"^(?P<body>.*?)(?:\[(?P<bracket>!?-?\d*(?::-?\d*){0,2})\]|\.(?P<old>!?-?\d+(?::-?\d*){0,2}))$")


class UnsupportedRuleError(RuntimeError):
    pass


class LegadoRuleEngine:
    def __init__(self, base_url: str = "", rhino=None, bindings: dict | None = None, scope_key: str = "default", js_lib: str = ""):
        self.base_url = base_url
        self.rhino = rhino
        self.bindings = bindings or {}
        state = self.bindings.setdefault("sourceState", {})
        if not isinstance(state, dict):
            state = {}
            self.bindings["sourceState"] = state
        self.rule_state = state
        self.scope_key = scope_key
        self.js_lib = js_lib or ""

    def get_string(self, content: Any, rule: str | None, base_url: str | None = None) -> str:
        values = self.get_string_list(content, rule, base_url=base_url)
        return values[0] if values else ""

    def get_string_list(self, content: Any, rule: str | None, base_url: str | None = None) -> List[str]:
        if not rule:
            return self._stringify_list(content)
        result = self.get_elements(content, rule, base_url=base_url)
        return self._stringify_list(result)

    def get_elements(self, content: Any, rule: str | None, base_url: str | None = None) -> List[Any]:
        if not rule:
            return self._ensure_list(content)
        active_base = base_url or self.base_url
        rule = rule.strip()
        if not rule:
            return self._ensure_list(content)
        if has_js_rule(rule):
            return self._eval_js_rule(content, rule)

        rule, put_rules = self._extract_put_rules(rule)
        for key, value_rule in put_rules.items():
            self.rule_state[str(key)] = self.get_string(content, str(value_rule), base_url=active_base)
        direct_get = self._direct_get_value(rule)
        if direct_get is not None:
            return [direct_get]
        rule = self._replace_get_rules(rule)
        if not rule.strip():
            return []

        if "{{" in rule:
            if self.rhino:
                rule = self._replace_inline_js(content, rule)
            else:
                raise UnsupportedRuleError(f"Rule requires Rhino JS: {rule[:80]}")

        for fallback in split_fallback_rules(rule):
            values = self._eval_join_rule(content, fallback, active_base)
            if values:
                return values
        return []


    def _extract_put_rules(self, rule: str):
        put_rules = {}

        def repl(match):
            raw = match.group(1)
            parsed = self._parse_put_map(raw)
            put_rules.update(parsed)
            return ""

        stripped = re.sub(r"@put:(\{[^{}]*\})", repl, rule, flags=re.I)
        return stripped, put_rules

    def _parse_put_map(self, raw: str) -> dict:
        try:
            data = json.loads(raw)
        except Exception:
            try:
                data = ast.literal_eval(raw)
            except Exception:
                data = {}
        return data if isinstance(data, dict) else {}

    def _direct_get_value(self, rule: str):
        match = re.fullmatch(r"\s*@get:\{([^{}]+)\}\s*", rule or "", flags=re.I)
        if not match:
            return None
        return str(self.rule_state.get(match.group(1).strip(), ""))

    def _replace_get_rules(self, rule: str) -> str:
        def repl(match):
            key = match.group(1).strip()
            return str(self.rule_state.get(key, ""))
        return re.sub(r"@get:\{([^{}]+)\}", repl, rule, flags=re.I)

    def _eval_js_rule(self, content: Any, rule: str) -> List[Any]:
        if not self.rhino:
            raise UnsupportedRuleError(f"Rule requires Rhino JS: {rule[:80]}")
        bindings = dict(self.bindings)
        bindings.setdefault("result", self._first_value(content))
        bindings.setdefault("src", self._first_value(content))
        bindings.setdefault("baseUrl", self.base_url)
        self._install_rhino_callback(content)
        value = self.rhino.eval(strip_js_wrapper(rule), bindings=bindings, scope_key=self.scope_key, js_lib=self.js_lib, callback_context={"content": content, "base_url": self.base_url})
        return self._ensure_list(value)

    def _replace_inline_js(self, content: Any, rule: str) -> str:
        def repl(match):
            js = match.group(1).strip()
            bindings = dict(self.bindings)
            bindings.setdefault("result", self._first_value(content))
            bindings.setdefault("src", self._first_value(content))
            bindings.setdefault("baseUrl", self.base_url)
            self._install_rhino_callback(content)
            value = self.rhino.eval(js, bindings=bindings, scope_key=self.scope_key, js_lib=self.js_lib, callback_context={"content": content, "base_url": self.base_url})
            return "" if value is None else str(value)
        return re.sub(r"\{\{(.*?)\}\}", repl, rule, flags=re.S)

    def _install_rhino_callback(self, content: Any) -> None:
        if not self.rhino:
            return
        def callback(name: str, args: List[Any], context: dict):
            rule = str(args[0]) if args else ""
            callback_engine = LegadoRuleEngine(
                context.get("base_url") or self.base_url,
                rhino=None,
                bindings=self.bindings,
                scope_key=self.scope_key,
                js_lib=self.js_lib,
            )
            target = context.get("content", content)
            active_base = context.get("base_url") or self.base_url
            if name == "getString":
                return callback_engine.get_string(target, rule, base_url=active_base)
            if name == "getStringList":
                return callback_engine.get_string_list(target, rule, base_url=active_base)
            if name == "getElement":
                values = callback_engine.get_elements(target, rule, base_url=active_base)
                return callback_engine._stringify_list(values[:1])[0] if values else ""
            if name == "getElements":
                return callback_engine.get_string_list(target, rule, base_url=active_base)
            raise UnsupportedRuleError(f"Unsupported Rhino callback: {name}")
        self.rhino.rule_callback = callback

    def _first_value(self, content: Any) -> str:
        values = self._stringify_list(content)
        return values[0] if values else ""

    def _eval_join_rule(self, content: Any, rule: str, base_url: str) -> List[Any]:
        parts = split_text(rule, ["&&", "%%"], keep_empty=False)
        if len(parts) > 1:
            values: List[str] = []
            for part in parts:
                values.extend(self.get_string_list(content, part.strip(), base_url=base_url))
            return values
        return self._eval_rule(content, rule.strip(), base_url)

    def _eval_rule(self, content: Any, rule: str, base_url: str) -> List[Any]:
        source, regex_ops = self._split_regex_ops(rule)
        if source.startswith("@CSS:"):
            values = self._eval_css_mode(content, source[5:], base_url)
        elif source.startswith("@XPath:") or source.startswith("/"):
            values = self._eval_xpath(content, source[7:] if source.startswith("@XPath:") else source)
        elif source.startswith("@Json:") or source.startswith("$.") or source.startswith("$["):
            values = self._eval_jsonpath(content, source[6:] if source.startswith("@Json:") else source)
        else:
            values = self._eval_chain(content, source, base_url)
        for pattern, replacement, first_only in regex_ops:
            values = self._apply_regex(values, pattern, replacement, first_only)
        return values

    def _split_regex_ops(self, rule: str):
        marker = "###" if "###" in rule else "##"
        if marker not in rule:
            return rule, []
        parts = split_text(rule, [marker], keep_empty=True)
        source = parts[0]
        ops = []
        for i in range(1, len(parts), 2):
            pattern = parts[i]
            replacement = parts[i + 1] if i + 1 < len(parts) else ""
            ops.append((pattern, replacement, marker == "###"))
        return source, ops

    def _eval_css_mode(self, content: Any, rule: str, base_url: str) -> List[Any]:
        selector, attr = self._selector_and_attr(rule)
        nodes = []
        for root in self._html_roots(content):
            nodes.extend(root.select(selector) if selector else [root])
        return self._extract_attr(nodes, attr, base_url)

    def _eval_chain(self, content: Any, rule: str, base_url: str) -> List[Any]:
        parts = split_rule_chain(rule)
        if not parts:
            return self._ensure_list(content)
        current = self._ensure_list(content)
        for part in parts:
            current = self._eval_chain_part(current, part, base_url)
        return current

    def _eval_chain_part(self, current: List[Any], part: str, base_url: str) -> List[Any]:
        body, index_expr = self._strip_index(part)
        body = body.strip()
        attr_ops = {"text", "textNodes", "ownText", "html", "all"}
        if body in attr_ops or self._looks_like_attr(body):
            values = self._extract_attr(current, body, base_url)
        elif body.startswith("class."):
            values = self._select(current, "." + body[6:])
        elif body.startswith("id."):
            values = self._select(current, "#" + body[3:])
        elif body.startswith("tag."):
            values = self._select(current, body[4:] or "*")
        elif body.startswith("text."):
            needle = body[5:]
            values = [node for node in self._select(current, "*") if needle in self._text(node)]
        elif body == "children":
            values = []
            for node in current:
                if isinstance(node, Tag):
                    values.extend([child for child in node.children if isinstance(child, Tag)])
        else:
            values = self._select(current, body)
        return self._apply_index(values, index_expr)

    def _selector_and_attr(self, rule: str):
        parts = split_rule_chain(rule)
        if not parts:
            return "", "text"
        if len(parts) == 1:
            return parts[0], "text"
        return "@".join(parts[:-1]), parts[-1]

    def _select(self, current: List[Any], selector: str) -> List[Tag]:
        if not selector:
            return [node for node in current if isinstance(node, Tag)]
        out: List[Tag] = []
        for root in self._html_roots(current):
            try:
                out.extend(root.select(selector))
            except Exception:
                continue
        return out

    def _eval_xpath(self, content: Any, rule: str) -> List[Any]:
        try:
            from lxml import html, etree
        except Exception as exc:
            raise UnsupportedRuleError("XPath requires lxml") from exc
        text = self._to_markup(content)
        if not text:
            return []
        tree = html.fromstring(text)
        try:
            return tree.xpath(rule)
        except Exception:
            return []

    def _eval_jsonpath(self, content: Any, rule: str) -> List[Any]:
        data = self._to_json(content)
        if data is None:
            return []
        if not rule.startswith("$"):
            rule = "$" + ("." if not rule.startswith("[") else "") + rule
        return self._jsonpath_read(data, rule)

    def _jsonpath_read(self, data: Any, rule: str) -> List[Any]:
        if rule == "$":
            return self._ensure_list(data)
        tokens = self._json_tokens(rule)
        current = [data]
        for token in tokens:
            kind = token[0]
            next_values: List[Any] = []
            if kind == "field":
                key = token[1]
                for value in current:
                    if isinstance(value, dict) and key in value:
                        next_values.append(value[key])
            elif kind == "deep":
                key = token[1]
                for value in current:
                    next_values.extend(self._json_deep_values(value, key))
            elif kind == "wildcard":
                for value in current:
                    next_values.extend(self._json_children(value))
            elif kind == "index":
                idx = token[1]
                for value in current:
                    if isinstance(value, list) and -len(value) <= idx < len(value):
                        next_values.append(value[idx])
            elif kind == "slice":
                start, stop, step = token[1]
                for value in current:
                    if isinstance(value, list):
                        next_values.extend(value[slice(start, stop, step)])
            elif kind == "filter":
                field, op, expected = token[1]
                for value in current:
                    candidates = value if isinstance(value, list) else self._json_children(value)
                    for item in candidates:
                        if self._json_filter_match(item, field, op, expected):
                            next_values.append(item)
            current = next_values
        return current

    def _json_tokens(self, rule: str):
        body = rule[1:] if rule.startswith("$") else rule
        tokens = []
        i = 0
        while i < len(body):
            if body.startswith("..", i):
                i += 2
                if i < len(body) and body[i] == "[":
                    raw, i = self._json_bracket(body, i)
                    key = raw.strip().strip('"\'')
                else:
                    start = i
                    while i < len(body) and body[i] not in ".[":
                        i += 1
                    key = body[start:i]
                if key:
                    tokens.append(("deep", key))
            elif body[i] == ".":
                i += 1
                if i < len(body) and body[i] == "*":
                    tokens.append(("wildcard", None))
                    i += 1
                    continue
                start = i
                while i < len(body) and body[i] not in ".[":
                    i += 1
                if start != i:
                    tokens.append(("field", body[start:i]))
            elif body[i] == "[":
                raw, i = self._json_bracket(body, i)
                raw = raw.strip()
                if raw in {"*", "' * '", '"*"'}:
                    tokens.append(("wildcard", None))
                elif raw.startswith("?"):
                    parsed = self._json_parse_filter(raw)
                    if parsed:
                        tokens.append(("filter", parsed))
                elif ":" in raw and not (raw.startswith("'") or raw.startswith('"')):
                    tokens.append(("slice", self._json_parse_slice(raw)))
                else:
                    key = raw.strip('"\'')
                    if key.lstrip("-").isdigit():
                        tokens.append(("index", int(key)))
                    elif key:
                        tokens.append(("field", key))
            else:
                i += 1
        return tokens

    def _json_bracket(self, text: str, index: int):
        quote = ""
        escape = False
        depth = 0
        i = index
        start = index + 1
        while i < len(text):
            ch = text[i]
            if escape:
                escape = False
                i += 1
                continue
            if quote:
                if ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = ""
                i += 1
                continue
            if ch in {'"', "'"}:
                quote = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start:i], i + 1
            i += 1
        return text[start:], len(text)

    def _json_parse_slice(self, raw: str):
        values = []
        for part in raw.split(":")[:3]:
            part = part.strip()
            values.append(int(part) if part else None)
        while len(values) < 3:
            values.append(None)
        return tuple(values)

    def _json_parse_filter(self, raw: str):
        expr = raw.strip()
        if expr.startswith("?(") and expr.endswith(")"):
            expr = expr[2:-1].strip()
        elif expr.startswith("?"):
            expr = expr[1:].strip()
        match = re.match(r"@(?:\.([A-Za-z_][\w-]*)|\[['\"]([^'\"]+)['\"]\])\s*(==|!=|>=|<=|>|<|=~)\s*(.+)$", expr)
        if not match:
            return None
        field = match.group(1) or match.group(2)
        op = match.group(3)
        raw_value = match.group(4).strip()
        if (raw_value.startswith("'") and raw_value.endswith("'")) or (raw_value.startswith('"') and raw_value.endswith('"')):
            expected: Any = raw_value[1:-1]
        elif raw_value.lower() == "true":
            expected = True
        elif raw_value.lower() == "false":
            expected = False
        elif raw_value.lower() == "null":
            expected = None
        else:
            try:
                expected = float(raw_value) if "." in raw_value else int(raw_value)
            except ValueError:
                expected = raw_value.strip("/") if op == "=~" else raw_value
        return field, op, expected

    def _json_filter_match(self, item: Any, field: str, op: str, expected: Any) -> bool:
        if not isinstance(item, dict) or field not in item:
            return False
        actual = item[field]
        if op in {"==", "="}:
            return actual == expected or str(actual) == str(expected)
        if op == "!=":
            return not (actual == expected or str(actual) == str(expected))
        if op == "=~":
            try:
                return re.search(str(expected), str(actual)) is not None
            except re.error:
                return False
        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError):
            return False
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        return False

    def _json_children(self, value: Any) -> List[Any]:
        if isinstance(value, dict):
            return list(value.values())
        if isinstance(value, list):
            return list(value)
        return []

    def _json_deep_values(self, value: Any, key: str) -> List[Any]:
        out = []
        if isinstance(value, dict):
            if key in value:
                out.append(value[key])
            for child in value.values():
                out.extend(self._json_deep_values(child, key))
        elif isinstance(value, list):
            for child in value:
                out.extend(self._json_deep_values(child, key))
        return out

    def _extract_attr(self, values: Iterable[Any], attr: str, base_url: str) -> List[Any]:
        out = []
        attr = (attr or "text").strip()
        for value in values:
            if isinstance(value, Tag):
                if attr in ("text", "textNodes"):
                    out.append(value.get_text(" ", strip=True))
                elif attr == "ownText":
                    out.append(" ".join(value.find_all(string=True, recursive=False)).strip())
                elif attr == "html":
                    out.append(value.decode_contents())
                elif attr == "all":
                    out.append(str(value))
                else:
                    found = value.get(attr, "")
                    if attr.lower() in {"href", "src", "data-src", "data-original"} and found:
                        found = urljoin(base_url, found)
                    out.append(found)
            elif isinstance(value, dict):
                out.append(value.get(attr, ""))
            else:
                out.append(str(value))
        return [value for value in out if value not in (None, "")]

    def _apply_regex(self, values: Iterable[Any], pattern: str, replacement: str, first_only: bool) -> List[str]:
        out = []
        for value in self._stringify_list(values):
            count = 1 if first_only else 0
            py_replacement = re.sub(r"\$(\d+)", r"\\\1", replacement or "")
            try:
                new_value = re.sub(pattern, py_replacement, value, count=count)
            except re.error:
                new_value = value
            if new_value:
                out.append(new_value)
        return out

    def _strip_index(self, part: str):
        match = _INDEX_RE.match(part)
        if not match:
            return part, None
        body = match.group("body")
        index = match.group("bracket") or match.group("old")
        if body.endswith("."):
            return part, None
        return body, index

    def _apply_index(self, values: List[Any], index_expr: str | None) -> List[Any]:
        if not index_expr:
            return values
        negate = index_expr.startswith("!")
        expr = index_expr[1:] if negate else index_expr
        selected: List[Any]
        if ":" in expr:
            parts = [int(x) if x not in ("", None) else None for x in expr.split(":")]
            while len(parts) < 3:
                parts.append(None)
            selected = values[slice(parts[0], parts[1], parts[2])]
        elif expr.lstrip("-").isdigit():
            idx = int(expr)
            selected = [values[idx]] if values and -len(values) <= idx < len(values) else []
        else:
            selected = values
        if negate:
            selected_ids = {id(v) for v in selected}
            return [v for v in values if id(v) not in selected_ids]
        return selected

    def _html_roots(self, content: Any) -> List[Tag]:
        roots = []
        for value in self._ensure_list(content):
            if isinstance(value, BeautifulSoup):
                roots.append(value)
            elif isinstance(value, Tag):
                roots.append(value)
            elif isinstance(value, str):
                roots.append(BeautifulSoup(value, "html.parser"))
        return roots

    def _ensure_list(self, value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [value]

    def _stringify_list(self, value: Any) -> List[str]:
        out = []
        for item in self._ensure_list(value):
            if isinstance(item, Tag):
                text = item.get_text(" ", strip=True)
            elif isinstance(item, (dict, list)):
                text = json.dumps(item, ensure_ascii=False)
            else:
                text = str(item)
            if text:
                out.append(text)
        return out

    def _text(self, value: Any) -> str:
        return self._stringify_list(value)[0] if self._stringify_list(value) else ""

    def _to_markup(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        return "".join(str(item) for item in self._ensure_list(content))

    def _to_json(self, content: Any):
        if isinstance(content, (dict, list)):
            return content
        if isinstance(content, str):
            try:
                return json.loads(content)
            except Exception:
                return None
        return None

    def _looks_like_attr(self, body: str) -> bool:
        return body in {"href", "src", "data-src", "data-original", "content", "value", "title", "alt"}
