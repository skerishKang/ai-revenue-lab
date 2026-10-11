# -*- coding: utf-8 -*-
"""B66 benchmark — generic text formatting utilities.

Shared by template compilation and runtime rendering. This module contains
ONLY generic document-formatting logic (Excel-compatible number/date/Korean
number-words formatting). It must never contain template- or customer-specific
facts; those live in quote_template.json.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_SERIAL_MIN = 1
EXCEL_SERIAL_MAX = 2958465  # 9999-12-31


def norm_text(s) -> str:
    """관용 정규화: 숫자/영문/한글 이외(콤마, 공백, 기호) 제거 — 컴파일 시
    셀 표시값과 PDF span 텍스트를 대조하기 위한 결정적 매칭 규칙."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(s))


def format_comma(n: int) -> str:
    """정수 → 천단위 콤마 (Excel '#,##0' 표시와 동일)."""
    return f"{int(n):,}"


def korean_number_words(n: int) -> str:
    """정수 → 한국어 수사 (Excel NUMBERSTRING(n,1) 호환, 만/억/조 단위).

    예: 123450000 → '일억이천삼백사십오만', 45000 → '사만오천'
    """
    digits = "공일이삼사오육칠팔구"
    units_small = ["", "십", "백", "천"]
    units_big = ["", "만", "억", "조", "경"]
    n = int(n)
    if n == 0:
        return "영"
    if n < 0:
        return "마이너스" + korean_number_words(-n)
    result = []
    big_idx = 0
    remaining = n
    while remaining > 0:
        remaining, part = divmod(remaining, 10000)
        if part:
            sub = []
            small_idx = 0
            while part > 0:
                part, d = divmod(part, 10)
                if d:
                    prefix = digits[d]
                    if d == 1 and small_idx > 0:
                        prefix = ""
                    sub.append(prefix + units_small[small_idx])
                small_idx += 1
            result.append("".join(reversed(sub)) + units_big[big_idx])
        big_idx += 1
    return "".join(reversed(result))


def serial_to_date(serial: int) -> date:
    return EXCEL_EPOCH + timedelta(days=int(serial))


def render_date_parts(serial: int, parts: list[dict]) -> list[str]:
    """컴파일된 날짜 parts 스펙(디지트 필드/리터럴) → 렌더 문자열 목록.

    parts: [{"kind": "Y"|"M"|"D"|"lit", "text": ...}, ...] — lit은 컴파일 시
    원본 span에서 추출된 리터럴 그대로 사용.
    """
    d = serial_to_date(serial)
    out = []
    for p in parts:
        kind = p["kind"]
        if kind == "Y":
            out.append(f"{d.year:04d}")
        elif kind == "M":
            out.append(f"{d.month:02d}")
        elif kind == "D":
            out.append(f"{d.day:02d}")
        else:
            out.append(p["text"])
    return out
