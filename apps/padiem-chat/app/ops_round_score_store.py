"""#8035 ③ (#7718 흡수): 회차 점수 저장소 — 입력·수정·숨김·집계.

한 행은 한 고객 이름의 한 회차(날짜·출처)다. 화면과 (후속) 운영 도구가 같은
함수를 쓴다(#8035 원칙). 지우기는 행을 없애지 않고 `hidden_at`만 채우므로
감사 기록과 함께 이력이 남고, 집계·목록에서는 빠진다.

점수는 1~5 정수만 받는다. 계정 식별자·이메일은 담지 않고, 관리자가 적는
고객 이름(표시용)만 담는다. 모든 쿼리는 바인딩이다.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .d1_rows import rows_from_result

SCORE_ID = re.compile(r"opsrs_[0-9a-f]{32}\Z")
ROUND_ON = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
SOURCES = ("ai", "human")
MEMO_MAX = 400
NAME_MAX = 120
_PAGE_LIMIT = 100
_COLUMNS = (
    "id, persona_name, round_no, round_on, source, return_score, pretty_score,"
    " memo, hidden_at, created_by, updated_by, created_at, updated_at"
)


class RoundScoreInvalid(Exception):
    """요청 값이 규칙을 벗어나다 — 라우트가 400으로 닫는다."""


class RoundScoreMissing(Exception):
    pass


class RoundScoreConflict(Exception):
    """같은 고객·회차·날짜·출처가 이미 있다."""


class RoundScoreUnavailable(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise RoundScoreInvalid()
    text = value.strip()
    if not 1 <= len(text) <= NAME_MAX or any(ord(ch) < 32 for ch in text):
        raise RoundScoreInvalid()
    return text


def _clean_round(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 9999:
        raise RoundScoreInvalid()
    return value


def _clean_day(value: Any) -> str:
    if not isinstance(value, str) or ROUND_ON.fullmatch(value) is None:
        raise RoundScoreInvalid()
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise RoundScoreInvalid() from None
    return value


def _clean_source(value: Any) -> str:
    if not isinstance(value, str) or value not in SOURCES:
        raise RoundScoreInvalid()
    return value


def _clean_score(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 5:
        raise RoundScoreInvalid()
    return value


def _clean_memo(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MEMO_MAX:
        raise RoundScoreInvalid()
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise RoundScoreInvalid()
    return value


def _row(row: dict) -> dict:
    return {
        "id": row["id"], "persona_name": row["persona_name"],
        "round_no": row["round_no"], "round_on": row["round_on"],
        "source": row["source"], "return_score": row["return_score"],
        "pretty_score": row["pretty_score"], "memo": row["memo"],
        "hidden": bool(row.get("hidden_at")),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


class D1OpsRoundScoreStore:
    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("ops round score binding missing")
        self._db = db

    async def _rows(self, sql: str, *values):
        try:
            result = await self._db.prepare(sql).bind(*values).run()
        except Exception:
            raise RoundScoreUnavailable() from None
        return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row)
                for row in rows_from_result(result)]

    async def create(self, *, actor: str, persona_name: Any, round_no: Any,
                     round_on: Any, source: Any, return_score: Any,
                     pretty_score: Any, memo: Any = "") -> dict:
        name = _clean_name(persona_name)
        number = _clean_round(round_no)
        day = _clean_day(round_on)
        origin = _clean_source(source)
        again = _clean_score(return_score)
        pretty = _clean_score(pretty_score)
        note = _clean_memo(memo)
        if not isinstance(actor, str) or not actor:
            raise RoundScoreInvalid()
        same = await self._rows(
            "SELECT id FROM ops_round_score WHERE persona_name=? AND round_no=?"
            " AND round_on=? AND source=?", name, number, day, origin)
        if same:
            raise RoundScoreConflict()
        score_id = "opsrs_" + secrets.token_hex(16)
        moment = _now()
        await self._rows(
            "INSERT INTO ops_round_score (id, persona_name, round_no, round_on,"
            " source, return_score, pretty_score, memo, hidden_at, created_by,"
            " updated_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
            score_id, name, number, day, origin, again, pretty, note,
            actor, actor, moment, moment)
        return await self.get(score_id)

    async def get(self, score_id: str) -> dict:
        if not isinstance(score_id, str) or SCORE_ID.fullmatch(score_id) is None:
            raise RoundScoreMissing()
        rows = await self._rows(
            "SELECT " + _COLUMNS + " FROM ops_round_score WHERE id=?", score_id)
        if not rows:
            raise RoundScoreMissing()
        return _row(rows[0])

    async def update(self, score_id: str, *, actor: str, changes: dict) -> dict:
        current = await self.get(score_id)
        if current["hidden"]:
            raise RoundScoreMissing()
        if not isinstance(actor, str) or not actor:
            raise RoundScoreInvalid()
        if not isinstance(changes, dict) or not changes:
            raise RoundScoreInvalid()
        allowed = {"persona_name", "round_no", "round_on", "source",
                   "return_score", "pretty_score", "memo"}
        if set(changes) - allowed:
            raise RoundScoreInvalid()
        values = {
            "persona_name": _clean_name(changes.get("persona_name", current["persona_name"])),
            "round_no": _clean_round(changes.get("round_no", current["round_no"])),
            "round_on": _clean_day(changes.get("round_on", current["round_on"])),
            "source": _clean_source(changes.get("source", current["source"])),
            "return_score": _clean_score(changes.get("return_score", current["return_score"])),
            "pretty_score": _clean_score(changes.get("pretty_score", current["pretty_score"])),
            "memo": _clean_memo(changes.get("memo", current["memo"])),
        }
        clash = await self._rows(
            "SELECT id FROM ops_round_score WHERE persona_name=? AND round_no=?"
            " AND round_on=? AND source=? AND id<>?",
            values["persona_name"], values["round_no"], values["round_on"],
            values["source"], score_id)
        if clash:
            raise RoundScoreConflict()
        await self._rows(
            "UPDATE ops_round_score SET persona_name=?, round_no=?, round_on=?,"
            " source=?, return_score=?, pretty_score=?, memo=?, updated_by=?,"
            " updated_at=? WHERE id=? AND hidden_at IS NULL",
            values["persona_name"], values["round_no"], values["round_on"],
            values["source"], values["return_score"], values["pretty_score"],
            values["memo"], actor, _now(), score_id)
        return await self.get(score_id)

    async def hide(self, score_id: str, *, actor: str) -> dict:
        current = await self.get(score_id)
        if current["hidden"]:
            raise RoundScoreMissing()
        if not isinstance(actor, str) or not actor:
            raise RoundScoreInvalid()
        await self._rows(
            "UPDATE ops_round_score SET hidden_at=?, updated_by=?, updated_at=?"
            " WHERE id=? AND hidden_at IS NULL", _now(), actor, _now(), score_id)
        return await self.get(score_id)

    async def list_scores(self, *, persona: str | None = None,
                          include_hidden: bool = False, limit: int = 50) -> list[dict]:
        bounded = limit if type(limit) is int and 0 < limit <= _PAGE_LIMIT else 50
        predicates = []
        values: list[Any] = []
        if not include_hidden:
            predicates.append("hidden_at IS NULL")
        if persona is not None:
            name = _clean_name(persona)
            predicates.append("persona_name=?")
            values.append(name)
        where = (" WHERE " + " AND ".join(predicates)) if predicates else ""
        rows = await self._rows(
            "SELECT " + _COLUMNS + " FROM ops_round_score" + where +
            " ORDER BY round_on DESC, round_no DESC, id DESC LIMIT ?",
            *values, bounded)
        return [_row(row) for row in rows]

    async def journal(self, *, days: int = 30, now=None) -> dict:
        """기간별 지표 + 고객별 회차 점수 추이(날짜 오름차순).

        기간 지표는 숨기지 않은 회차만 센다. 활동/떠난 고객은 의견 저장소의
        집계(이미 있는 값)를 그대로 쓰고, 여기서는 점수 쪽만 더한다.
        """
        bounded = days if type(days) is int and 0 < days <= 365 else 30
        current = now or datetime.now(timezone.utc)
        since = (current - timedelta(days=bounded)).strftime("%Y-%m-%d")
        totals = await self._rows(
            "SELECT COUNT(*) AS n, AVG(return_score) AS again,"
            " AVG(pretty_score) AS pretty FROM ops_round_score"
            " WHERE hidden_at IS NULL AND round_on>=?", since)
        head = totals[0] if totals else {}
        rows = await self._rows(
            "SELECT persona_name, source, round_no, round_on, return_score,"
            " pretty_score FROM ops_round_score"
            " WHERE hidden_at IS NULL AND round_on>=?"
            " ORDER BY persona_name ASC, round_on ASC, round_no ASC", since)
        people: dict[str, dict] = {}
        for row in rows:
            name = row["persona_name"]
            person = people.setdefault(name, {
                "persona": name, "source": row["source"], "rounds": 0,
                "latest_score": None, "latest_on": None, "entries": []})
            person["rounds"] += 1
            person["source"] = row["source"]
            person["latest_score"] = row["return_score"]
            person["latest_on"] = row["round_on"]
            person["entries"].append({
                "round": row["round_no"], "at": row["round_on"],
                "score": row["return_score"], "pretty": row["pretty_score"]})
        again = head.get("again")
        pretty = head.get("pretty")
        return {
            "days": bounded,
            "rounds": int(head.get("n") or 0),
            "return_avg": round(float(again), 2) if again is not None else None,
            "pretty_avg": round(float(pretty), 2) if pretty is not None else None,
            "personas": list(people.values()),
        }