"""Review-only adapter; consumes LOCAL1's unchanged, hash-pinned Sol engine."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from pypdf import PdfReader, PdfWriter
from align_template import LEFT, TEMPLATE_ID, sha

UPSTREAM_ADAPTER_SHA = "bb490106e8d11cabadf3e9f68b480ed2d2441f2d46607c5cd303bf5f78cbd646"

def load_upstream(directory, expected_hash):
    directory = Path(directory).resolve()
    path = directory / "sol61_multipage.py"
    if sha(path) != expected_hash:
        raise ValueError("Upstream renderer hash mismatch; refresh the review contract")
    if sha(directory / "slots_multipage.cjs") != UPSTREAM_ADAPTER_SHA:
        raise ValueError("Upstream QuoteCore adapter hash mismatch; refresh the review contract")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("sol61_alignment_upstream", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_candidate(module, bundle, output, changes, node="node"):
    bundle, output = Path(bundle), Path(output)
    template = json.loads((bundle / "template/template.json").read_text(encoding="utf-8"))
    if template["templateId"] != TEMPLATE_ID or template["certification"]["status"] != "PENDING":
        raise ValueError("Review-only versioned candidate required")
    engine = module.SolMultipage(bundle / "template", node=node)
    # LOCAL1 rounds its columns to 2 decimals. Use the actual source anchor so
    # its added grid and the template border coincide, including vector probes.
    engine.columns[0] = LEFT
    result = engine.render(output, changes)
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(output))
    writer.add_metadata({"/Producer": "B66 same-Sol geometry v2 CANDIDATE - NOT CERTIFIED",
                         "/TemplateId": TEMPLATE_ID, "/CertificationStatus": "PENDING"})
    with output.open("wb") as stream:
        writer.write(stream)
    result.update({"rendererId": "b66.sol61.geometry-v2.candidate", "rendererVersion": 2,
        "certifiedPath": False, "sourceRoute": "single-page" if result["itemCount"] <= 3 else "multipage",
        "newTemplateCertification": "PENDING", "ownerVisualApproval": "PENDING",
        "pdfSha256": sha(output)})
    instance = output.with_suffix(".instance.json")
    # Multipage upstream has no sidecar. Always write CURRENT authoritative
    # results, so a reused output path cannot attach old items/totals to a new PDF.
    data = {**result, "changes": changes, "templateManifestHash": sha(bundle / "template/template.json"),
            "certificationStatus": "PENDING", "runtimeSourceAccess": False, "modelCalls": 0}
    instance.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
