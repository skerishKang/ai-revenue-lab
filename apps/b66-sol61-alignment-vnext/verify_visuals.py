"""Produce reproducible before/after evidence from the final PDF bytes."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import fitz
import numpy as np
from PIL import Image, ImageDraw

from align_template import LEFT, WIDTH, derive_bundle, sha
from render_candidate import load_upstream, render_candidate

UPSTREAM_COMMIT = "f25b02541726e06bef8685d366e71815394b7614"
UPSTREAM_SHA = "c0d6073df539b08b0aa47eb60fcbdac5bb18e3118e0815006a01660e64d71f0e"
COUNTS = (1, 2, 3, 4, 8, 25, 100)


def rows(n):
    return [{"name": f"검증품목{i+1:04d}" if n < 25 or i % 10 else f"장기공사비용 초장문 품목명 표본 {i+1:04d} 검증 항목",
        "spec": f"규격-{i+1:04d}", "unit": "EA", "qty": i % 9 + 1,
        "unitPrice": 137000 + i*9137, "note": ""} for i in range(n)]


def segments(page):
    result = []
    for draw in page.get_drawings():
        if draw.get("color") != (0.0, 0.0, 0.0) or not draw.get("width"):
            continue
        for item in draw["items"]:
            if item[0] == "l":
                result.append((item[1], item[2], draw["width"]))
            elif item[0] == "re":
                r = item[1]
                pts = (r.tl, r.tr, r.br, r.bl, r.tl)
                result.extend((a, b, draw["width"]) for a, b in zip(pts, pts[1:]))
    return result


def vector_audit(page):
    lines = segments(page)
    lefts = [(a.x, w) for a, b, w in lines
             if abs(a.x-b.x) < 0.0001 and a.x < 28 and abs(a.y-b.y) > 40]
    diagonals = [(tuple(a), tuple(b)) for a, b, _ in lines
                 if abs(a.x-b.x) > 0.001 and abs(a.y-b.y) > 0.001]
    keys = [tuple(round(v, 4) for v in (*a, *b, w)) for a, b, w in lines]
    histogram = Counter(round(w, 4) for _, _, w in lines)
    return {"leftVerticals": [{"x": round(x, 6), "width": round(w, 6)} for x, w in lefts],
        "leftMaxOffsetPt": round(max(x for x, _ in lefts)-min(x for x, _ in lefts), 6),
        "leftWidthsPt": sorted({round(w, 6) for _, w in lefts}),
        "blackDiagonalSegments": len(diagonals),
        "exactDuplicateBlackSegments": sum(c-1 for c in Counter(keys).values() if c > 1),
        "strokeWidthHistogram": dict(histogram)}


def raster(page, scale):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()


def raster_audit(before, after, scale):
    diff = np.any(before != after, axis=2)
    allowed = np.zeros(diff.shape, dtype=bool)
    def allow(x0, y0, x1, y1):
        allowed[int(y0*scale):int(y1*scale+1), int(x0*scale):int(x1*scale+1)] = True
    allow(22, 0, 28, 841)
    allow(22, 132, 574, 136)
    allow(22, 259, 574, 263)
    allow(571, 0, 574, 841)
    gray = after.min(axis=2)
    bounds = {"left": gray[:, :int((LEFT-WIDTH/2)*scale)],
        "right": gray[:, int(585*scale):], "top": gray[:int(20*scale), :],
        "bottom": gray[int(830*scale):, :]}
    margins = {k: int(np.count_nonzero(v < 100)) for k, v in bounds.items()}
    edges = []
    for y in (160, 190, 230, 280, 310, 570, 590):
        pixels = np.flatnonzero(gray[int(y*scale), :int(28*scale)] < 100)
        edges.append({"yPt": y, "darkColumns": pixels.tolist()})
    return {"dpi": 72*scale, "changedPixels": int(diff.sum()),
        "pixelsChangedOutsideDeclaredGeometry": int(np.count_nonzero(diff & ~allowed)),
        "allMarginsDarkPixels": margins, "leftEdgeRows": edges,
        "leftEdgeRasterCollinear": len({tuple(e["darkColumns"]) for e in edges}) == 1}


def main(source, upstream, out):
    source, upstream, out = Path(source).resolve(), Path(upstream).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate = out / "candidate-sol"
    audit = derive_bundle(source, candidate)
    module = load_upstream(upstream, UPSTREAM_SHA)
    dependency_hashes = {n: sha(upstream / n) for n in ("sol61_multipage.py", "slots_multipage.cjs")}
    before_engine = module.SolMultipage(source / "template")
    pdfs, images = out / "pdf", out / "images"
    pdfs.mkdir(exist_ok=True)
    images.mkdir(exist_ok=True)
    result = {"templateId": audit["templateId"], "upstreamCommit": UPSTREAM_COMMIT,
        "upstreamHashes": dependency_hashes, "pymupdfVersion": fitz.VersionBind,
        "candidateProgramSha256": audit["candidateProgramSha256"], "samples": {}}
    cards = []
    for n in COUNTS:
        changes = {"recipient": "검증대학교", "project": "테두리 정렬 검증 공사",
            "quoteNo": "ALIGN-3839", "issueDate": "2026-10-10", "items": rows(n)}
        before, after = pdfs / f"before-{n}.pdf", pdfs / f"after-{n}.pdf"
        old_info = before_engine.render(before, changes)
        new_info = render_candidate(module, candidate, after, changes)
        repeat = out / "determinism.pdf"
        render_candidate(module, candidate, repeat, changes)
        for rendered in (after, repeat):
            record = json.loads(rendered.with_suffix(".instance.json").read_text(encoding="utf-8"))
            assert record["itemCount"] == n and record["changes"] == changes
            assert record["totals"] == new_info["totals"] and record["pages"] == new_info["pages"]
            assert record["pdfSha256"] == sha(rendered) and record["certificationStatus"] == "PENDING"
        deterministic = sha(after) == sha(repeat)
        with fitz.open(before) as a, fitz.open(after) as b:
            assert len(a) == len(b)
            page_results = []
            picked = {0, len(b)//2, len(b)-1}
            for i in range(len(b)):
                va, vb = vector_audit(a[i]), vector_audit(b[i])
                checks = []
                for scale in (1, 2):
                    ra, rb = raster(a[i], scale), raster(b[i], scale)
                    checks.append(raster_audit(ra, rb, scale))
                    if i in picked:
                        base = f"n{n}-p{i+1}-{scale}x"
                        Image.fromarray(ra).save(images / f"{base}-before.png")
                        Image.fromarray(rb).save(images / f"{base}-after.png")
                        sheet = Image.new("RGB", (ra.shape[1]*2, ra.shape[0]+32), "white")
                        sheet.paste(Image.fromarray(ra), (0, 32))
                        sheet.paste(Image.fromarray(rb), (ra.shape[1], 32))
                        draw = ImageDraw.Draw(sheet)
                        draw.text((12, 8), f"BEFORE | {n} items | page {i+1}/{len(b)} | {72*scale} dpi", fill="black")
                        draw.text((ra.shape[1]+12, 8), f"AFTER | v2 CANDIDATE | {72*scale} dpi", fill="black")
                        sheet.save(images / f"{base}-comparison.png")
                        crop = Image.new("RGB", (100*scale, int(485*scale)+32), "white")
                        crop.paste(Image.fromarray(ra).crop((int(18*scale), int(130*scale), int(68*scale), int(615*scale))), (0, 32))
                        crop.paste(Image.fromarray(rb).crop((int(18*scale), int(130*scale), int(68*scale), int(615*scale))), (50*scale, 32))
                        ImageDraw.Draw(crop).text((4, 8), "BEFORE | AFTER", fill="black")
                        crop.save(images / f"{base}-left-edge.png")
                        cards.append((n, i+1, len(b), scale, base))
                text_equal = a[i].get_text() == b[i].get_text()
                page_results.append({"page": i+1, "before": va, "after": vb,
                    "textExactlyPreserved": text_equal, "raster": checks})
                assert text_equal
                assert vb["leftMaxOffsetPt"] == 0 and vb["leftWidthsPt"] == [WIDTH]
                assert vb["blackDiagonalSegments"] == 0
                assert all(c["pixelsChangedOutsideDeclaredGeometry"] == 0
                    and not any(c["allMarginsDarkPixels"].values())
                    and c["leftEdgeRasterCollinear"] for c in checks)
            text = re.sub(r"\s+", "", "\n".join(p.get_text() for p in b))
            row_counts = [text.count(re.sub(r"\s+", "", r["name"])) for r in changes["items"]]
            assert all(c == 1 for c in row_counts)
            assert old_info["totals"] == new_info["totals"] and deterministic
            result["samples"][str(n)] = {"pages": len(b), "totalsUnchanged": True,
                "QuoteCoreTotals": new_info["totals"], "allItemsExactlyOnce": True,
                "deterministicPdfBytes": deterministic, "currentInstanceMetadata": True, "beforeSha256": sha(before),
                "afterSha256": sha(after), "pageChecks": page_results}
        print(f"N={n} pages={new_info['pages']} geometry/raster/text/money/determinism=PASS", flush=True)
    manifest = source.parent / "PUBLIC_RELEASE_MANIFEST.json"
    result["certifiedOriginalUnchanged"] = sha(manifest) == audit["issuedManifestSha256"] and all(
        sha(source.parent / name) == value for name, value in audit["issuedArtifactHashes"].items())
    result["local1SourceUnchanged"] = all(sha(upstream / name) == value for name, value in dependency_hashes.items())
    assert result["certifiedOriginalUnchanged"] and result["local1SourceUnchanged"]
    result.update({"ownerVisualApproval": "PENDING", "newCertificationRequired": True,
                   "productionMutation": 0, "modelCalls": 0,
                   "remainingUpstreamLayoutReview": "Open right-side area below multipage item rows; unchanged from #4001"})
    (out / "visual-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sections = []
    for n, page, total, scale, base in cards:
        sections.append(f'<section data-scale="{scale}"><h2>{n}품목 / {page} of {total} / {scale*100}%</h2>'
            f'<p><a href="pdf/before-{n}.pdf">수정 전 PDF</a> · <a href="pdf/after-{n}.pdf">새 버전 후보 PDF</a></p>'
            f'<img src="images/{base}-comparison.png" alt="수정 전후 전체 페이지">'
            f'<details><summary>왼쪽 경계 확대</summary><img class="edge" src="images/{base}-left-edge.png" alt="왼쪽 선 전후"></details></section>')
    report = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>Sol CGI 테두리 보정 후보</title>' \
        '<style>body{font:15px system-ui;margin:24px;color:#222;background:#f6f7f8}h1{font-size:24px}h2{font-size:18px}section{border-top:1px solid #ccc;padding:20px 0}img{display:block;max-width:100%;height:auto;background:white}.edge{max-width:none}button{padding:7px 14px;margin-right:8px}a{color:#006f65}pre{white-space:pre-wrap}section[data-scale="2"]{display:none}</style>' \
        '<h1>Sol CGI 새 버전: 왼쪽 테두리 정렬 후보</h1>' \
        '<p>검증 완료 · Owner 시각 승인 및 재인증 대기 · 운영 변경 0</p>' \
        '<p>검은 상단 이중 테두리를 0.72pt 단일 외곽선으로 정리하고, 상단·노란 합계·품목·하단 경계를 x=24.587pt로 맞췄습니다. 위·오른쪽·아래 경계는 기존 이중 테두리 중심선을 사용합니다. 내부 점선·글꼴·로고·도장·계산은 보존했습니다.</p>' \
        '<p>1·2·3·4·8·25·100품목 모든 페이지: 선 좌표 및 100%/200% 렌더링 검사 통과. 첫·중간·마지막 페이지 이미지를 아래에 수록했습니다. 실제 기존 인증 양식의 경계 배치는 <a href="source-original.png">공개 원본 이미지</a>에서 확인할 수 있습니다.</p>' \
        '<p>LOCAL1 후속 검토: 다중 페이지의 품목 아래 오른쪽 외곽선이 열린 형태는 수정 전후에 동일하게 남아 있습니다. 이 후보의 통과 판정은 왼쪽 정렬 범위이며, 전체 다중 페이지 인증은 별도입니다.</p>' \
        '<button onclick="show(1)">100% · 72 dpi</button><button onclick="show(2)">200% · 144 dpi</button>' \
        '<p><a href="visual-audit.json">전체 벡터·픽셀·해시 검증 결과</a></p>' + ''.join(sections) + \
        '<script>function show(n){document.querySelectorAll("section[data-scale]").forEach(e=>e.style.display=Number(e.dataset.scale)===n?"block":"none")}</script></html>'
    (out / "comparison.html").write_text(report, encoding="utf-8")
    with fitz.open(source.parent / "source/original.pdf") as original:
        Image.fromarray(raster(original[0], 2)).save(out / "source-original.png")
    (out / "completion.ini").write_text(
        "ORIGINAL_TEMPLATE_GEOMETRY=info ring outer25.786 inner26.506; lower24.587\n"
        "LEFT_BORDER_MISALIGNMENT_CAUSE=section anchor offset plus filled/stroked double frame and redundant rule\n"
        "CORRECTED_GEOMETRY=left24.587pt width0.72pt; info top/right/bottom original ring midlines\n"
        "BEFORE_AFTER_IMAGES=comparison.html; images/*.png\n"
        "ONE_PAGE_VISUAL_RESULT=SELF_CHECK_PASS_1_2_3\n"
        "MULTIPAGE_VISUAL_RESULT=ALIGNMENT_PASS_4_8_25_100_ALL_PAGES_OTHER_LOCAL1_LAYOUT_PENDING\n"
        "CERTIFIED_ORIGINAL_UNCHANGED=YES_18_ARTIFACTS_PLUS_MANIFEST\n"
        "NEW_TEMPLATE_VERSION_REQUIRED=YES_V2_CANDIDATE_REQUIRES_NEW_CERTIFICATE\n"
        "OWNER_VISUAL_APPROVAL=PENDING\nPRODUCTION_MUTATION=0\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--upstream-engine", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    main(args.source_bundle, args.upstream_engine, args.out)
