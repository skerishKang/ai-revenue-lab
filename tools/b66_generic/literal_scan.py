# -*- coding: utf-8 -*-
"""B66 generic-module literal scan.

Proves the generic analyzer/compiler/renderer know NO document-specific or
customer-specific fact. The forbidden literal set is derived *automatically*
from the source evidence — every string that is present both in the source
workbook cells and in the rendered reference page, minus the compiler's generic
Korean-quotation vocabulary — plus the compiled template's baseline facts.

Usage:
    literal_scan.py --template-dir <dir> --evidence <dir> --modules <dir> [--out <json>]

Exit code 1 if any forbidden literal is found in the generic modules.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VOCAB = {
    # field labels
    "견적번호", "견적번호", "작성일자", "견적일자", "제출처", "수신처", "공급받는자",
    "건명", "공사명", "작성자", "담당자", "귀하",
    # item column names
    "품명", "품목", "품명및규격", "수량", "단가", "금액", "규격", "단위", "번호", "비고",
    # totals vocabulary
    "소계", "부가세", "합계", "총계", "종합금액",
    # written-total markers
    "합계금액", "일금",
}
VOCAB_NORM = {re.sub(r"[^0-9A-Za-z가-힣]", "", v).lower() for v in VOCAB}


def derive_forbidden(template: dict, xlsx: dict, pdf: dict) -> set[str]:
    out: set[str] = set()
    bv = template["baseline_values"]
    for k in ("quote_number", "recipient", "project_name"):
        v = bv.get(k)
        if v and str(v).strip():
            out.add(str(v).strip())
    for it in bv.get("items", []):
        if it.get("name"):
            out.add(str(it["name"]).strip())
        if it.get("unit_price") is not None:
            out.add(str(int(it["unit_price"])))
            out.add(f"{int(it['unit_price']):,}")
    if bv.get("issue_date_serial") is not None:
        out.add(str(int(bv["issue_date_serial"])))

    # strings present in BOTH the workbook and the rendered page = rendered facts
    page = pdf["pages"][template["page"].get("index", 0)]
    page_texts = {re.sub(r"\s+", " ", s["text"]).strip() for s in page["text_spans"]}
    sheet_name = template.get("certification", {}).get("source_sheet")
    sheets = xlsx["sheets"]
    cell_texts = set()
    for sname, sh in sheets.items():
        for _ref, c in sh["cells"].items():
            v = c["value"]
            if isinstance(v, str) and v.strip():
                cell_texts.add(re.sub(r"\s+", " ", v).strip())
    for t in cell_texts & page_texts:
        n = re.sub(r"[^0-9A-Za-z가-힣]", "", t).lower()
        if len(n) < 3 or n in VOCAB_NORM:
            continue
        out.add(t)

    # source file basenames are also private
    for src in (xlsx["source"]["path"], pdf["source"]["path"]):
        out.add(Path(src).stem)

    def fact_like(s: str) -> bool:
        """Customer/document facts in these quotations are Korean text or
        numbers. Plain ASCII words (e.g. a generic fixture file name) are not
        treated as facts, so the scan does not fire on ordinary code words."""
        core = re.sub(r"[^0-9A-Za-z가-힣]", "", s)
        has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in core)
        return len(core) >= 3 and (any(ch.isdigit() for ch in core) or has_hangul)

    return {s for s in out if fact_like(s)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-dir", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--modules", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    template = json.loads((Path(a.template_dir) / "quote_template.json").read_text(encoding="utf-8"))
    xlsx = json.loads((Path(a.evidence) / "xlsx_analysis.json").read_text(encoding="utf-8"))
    pdf = json.loads((Path(a.evidence) / "pdf_analysis.json").read_text(encoding="utf-8"))
    forbidden = derive_forbidden(template, xlsx, pdf)

    findings = []
    files = sorted(p for p in Path(a.modules).glob("*.py") if p.name != "literal_scan.py")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for lit in forbidden:
                if lit in line:
                    findings.append({"file": path.name, "line": lineno,
                                     "literal": lit, "text": line.strip()[:100]})
    result = {
        "CGI_SPECIFIC_LITERAL_IN_GENERIC_COMPILER": len(findings),
        "CUSTOMER_PRIVATE_FACT_IN_GENERIC_ENGINE": len(findings),
        "forbidden_literals_derived": len(forbidden),
        "scanned_modules": [p.name for p in files],
        "findings": findings,
        "PASS": len(findings) == 0,
    }
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "findings"}, ensure_ascii=False, indent=1))
    if findings:
        print(json.dumps(findings[:20], ensure_ascii=False, indent=1))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
