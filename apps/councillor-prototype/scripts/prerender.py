"""Build-time prerender and thumbnail helpers for the councillor site.

The source keeps the .html containers empty so the plain local preview still runs
the client-side renderer. The dist build injects the same content as static HTML
so the first paint has the final height (CLS) and no-JS visitors still see the
records. Activity rows are enhanced in place; other renderers keep their existing behavior.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def _href(url) -> str:
    value = str(url or "")
    return value if value.startswith(("http://", "https://", "./")) else ""


def _link(url, class_name: str, label: str, external: bool = False) -> str:
    href = _href(url)
    if href:
        attrs = f'href="{_e(href)}"'
        if external:
            attrs += ' target="_blank" rel="noopener"'
        return f'<a class="{class_name}" {attrs}>{label}</a>'
    return f'<span class="{class_name} {class_name}-static">{label}</span>'


def _thumb_srcset(path) -> str:
    raw = str(path or "").split("?")[0]
    name = Path(raw).stem
    if not name:
        return ""
    return f"./static/images/thumbs/{name}-320.webp 320w, ./static/images/thumbs/{name}-640.webp 640w"


def _img(path, cls: str, sizes: str, width: int, height: int, alt: str = "") -> str:
    return (
        f'<img class="{cls}" src="{_e(path)}" srcset="{_e(_thumb_srcset(path))}" '
        f'sizes="{sizes}" width="{width}" height="{height}" alt="{_e(alt)}" loading="lazy">'
    )


def prerender_home(data: dict) -> dict:
    activities = data["activity"]["items"][:3]
    cards = []
    for item in activities:
        media = (
            f'<div class="ka-media">{_img(item.get("thumb"), "ka-thumb", "(max-width: 760px) 40vw, 180px", 600, 210)}'
            f'<span class="ka-badge" aria-hidden="true">◆</span></div>'
            if item.get("thumb")
            else ""
        )
        cards.append(
            f'<a class="key-activity-card" href="./activity#{_e(item["id"])}">'
            f'{media}'
            f'<div class="ka-body"><span class="ka-date">{_e(item["date"])} · {_e(item["tag"])}</span>'
            f'<p class="ka-title">{_e(item["title"])}</p>'
            f'<p class="ka-desc">{_e(item.get("body", ""))}</p></div></a>'
        )
    summary = (
        '<a class="key-activity-card is-summary" href="./activity"><div class="ka-body">'
        '<span class="ka-date">전체 기록</span>'
        '<p class="ka-desc">의회 공개 자료로 확인한 의정활동 기록입니다.</p>'
        '<span class="ka-foot">전체 의정활동 보기 →</span></div></a>'
    )
    media = [m for m in data["media"]["tiles"] if m.get("thumb")][1:4]
    media_html = "".join(
        "<li>"
        + _link(
            m["url"],
            "col-item",
            f'{_img(m["thumb"], "col-thumb", "(max-width: 900px) 120px, 60px", 120, 90)}'
            f'<div><p class="col-item-title">{_e(m["title"])}</p>'
            f'<p class="col-item-meta">{_e(m["kind"])}</p></div>',
            external=True,
        )
        + "</li>"
        for m in media
    )
    links = [
        ("◆", "정책자료", "./policy"),
        ("◆", "의원 소개", "./about"),
        ("◆", "의정활동", "./activity"),
        ("◆", "미디어", "./media"),
        ("↗", "의회 공식 페이지", "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList"),
        ("↗", "중앙선거관리위원회", "http://data.nec.go.kr/resource/Cnddt_100157517520260603"),
    ]
    links_html = "".join(
        _link(
            href,
            "col-tile",
            f'<span class="col-tile-icon" aria-hidden="true">{icon}</span>'
            f'<span class="col-tile-label">{_e(label)}</span>',
            external=href.startswith("http"),
        )
        for icon, label, href in links
    )
    return {"keyActivities": "".join(cards) + summary, "homeMedia": media_html, "homeLinks": links_html}


def _policy_cards(items, label: str) -> str:
    cards = []
    for index, item in enumerate(items, 1):
        meta = " · ".join(str(x) for x in (item.get("date"), item.get("note")) if x)
        cards.append(
            f'<article class="info-card"><div class="card-num">{index:02d}</div>'
            f'<h3>{_e(item["title"])}</h3>'
            + (f'<p class="policy-meta">{_e(meta)}</p>' if meta else "")
            + (f'<p>{_e(item["summary"])}</p>' if item.get("summary") else "")
            + _link(item.get("url"), "card-link", label, external=True)
            + "</article>"
        )
    return "".join(cards)


def prerender_activity(data: dict) -> str:
    rows = []
    for index, item in enumerate(data["activity"]["items"], 1):
        activity_id = item.get("id") or f'a-{item.get("date") or "unknown"}-{index:02d}'
        # Keep the existing interactive row geometry. The summary and safe
        # source link are also readable when JavaScript is unavailable.
        rows.append(
            f'<li class="activity-item" id="{_e(activity_id)}">'
            f'<div class="item-date">{_e(item["date"])}'
            f'<span class="item-tag">{_e(item["tag"])}</span></div>'
            f'<div class="item-title">{_e(item["title"])}'
            '<span class="item-more" aria-hidden="true">자세히 ›</span></div>'
            '<noscript>'
            f'<p class="detail-body">{_e(item.get("body", ""))}</p>'
            + (_link(item.get("url"), "detail-link", "?? 자세히 ›?", external=True)
               if _href(item.get("url")) else "")
            + '</noscript></li>'
        )
    return "".join(rows)


def prerender_media(data: dict) -> str:
    tiles = [m for m in data["media"]["tiles"] if m.get("thumb")]
    cards = []
    for m in tiles:
        notes = "".join(f"<li>{_e(note)}</li>" for note in (m.get("notes") or []))
        cards.append(
            _link(
                m["url"],
                "media-tile",
                f'{_img(m["thumb"], "tile-thumb", "(max-width: 760px) 50vw, 33vw", 640, 480, m.get("title", ""))}'
                f'<div class="tile-kind">{_e(m["kind"])}</div>'
                f'<div class="tile-title">{_e(m["title"])}</div>'
                f'<ul class="tile-notes">{notes}</ul>',
                external=True,
            )
        )
    return "".join(cards)


def prerender_policy(data: dict) -> dict:
    policy = data["policy"]
    bills = policy["bills"]
    assemblies = sorted({int(item["assembly"]) for item in bills}, reverse=True)
    groups = []
    for assembly in assemblies:
        rows = [item for item in bills if int(item["assembly"]) == assembly]
        row_html = "".join(
            '<li class="bill-row">'
            + _link(
                item["url"],
                "bill-row-link",
                f'<span class="bill-number">{_e(item["number"])}</span>'
                f'<span class="bill-title">{_e(item["title"])}</span>'
                f'<span class="bill-date">{_e(item["date"])}</span>'
                f'<span class="bill-result">{_e(item["result"])}</span>',
                external=True,
            )
            + "</li>"
            for item in rows
        )
        label = f'제{assembly}대 광주광역시의회<span class="bill-count">{len(rows)}건</span>'
        if assembly == 8:
            groups.append(
                f'<details class="bill-group"><summary class="bill-group-title" id="bills-{assembly}">'
                f'{label}</summary><ul class="bill-list">{row_html}</ul></details>'
            )
        else:
            groups.append(
                f'<section class="bill-group" aria-labelledby="bills-{assembly}">'
                f'<h3 class="bill-group-title" id="bills-{assembly}">{label}</h3>'
                f'<ul class="bill-list">{row_html}</ul></section>'
            )
    return {
        "policyForums": _policy_cards(policy["forums"], "원문 보기"),
        "policyVideos": _policy_cards(policy["videos"], "영상 보기"),
        "policyBills": "".join(groups),
    }


def make_thumbs(data: dict, out_dir: Path) -> int:
    try:
        from PIL import Image
    except Exception:
        print("thumbnails: skipped (Pillow is not installed)")
        return 0
    thumbs = out_dir / "static" / "images" / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    paths = [item.get("thumb") for item in data["activity"]["items"] if item.get("thumb")]
    paths += [tile.get("thumb") for tile in data["media"]["tiles"] if tile.get("thumb")]
    count = 0
    for rel in paths:
        src = APP_ROOT / rel[2:] if str(rel).startswith("./") else APP_ROOT / str(rel)
        if not src.is_file():
            continue
        try:
            with Image.open(src) as image:
                image = image.convert("RGB")
                for size in (320, 640):
                    thumb = image.copy()
                    thumb.thumbnail((size, size))
                    thumb.save(thumbs / f"{src.stem}-{size}.webp", "WEBP", quality=82)
                    count += 1
        except Exception as exc:
            print(f"thumbnail skipped {rel}: {exc}")
    return count


def inject(out_dir: Path, data: dict) -> None:
    home = prerender_home(data)
    index = out_dir / "index.html"
    if index.is_file():
        html = index.read_text(encoding="utf-8")
        html = html.replace(
            '<div class="key-activity-grid" id="keyActivities"></div>',
            f'<div class="key-activity-grid" id="keyActivities">{home["keyActivities"]}</div>',
        )
        html = html.replace(
            '<ul class="col-list" id="homeMedia"></ul>',
            f'<ul class="col-list" id="homeMedia">{home["homeMedia"]}</ul>',
        )
        html = html.replace(
            '<div class="col-tile-grid" id="homeLinks"></div>',
            f'<div class="col-tile-grid" id="homeLinks">{home["homeLinks"]}</div>',
        )
        index.write_text(html, encoding="utf-8")

    activity_path = out_dir / "activity.html"
    if activity_path.is_file():
        html = activity_path.read_text(encoding="utf-8")
        html = html.replace(
            '<ul class="activity-list" id="activityList" aria-live="polite"></ul>',
            f'<ul class="activity-list" id="activityList" aria-live="polite">{prerender_activity(data)}</ul>',
        )
        activity_path.write_text(html, encoding="utf-8")

    policy = prerender_policy(data)
    policy_path = out_dir / "policy.html"
    if policy_path.is_file():
        html = policy_path.read_text(encoding="utf-8")
        html = html.replace(
            '<div class="card-grid" id="policyForums"></div>',
            f'<div class="card-grid" id="policyForums">{policy["policyForums"]}</div>',
        )
        html = html.replace(
            '<div class="card-grid" id="policyVideos"></div>',
            f'<div class="card-grid" id="policyVideos">{policy["policyVideos"]}</div>',
        )
        html = html.replace(
            '<div class="bill-groups" id="policyBills"></div>',
            f'<div class="bill-groups" id="policyBills">{policy["policyBills"]}</div>',
        )
        policy_path.write_text(html, encoding="utf-8")

    media = prerender_media(data)
    media_path = out_dir / "media.html"
    if media_path.is_file():
        html = media_path.read_text(encoding="utf-8")
        html = html.replace(
            '<div class="media-grid" id="mediaGrid"></div>',
            f'<div class="media-grid" id="mediaGrid">{media}</div>',
        )
        media_path.write_text(html, encoding="utf-8")