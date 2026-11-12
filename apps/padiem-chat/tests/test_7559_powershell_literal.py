"""#7559 / #7560: values placed in PC PowerShell commands stay data.

PowerShell closes a single-quoted string on five characters: ``'`` and the
typographic quotes U+2018, U+2019, U+201A, U+201B. Every command builder now uses
``padiem_ai_core.powershell_literal.ps_literal``, which doubles all five.

Two layers of proof:

* Python checks (always run): the shared literal doubles each quote, and each
  builder places a hostile value only as that literal.
* PowerShell parser checks (run where ``pwsh`` is on PATH, as on the GitHub
  ubuntu/windows runners): the built commands parse without errors, a hostile
  value adds no statement compared with a plain value, the injected command name
  never appears as a command, and each literal parses back to the exact text.
  Nothing is executed; only ``Parser.ParseInput`` runs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from padiem_ai_core.powershell_literal import PS_SINGLE_QUOTES, ps_literal  # noqa: E402

import app.pc_file_exchange_routes as exchange  # noqa: E402
from app.claw_pc_read_command import pc_read_chunk_command  # noqa: E402
from app.claw_pc_search_command import pc_search_command  # noqa: E402
from app.oracle_mesh_read_return_routes import (  # noqa: E402
    _pc_files_command,
    _pc_write_command,
)
from kagent.local_agent_oracle_mesh_executor import (  # noqa: E402
    _ps_literal_for_root,
    _single_roundtrip_script,
)

INJECTED = "Invoke-PadiemInjected"
QUOTES = ("'", "\u2018", "\u2019", "\u201a", "\u201b")
#: One hostile value per quote character, each trying to close the string, run a
#: command and reopen it; plus the other characters a double-quoted context or a
#: careless builder would treat as syntax.
HOSTILE = tuple(
    "a" + close + ";" + INJECTED + ";" + reopen + "b"
    for close in QUOTES for reopen in QUOTES
) + (
    "a`$(" + INJECTED + ")b",
    "a$(" + INJECTED + ")b",
    "a;" + INJECTED + ";b",
)
#: Ordinary names that must keep working: an English possessive, Korean, spaces.
ORDINARY = ("John's report", "John\u2019s report", "분기 보고서", "a b  c")
PLAIN = "plain"


def _doubled(value: str) -> str:
    """The expected literal content, written out here rather than imported."""
    for quote in QUOTES:
        value = value.replace(quote, quote + quote)
    return value

ROOT = "C:/Users/qa/문서"
WIN_ROOT = "C:\\Users\\qa\\문서\\"
BACKUP_DIR = "C:\\.padiem-backup\\20261112"


# --- the shared literal ----------------------------------------------------


def test_the_literal_doubles_every_powershell_single_quote():
    assert PS_SINGLE_QUOTES == frozenset(QUOTES)
    for quote in QUOTES:
        assert ps_literal("x" + quote + "y") == "'x" + quote + quote + "y'"
    assert ps_literal("") == "''"
    assert ps_literal("`$(a); b\nc") == "'`$(a); b\nc'"


def test_the_literal_refuses_what_is_not_text():
    with pytest.raises(ValueError):
        ps_literal("a\x00b")
    with pytest.raises(TypeError):
        ps_literal(None)  # type: ignore[arg-type]


# --- every builder --------------------------------------------------------


def _write(value: str) -> str:
    return _pc_write_command(
        op="move", root=WIN_ROOT, target=WIN_ROOT + value, backup_dir=BACKUP_DIR,
        relative=value, destination=WIN_ROOT + value + "-moved",
    )


def _delete(value: str) -> str:
    return _pc_write_command(
        op="delete", root=WIN_ROOT, target=WIN_ROOT + value, backup_dir=BACKUP_DIR,
        relative=value,
    )


def _list(value: str) -> str:
    return _pc_files_command(op="list", root=ROOT, relative=value, filter_term=value)


def _search(value: str) -> str:
    return pc_search_command(roots=[{"label": "문서", "path": ROOT}], query=value, mode="content")


def _read(value: str) -> str:
    return pc_read_chunk_command(root=ROOT, relative=value + ".txt", offset=0, length=1024)


def _seed(value: str) -> str:
    return exchange._seed_search_command([{"path": ROOT}, {"path": ROOT + "/" + value}], value)


def _sweep(value: str) -> str:
    return exchange._sweep_command(ROOT + "/" + value, value)


def _executor(value: str) -> str:
    return _single_roundtrip_script(
        granted_root=WIN_ROOT, file_path=WIN_ROOT + value + ".txt", max_bytes=1024,
    )


BUILDERS = {
    "write_move": _write,
    "write_delete": _delete,
    "files_list": _list,
    "search": _search,
    "read_chunk": _read,
    "find_seed": _seed,
    "find_sweep": _sweep,
    "executor_read": _executor,
}


@pytest.mark.parametrize("name", sorted(BUILDERS))
@pytest.mark.parametrize("value", HOSTILE)
def test_a_hostile_value_reaches_the_command_only_as_the_shared_literal(name, value):
    command = BUILDERS[name](value)
    assert _doubled(value) in command
    # No quote character from the value survives undoubled next to the injected name.
    for quote in QUOTES:
        assert quote + ";" + INJECTED not in command.replace(quote + quote, "")


def test_the_executor_root_literal_is_the_shared_literal():
    assert _ps_literal_for_root("C:\\a\u2019b") == "'C:\\a\u2019\u2019b'"


def test_a_find_name_is_wildcard_escaped_on_the_pc_after_powershell_reads_it():
    command = _sweep("2026*보고서")
    assert "WildcardPattern]::Escape('2026*보고서')" in command
    assert "-like $padiemFindPattern" in command
    hostile = _seed("it\u2019s';" + INJECTED + ";'")
    assert "Escape('" + _doubled("it\u2019s';" + INJECTED + ";'") + "')" in hostile


# --- the PowerShell parser ------------------------------------------------

_PWSH = shutil.which("pwsh")

_PARSE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$cases = [Console]::In.ReadToEnd() | ConvertFrom-Json
$out = foreach ($case in $cases) {
  $tokens = $null; $errors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$case.script, [ref]$tokens, [ref]$errors)
  $statements = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.StatementAst] }, $true).Count
  $injected = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Invoke-PadiemInjected' }, $true).Count
  $value = $null
  if ($case.literal) {
    $const = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.StringConstantExpressionAst] }, $true)
    if ($const) { $value = $const.Value }
  }
  [pscustomobject]@{ id = $case.id; errors = @($errors).Count; statements = $statements; injected = $injected; value = $value }
}
@($out) | ConvertTo-Json -Depth 3 -Compress
"""


