"""Fail if the retired model selector reappears outside approved refusals."""
from pathlib import Path
import ast
import subprocess

ROOT = Path(__file__).resolve().parents[3]
NEEDLES = (
    'b14' + '/auto', 'business14' + '/auto', 'RouteMode' + '.AUTO',
    'AUTO_' + 'B14_MODEL_ID', 'B14_' + 'AUTO_MODEL_ID',
    'auto_' + 'stream_gateway', 'ensure_generic_' + 'auto_enabled',
    'B14_ENABLE_' + 'FUTURE_AUTO',
)
GATEWAY = 'apps/korean-ai-platform/app/pilot/gateway.py'
REFUSAL_TEST = 'apps/korean-ai-platform/tests/test_5824_b14_user_credential.py'
REFUSAL_FUNCTION = 'test_b14_auto_is_not_served_by_a_request_key'
GATEWAY_ALLOWED = frozenset({
    'if model == "b14' + '/auto":',
    '# The retired b14' + '/auto id is rejected as a string (B1/B7 pattern):',
    'raise _InvalidBody("b14' + '/auto is retired; select a Business 14 catalog model.")',
})

def test_retired_route_is_not_reintroduced():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    bad = []
    for rel in tracked:
        if not rel.startswith(('apps/', 'packages/', 'scripts/', '.github/', 'docs/')):
            continue
        if rel.startswith(('docs/operations/', 'docs/history/')):
            continue
        if not rel.endswith(('.py', '.js', '.ts', '.json', '.toml', '.yml', '.yaml', '.sh', '.ps1', '.html', '.md')):
            continue
        path = ROOT / rel
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError):
            continue
        approved_lines = set()
        if rel == REFUSAL_TEST:
            tree = ast.parse('\n'.join(lines), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == REFUSAL_FUNCTION:
                    approved_lines.update(range(node.lineno, node.end_lineno + 1))
        for number, line in enumerate(lines, 1):
            if not any(token in line for token in NEEDLES):
                continue
            if rel == GATEWAY and line.strip() in GATEWAY_ALLOWED:
                continue
            if number in approved_lines:
                continue
            bad.append(f'{rel}:{number}')
    assert not bad, 'Retired route references need classification/removal:\n' + '\n'.join(bad)
