# -*- coding: utf-8 -*-
"""check_venv_freshness — 로컬 venv의 저장소 내부 공유 패키지 낡음 점검.

실제로 반복된 문제(#6316/#6325 이후 test_2824·test_oracle_mesh 실패, #6342 작업
중 util 회귀 22건 실패): 각 앱 venv에 복사 설치된 공유 패키지(padiem-ai-core,
padiem-control-plane 등)가 저장소 소스보다 오래돼, 낡은 설치본이 진짜 결함을
가리거나 가짜 실패를 만든다. 이 도구는 선언(각 앱의 uv.lock directory 소스)과
실제 설치본 파일을 해시 비교해 그 격차를 한 번에 보고한다.

발견 규칙:
  * 대상 앱 = ``apps/<name>/`` 에 pyproject.toml과 uv.lock이 함께 있는 앱.
    uv.lock을 tomllib로 읽고 트리 전체에서 ``directory = ".../packages/<dir>"``
    형태의 로컬 소스 매핑을 수집한다(``[[package]]`` 항목의 ``source``와
    manifest 의존 항목 두 형태를 모두 커버 — uv 버전에 따라 위치가 다르다).
  * 설치본 = ``apps/<name>/.venv`` 의 site-packages. Editable 설치
    (``direct_url.json`` 의 ``editable: true``)는 소스를 직접 로드하므로
    FRESH로 판정한다. 이 스크립트가 그 설치를 고치지 않는다.
  * 비교 = 소스 패키지 디렉토리와 site-packages 복사본의 파일 sha256 대조.
    ``__pycache__`` 와 ``*.pyc`` 는 실행 산물이라 제외한다.

사용:
  python scripts/dev/check_venv_freshness.py                 # 전체 앱 보고
  python scripts/dev/check_venv_freshness.py --app padiem-chat
  python scripts/dev/check_venv_freshness.py --json          # 기계 판독
  python scripts/dev/check_venv_freshness.py --fix           # STALE만 재설치

--fix는 STALE 패키지에 한해 ``uv sync --locked --reinstall-package <pkg>`` 를
해당 앱 디렉토리에서 실행한다(문서 docs/operations/WINDOWS_LOCAL_TEST_SETUP.md
의 워크플로와 같은 잠금 경로). 기본은 보고만이며, 다른 레인의 venv를 고치지
않도록 --repo-root로 범위를 좁혀 실행하는 것을 권한다.

종료 코드: 모두 FRESH(또는 점검 대상 0) = 0, STALE 또는 MISSING 존재 = 1.
MISSING은 "잠겨 있는데 설치본이 없다"는 깨진 상태로 FRESH가 아니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

EXCLUDED_DIRS = {"__pycache__", ".git", "tests", ".pytest_cache", "*.egg-info"}
SKIP_SUFFIXES = (".pyc", ".pyo")


def find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit(f"no git repository above {start}")


def app_candidates(repo_root: Path) -> list[str]:
    apps = []
    for pyproject in sorted((repo_root / "apps").glob("*/pyproject.toml")):
        app_dir = pyproject.parent
        if (app_dir / "uv.lock").is_file():
            apps.append(app_dir.name)
    return apps


def collect_directory_sources(node: object) -> dict[str, str]:
    """Walk a parsed uv.lock and collect every {name, directory} source mapping.

    uv puts the local-path mapping in two places depending on the section and
    uv version: a package entry's ``source = { directory = ... }`` and the
    manifest's ``{ name = ..., directory = ... }`` dependency rows. Both carry
    the same meaning for this check, so the walker keeps them together.
    """
    found: dict[str, str] = {}
    if isinstance(node, dict):
        if (
            isinstance(node.get("name"), str)
            and isinstance(node.get("directory"), str)
        ):
            found[node["name"]] = node["directory"]
        if isinstance(node.get("source"), dict):
            source = node["source"]
            if isinstance(source.get("directory"), str) and isinstance(node.get("name"), str):
                found[node["name"]] = source["directory"]
        for value in node.values():
            found.update(collect_directory_sources(value))
    elif isinstance(node, list):
        for item in node:
            found.update(collect_directory_sources(item))
    return found


def locked_local_packages(app_dir: Path, repo_root: Path) -> dict[str, Path]:
    """Return {dist name: absolute source dir} for repo-internal locked deps."""
    lock_path = app_dir / "uv.lock"
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)
    mapping: dict[str, Path] = {}
    for name, relative in collect_directory_sources(lock).items():
        source_dir = (app_dir / relative).resolve()
        # 저장소 밖 경로는 이 점검의 대상이 아니다(외부 패키지는 잠금 버전이 정본).
        if source_dir.is_relative_to(repo_root):
            mapping[name] = source_dir
    return mapping


def venv_site_packages(venv_dir: Path) -> Path | None:
    candidates = [venv_dir / "Lib" / "site-packages"]
    candidates.extend(sorted((venv_dir / "lib").glob("python*/site-packages")))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def source_import_roots(source_dir: Path) -> dict[str, Path]:
    """Map {import name: source package dir} the same way setuptools.find does.

    The source pyproject's ``[tool.setuptools.packages.find]`` decides where to
    look (``where`` — the src layout used by korean-ai-code-agent points at
    ``src``) and which names to keep (``include`` globs). Without that section,
    a direct subdirectory holding ``__init__.py`` is the import root.
    """
    where_dirs = [source_dir]
    include_globs: list[str] | None = None
    pyproject = source_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            with pyproject.open("rb") as handle:
                config = tomllib.load(handle)
            find_cfg = config.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
            where_names = find_cfg.get("where")
            if isinstance(where_names, str):
                where_names = [where_names]
            if isinstance(where_names, list) and where_names:
                where_dirs = [source_dir / name for name in where_names]
            include_names = find_cfg.get("include")
            if isinstance(include_names, list) and include_names:
                include_globs = [str(glob) for glob in include_names]
        except (tomllib.TOMLDecodeError, OSError):
            pass
    roots: dict[str, Path] = {}
    import fnmatch

    for base in where_dirs:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name in EXCLUDED_DIRS or child.name.endswith(".egg-info"):
                continue
            if not (child / "__init__.py").is_file():
                continue
            if include_globs is not None and not any(fnmatch.fnmatch(child.name, glob) for glob in include_globs):
                continue
            roots[child.name] = child
    return roots


def find_installed(site_packages: Path, import_name: str) -> tuple[Path | None, dict | None]:
    """Locate the installed copy: (package dir, dist-info metadata dict)."""
    installed = site_packages / import_name
    if not installed.is_dir():
        return None, None
    meta: dict = {}
    for dist_info in sorted(site_packages.glob(f"{import_name.replace('_', '-')}-*.dist-info")):
        direct_url = dist_info / "direct_url.json"
        if direct_url.is_file():
            try:
                meta = json.loads(direct_url.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        meta.setdefault("dist_info", str(dist_info))
        break
    return installed, meta


def iter_files(base: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in path.relative_to(base).parts):
            continue
        if rel.endswith(SKIP_SUFFIXES):
            continue
        files[rel] = path
    return files


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_package(import_name: str, source_dir: Path, site_packages: Path) -> dict:
    installed, dist_meta = find_installed(site_packages, import_name)
    if installed is None:
        return {"import_name": import_name, "state": "MISSING", "differences": 0, "examples": []}
    if dist_meta and isinstance(dist_meta.get("dir_info"), dict) and dist_meta["dir_info"].get("editable"):
        return {
            "import_name": import_name,
            "state": "FRESH",
            "differences": 0,
            "examples": [],
            "note": "editable install loads the repo source directly",
        }
    sources = iter_files(source_dir)
    installed_files = iter_files(installed)
    differing = [rel for rel, path in sources.items()
                 if rel in installed_files and sha256_of(path) != sha256_of(installed_files[rel])]
    missing = [rel for rel in sources if rel not in installed_files]
    extra = [rel for rel in installed_files if rel not in sources]
    differences = len(differing) + len(missing) + len(extra)
    # 예시는 import 루트가 아니라 패키지 기준 경로로 보여준다 — 보고를 읽는
    # 사람이 어느 파일인지 바로 찾을 수 있게.
    examples = [f"{import_name}/{rel}" for rel in (differing + missing + extra)[:3]]
    return {
        "import_name": import_name,
        "state": "FRESH" if differences == 0 else "STALE",
        "differences": differences,
        "examples": examples,
        "installed_version": _installed_version(site_packages, import_name),
    }


def _installed_version(site_packages: Path, import_name: str) -> str | None:
    for dist_info in sorted(site_packages.glob(f"{import_name.replace('_', '-')}-*.dist-info")):
        return dist_info.name[len(import_name.replace('_', '-')) + 1:-len(".dist-info")]
    return None


def fix_package(app_dir: Path, dist_name: str) -> tuple[bool, str]:
    """Reinstall one stale package through the documented locked sync path."""
    uv_cmd = [sys.executable, "-m", "uv"] if shutil.which("uv") is None else ["uv"]
    command = [*uv_cmd, "sync", "--locked", "--reinstall-package", dist_name]
    try:
        completed = subprocess.run(
            command, cwd=app_dir, capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"uv 실행 실패: {exc}"
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-3:]
        return False, "uv sync 실패 (exit %d): %s" % (completed.returncode, " | ".join(tail))
    return True, " ".join(command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="기본: 이 스크립트가 속한 git 저장소 루트")
    parser.add_argument("--app", action="append", default=None,
                        help="점검할 앱 이름(반복 가능). 기본: 전체")
    parser.add_argument("--fix", action="store_true",
                        help="STALE 패키지에 한해 uv sync --reinstall-package 실행")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args()

    repo_root = args.repo_root or find_repo_root(Path(__file__).resolve())
    wanted = args.app or app_candidates(repo_root)
    unknown = sorted(set(wanted) - set(app_candidates(repo_root)))
    if unknown:
        parser.error(f"uv.lock을 가진 앱이 아님: {', '.join(unknown)}")

    report: dict = {"repo_root": str(repo_root), "apps": []}
    any_stale = False

    for app_name in wanted:
        app_dir = repo_root / "apps" / app_name
        locked = locked_local_packages(app_dir, repo_root)
        app_entry: dict = {"app": app_name, "packages": []}
        if not locked:
            app_entry["skipped"] = "uv.lock에 저장소 내부 소스가 없다"
            report["apps"].append(app_entry)
            continue
        venv_dir = app_dir / ".venv"
        site_packages = venv_site_packages(venv_dir)
        if site_packages is None:
            app_entry["skipped"] = ".venv가 없다 — uv sync로 환경을 만든 뒤 점검"
            report["apps"].append(app_entry)
            continue
        source_roots: dict[str, dict[str, Path]] = {}
        for dist_name, source_dir in locked.items():
            source_roots[dist_name] = source_import_roots(source_dir)
        for dist_name, source_dir in locked.items():
            roots = source_roots[dist_name]
            if not roots:
                app_entry["packages"].append({
                    "dist_name": dist_name, "state": "MISSING",
                    "note": f"소스에서 import 루트를 못 찾음: {source_dir}",
                })
                any_stale = True
                continue
            for import_name, import_dir in roots.items():
                outcome = compare_package(import_name, import_dir, site_packages)
                outcome["dist_name"] = dist_name
                outcome["source_dir"] = str(import_dir)
                if outcome["state"] == "STALE" and args.fix:
                    ok, detail = fix_package(app_dir, dist_name)
                    recheck = compare_package(import_name, import_dir, site_packages)
                    outcome["fix"] = {"ran": detail, "ok": ok, "state_after": recheck["state"]}
                    if recheck["state"] == "STALE":
                        any_stale = True
                    elif ok:
                        outcome["state"] = "FRESH"
                elif outcome["state"] == "STALE":
                    any_stale = True
                elif outcome["state"] == "MISSING":
                    any_stale = True
                app_entry["packages"].append(outcome)
        report["apps"].append(app_entry)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)
    return 1 if any_stale else 0


def print_human(report: dict) -> None:
    print(f"저장소: {report['repo_root']}")
    for app in report["apps"]:
        if app.get("skipped"):
            print(f"\n[{app['app']}] 건너뜀 — {app['skipped']}")
            continue
        print(f"\n[{app['app']}] (.venv)")
        for pkg in app["packages"]:
            line = f"  {pkg['dist_name']} ({pkg['import_name']}): {pkg['state']}"
            if pkg.get("installed_version"):
                line += f" — 설치 버전 {pkg['installed_version']}"
            if pkg.get("note"):
                line += f" — {pkg['note']}"
            print(line)
            if pkg["state"] == "STALE":
                print(f"    차이 파일 {pkg['differences']}개, 예시:")
                for example in pkg["examples"]:
                    print(f"      - {example}")
            if pkg.get("fix"):
                fix = pkg["fix"]
                mark = "성공" if fix["ok"] else "실패"
                print(f"    --fix {mark}: {fix['ran']} → 재검증 {fix['state_after']}")
    stale = sum(
        1 for app in report["apps"] for pkg in app.get("packages", [])
        if pkg["state"] == "STALE"
    )
    missing = sum(
        1 for app in report["apps"] for pkg in app.get("packages", [])
        if pkg["state"] == "MISSING"
    )
    fresh = sum(
        1 for app in report["apps"] for pkg in app.get("packages", [])
        if pkg["state"] == "FRESH"
    )
    print(f"\n요약: FRESH {fresh} / STALE {stale} / MISSING {missing}")
    if stale or missing:
        print("로컬 테스트를 돌리기 전에 --fix로 재설치하거나 uv sync를 먼저 실행하라.")


if __name__ == "__main__":
    raise SystemExit(main())