def _parse(cases: list[dict]) -> dict:
    completed = subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", _PARSE_SCRIPT],
        input=json.dumps(cases, ensure_ascii=False), capture_output=True,
        text=True, encoding="utf-8", timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    rows = json.loads(completed.stdout)
    rows = rows if isinstance(rows, list) else [rows]
    return {row["id"]: row for row in rows}


@pytest.mark.skipif(_PWSH is None, reason="pwsh is not on PATH (runs on the GitHub runners)")
def test_powershell_parses_every_command_with_no_extra_statement():
    cases = []
    for name, build in BUILDERS.items():
        cases.append({"id": name + "|plain", "script": build(PLAIN)})
        for index, value in enumerate(HOSTILE + ORDINARY):
            cases.append({"id": "%s|%d" % (name, index), "script": build(value)})
    parsed = _parse(cases)
    for name in BUILDERS:
        base = parsed[name + "|plain"]
        assert base["errors"] == 0, name
        for index, value in enumerate(HOSTILE + ORDINARY):
            row = parsed["%s|%d" % (name, index)]
            assert row["errors"] == 0, (name, value)
            assert row["injected"] == 0, (name, value)
            assert row["statements"] == base["statements"], (name, value)


@pytest.mark.skipif(_PWSH is None, reason="pwsh is not on PATH (runs on the GitHub runners)")
def test_powershell_reads_each_literal_back_as_the_exact_text():
    values = HOSTILE + ORDINARY + ("line\nbreak", "tab\tand `backtick", "")
    cases = [{"id": "plain", "script": ps_literal(PLAIN), "literal": True}]
    cases += [{"id": str(i), "script": ps_literal(v), "literal": True} for i, v in enumerate(values)]
    parsed = _parse(cases)
    # A lone literal is one pipeline holding one expression; compare with that
    # shape rather than a fixed node count.
    base = parsed["plain"]
    assert base["errors"] == 0 and base["value"] == PLAIN
    for index, value in enumerate(values):
        row = parsed[str(index)]
        assert row["errors"] == 0, value
        assert row["statements"] == base["statements"], value
        assert row["injected"] == 0, value
        assert (row["value"] or "") == value, value
