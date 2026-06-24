from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class SplitToken:
    text: str
    separator: str = ""


def strip_js_wrapper(rule: str) -> str:
    value = (rule or "").strip()
    if value.startswith("@js:"):
        return value[4:]
    if value.startswith("<js>") and "</js>" in value:
        return value[4:value.rfind("</js>")]
    if value.startswith("<js>") and value.endswith("<"):
        return value[4:value.rfind("<")]
    return value


def has_js_rule(rule: str) -> bool:
    value = (rule or "").strip()
    return value.startswith("@js:") or value.startswith("<js>")


def split_top_level(text: str, separators: Sequence[str]) -> List[SplitToken]:
    """Split text by separators, ignoring nested JS/string/bracket regions.

    This mirrors the important Legado RuleAnalyzer behavior needed by native
    rules. It is intentionally conservative: ambiguous separators inside
    quotes, regex literals, braces, brackets, parentheses, or {{...}} are kept.
    """
    if not text:
        return []
    separators = sorted(separators, key=len, reverse=True)
    tokens: List[SplitToken] = []
    start = 0
    i = 0
    depth_round = depth_square = depth_curly = 0
    quote = ""
    escape = False
    in_regex = False
    template_depth = 0

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\" and (quote or in_regex):
            escape = True
            i += 1
            continue

        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue

        if in_regex:
            if ch == "/":
                in_regex = False
            i += 1
            continue

        if ch in ('"', "'", "`"):
            quote = ch
            i += 1
            continue

        if ch == "{" and nxt == "{":
            template_depth += 1
            depth_curly += 1
            i += 2
            continue
        if ch == "}" and nxt == "}" and template_depth:
            template_depth -= 1
            depth_curly = max(0, depth_curly - 1)
            i += 2
            continue

        if ch == "(":
            depth_round += 1
        elif ch == ")":
            depth_round = max(0, depth_round - 1)
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square = max(0, depth_square - 1)
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly = max(0, depth_curly - 1)
        elif ch == "/" and _looks_like_regex_start(text, i):
            in_regex = True
            i += 1
            continue

        if depth_round == depth_square == depth_curly == template_depth == 0:
            for sep in separators:
                if text.startswith(sep, i):
                    tokens.append(SplitToken(text[start:i], sep))
                    i += len(sep)
                    start = i
                    break
            else:
                i += 1
            continue
        i += 1

    tokens.append(SplitToken(text[start:], ""))
    return tokens


def split_text(text: str, separators: Sequence[str], keep_empty: bool = False) -> List[str]:
    values = [token.text for token in split_top_level(text, separators)]
    if keep_empty:
        return values
    return [value for value in values if value != ""]


def _looks_like_regex_start(text: str, index: int) -> bool:
    if index + 1 < len(text) and text[index + 1] in ("/", "*"):
        return False
    j = index - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return False
    return text[j] in "=(:,![{;&|?"


def split_rule_chain(rule: str) -> List[str]:
    if not rule:
        return []
    if has_js_rule(rule):
        return [rule]
    return [part.strip() for part in split_text(rule, ["@"], keep_empty=False) if part.strip()]


def split_fallback_rules(rule: str) -> List[str]:
    return [part.strip() for part in split_text(rule or "", ["||"], keep_empty=False) if part.strip()]


def split_join_rules(rule: str) -> List[str]:
    return [part.strip() for part in split_text(rule or "", ["&&", "%%"], keep_empty=False) if part.strip()]
