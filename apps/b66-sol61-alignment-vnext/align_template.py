"""Derive an unapproved geometry revision of the SAME Sol CGI vector program."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zlib

from pypdf import PdfReader
from pypdf.generic import ContentStream, DecodedStreamObject, FloatObject
from io import BytesIO

TEMPLATE_ID = "cgi-220621-source-vector-v2-alignment-candidate"
SOURCE_PROGRAM_SHA = "06d093382a2fa53f0254456452a214fa8dab1a273b099ef081c8a2cd73ecd309"
LEFT = 24.587
WIDTH = 0.72
LEFT_ANCHORS = (24.587, 24.706, 25.306, 25.670, 25.786, 26.506)
RING = [
    ([25.786, 707.226], b"m"), ([572.962, 707.226], b"l"),
    ([572.962, 579.896], b"l"), ([25.786, 579.896], b"l"),
    ([25.786, 707.226], b"l"), ([], b"h"),
    ([26.506, 580.645], b"m"), ([572.212, 580.645], b"l"),
    ([572.212, 706.507], b"l"), ([26.506, 706.507], b"l"),
    ([26.506, 580.645], b"l"), ([], b"h"),
]
RING_CLIP = [([24.587, 776.63], b"m"), ([572.692, 776.63], b"l"),
             ([572.692, 147.199], b"l"), ([24.587, 147.199], b"l"), ([], b"h")]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def serialize(args, op):
    stream = BytesIO()
    for arg in args:
        arg.write_to_stream(stream)
        stream.write(b" ")
    stream.write(op + b"\n")
    return stream.getvalue()


def _mul(a, b):
    return [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
            a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5]]


def _anchor(x):
    return any(abs(x - a) < 0.00001 for a in LEFT_ANCHORS)


def aligned_program(raw, reader):
    if hashlib.sha256(raw).hexdigest() != SOURCE_PROGRAM_SHA:
        raise ValueError("Unrecognised source program; review geometry before deriving")
    stream = DecodedStreamObject()
    stream.set_data(raw)
    ops = ContentStream(stream, reader).operations
    originals = [serialize(a, op) for a, op in ops]
    if b"".join(originals) != raw:
        raise ValueError("Serializer changed: cannot safely remap source bindings")
    replacements = {}
    cm, stack, path = [1, 0, 0, 1, 0, 0], [], []
    last_width = None
    audit = {"leftAnchorPt": LEFT, "leftStrokeWidthPt": WIDTH,
             "sourceProgramSha256": SOURCE_PROGRAM_SHA, "geometryEdits": [],
             "removedDuplicateLeftRules": 0, "replacedInfoFrames": 0,
             "expandedInfoFrameClips": 0}
    paints = (b"n", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*")
    for i, (args, op) in enumerate(ops):
        if op == b"q":
            stack.append((cm[:], last_width))
        elif op == b"Q":
            cm, last_width = stack.pop()
        elif op == b"cm":
            cm = _mul([float(v) for v in args], cm)
        elif op == b"w":
            last_width = i
        elif op in (b"m", b"l", b"re", b"c", b"v", b"y", b"h"):
            path.append((i, args, op, cm[:]))
        elif op in paints:
            signature = [([float(v) for v in a], o) for _, a, o, _ in path]
            if op == b"n" and signature == RING_CLIP:
                # The old clip starts at the NEW stroke centre. Include the
                # complete half-width on both sides, otherwise 200% raster
                # reveals a half-clipped (visually thinner) left border.
                for index, a, o, m in path:
                    if m != [1, 0, 0, 1, 0, 0]:
                        raise ValueError("Unexpected transformed frame clip")
                    if o in (b"m", b"l"):
                        new = copy.deepcopy(a)
                        new[0] = FloatObject(LEFT-WIDTH/2 if float(a[0]) < 100
                                             else (572.962+572.212)/2+WIDTH/2)
                        replacements[index] = serialize(new, o)
                audit["expandedInfoFrameClips"] += 1
            elif op == b"B" and signature == RING:
                if any(m != [1, 0, 0, 1, 0, 0] for _, _, _, m in path):
                    raise ValueError("Unexpected transformed information frame")
                # Keep the old ring's centre lines at top, right and bottom;
                # the left centre line is shared with the item/footer table.
                top = (707.226 + 706.507) / 2
                bottom = (579.896 + 580.645) / 2
                right = (572.962 + 572.212) / 2
                replacements[path[0][0]] = serialize(
                    [FloatObject(v) for v in (LEFT, bottom, right-LEFT, top-bottom)], b"re")
                for index, _, _, _ in path[1:]:
                    replacements[index] = b""
                replacements[i] = b"S\n"
                replacements[last_width] = b"0.72 w\n"
                audit["replacedInfoFrames"] += 1
                audit["infoFrameCentreLinesPdf"] = [LEFT, bottom, right, top]
            else:
                points = [(float(a[0])*m[0]+m[4], float(a[1])*m[3]+m[5])
                          for _, a, o, m in path if o in (b"m", b"l")]
                is_duplicate_left = (op in (b"S", b"s") and len(points) == 2
                    and all(abs(x-26.506) < 0.00001 for x, _ in points)
                    and min(y for _, y in points) >= 579
                    and max(y for _, y in points) <= 708)
                if is_duplicate_left:
                    replacements[i] = b"n\n"
                    audit["removedDuplicateLeftRules"] += 1
                is_short_dash = (op in (b"S", b"s") and len(points) == 2
                    and abs(points[0][1]-points[1][1]) < 0.00001
                    and abs(points[0][0]-points[1][0]) < 2)
                for index, a, o, m in path:
                    if is_duplicate_left or is_short_dash:
                        continue
                    if o not in (b"m", b"l", b"re"):
                        continue
                    if m[1] or m[2] or not m[0]:
                        continue
                    x = float(a[0])*m[0]+m[4]
                    if not _anchor(x):
                        continue
                    new = copy.deepcopy(a)
                    new_x = (LEFT-m[4])/m[0]
                    new[0] = FloatObject(new_x)
                    if o == b"re":
                        new[2] = FloatObject(float(a[0])+float(a[2])-new_x)
                    replacements[index] = serialize(new, o)
                    if abs(x-LEFT) > 0.00001:
                        audit["geometryEdits"].append({"operatorIndex": index,
                            "operator": o.decode(), "oldLeftPt": x, "newLeftPt": LEFT})
            path = []
    if (audit["replacedInfoFrames"] != 1 or audit["removedDuplicateLeftRules"] != 1
            or audit["expandedInfoFrameClips"] != 2):
        raise ValueError("Unexpected frame/rule/clip counts: " + str((audit["replacedInfoFrames"],
            audit["removedDuplicateLeftRules"], audit["expandedInfoFrameClips"])))
    offset_map, old_offset, new_offset, chunks = {}, 0, 0, []
    for i, original in enumerate(originals):
        offset_map[old_offset] = new_offset
        chunk = replacements.get(i, original)
        chunks.append(chunk)
        old_offset += len(original)
        new_offset += len(chunk)
    offset_map[old_offset] = new_offset
    return b"".join(chunks), offset_map, audit


def _remap_metadata(value, offsets):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("start", "end", "insertion") and isinstance(child, int):
                if child not in offsets:
                    raise ValueError(f"Binding offset is not an operation boundary: {key}={child}")
                value[key] = offsets[child]
            else:
                _remap_metadata(child, offsets)
    elif isinstance(value, list):
        for child in value:
            _remap_metadata(child, offsets)


def derive_bundle(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError("Candidate must be isolated from the issued bundle")
    if destination.exists():
        raise ValueError("Use an empty new destination; issued/candidate assets are never overwritten")
    manifest_path = source.parent / "PUBLIC_RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = {}
    for name, entry in manifest["artifacts"].items():
        actual = sha(source.parent / name)
        if actual != entry["sha256"]:
            raise ValueError(f"Issued public release integrity failure: {name}")
        hashes[name] = actual
    template = json.loads((source / "template/template.json").read_text(encoding="utf-8"))
    raw = zlib.decompress((source / "template/program.zlib").read_bytes())
    program, offsets, audit = aligned_program(raw, PdfReader(source / "template/resources.pdf"))
    _remap_metadata(template, offsets)
    template["derivedFromTemplateId"] = template["templateId"]
    template["templateId"] = TEMPLATE_ID
    template["geometryRevision"] = {"version": 2, "status": "OWNER_VISUAL_APPROVAL_PENDING",
        "requiresNewCertificate": True, "leftAnchorPt": LEFT, "leftStrokeWidthPt": WIDTH}
    template["certification"] = {"status": "PENDING", "requiresNewCertificate": True,
        "ownerVisualApproval": "PENDING", "scope": "new geometry; all item counts unapproved"}
    template["renderer"]["programSha256"] = hashlib.sha256(program).hexdigest()
    template["renderer"]["geometryVersion"] = 2
    destination.mkdir(parents=True)
    shutil.copytree(source / "engine", destination / "engine", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(source / "template", destination / "template", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(source / "quote-core.js", destination / "quote-core.js")
    (destination / "template/program.zlib").write_bytes(zlib.compress(program))
    (destination / "template/template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    audit.update({"templateId": TEMPLATE_ID, "certificationStatus": "PENDING",
        "issuedManifestSha256": sha(manifest_path), "issuedArtifactHashes": hashes,
        "candidateProgramSha256": hashlib.sha256(program).hexdigest(),
        "certificateInherited": False})
    (destination / "ALIGNMENT_CANDIDATE.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--candidate-bundle", type=Path, required=True)
    args = parser.parse_args()
    result = derive_bundle(args.source_bundle, args.candidate_bundle)
    print(json.dumps({k: result[k] for k in ("templateId", "certificationStatus",
        "candidateProgramSha256", "leftAnchorPt", "leftStrokeWidthPt")}, indent=2))
