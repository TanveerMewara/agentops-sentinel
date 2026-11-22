"""Offline readiness diagnostic for the native, Docker-free Sentinel installation."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import dev
import native_postgres
from sentinel.database import Database

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = {}
    checks['python_3_11_or_newer'] = sys.version_info >= (3, 11)
    for module in ('fastapi', 'psycopg', 'langgraph', 'openai', 'sentinel.main'):
        try:
            importlib.import_module(module); checks['import_' + module.replace('.', '_')] = True
        except Exception:
            checks['import_' + module.replace('.', '_')] = False
    node = next(iter(sorted((ROOT / '.local').glob('node-*-win-x64/node.exe'), reverse=True)), None)
    checks['bundled_node'] = bool(node and node.is_file())
    checks['frontend_dependencies'] = (ROOT / 'web' / 'node_modules' / 'vinext').is_dir()
    checks['frontend_build'] = (ROOT / 'web' / 'dist' / 'server').is_dir()
    checks['gitignore_local_secrets'] = '.local/' in (ROOT / '.gitignore').read_text(encoding='utf-8')
    try:
        dev.setup()
        with Database(native_postgres.dsn()).connect() as connection:
            checks['postgres_ready'] = connection.execute('SELECT 1 AS ready').fetchone()['ready'] == 1
        config = dev.load_config()
        checks['local_credentials'] = all(config.get(name) for name in
            ('auth_pepper', 'credential_encryption_key', 'keys'))
    except Exception:
        checks['postgres_ready'] = False; checks['local_credentials'] = False
    checks['pip_dependencies'] = subprocess.run([sys.executable, '-m', 'pip', 'check'],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    report = {'schema_version': 1, 'passed': all(checks.values()), 'checks': checks,
              'docker_required': False}
    target = ROOT / '.local' / 'release-checks' / 'install.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
