from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook, load_workbook


XLSX_VALUE = "Padiem XLSX worker compatibility"


def test_openpyxl_in_memory_round_trip_extracts_known_value() -> None:
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = XLSX_VALUE
    workbook.save(output)

    output.seek(0)
    parsed = load_workbook(output, read_only=True, data_only=True)
    try:
        assert parsed.active["A1"].value == XLSX_VALUE
    finally:
        parsed.close()
