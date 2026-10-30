"""Fail if the retired model selector reappears outside approved refusals."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
NEEDLES = ('b14' + '/auto', 'business14' + '/auto', 'RouteMode' + '.AUTO')
GATEWAY = 'apps/korean-ai-platform/app/pilot/gateway.py'
GATEWAY_ALLOWED = frozenset({
    'if model == "b14' + '/auto":',
    '# The retired b14' + '/auto id is rejected as a string (B1/B7 pattern):',
    'raise _InvalidBody("b14' + '/auto is retired; select a Business 14 catalog model.")',
})

def test_retired_route_is_not_reintroduced():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    bad = []
    for rel in tracked:
        if not rel.startswith(('apps/', 'packages/', 'scripts/', '.github/')):
            continue
        if not rel.endswith(('.py', '.js', '.ts', '.json', '.toml', '.yml', '.yaml', '.sh', '.ps1', '.html', '.md')):
            continue
        path = ROOT / rel
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            if not any(token in line for token in NEEDLES):
                continue
            if rel == GATEWAY and line.strip() in GATEWAY_ALLOWED:
                continue
            bad.append(f'{rel}:{number}')
    assert not bad, 'Retired route references need classification/removal:\n' + '\n'.join(bad)
