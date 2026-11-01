"""Static asset content-hash versioning for the council apps entry.

2026-11-01: 배포 후에도 Cloudflare가 옛 JS·CSS를 최대 4시간 내보낸 일이 있었다.
원인은 진입 HTML이 버전 없는 자산 URL(``./static/council-app.js``)을 가리켜
새 배포가 엣지 캐시에 가려진 것. 이 모듈은 앱이 직접 서빙하는 모든 정적 파일에
짧은 내용 해시를 붙이고, 진입 HTML의 로컬 참조를 ``?v=<해시>`` 로 바꾼다.

- 서빙 때 자동: ``app_factory.create_app()`` 가 시작마다 다시 해시를 계산해
  대입한다(배포 = 프로세스 시작이므로 별도 빌드 단계가 없어도 항상 새 값).
- 정적 호스팅 배포 때: ``python -m app.asset_versions --write`` 로 미리 굽는다.
- 규칙: 이 앱이 소유한 참조(``./static/…``, ``/static/…``)만 바꾼다. 호스트가
  제공하는 ``/padiem-themes.css`` 등 외부 자산은 손대지 않는다.
- 진입 HTML에는 JS 동적 로더(photo-resize.js, pc-file-exchange.js/css)가 읽는
  버전 지도를 ``<script type="application/json" id="padiem-asset-versions">``
  로 실어 보낸다.
- 캐시 헤더: HTML은 ``Cache-Control: no-cache``(매 요청 재검증), 해시가 붙은
  자산 URL은 내용이 바뀌면 URL 자체가 바뀌므로 1년 불변 캐시가 안전한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
MAP_SCRIPT_ID = "padiem-asset-versions"
HASH_LENGTH = 8
ENTRY_NAME = "index.html"

# href/src에 실린 로컬 static 경로: (접두사, URL, 파일 상대경로, 닫는 따옴표).
# 이미 ?v=가 붙은 참조도 통째로 받아 현재 해시로 되쓴다 — 굽은 진입을 다시
# 대입해도 기존 해시가 남지 않는 진짜 멱등성(내용이 바뀌면 URL이 따라 바뀐다).
STATIC_REF = re.compile(r'((?:href|src)=")((?:\./|/)?static/([^"#?]+))(?:\?[^"#]*)?(")')
OLD_MAP = re.compile(
    r'<script type="application/json" id="' + MAP_SCRIPT_ID + r'">.*?</script>', re.S)


def canonical_asset_bytes(data: bytes) -> bytes:
    r"""OS-independent hash input: NUL-free (text-treated) files hash their
    CRLF→LF normalized form, everything else hashes the raw bytes.

    Git stores text blobs LF-normalized, so a Windows checkout with
    core.autocrlf=true materializes them CRLF while CI's Linux checkout keeps
    LF — the same reviewed file must hash the same in both (#6578: a ?v= entry
    baked on Windows failed the bake-freshness test on Linux). The NUL check is
    the same axis as git's own binary detection: a file git would convert is
    normalized here, a file git leaves byte-exact is hashed raw.
    """
    if b"\0" in data:
        return data
    return data.replace(b"\r\n", b"\n")


def short_hash(data: bytes) -> str:
    return hashlib.sha1(canonical_asset_bytes(data)).hexdigest()[:HASH_LENGTH]


def compute_versions(static_dir: Path = STATIC_DIR) -> dict[str, str]:
    """서빙하는 자산(진입 HTML 제외) → {상대 경로: 짧은 내용 해시}.

    진입 index.html은 no-cache로 매 요청 재검증되므로 버전이 필요 없고,
    자기 자신을 지도에 넣으면 지도를 쓸 때마다 자기 해시가 바뀌어 멱등성이 깨진다.
    """
    versions: dict[str, str] = {}
    for path in sorted(static_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(static_dir).as_posix()
        if rel == ENTRY_NAME:
            continue
        versions[rel] = short_hash(path.read_bytes())  # short_hash normalizes per canonical_asset_bytes
    return versions


def version_map_script(versions: dict[str, str]) -> str:
    payload = json.dumps(versions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f'<script type="application/json" id="{MAP_SCRIPT_ID}">{payload}</script>'


def _rewrite(reference: "re.Match[str]", versions: dict[str, str]) -> str:
    prefix = reference.group(1)
    url = reference.group(2)
    rel = reference.group(3)
    quote = reference.group(4)
    digest = versions.get(rel)
    if not digest:
        return reference.group(0)
    return f"{prefix}{url.split('?')[0]}?v={digest}{quote}"


def versioned_html(html: str, versions: dict[str, str]) -> str:
    """로컬 static 참조에 ``?v=<내용 해시>`` 를 붙이고 버전 지도를 주입한다.

    멱등하다: 이미 버전이 붙은 입력도 같은 출력이 나오므로, 미리 구운 파일과
    서빙 때의 재대입이 겹쳐도 쿼리 문자열이 누적되지 않는다.
    """
    out = STATIC_REF.sub(lambda m: _rewrite(m, versions), html)
    marker = version_map_script(versions)
    if OLD_MAP.search(out):
        return OLD_MAP.sub(lambda _: marker, out)
    return out.replace("</head>", "  " + marker + "\n</head>", 1)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    static_dir = STATIC_DIR
    if "--static-dir" in argv:
        i = argv.index("--static-dir")
        static_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    versions = compute_versions(static_dir)
    index_path = static_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    baked = versioned_html(html, versions)
    if "--write" in argv:
        index_path.write_text(baked, encoding="utf-8")
        print(f"wrote versioned entry: {index_path} ({len(versions)} assets)")
        return 0
    if "--check" in argv:
        unbaked = MAP_SCRIPT_ID not in html and not OLD_MAP.search(html) and "?v=" not in html
        if baked == html or (unbaked and baked != html):
            # 미구운 정본이면 서빙 때 버전을 붙이므로 그대로 정상이다. 구운 파일은
            # 현재 해시와 어긋나면 탈락한다.
            if baked == html or unbaked:
                print("entry is current (baked hashes match, or server-side versioning active)")
                return 0
        print("entry is stale: local static references do not carry current content hashes")
        return 1
    print("usage: python -m app.asset_versions [--static-dir PATH] (--write | --check)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
