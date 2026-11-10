"""Find tests that read files owned by another bundle and check PR coverage (#7346).

A test that reads another bundle's deployed source is a dependency on that
bundle: when only the read path changes, the reading bundle's PR check must
still run, or main breaks and only the nightly full suite notices
(#7336 -> #7340).

Output: one row per (reading bundle, read bundle) pair with per-file verdicts.

    paired   - every reading test file is run by a PR workflow that also
               triggers on the read path
    unpaired - at least one reading test file is not covered; the workflow
               paths mapping needs the pair (or an explicit allowlist reason)
    unknown  - the reading file's PR suite cannot be resolved statically

Run: python .github/scripts/cross_path_test_reads_7346.py [--json]
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

READ_CALL = re.compile(
    r"\b(read_text|read_bytes|readFileSync|readFile|open|spec_from_file_location|"
    r"exec_module|compile|import_module)\s*\("
)
PATH_LITERAL = re.compile(r"""["']((?:apps|packages)/[^"'\n]+)["']""")
EXTENSION = re.compile(r"\.(py|js|cjs|mjs|ts|tsx|json|toml|ya?ml|md|sql|html|css|txt|sh|ps1|pdf)$")
READ_CONTEXT_LINES = 4

TEST_ROOTS = ("apps", "packages", ".github")


def group_of(path: Path) -> str | None:
    parts = path.relative_to(ROOT).parts
    if parts[0] == "apps" and len(parts) > 1:
        return f"apps/{parts[1]}"
    if parts[0] == "packages" and len(parts) > 1:
        return f"packages/{parts[1]}"
    if parts[0] == ".github":
        return ".github"
    return None


def iter_test_files():
    for base in ("apps", "packages"):
        root = ROOT / base
        if not root.is_dir():
            continue
        for group_dir in sorted(root.iterdir()):
            tests = group_dir / "tests"
            if not tests.is_dir():
                continue
            for pattern in ("*.py", "*.js", "*.cjs", "*.mjs"):
                yield from sorted(tests.rglob(pattern))
    extra = ROOT / ".github" / "tests"
    if extra.is_dir():
        yield from sorted(extra.rglob("*.py"))


def is_file_path(literal: str) -> bool:
    literal = literal.strip()
    if "*" in literal:
        return True
    return bool(EXTENSION.search(literal))


def read_targets(test_file: Path) -> list[dict]:
    try:
        lines = test_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    read_lines = [i for i, line in enumerate(lines) if READ_CALL.search(line)]
    if not read_lines:
        return []
    owner = group_of(test_file)
    found: list[dict] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        for match in PATH_LITERAL.finditer(line):
            literal = match.group(1).strip()
            if not is_file_path(literal):
                continue
            group = literal.split("/")[0] + "/" + literal.split("/")[1]
            if group == owner:
                continue
            near = any(abs(index - r) <= READ_CONTEXT_LINES for r in read_lines)
            if not near:
                target_var = line.split("=")[0].strip()
                near = bool(target_var) and any(
                    target_var in lines[r] and target_var.isidentifier() for r in read_lines
                )
            if not near:
                continue
            key = f"{literal}:{index + 1}"
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "path": literal,
                "group": group,
                "line": index + 1,
                "evidence": line.strip()[:160],
            })
    return found


def pull_request_paths(data: dict) -> list[str] | None:
    on = data.get("on") or data.get(True) or {}
    if isinstance(on, list):
        return None if "pull_request" in on else []
    if not isinstance(on, dict) or "pull_request" not in on:
        return []
    config = on.get("pull_request")
    if not isinstance(config, dict):
        return None
    paths = config.get("paths")
    if paths is None:
        return None
    return [str(p) for p in paths]


def workflow_commands(data: dict) -> list[tuple[str, str]]:
    """(working-directory, run script) for every step, honoring job defaults."""
    commands = []
    jobs = data.get("jobs") or {}
    for job in jobs.values() if isinstance(jobs, dict) else ():
        defaults = (((job or {}).get("defaults") or {}).get("run") or {}).get(
            "working-directory"
        ) or ""
        for step in (job or {}).get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str):
                commands.append((str(step.get("working-directory") or defaults), run))
    return commands


def load_workflows() -> list[dict]:
    result = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        commands = workflow_commands(data)
        suites: set[str] = set()
        for wd, run in commands:
            if not re.search(r"(pytest|node --test|playwright test|npm test|unittest)", run):
                continue
            for group in re.findall(r"((?:apps|packages)/[A-Za-z0-9._-]+)", wd):
                suites.add(group)
            for group in re.findall(r"((?:apps|packages)/[A-Za-z0-9._-]+)/tests", run):
                suites.add(group)
        result.append({
            "file": path.name,
            "paths": pull_request_paths(data),
            "suites": suites,
            "commands": commands,
        })
    return result


def triggers_on(paths: list[str] | None, probe: str) -> bool:
    if paths is None:
        return True
    for pattern in paths:
        if fnmatch.fnmatch(probe, pattern):
            return True
        if pattern.endswith("/**") and probe.startswith(pattern[:-3] + "/"):
            return True
        if pattern.rstrip("/") == probe:
            return True
    return False


def runs_file(workflow: dict, test_file: Path, suite_group: str | None) -> bool:
    rel = str(test_file.relative_to(ROOT)).replace("\\", "/")
    name = test_file.name
    for wd, run in workflow["commands"]:
        if rel in run or name in run:
            return True
        if suite_group == ".github":
            for match in re.finditer(r"discover\s+-s\s+\.github/tests\s+-p\s+(\S+)", run):
                if fnmatch.fnmatch(name, match.group(1)):
                    return True
            if re.search(r"pytest[^\n]*\.github/tests(\s|$)", run) and not re.search(
                r"\.github/tests/[\w.-]+\.py", run
            ):
                return True
            continue
        match = re.search(r"((?:apps|packages)/[A-Za-z0-9._-]+)", wd)
        if not match or match.group(1) != suite_group:
            continue
        if not re.search(r"\b(pytest|node --test|unittest)\b", run):
            continue
        if re.search(r"tests/[\w./*-]+", run):
            if name in run or rel in run:
                return True
            continue
        return True
    return False


def survey() -> dict:
    workflows = load_workflows()
    files: list[dict] = []
    for test_file in iter_test_files():
        owner = group_of(test_file)
        if owner is None:
            continue
        for target in read_targets(test_file):
            runners = [
                w for w in workflows
                if runs_file(w, test_file, owner)
            ]
            triggered = [w for w in runners if triggers_on(w["paths"], target["path"])]
            if not runners:
                verdict = "unknown"
            elif triggered:
                verdict = "paired"
            else:
                verdict = "unpaired"
            files.append({
                "test": str(test_file.relative_to(ROOT)).replace("\\", "/"),
                "suite": owner,
                "reads": target["group"],
                "read_path": target["path"],
                "line": target["line"],
                "evidence": target["evidence"],
                "runners": sorted(w["file"] for w in runners),
                "triggered_by": sorted(w["file"] for w in triggered),
                "verdict": verdict,
            })

    pairs: dict[tuple[str, str], dict] = {}
    for row in files:
        key = (row["suite"], row["reads"])
        pair = pairs.setdefault(key, {
            "suite": row["suite"], "reads": row["reads"], "files": [], "paths": set(),
        })
        pair["files"].append(row)
        pair["paths"].add(row["read_path"])
    rows = []
    for pair in pairs.values():
        verdicts = {f["verdict"] for f in pair["files"]}
        if "unpaired" in verdicts:
            pair["verdict"] = "unpaired"
        elif "unknown" in verdicts:
            pair["verdict"] = "unknown"
        else:
            pair["verdict"] = "paired"
        pair["paths"] = sorted(pair["paths"])
        rows.append(pair)
    rows.sort(key=lambda r: (r["verdict"], r["suite"], r["reads"]))
    return {"pairs": rows, "files": files}


def main() -> int:
    data = survey()
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    counts: dict[str, int] = {}
    for row in data["pairs"]:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        if row["verdict"] == "paired":
            print(f"paired   {row['suite']} -> {row['reads']}  ({len(row['files'])} files)")
            continue
        print(f"{row['verdict']:8} {row['suite']} -> {row['reads']}")
        for entry in row["files"]:
            print(f"   {entry['verdict']:8} {entry['test']}:{entry['line']}  {entry['read_path']}")
            print(f"            runners={entry['runners']}")
    print("counts:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
