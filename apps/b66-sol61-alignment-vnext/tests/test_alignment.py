"""Regressions for the isolated, unapproved Sol geometry revision."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import zlib

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream, DecodedStreamObject


APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
SOURCE = REPO / "reference/b66-public-standard-templates/cgi/v1/sol61"
SPEC = importlib.util.spec_from_file_location("alignment_under_test", APP / "align_template.py")
ALIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALIGN)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operations(raw, reader):
    stream = DecodedStreamObject()
    stream.set_data(raw)
    return ContentStream(stream, reader).operations


def multiplication(a, b):
    return [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
            a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5]]


def painted_paths(raw, reader):
    """Inspect absolute geometry without authoring or rendering a PDF."""
    cm, width, color, stack, path = [1, 0, 0, 1, 0, 0], 1, [0, 0, 0], [], []
    clip = [0, 0, float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)]
    pending_clip = False
    start, offset = None, 0
    for args, op in operations(raw, reader):
        chunk = ALIGN.serialize(args, op)
        if op == b"q":
            stack.append((cm[:], width, color[:], clip[:]))
        elif op == b"Q":
            cm, width, color, clip = stack.pop()
        elif op == b"cm":
            cm = multiplication([float(v) for v in args], cm)
        elif op == b"w":
            width = float(args[0])
        elif op == b"G":
            color = [float(args[0])]*3
        elif op == b"RG":
            color = [float(v) for v in args]
        elif op in (b"m", b"l", b"re"):
            if start is None:
                start = offset
            if op == b"re":
                x, y, w, h = map(float, args)
                points = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
            else:
                points = [(float(args[0]), float(args[1]))]
            path.extend((x*cm[0]+y*cm[2]+cm[4], x*cm[1]+y*cm[3]+cm[5])
                        for x, y in points)
        elif op in (b"W", b"W*"):
            pending_clip = True
        elif op in (b"n", b"S", b"s", b"f", b"f*", b"B", b"B*", b"b", b"b*"):
            if path:
                if pending_clip:
                    xs, ys = zip(*path)
                    clip = [max(clip[0], min(xs)), max(clip[1], min(ys)),
                            min(clip[2], max(xs)), min(clip[3], max(ys))]
                yield {"paint": op, "points": path, "width": width*abs(cm[0]),
                       "color": color[:], "clip": clip[:],
                       "start": start, "end": offset+len(chunk)}
            path, start = [], None
            pending_clip = False
        offset += len(chunk)


@pytest.fixture(scope="module")
def candidate(tmp_path_factory):
    manifest_file = SOURCE.parent / "PUBLIC_RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    before = {name: digest(SOURCE.parent / name) for name in manifest["artifacts"]}
    manifest_before = digest(manifest_file)
    destination = tmp_path_factory.mktemp("alignment") / "candidate"
    audit = ALIGN.derive_bundle(SOURCE, destination)
    after = {name: digest(SOURCE.parent / name) for name in manifest["artifacts"]}
    raw = zlib.decompress((SOURCE / "template/program.zlib").read_bytes())
    new = zlib.decompress((destination / "template/program.zlib").read_bytes())
    reader = PdfReader(SOURCE / "template/resources.pdf")
    _, offsets, _ = ALIGN.aligned_program(raw, reader)
    return {"destination": destination, "audit": audit, "before": before, "after": after,
            "manifest_before": manifest_before, "manifest_file": manifest_file,
            "raw": raw, "new": new, "reader": reader, "offsets": offsets}


def test_derivation_preserves_all_18_issued_artifact_hashes(candidate):
    manifest = json.loads(candidate["manifest_file"].read_text(encoding="utf-8"))
    expected = {name: entry["sha256"] for name, entry in manifest["artifacts"].items()}
    assert len(expected) == 18
    assert candidate["before"] == expected == candidate["after"]
    assert digest(candidate["manifest_file"]) == candidate["manifest_before"]
    assert candidate["audit"]["issuedArtifactHashes"] == expected
    assert candidate["audit"]["issuedManifestSha256"] == candidate["manifest_before"]


def test_candidate_has_new_identity_and_no_inherited_certificate(candidate):
    destination = candidate["destination"]
    old = json.loads((SOURCE / "template/template.json").read_text(encoding="utf-8"))
    new = json.loads((destination / "template/template.json").read_text(encoding="utf-8"))
    assert new["templateId"] != old["templateId"]
    assert new["derivedFromTemplateId"] == old["templateId"]
    assert new["geometryRevision"]["requiresNewCertificate"] is True
    assert new["geometryRevision"]["status"] == "OWNER_VISUAL_APPROVAL_PENDING"
    assert new["certification"]["status"] != "CERTIFIED"
    assert "validatedCandidateManifestSha256" not in new["certification"]
    assert not new["certification"].get("evidence")
    assert not list(destination.rglob("certificate.json"))
    assert not list(destination.rglob("PUBLIC_RELEASE_MANIFEST.json"))
    assert candidate["audit"]["certificateInherited"] is False
    assert new["renderer"]["programSha256"] == hashlib.sha256(candidate["new"]).hexdigest()


def test_only_geometry_authority_changes_in_candidate(candidate):
    destination = candidate["destination"]
    for relative in ["template/resources.pdf", "quote-core.js"]:
        assert digest(destination / relative) == digest(SOURCE / relative)
    for original in (SOURCE / "engine").rglob("*"):
        if original.is_file() and "__pycache__" not in original.parts:
            assert digest(destination / original.relative_to(SOURCE)) == digest(original)


def test_binding_ranges_and_text_bytes_remain_valid(candidate):
    old = json.loads((SOURCE / "template/template.json").read_text(encoding="utf-8"))
    new = json.loads((candidate["destination"] / "template/template.json").read_text(encoding="utf-8"))
    assert len(old["bindings"]) == len(new["bindings"])
    for before, after in zip(old["bindings"], new["bindings"]):
        assert before["key"] == after["key"]
        for key in ("bbox", "cm", "tm", "family", "size", "nominalSize", "original"):
            assert before[key] == after[key]
        for before_run, after_run in zip(before["runs"], after["runs"]):
            old_bytes = candidate["raw"][before_run["start"]:before_run["end"]]
            new_bytes = candidate["new"][after_run["start"]:after_run["end"]]
            assert old_bytes.startswith(b"BT\n")
            assert old_bytes.endswith(b"ET\n")
            assert new_bytes == old_bytes
        if "underline" in before:
            b, a = before["underline"], after["underline"]
            assert candidate["new"][a["start"]:a["end"]] == candidate["raw"][b["start"]:b["end"]]
    old_insert, new_insert = old["renderer"]["insertion"], new["renderer"]["insertion"]
    assert candidate["new"][new_insert:new_insert+50] == candidate["raw"][old_insert:old_insert+50]
    text_ops = (b"BT", b"ET", b"Tf", b"Tm", b"TJ", b"Tj", b"Tr")
    before_text = [ALIGN.serialize(a, o) for a, o in operations(candidate["raw"], candidate["reader"]) if o in text_ops]
    after_text = [ALIGN.serialize(a, o) for a, o in operations(candidate["new"], candidate["reader"]) if o in text_ops]
    assert before_text == after_text


def test_source_dashes_are_preserved_byte_for_byte(candidate):
    checked = 0
    for path in painted_paths(candidate["raw"], candidate["reader"]):
        points = path["points"]
        if path["paint"] != b"S" or len(points) != 2:
            continue
        dx, dy = abs(points[0][0]-points[1][0]), abs(points[0][1]-points[1][1])
        if abs(path["width"]-0.836) > 0.00001 or max(dx, dy) >= 2:
            continue
        start, end = path["start"], path["end"]
        assert candidate["raw"][start:end] == candidate["new"][candidate["offsets"][start]:candidate["offsets"][end]]
        checked += 1
    assert checked > 1500


def test_nested_info_ring_becomes_one_uniform_stroked_frame(candidate):
    paths = list(painted_paths(candidate["new"], candidate["reader"]))
    frames = [p for p in paths if p["paint"] == b"S" and len(p["points"]) == 4
              and min(x for x, _ in p["points"]) < 27
              and 126 < max(y for _, y in p["points"])-min(y for _, y in p["points"]) < 128]
    assert len(frames) == 1
    frame = frames[0]
    assert frame["width"] == pytest.approx(0.72)
    assert min(x for x, _ in frame["points"]) == pytest.approx(24.587)
    assert max(x for x, _ in frame["points"]) == pytest.approx(572.587)
    assert min(y for _, y in frame["points"]) == pytest.approx(580.2705)
    assert max(y for _, y in frame["points"]) == pytest.approx(706.8665)
    assert not any(p["paint"] == b"B" for p in paths)
    long_old_rules = [p for p in paths if p["paint"] in (b"S", b"s")
                      and len(p["points"]) == 2
                      and all(abs(x-26.506) < 0.00001 for x, _ in p["points"])
                      and abs(p["points"][0][1]-p["points"][1][1]) > 100]
    assert not long_old_rules


def test_header_clip_contains_the_complete_stroke(candidate):
    frames = [p for p in painted_paths(candidate["new"], candidate["reader"])
              if p["paint"] == b"S" and len(p["points"]) == 4
              and min(x for x, _ in p["points"]) < 27
              and 126 < max(y for _, y in p["points"])-min(y for _, y in p["points"]) < 128]
    assert len(frames) == 1
    frame = frames[0]
    xs, ys = zip(*frame["points"])
    half_stroke = frame["width"] / 2
    x0, y0, x1, y1 = frame["clip"]
    assert x0 <= min(xs)-half_stroke+0.00001, "Header clip truncates the left half-stroke"
    assert x1 >= max(xs)+half_stroke-0.00001, "Header clip truncates the right half-stroke"
    assert y0 <= min(ys)-half_stroke+0.00001, "Header clip truncates the bottom half-stroke"
    assert y1 >= max(ys)+half_stroke-0.00001, "Header clip truncates the top half-stroke"


def test_unknown_source_program_is_rejected_before_derivation(candidate):
    with pytest.raises(ValueError, match="Unrecognised source program"):
        ALIGN.aligned_program(candidate["raw"] + b"\n", candidate["reader"])


def test_non_operation_metadata_offset_is_rejected():
    metadata = {"runs": [{"start": 1, "end": 8}]}
    with pytest.raises(ValueError, match="not an operation boundary"):
        ALIGN._remap_metadata(metadata, {0: 0, 8: 8})


def test_issued_hash_mismatch_blocks_creation(tmp_path):
    copied_release = tmp_path / "public-release"
    shutil.copytree(SOURCE.parent, copied_release)
    quote_core = copied_release / "sol61/quote-core.js"
    quote_core.write_bytes(quote_core.read_bytes() + b"\n")
    destination = tmp_path / "candidate"
    with pytest.raises(ValueError, match="Issued public release integrity failure"):
        ALIGN.derive_bundle(copied_release / "sol61", destination)
    assert not destination.exists()


@pytest.mark.parametrize("relative", [".", "template/new-candidate", ".."])
def test_candidate_cannot_overwrite_or_nest_in_issued_bundle(relative):
    with pytest.raises(ValueError, match="isolated"):
        ALIGN.derive_bundle(SOURCE, SOURCE / relative)


def test_existing_candidate_cannot_be_overwritten(candidate):
    marker = candidate["destination"] / "ALIGNMENT_CANDIDATE.json"
    before = marker.read_bytes()
    with pytest.raises(ValueError, match="empty new destination"):
        ALIGN.derive_bundle(SOURCE, candidate["destination"])
    assert marker.read_bytes() == before


def test_unapproved_money_adapter_is_rejected_before_renderer_import(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    spec = importlib.util.spec_from_file_location("candidate_adapter_under_test", APP / "render_candidate.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    renderer = tmp_path / "sol61_multipage.py"
    renderer.write_text("raise RuntimeError('unapproved code executed')\n", encoding="utf-8")
    (tmp_path / "slots_multipage.cjs").write_text("unapproved money adapter", encoding="utf-8")
    with pytest.raises(ValueError, match="QuoteCore adapter hash mismatch"):
        adapter.load_upstream(tmp_path, digest(renderer))


def test_final_instance_records_describe_their_actual_pdfs_and_reused_output():
    pair_json = os.environ.get("B66_ALIGNMENT_RASTER_PAIRS")
    if not pair_json:
        pytest.skip("Set B66_ALIGNMENT_RASTER_PAIRS to generated delivery evidence")
    fitz = pytest.importorskip("fitz")
    pairs = json.loads(pair_json)
    paths = [Path(pair["candidate"]) for pair in pairs]
    paths.append(paths[0].parent.parent / "determinism.pdf")
    for path in paths:
        instance = json.loads(path.with_suffix(".instance.json").read_text(encoding="utf-8"))
        assert instance["pdfSha256"] == digest(path)
        assert instance["itemCount"] == len(instance["changes"]["items"])
        assert instance["certificationStatus"] == "PENDING"
        assert instance["certifiedPath"] is False
        with fitz.open(path) as doc:
            assert instance["pages"] == len(doc)
            text = "".join("".join(page.get_text().split()) for page in doc)
            for item in instance["changes"]["items"]:
                assert text.count("".join(item["name"].split())) == 1
            for key in ("subtotal", "vat", "grand"):
                total = instance["totals"][key]
                assert (f"{total:,}" if isinstance(total, int) else total) in text


@pytest.mark.parametrize("dpi", [72, 144])
def test_raster_collinearity_oracle_rejects_original_and_accepts_candidate(dpi):
    pair_json = os.environ.get("B66_ALIGNMENT_RASTER_PAIRS")
    if not pair_json:
        pytest.skip("Set B66_ALIGNMENT_RASTER_PAIRS to pre-rendered original/candidate PDF pairs")
    fitz = pytest.importorskip("fitz")
    pairs = json.loads(pair_json)
    assert pairs
    scale = dpi / 72

    def border_columns(page):
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        samples = pix.samples
        result = []
        for top in (180, 350, 570):
            row = int(top*scale)*pix.width
            dark = [x for x in range(int(22*scale), int(28*scale))
                    if samples[row+x] < 160]
            assert dark, f"Missing border at y={top}, dpi={dpi}"
            result.append(min(dark))
        return result

    for pair in pairs:
        with fitz.open(pair["original"]) as original, fitz.open(pair["candidate"]) as revised:
            assert len(original) == len(revised)
            for index in sorted({0, len(revised)//2, len(revised)-1}):
                assert len(set(border_columns(original[index]))) > 1
                assert len(set(border_columns(revised[index]))) == 1
