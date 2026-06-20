#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified AI client for Transbot — one module for every AI call in the system.

Replaces 4 copy-pasted call_ai implementations (pipeline_common, run_hourly_updater,
command_executor, entity_manager). Adds a priority-ordered provider list with
automatic fallback: a provider that errors, times out, or returns empty is skipped
to the next; a provider that signals rate-limit/quota (HTTP 429 or a body mentioning
rate/quota/provider_account_unavailable) is put in a cooldown so we stop hammering it.
CLI tools (agy, claude) are the final fallback tier.

Config: ai_providers.json at ROOT. If absent, it is bootstrapped from the legacy
ai_config.json (single provider) so nothing breaks on first run.

Public API:
    call_ai(prompt, *, stream=False, temperature=0.2, timeout=240) -> str   # '' on total failure
    call_ai_checked(prompt, **kw) -> (text|None, error|None)                # for the bot
    load_providers() / save_providers(data)                                 # for bot management
"""
import os
import json
import time
import subprocess
import urllib.request
import urllib.error
import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROVIDERS_JSON = ROOT / 'ai_providers.json'
LEGACY_CONFIG = ROOT / 'Temp' / 'ai_config.json'
COOLDOWN_STATE = ROOT / 'Dashboard' / 'data' / 'ai_cooldown.json'

DEFAULT_COOLDOWN = 300  # seconds a rate-limited provider sits out
DEFAULT_CLI_FALLBACK = ['agy', 'claude']

# Signatures in an error body that mean "this provider is rate-limited / out of quota".
_RATELIMIT_MARKERS = ('rate', 'quota', 'provider_account_unavailable',
                      'too many requests', 'insufficient', 'overloaded')


def _log(msg):
    print(f'[{datetime.datetime.now():%H:%M:%S}] [ai_client] {msg}', flush=True)


def clean_env():
    """Minimal env for CLI fallbacks — strips LD_*/DYLD_*/PYTHONHOME so a preload
    meant for the parent never leaks into agy/claude (the old code passed full environ)."""
    keep = {
        'HOME': os.environ.get('HOME', '/data/data/com.termux/files/home'),
        'USER': os.environ.get('USER', 'u0_a146'),
        'LOGNAME': os.environ.get('LOGNAME', os.environ.get('USER', 'u0_a146')),
        'LANG': os.environ.get('LANG', 'C.UTF-8'),
        'LC_ALL': os.environ.get('LC_ALL', 'C.UTF-8'),
        'PATH': '/data/data/com.termux/files/usr/bin:/root/.local/bin:/usr/bin:/bin:/system/bin:/system/xbin',
        'TMPDIR': os.environ.get('TMPDIR', '/data/data/com.termux/files/usr/tmp'),
    }
    env = dict(keep)
    for k, v in os.environ.items():
        if k.startswith(('LD_', 'DYLD_', 'PYTHONHOME')) or k in env:
            continue
        if k.startswith('GOCLAW_'):
            env[k] = v
    return env


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def _write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _bootstrap_from_legacy():
    """Build a providers.json shape from the single-provider ai_config.json."""
    cfg = _read_json(LEGACY_CONFIG, {}) or {}
    prov = {
        'name': 'default',
        'base_url': cfg.get('base_url', 'https://openrouter.ai/api/v1/chat/completions'),
        'api_key': cfg.get('api_key', ''),
        'model': cfg.get('model', 'google/gemini-pro'),
        'priority': 1,
        'enabled': True,
    }
    return {'providers': [prov], 'cli_fallback': list(DEFAULT_CLI_FALLBACK),
            'cooldown_seconds': DEFAULT_COOLDOWN}


def load_providers():
    """Return the providers config dict, bootstrapping from ai_config.json if needed.
    First-time bootstrap is persisted so the bot has a real file to manage."""
    data = _read_json(PROVIDERS_JSON)
    bootstrapped = False
    if not isinstance(data, dict) or not data.get('providers'):
        data = _bootstrap_from_legacy()
        bootstrapped = True
    data.setdefault('cli_fallback', list(DEFAULT_CLI_FALLBACK))
    data.setdefault('cooldown_seconds', DEFAULT_COOLDOWN)
    if bootstrapped:
        try:
            _write_json(PROVIDERS_JSON, data)
        except Exception:
            pass  # read-only FS or race; in-RAM config still works
    return data


def save_providers(data):
    _write_json(PROVIDERS_JSON, data)


# ---------------------------------------------------------------------------
# cooldown state (persisted so a 429 survives across separate process runs)
# ---------------------------------------------------------------------------
def _load_cooldowns():
    return _read_json(COOLDOWN_STATE, {}) or {}


def _save_cooldowns(state):
    _write_json(COOLDOWN_STATE, state)


def _in_cooldown(name, state):
    until = state.get(name, 0)
    return until > time.time()


def _set_cooldown(name, seconds):
    state = _load_cooldowns()
    state[name] = time.time() + seconds
    _save_cooldowns(state)


def cooldown_remaining(name):
    state = _load_cooldowns()
    return max(0, int(state.get(name, 0) - time.time()))


# ---------------------------------------------------------------------------
# HTTP call to one provider
# ---------------------------------------------------------------------------
class _RateLimited(Exception):
    pass


def _parse_stream(response):
    text_parts = []
    for line in response:
        line_str = line.decode('utf-8', 'replace').strip()
        if not line_str:
            continue
        if line_str.startswith('data: '):
            data_content = line_str[6:]
            if data_content == '[DONE]':
                break
            try:
                res = json.loads(data_content)
                ch = res.get('choices', [{}])[0]
                content = ch.get('delta', {}).get('content', '') or \
                    ch.get('message', {}).get('content', '')
                if content:
                    text_parts.append(content)
            except Exception:
                pass
        elif line_str.startswith('{'):
            try:
                res = json.loads(line_str)
                content = res['choices'][0].get('message', {}).get('content', '')
                if content:
                    return content.strip()
            except Exception:
                pass
    return ''.join(text_parts).strip()


def _call_provider(prov, prompt, stream, temperature, timeout, system_prompt=None):
    """One HTTP attempt. Returns text (may be ''), or raises _RateLimited / Exception."""
    base = prov.get('base_url')
    key = prov.get('api_key', '')
    model = prov.get('model')
    if not base or not model:
        raise ValueError('provider missing base_url/model')
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': prompt})
    body = json.dumps({
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'stream': bool(stream),
    }).encode('utf-8')
    req = urllib.request.Request(base, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if stream:
                return _parse_stream(resp)
            data = json.loads(resp.read().decode('utf-8', 'replace'))
            return (data['choices'][0]['message']['content'] or '').strip()
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')
        except Exception:
            pass
        if e.code == 429 or _is_ratelimit(detail):
            raise _RateLimited(f'{e.code}: {detail[:120]}')
        raise Exception(f'HTTP {e.code}: {detail[:120]}')


def _is_ratelimit(text):
    t = (text or '').lower()
    return any(m in t for m in _RATELIMIT_MARKERS)


# ---------------------------------------------------------------------------
# CLI fallback
# ---------------------------------------------------------------------------
_CLI_CMDS = {
    'agy': ['agy', '-p'],
    'claude': ['claude', '-p', '--print'],
}


def _call_cli(tool, prompt, timeout):
    cmd = _CLI_CMDS.get(tool)
    if not cmd:
        return ''
    try:
        result = subprocess.run([*cmd, prompt], capture_output=True, text=True,
                                timeout=timeout, env=clean_env())
        if result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        _log(f'{tool} timeout')
    except Exception as e:
        _log(f'{tool} error: {e}')
    return ''


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def call_ai_checked(prompt, *, stream=False, temperature=0.2, timeout=240, system_prompt=None, max_retries=None):
    """Try every enabled provider in priority order, then CLI fallbacks.
    Returns (text, None) on success, (None, error_summary) if everything failed."""
    if max_retries is None: max_retries = 3
    
    cfg = load_providers()
    cooldowns = _load_cooldowns()
    cooldown_secs = cfg.get('cooldown_seconds', DEFAULT_COOLDOWN)
    providers = sorted((p for p in cfg.get('providers', []) if p.get('enabled', True)),
                       key=lambda p: p.get('priority', 99))
    errors = []
    skipped_cooldown = []

    for attempt in range(max_retries):
        for prov in providers:
            name = prov.get('name', '?')
            if _in_cooldown(name, cooldowns):
                skipped_cooldown.append(name)
                continue
            try:
                text = _call_provider(prov, prompt, stream, temperature, timeout, system_prompt)
                if text:
                    return text, None
                errors.append(f'{name}: empty')
            except _RateLimited as e:
                _log(f'{name} rate-limited -> cooldown {cooldown_secs}s ({e})')
                _set_cooldown(name, cooldown_secs)
                errors.append(f'{name}: ratelimited')
                cooldowns = _load_cooldowns() # Reload cooldowns immediately
            except Exception as e:
                _log(f'{name} error: {e}')
                errors.append(f'{name}: {str(e)[:60]}')
        
        if attempt < max_retries - 1:
            time.sleep(5)

    # CLI fallback tier
    for tool in cfg.get('cli_fallback', []):
        if system_prompt: # CLI tools typically don't support custom system prompt via simple argv
            pass
        text = _call_cli(tool, prompt, timeout)
        if text:
            return text, None
        errors.append(f'{tool}: empty/fail')

    if skipped_cooldown and not providers_available(providers, cooldowns):
        errors.append(f'all providers in cooldown: {skipped_cooldown}')
    return None, '; '.join(errors) or 'no providers configured'


def providers_available(providers, cooldowns):
    return any(not _in_cooldown(p.get('name', '?'), cooldowns) for p in providers)


def call_one_checked(name, prompt, *, stream=False, temperature=0.2, timeout=60, system_prompt=None):
    """Ping a SINGLE provider by name, ignoring cooldown/priority. For /ai_test.
    Returns (text, None) on success or (None, error). Does not set cooldown."""
    cfg = load_providers()
    prov = next((p for p in cfg.get('providers', []) if p.get('name') == name), None)
    if not prov:
        return None, f'không thấy provider {name}'
    try:
        text = _call_provider(prov, prompt, stream, temperature, timeout, system_prompt)
        return (text, None) if text else (None, 'empty response')
    except _RateLimited as e:
        return None, f'ratelimited: {e}'
    except Exception as e:
        return None, str(e)[:120]


def call_ai(prompt, *, stream=False, temperature=0.2, timeout=240, max_retries=None, system_prompt=None):
    """Text-returning variant ('' on failure). max_retries accepted for backward
    compatibility with the old pipeline_common.call_ai(prompt, max_retries=2) shim."""
    text, _err = call_ai_checked(prompt, stream=stream, temperature=temperature, timeout=timeout, system_prompt=system_prompt, max_retries=max_retries)
    return text or ''


if __name__ == '__main__':
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else 'Trả lời đúng một từ: OK'
    txt, err = call_ai_checked(p, stream=False, timeout=60)
    print('TEXT:', txt)
    print('ERR :', err)
