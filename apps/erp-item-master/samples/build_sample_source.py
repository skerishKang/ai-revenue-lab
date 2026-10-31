"""Write the anonymous sample catalog for the ERP item-master pilot (#5447).

The catalog is synthetic. Every maker, supplier, item and price in it was
made up for this pilot, so it can be committed and published without carrying
a customer's product list, price list or business information.

The rows are deliberately messy in the ways a real supplier file is messy:
mixed spacing, a lower-case code, full-width digits, a currency suffix, a
thousands separator, a price that was never filled in, a price that only says
"ask", a row with no code at all and one item submitted twice.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HEADERS = (
    "품목코드",
    "상품명",
    "모델명",
    "제조사",
    "공급사",
    "규격",
    "단위",
    "분류",
    "매입가",
    "판매가",
    "담당자",
    "메모",
)

ROWS: tuple[tuple[str, ...], ...] = (
    (
        " brg-6205-01 ",
        " 볼  베어링  6205-2RS ",
        "6205-2RS",
        "한빛베어링",
        "대한물산",
        "6205-2RS / 내경25mm 외경52mm",
        "EA",
        "베어링",
        "8,500원",
        "12,000",
        "김민수",
        "표준 재고 품목",
    ),
    (
        "HOS-0150-01",
        "유압호스 조립체",
        "HH-2024-08",
        "유니크라스트",
        "한국산업",
        "1/2인치 x 1500mm",
        "본",
        "호스/튜브",
        "32000",
        "45000",
        "박지훈",
        "4MPa 등급",
    ),
    (
        "BLT-M8-30-A",
        "스테인리스 육각볼트 M8x30",
        "M8x30-A2-70",
        "스틸패스",
        "동양패스",
        "M8 x 30mm / SUS304",
        "EA",
        "볼트/너트",
        "1,200",
        "190",
        "박지훈",
        "",
    ),
    (
        "SEN-018N-01",
        "포토센서 NPN 18mm",
        "PS-18N",
        "센서텍",
        "서남전자",
        "감도 18mm / NPN NO",
        "EA",
        "센서",
        "18000",
        "25000",
        "최유진",
        "",
    ),
    (
        "OIL-VG220-18",
        "기어오일 ISO VG 220",
        "VG220-18L",
        "오일텍",
        "석화케미칼",
        "ISO VG 220 / 18L",
        "드럼",
        "윤활유",
        "",
        "128000",
        "최유진",
        "18L 드럼 기준",
    ),
    (
        "BLT-A45-000",
        "A형 벨트 A-45",
        "A-45",
        "벨트코어",
        "태성벨트",
        "A-45 / 15mm",
        "EA",
        "벨트",
        "문의",
        "12000",
        "김민수",
        "",
    ),
    (
        "",
        "알루미늄 ４０x４０ 프로파일",
        "AL-4040",
        "알루미늄텍",
        "메탈프론",
        "40 x 40 x 2000mm",
        "본",
        "알루미늄",
        "6800",
        "9500",
        "박지훈",
        "",
    ),
    (
        "CAL-0150-00",
        "디지털 캘리퍼스 150mm",
        "",
        "메ASUREKOREA",
        "",
        "0-150mm / 0.01mm",
        "EA",
        "계측기",
        "28000",
        "39000",
        "최유진",
        "정밀계측상 외주 발주 건. 감도 0.01mm 규격 확인 요망",
    ),
    (
        "CAL-0150-01",
        "디지털 캘리퍼스 150mm 정밀",
        "",
        "메ASUREKOREA",
        "정밀계측",
        "0-150mm / 해상도 0.01mm",
        "EA",
        "계측기",
        "27500",
        "38500",
        "최유진",
        "",
    ),
    (
        "SEN-018N-01",
        "포토센서 NPN 18mm",
        "PS-18N",
        "센서텍",
        "서남전자",
        "감도 18mm / NPN NO",
        "EA",
        "센서",
        "18000",
        "25000",
        "최유진",
        "동일 품목 재전송 건",
    ),
)

#: The extraction result the pilot feeds into the pipeline. It is keyed by
#: item code. One proposal is accepted (a supplier read out of a free-text
#: note) and two are refused (a price and a price), because a generated price
#: is a fabricated business fact.
EXTRACTIONS: dict[str, dict[str, object]] = {
    "CAL-0150-00": {
        "fields": {
            "supplier": {"value": "정밀계측", "confidence": 0.72},
            "sales_price": {"value": "39500", "confidence": 0.9},
        }
    },
    "BLT-A45-000": {
        "fields": {
            "purchase_price": {"value": "12000", "confidence": 0.85},
        }
    },
}


def main() -> None:
    here = Path(__file__).resolve().parent
    catalog = here / "source_items_raw.csv"
    with catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(HEADERS)
        for row in ROWS:
            writer.writerow(list(row))

    extraction = here / "extraction_results.json"
    extraction.write_text(
        json.dumps(EXTRACTIONS, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {catalog.name} ({len(ROWS)} rows)")
    print(f"wrote {extraction.name} ({len(EXTRACTIONS)} entries)")


if __name__ == "__main__":
    main()
