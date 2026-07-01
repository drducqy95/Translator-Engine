#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe launcher for Translator Engine scripts.

Purpose:
- Run engine scripts with a clean environment.
- Support OS-level auto-start wrappers.
"""

import os
import sys
import subprocess
from pathlib import Path

ROOT = Path('/sdcard/My Agent/Translator Engine')
SCRIPT_DIR = ROOT / 'Script'

SCRIPT_MAP = {
    'telegram_bot': ROOT / 'telegram_bot_v2.py',
    'telegram_bot_keepalive': ROOT / 'bin' / 'telegram_bot_keepalive.sh',
    'hymt_server': ROOT / 'bin' / 'hymt_server.sh',
    'hymt_keepalive': ROOT / 'bin' / 'hymt_keepalive.sh',
}

BAD_ENV_PREFIXES = ('LD_', 'DYLD_', 'PYTHONHOME')


def clean_env():
    env = {}
    env.update({
        'HOME': os.environ.get('HOME', '/data/data/com.termux/files/home'),
        'USER': os.environ.get('USER', 'u0_a146'),
        'LOGNAME': os.environ.get('LOGNAME', os.environ.get('USER', 'u0_a146')),
        'LANG': os.environ.get('LANG', 'C.UTF-8'),
        'LC_ALL': os.environ.get('LC_ALL', 'C.UTF-8'),
        'PATH': '/data/data/com.termux/files/usr/bin:/root/.local/bin:/usr/bin:/bin:/system/bin:/system/xbin',
        'TMPDIR': os.environ.get('TMPDIR', '/data/data/com.termux/files/usr/tmp'),
    })
    for key, value in os.environ.items():
        if key.startswith(BAD_ENV_PREFIXES) or key in env:
            continue
        if key.startswith('GOCLAW_'):
            env[key] = value
    return env


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SCRIPT_MAP:
        print('Usage: safe_run.py <script>')
        print('Available:', ', '.join(sorted(SCRIPT_MAP)))
        sys.exit(2)

    target = SCRIPT_MAP[sys.argv[1]]
    maintenance_lock = ROOT / 'Temp' / 'MAINTENANCE.lock'
    if maintenance_lock.exists() and sys.argv[1] in {'telegram_bot', 'telegram_bot_keepalive', 'hymt_server', 'hymt_keepalive'}:
        print(f'Maintenance lock present: {maintenance_lock}')
        sys.exit(0)
    if not target.exists():
        print(f'ERROR: script not found: {target}')
        sys.exit(1)

    env = clean_env()
    if target.suffix == '.sh':
        cmd = ['/usr/bin/env', 'bash', str(target), *sys.argv[2:]]
    else:
        python = sys.executable or '/data/data/com.termux/files/usr/bin/python3'
        cmd = [python, str(target), *sys.argv[2:]]

    print('Safe runner executing:')
    print('  target:', target)
    print('  cwd:', ROOT)
    print('  LD_* stripped: yes')

    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True)
    sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
