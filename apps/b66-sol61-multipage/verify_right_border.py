"""Offline actual-PDF evidence for LOCAL1 #3839, with read-only Sol v2 previews."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import fitz
import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
COUNTS = (1, 2, 3, 4, 8, 10, 25, 100, 101, 125, 500)
OLD_SHA = "c0d6073df539b08b0aa47eb60fcbdac5bb18e3118e0815006a01660e64d71f0e"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def norm(text):
    return re.sub(r"\s+", "", text)


def rows(n):
    return [{"name": f"검증품목{i+1:04d}" if n < 25 or i % 10 else
             f"장기공사비용 초장문 품목명 표본 {i+1:04d} 검증 항목",
             "spec": f"규격-{i+1:04d}", "unit": "EA", "qty": i % 9+1,
             "unitPrice": 137000+i*9137, "note": ""} for i in range(n)]


def money(value):
    return int(str(value).replace(",", ""))


def gray(page, dpi):
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def margin_scan(page, dpi):
    data, scale = gray(page, dpi), dpi/72
    areas = {"left": data[:, :int(24*scale)], "right": data[:, int(585*scale):],
             "top": data[:int(20*scale), :], "bottom": data[int(830*scale):, :]}
    return {name: int(np.count_nonzero(pixels < 100)) for name, pixels in areas.items()}


def diagonal_count(page):
    return sum(1 for d in page.get_drawings() if d.get("color") == (0.0, 0.0, 0.0)
               for item in d["items"] if item[0] == "l"
               and abs(item[1].x-item[2].x) > 0.001 and abs(item[1].y-item[2].y) > 0.001)


def verify_file(pdf, eng, info, changes, oracle, reference_top, candidate=False):
    reader, checks = PdfReader(pdf), []
    with fitz.open(pdf) as doc:
        assert len(doc) == info["pages"] == len(reader.pages)
        text = norm("\n".join(page.get_text() for page in doc))
        names = [norm(item["name"]) for item in changes["items"]]
        assert all(text.count(name) == 1 for name in names)
        positions = [text.find(name) for name in names]
        assert positions == sorted(positions)
        subtotal = sum(item["qty"]*item["unitPrice"] for item in changes["items"])
        vat = int((Decimal(subtotal)*Decimal("0.1")).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        expected = {"subtotal": subtotal, "vat": vat, "grand": subtotal+vat}
        assert {k: money(info["totals"][k]) for k in expected} == expected
        assert all(f"{value:,}" in doc[-1].get_text() for value in expected.values())
        for i, page in enumerate(doc):
            oracle.assert_frame(reader.pages[i].get_contents().get_data(), reader, eng)
            raster_checks = []
            for dpi in (72, 144):
                oracle.assert_raster_frame(page, eng, dpi)
                hidden = oracle.top_raster_occlusion(page, eng, dpi)
                assert hidden == reference_top[dpi], "New occlusion differs from the issued seal"
                margins = margin_scan(page, dpi)
                assert not any(margins.values())
                raster_checks.append({"dpi": dpi, "visibleFrameContinuous": True,
                    "sourceSealOcclusionSamples": len(hidden), "marginDarkPixels": margins})
            assert diagonal_count(page) == 0
            checks.append({"page": i+1, "fourVectorEdgesContinuousExactlyOnce": True,
                           "diagonals": 0, "raster": raster_checks})
        if info.get("plan"):
            assert sum(p["rows"] for p in info["plan"]) == len(names)
            for plan in info["plan"]:
                bottom = plan["row_tops"][-1]+plan["row_heights"][-1]
                limit = eng.totals_top if plan["kind"] == "last" else eng.footer_top
                assert bottom <= limit-6+0.011
                assert f"{plan['index']+1} / {len(doc)}" in doc[plan["index"]].get_text()
        if candidate:
            record = json.loads(Path(pdf).with_suffix(".instance.json").read_text(encoding="utf-8"))
            assert record["itemCount"] == len(names) and record["pages"] == len(doc)
            assert record["changes"] == changes and record["certificationStatus"] == "PENDING"
            assert record["pdfSha256"] == info["pdfSha256"]
            assert record["certifiedPath"] is False
        return {"pages": len(doc), "allItemsExactlyOnceInOrder": True,
                "QuoteCoreParity": expected, "rowSummaryFooterClearance": True,
                "pageChecks": checks, "pdfSha256": info["pdfSha256"]}


def save_comparison(before, after, v2, count, directory):
    result = []
    with fitz.open(before) as a, fitz.open(after) as b, fitz.open(v2) as c:
        for label, index in (("first", 0), ("middle", len(b)//2), ("last", len(b)-1)):
            for dpi in (72, 144):
                old_index = min(index, len(a)-1)
                parts = []
                for doc, pi in ((a, old_index), (b, index), (c, index)):
                    pix = doc[pi].get_pixmap(dpi=dpi, alpha=False)
                    parts.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                w, h = parts[0].size
                sheet = Image.new("RGB", (w*3, h+32), "white")
                draw = ImageDraw.Draw(sheet)
                for column, (part, title, pi, total) in enumerate(zip(parts,
                        ("BEFORE #4001", "FIXED #4001", "COMBINED v2 PENDING"),
                        (old_index, index, index), (len(a), len(b), len(c)))):
                    sheet.paste(part, (w*column, 32))
                    draw.text((w*column+10, 8), f"{title} | {count} items | {pi+1}/{total} | {dpi} dpi", fill="black")
                filename = f"n{count}-{label}-{dpi}dpi.png"
                sheet.save(directory / filename)
                edge = Image.new("RGB", (36*dpi//72*3, h+32), "white")
                for column, part in enumerate(parts):
                    strip = part.crop((int(555*dpi/72), 0, int(591*dpi/72), h))
                    edge.paste(strip, (column*strip.width, 32))
                ImageDraw.Draw(edge).text((3, 8), "BEFORE | FIXED | v2", fill="black")
                edge.save(directory / f"n{count}-{label}-{dpi}dpi-right.png")
                result.append({"count": count, "label": label, "dpi": dpi, "file": filename})
    return result


def main(args):
    bundle, v2_app, out = map(lambda p: Path(p).resolve(), (args.bundle, args.v2_app, args.out))
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(v2_app))
    v2 = load("local1_v2_adapter", v2_app / "render_candidate.py")
    align = load("local1_read_only_alignment", v2_app / "align_template.py")
    sha = align.sha
    if sha(HERE / "sol61_multipage.py") != args.expected_engine_sha:
        raise ValueError("Reviewed LOCAL1 engine SHA changed")
    old_dir = Path(args.before_engine).resolve()
    old = v2.load_upstream(old_dir, OLD_SHA)
    new = v2.load_upstream(HERE, args.expected_engine_sha)
    oracle = load("local1_frame_oracle", HERE / "tests/test_multipage_frame_regression.py")
    source_hashes = {p.relative_to(v2_app).as_posix(): sha(p) for p in v2_app.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts}
    derived = align.derive_bundle(bundle, out / "candidate-sol-v2")
    engines = {"before": old.SolMultipage(bundle / "template"),
               "after": new.SolMultipage(bundle / "template"),
               "v2": new.SolMultipage(out / "candidate-sol-v2/template")}
    with fitz.open(bundle.parent / "source/original.pdf") as doc:
        reference_top = {dpi: oracle.top_raster_occlusion(doc[0], engines["after"], dpi) for dpi in (72, 144)}
    pdfs, images = out / "pdf", out / "images"
    pdfs.mkdir(exist_ok=True)
    images.mkdir(exist_ok=True)
    report = {"beforeHead": "f25b02541726e06bef8685d366e71815394b7614",
        "v2Head": "a163f11d2e9c734d66c95293464541d85335ebad",
        "engineSha256": args.expected_engine_sha, "samples": {}, "negativeControls": {},
        "frame": {"left": engines["after"].frame_left, "right": engines["after"].frame_right,
                  "top": engines["after"].frame_top, "bottom": engines["after"].frame_bottom,
                  "width": engines["after"].rule_width},
        "sourceSealOcclusion": {str(d): sorted(v) for d, v in reference_top.items()},
        "intentionalSourceHeaderDoubleRulesPreserved": True}
    pictures = []
    for count in COUNTS:
        request = {"recipient": "경계 검증대학교", "project": "테두리 회귀 검증 공사",
                   "quoteNo": "FRAME-3839", "issueDate": "2026-10-10", "items": rows(count)}
        paths = {key: pdfs / f"{key}-{count}.pdf" for key in engines}
        old_info = engines["before"].render(paths["before"], request)
        new_info = engines["after"].render(paths["after"], request)
        v2_info = v2.render_candidate(new, out / "candidate-sol-v2", paths["v2"], request)
        assert {k: money(old_info["totals"][k]) for k in ("subtotal", "vat", "grand")} == {
            k: money(new_info["totals"][k]) for k in ("subtotal", "vat", "grand")}
        if count <= 3:
            assert paths["before"].read_bytes() == paths["after"].read_bytes()
        fixed = verify_file(paths["after"], engines["after"], new_info, request, oracle, reference_top)
        combined = verify_file(paths["v2"], engines["v2"], v2_info, request, oracle, reference_top, candidate=True)
        repeat = out / f"repeat-native-{count}.pdf"
        engines["after"].render(repeat, request)
        assert sha(repeat) == sha(paths["after"])
        repeat_v2 = out / f"repeat-v2-{count}.pdf"
        v2.render_candidate(new, out / "candidate-sol-v2", repeat_v2, request)
        assert sha(repeat_v2) == sha(paths["v2"])
        baseline = PdfReader(paths["before"])
        failures = []
        for pi, page in enumerate(baseline.pages):
            try:
                oracle.assert_frame(page.get_contents().get_data(), baseline, engines["after"])
            except AssertionError as exc:
                failures.append({"page": pi+1, "reason": str(exc)})
        if count >= 4:
            assert failures, "The frozen pre-fix PDF must fail the new boundary oracle"
        report["samples"][str(count)] = {"native": fixed, "v2Preview": combined,
            "beforePages": len(baseline.pages), "beforeFailures": failures,
            "nativeCertifiedBytesUnchanged": count <= 3,
            "deterministicNativeAndV2": True}
        pictures += save_comparison(paths["before"], paths["after"], paths["v2"], count, images)
        print(f"N={count} before={old_info['pages']} fixed={new_info['pages']} v2={v2_info['pages']} full-vector/raster/items/QuoteCore/determinism=PASS", flush=True)
    final_right = [l for l in engines["after"].program.lines if engines["after"]._is_outer_frame_rule(l)
                   and abs(l["box"][0]-engines["after"].frame_right) < .001
                   and abs(engines["after"].height-l["box"][1]-engines["after"].frame_bottom) < .001]
    assert len(final_right) == 1
    with fitz.open(pdfs / "after-8.pdf") as doc:
        raw = doc[-1].read_contents()
        block = engines["after"]._emit_line(final_right[0])
        assert raw.count(block) == 1
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, raw.replace(block, b"", 1))
        doc[-1].set_contents(xref)
        mutated = pdfs / "mutation-missing-right.pdf"
        doc.save(mutated)
    mutated_reader = PdfReader(mutated)
    try:
        oracle.assert_frame(mutated_reader.pages[-1].get_contents().get_data(), mutated_reader, engines["after"])
    except AssertionError as exc:
        report["negativeControls"]["removedFinalRightSegment"] = {"detected": True, "reason": str(exc)}
    else:
        raise AssertionError("Removed right edge was not detected")
    assert all(sha(bundle.parent / name) == value for name, value in derived["issuedArtifactHashes"].items())
    assert sha(bundle.parent / "PUBLIC_RELEASE_MANIFEST.json") == derived["issuedManifestSha256"]
    assert all(sha(v2_app / name) == value for name, value in source_hashes.items())
    report.update({"original18HashesUnchanged": True, "publicManifestUnchanged": True,
        "v2SourceUnchanged": True, "v2ReadOnlyHashes": source_hashes,
        "nativePagesVerified": sum(s["native"]["pages"] for s in report["samples"].values()),
        "v2PagesVerified": sum(s["v2Preview"]["pages"] for s in report["samples"].values()),
        "ownerVisualApproval": "PENDING", "newCertification": "PENDING",
        "productionMutation": 0, "modelCallsPerPdf": 0, "issueClose": False})
    (out / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sections = []
    for p in pictures:
        count, dpi, label = p["count"], p["dpi"], p["label"]
        sections.append(f'<section data-dpi="{dpi}"><h2>{count}품목 / {label} / {dpi}dpi</h2>'
            f'<p><a href="pdf/before-{count}.pdf">수정 전</a> · <a href="pdf/after-{count}.pdf">수정 후</a> · <a href="pdf/v2-{count}.pdf">v2 통합 미승인 후보</a></p>'
            f'<img src="images/{p["file"]}" alt="수정 전·후 및 v2 통합 후보">'
            f'<details><summary>오른쪽 테두리 확대</summary><img class="edge" src="images/n{count}-{label}-{dpi}dpi-right.png"></details></section>')
    page = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>LOCAL1 Sol CGI 오른쪽 테두리 검증</title>' \
        '<style>body{font:15px system-ui;color:#222;margin:24px;background:#f5f7f7}h1{font-size:24px}h2{font-size:18px}section{border-top:1px solid #bbb;padding:18px 0}img{display:block;max-width:100%;height:auto}.edge{max-width:none}button{padding:7px 12px;margin-right:6px}section[data-dpi="144"]{display:none}a{color:#006d67}</style>' \
        '<h1>LOCAL1: Sol CGI 오른쪽 테두리 수정 및 v2 통합 검토</h1>' \
        f'<p>11개 품목 수 / native {report["nativePagesVerified"]}페이지 + v2 {report["v2PagesVerified"]}페이지 / 72·144dpi 검사 완료</p>' \
        '<p>원본의 오른쪽 외곽선 구간을 페이지 구조로 보존하고 새 행 격자의 중복을 제거했습니다. 합계 셀의 실제 상단을 기준으로 마지막 페이지 높이를 계산합니다. 인증 v1의 1~3품목 바이트는 그대로입니다.</p>' \
        '<p>v2는 승인 대기 미리보기이며 운영에 활성화되지 않았습니다. 도장이 상단 선을 덮는 원본 영역은 원본과 동일함을 검사했습니다. 원본의 의도된 상단 이중선·점선은 보존했습니다.</p>' \
        '<p><a href="audit.json">전체 벡터·이미지·품목·계산·무결성 검증</a> · <a href="pdf/mutation-missing-right.pdf">실패해야 하는 제거 대조군</a></p>' \
        '<button onclick="show(72)">100% · 72dpi</button><button onclick="show(144)">200% · 144dpi</button>' + ''.join(sections) + \
        '<script>function show(d){document.querySelectorAll("section[data-dpi]").forEach(s=>s.style.display=Number(s.dataset.dpi)===d?"block":"none")}</script></html>'
    (out / "comparison.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--before-engine", required=True)
    parser.add_argument("--v2-app", required=True)
    parser.add_argument("--expected-engine-sha", required=True)
    parser.add_argument("--out", required=True)
    main(parser.parse_args())
