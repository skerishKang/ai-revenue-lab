"""Evidence check for PC mutations; a question is a normal completed turn.

Only role-preserved user speech establishes intent. Material read from tools
cannot authorize a mutation, even when it contains an imperative or a path.
The side channel is supplied by the authenticated product, never the model.
It neither changes the model prompt nor grants a tool/device permission.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

_ROLES = {"user", "assistant", "tool_result"}
_SOURCES = {"list", "file", "web", "mail", "unknown"}
_KEYS = {"role", "content", "source", "visible", "paths"}
_OPS = {"claw.pc.delete_file": "delete", "claw.pc.move_file": "move", "claw.pc.write_file": "write"}
# These tools return source material even when their names omit "read".
# A handle or a compacted-source recall never turns that material into intent.
_EXTERNAL_MATERIAL_TOOLS = frozenset({
    "claw.pc.read_file", "claw.pc.read_output", "claw.pc.search_output",
    "claw.pc.job_output", "claw.pc.recall_context",
})


def _external_material_tool(tool_id) -> bool:
    return isinstance(tool_id, str) and tool_id != "claw.pc.list_files" and (
        tool_id in _EXTERNAL_MATERIAL_TOOLS
        or any(word in tool_id.lower() for word in ("web", "mail", "fetch", "read"))
    )


_BATCH_NON_MATERIAL_TOOLS = frozenset({
    "claw.pc.query_drives", "claw.pc.list_files", "claw.pc.write_file",
    "claw.pc.move_file", "claw.pc.delete_file",
})


def _external_material_observation(record) -> bool:
    if not isinstance(record, Mapping):
        return False
    if record.get("tool_id") != "claw.pc.batch":
        return _external_material_tool(record.get("tool_id"))
    output = record.get("output")
    source_ids = output.get("source_tool_ids") if isinstance(output, Mapping) else None
    # A composite result preserves attempted child IDs. Missing/malformed or
    # unknown provenance cannot conceal a source read behind the batch wrapper.
    return not (
        isinstance(source_ids, (list, tuple)) and source_ids
        and all(isinstance(tool_id, str) and tool_id in _BATCH_NON_MATERIAL_TOOLS
                for tool_id in source_ids)
    )


_VERBS = {"delete": "지울까요", "move": "옮길까요", "write": "저장할까요"}
_INTENT = {
    "delete": re.compile(r"(?:지워|지우|지울|삭제|제거|\b(?:delete|remove|erase)\b)", re.I),
    "move": re.compile(r"(?:옮겨|옮기|옮길|이동|이름.{0,8}바꿔|이름.{0,8}변경|\b(?:move|rename)\b)", re.I),
    "write": re.compile(r"(?:저장|덮어|파일.{0,16}(?:만들|작성|써)|\b(?:save|overwrite)\b|\b(?:write|create)\b.{0,40}\b(?:file|to|into)\b)", re.I),
}
_QUOTED = re.compile(r'`[^`]*`|"[^"\n]*"|\'[^\'\n]*\'|“[^”]*”|‘[^’]*’')
_PATH = re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|/)?(?:[^\\/\s<>\"'`:,;()[\]{}]+[\\/])*[^\\/\s<>\"'`:,;()[\]{}]+\.[A-Za-z0-9]{1,12}")
_LIST_LINE = re.compile(r"^\s*(?:[①-⑳]|\d+[.)번]|[-*•])\s*(.+)$")
_CHOICE = re.compile(r"^\s*(?:([①-⑳])|(?:제\s*)?(\d+))\s*(?:번째|번)?(?:\s*(?:파일|으로|을|를|이요|요|해줘|해 주세요|부탁해))*[.!。]?\s*$")
_YES = re.compile(r"^\s*(?:네|예|응|그래|맞아|진행해|해줘|확인|yes|ok|okay|go ahead)[.!。]?\s*$", re.I)
_DEICTIC = re.compile(r"(?:그\s*(?:파일|문서|것)|이\s*파일|방금|해당|첫\s*번째|두\s*번째|\b(?:that|it|this file)\b)", re.I)


def parse_pc_action_context(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("PC action context must be role-structured")
    records = []
    for record in value:
        if (not isinstance(record, Mapping) or not {"role", "content"} <= set(record)
                or set(record) - _KEYS or not isinstance(record.get("role"), str) or record["role"] not in _ROLES
                or not isinstance(record.get("content"), str)):
            raise ValueError("PC action context record is invalid")
        if "source" in record and (not isinstance(record["source"], str) or record["source"] not in _SOURCES):
            raise ValueError("PC action context source is invalid")
        if "visible" in record and type(record["visible"]) is not bool:
            raise ValueError("PC action context visibility is invalid")
        if "paths" in record and (not isinstance(record["paths"], (list, tuple))
                or any(not isinstance(p, str) or not p.strip() for p in record["paths"])):
            raise ValueError("PC action context targets are invalid")
        copied = dict(record)
        if "paths" in copied:
            copied["paths"] = list(copied["paths"])
        records.append(copied)
    return tuple(records)


def _normal(path: str) -> str:
    return path.strip().replace("\\", "/").rstrip("/").casefold()


def _paths(text: str) -> list[str]:
    values = []
    quoted_ranges = []
    for quoted in _QUOTED.finditer(text):
        item = quoted.group()[1:-1].strip()
        if ("/" in item or "\\" in item or re.search(r"\.[A-Za-z0-9]+$", item)) and not any(c in item for c in "\n\r"):
            values.append((quoted.start(), item))
            quoted_ranges.append(quoted.span())
    values.extend((match.start(), match.group()) for match in _PATH.finditer(text)
                  if not any(start <= match.start() < end for start, end in quoted_ranges))
    return _unique(value for _, value in sorted(values))


def _unique(values) -> list[str]:
    result, seen = [], set()
    for item in values:
        if isinstance(item, str) and item.strip() and _normal(item) not in seen:
            result.append(item.strip())
            seen.add(_normal(item))
    return result


def _mention(text: str, path: str):
    # Segment boundaries avoid a.txt authorizing not-a.txt or a.txt.exe.
    literal = re.escape(_normal(path))
    return re.search(r"(?<![\w./:-])" + literal + r"(?![A-Za-z0-9_./:-])", text.replace("\\", "/").casefold())


def _mentions(text: str, path: str) -> bool:
    return _mention(text, path) is not None


def _same_target(candidate: str, path: str) -> bool:
    candidate, path = _normal(candidate), _normal(path)
    return candidate == path or ("/" not in candidate and ":" not in candidate and candidate == path.rsplit("/", 1)[-1])


def _intent(op: str, text: str) -> bool:
    # Quoted material is not an instruction even when the user discusses it.
    speech = _QUOTED.sub("", text)
    if re.search(r"(?:나중에|허락하면|허용하면|승인하면|확인하면|\b(?:if|unless|when)\b)", speech, re.I):
        return False
    for match in _INTENT[op].finditer(speech):
        before, after = speech[:match.start()], speech[match.end():]
        # Check the requested verb, not unrelated words elsewhere in the turn:
        # "요약한 글을 저장해줘" is a write; "삭제하는 방법" is discussion.
        if re.search(r"(?:\b(?:don['’]?t|do not|never|without|not|how to)\b[^.!?;\n]*|안\s*)$", before, re.I):
            continue
        if re.match(r"\s*(?:는\s*)?(?:하지\s*마|지\s*마|하지\s*말|지\s*말|금지|안\s*해|하지\s*않|면\s*안|하면\s*안)", after):
            continue
        if re.match(r"\s*(?:하는\s*(?:방법|법)|는\s*법|하?라고|하?라는|의\s*(?:뜻|의미)|가\s*가능|에\s*대해|\s*요청에\s*대해)", after):
            continue
        return True
    return False


def _shown(record: Mapping[str, Any]) -> list[str]:
    if record["role"] == "tool_result":
        return _unique(record.get("paths", ())) if record.get("source") == "list" and record.get("visible") is True else []
    if record["role"] != "assistant":
        return []
    result = []
    for line in record["content"].splitlines():
        matched = _LIST_LINE.match(line)
        if matched:
            result.extend(_paths(matched[1]))
    for item in re.findall(r"[①-⑳]\s*([^①-⑳\n]+)", record["content"]):
        result.extend(_paths(item))
    # A harness question presents one concrete path as an explicit choice.
    if "?" in record["content"] and any(v in record["content"] for v in _VERBS.values()):
        result.extend(_paths(record["content"]))
    return _unique(result)


def _numbered_choices(text: str) -> dict[int, str]:
    choices = {}
    # Preserve displayed numbers; a non-file menu entry must not shift them.
    for line in re.split(r"\n|(?=[①-⑳])", text):
        match = re.match(r"\s*([①-⑳]|\d+[.)번])\s*(.+)$", line)
        if match:
            paths = _paths(match[2])
            number = ord(match[1]) - ord("①") + 1 if match[1] in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳" else int(match[1][:-1])
            if len(paths) == 1:
                choices[number] = paths[0]
    return choices


def _observation_paths(observations) -> list[str]:
    paths = []
    for observation in observations:
        if not isinstance(observation, Mapping) or observation.get("tool_id") != "claw.pc.list_files":
            continue
        output = observation.get("output", {})
        output = output.get("output", output) if isinstance(output, Mapping) else output
        try:
            output = json.loads(output) if isinstance(output, str) else output
        except ValueError:
            continue
        entries = output.get("entries", ()) if isinstance(output, Mapping) else ()
        if isinstance(entries, list):
            paths.extend(row.get("relative_path") for row in entries if isinstance(row, Mapping) and row.get("PSIsContainer") is not True)
    return _unique(paths)


class PcActionHarness:
    def __init__(self, records=()):
        self.records = parse_pc_action_context(records)

    def question(self, tool_id: str, arguments: Mapping[str, Any], *, observations=(), preceding_tool_ids=()) -> str | None:
        op = _OPS.get(tool_id)
        if op is None:
            return None
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return self._ask(op, [])
        users = [i for i, row in enumerate(self.records) if row["role"] == "user"]
        if not users:
            return self._ask(op, [])
        index = users[-1]
        speech = self.records[index]["content"]
        before = self.records[:index]
        shown = _unique(p for row in before for p in _shown(row))
        previous_user_paths = _unique(p for row in before if row["role"] == "user" for p in _paths(row["content"]))
        candidates = _unique(shown + previous_user_paths + _observation_paths(observations))
        assistant = next((row for row in reversed(before) if row["role"] == "assistant"), None)
        choices = _shown(assistant) if assistant else []
        selection = _CHOICE.fullmatch(speech)
        selected = None
        if selection and choices:
            number = ord(selection[1]) - ord("①") + 1 if selection[1] else int(selection[2])
            selected = _numbered_choices(assistant["content"]).get(number)
        # A bare choice answers the concrete operation question we showed.
        # An unrelated menu mentioning delete cannot authorize every choice.
        question_intent = bool(assistant and re.search(
            re.escape(_VERBS[op]) + r"\s*\?", assistant["content"].splitlines()[0]))
        if _YES.fullmatch(speech) and len(choices) == 1 and question_intent:
            selected = choices[0]
        from app.pc_action_delegation import confirmed_delegation_action

        delegation_confirmation = confirmed_delegation_action(tool_id, arguments, self.records)
        if delegation_confirmation:
            # A new user reply can confirm the exact two-path move question.
            # Current-turn tool material is still checked below before acting.
            selected, question_intent = path, True
        intent = _intent(op, speech) or (selected is not None and question_intent)
        if not intent:
            return self._ask(op, candidates, path if _mentions(speech, path) else None)

        # Current-turn material cannot escalate an authorized read into a write.
        external = any(row["role"] == "tool_result" and row.get("source") != "list" for row in self.records[index + 1:])
        external = external or any(_external_material_observation(row) for row in observations)
        # Composite preflight checks planned reads before any step runs. These
        # IDs express ordering, never a claim that a tool has already executed.
        external = external or any(_external_material_tool(tool) for tool in preceding_tool_ids)
        if external:
            return f"읽은 자료에 이어 `{path}` 파일을 {_VERBS[op]}?"

        explicit = _paths(speech)
        if _mentions(speech, path):
            explicit.append(path)
        relevant = _unique(explicit)
        if selected is not None:
            relevant = [selected]
        elif not relevant and _DEICTIC.search(speech):
            # Prefer the latest user-visible list; multiple candidates ask.
            relevant = next((targets for row in reversed(before)
                if (targets := (_paths(row["content"]) if row["role"] == "user" else _shown(row)))), [])
        # A basename cannot invent a parent directory. Resolve it only against
        # a full path already shown to the user, never a model-only listing.
        known_path = any(_normal(p) == _normal(path) for p in shown + previous_user_paths)
        if not relevant or not any(_normal(p) == _normal(path) or (known_path and _same_target(p, path)) for p in relevant):
            return self._ask(op, candidates)
        matching = [p for p in candidates if _same_target(path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], p)]
        named_exactly = any(_normal(p) == _normal(path) for p in relevant)
        if (len(relevant) > 1 and selected is None and op != "move") or (len(matching) > 1 and not named_exactly):
            return self._ask(op, relevant if len(relevant) > 1 else matching)
        if op == "move":
            if delegation_confirmation:
                return None
            destination = arguments.get("destination")
            destination_match = _mention(speech, destination) if isinstance(destination, str) else None
            if destination_match is None:
                return "어디로 옮길까요? 도착할 폴더나 파일 경로를 알려 주세요."
            source_match = next((_mention(speech, p) for p in relevant if _same_target(p, path)), None)
            if source_match is None or source_match.start() >= destination_match.start():
                return "어떤 파일을 어디로 옮길까요? 출발 경로와 도착 경로를 순서대로 알려 주세요."
        return None

    @staticmethod
    def _ask(op, candidates, target=None):
        if target:
            return f"`{target}` 파일을 정말 {_VERBS[op]}?"
        candidates = _unique(candidates)
        if not candidates:
            return f"어떤 파일을 {_VERBS[op]}? 대상 파일의 경로를 알려 주세요."
        labels = [chr(ord("①") + i) if i < 20 else f"{i + 1}." for i in range(len(candidates))]
        return f"어떤 파일을 {_VERBS[op]}?\n" + "\n".join(f"{label} `{p}`" for label, p in zip(labels, candidates))
