"""#5573 PC pairing store: who owns which PC, and which folders that link allows.

The tables from migration 072 (plus 089's supersede columns and 093's install
tokens). The rules this module owns are narrow on purpose:

* A pairing code is a **possession proof**, never an identity. Only its SHA-256
  and the SHA-256 of the install tag derived from it are stored; the plaintext
  code exists only in the response that hands it to the browser and the install
  link built from it. A code is single use and short lived.
* #6695 PR-4: each code is minted with one **install token**, also stored only
  as its SHA-256. The token is what an install URL carries, so a claim that
  presents a token minted for another account - or one the owner has revoked -
  is refused before any link is written. A code minted before this table
  existed has no token and pairs exactly as it did.
* A link is `(user_id, mesh_node_id)` — many accounts to many PCs (R1). The
  identity is validated by the same Core grammar the dispatch and presence
  lanes already use, in either canonical form, so a link can never name a
  device the Mesh lane cannot address.
* Folder approval belongs to the link, not the account and not the PC (R1, R5).
  Revoking one link cannot widen or narrow another account's roots on the same
  machine.
* Nothing here authorizes an execution. Dispatch keeps asking the same questions
  it asks today; this store only answers "is this PC this user's, and is this
  folder approved on that link".

No request ever supplies a `user_id`: it comes from the verified session, the
same as every other owner-scoped Chat store.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Mapping, Protocol

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .history import _row_to_dict, _rows_from_result

#: Ten minutes, as the CTO's contract states. A code that is never redeemed is
#: simply unusable after this; no sweeper is required because expiry is read
#: against a trusted receipt time on every path that matters.
PAIRING_CODE_TTL_SECONDS = 600
#: The plaintext never touches the database, so the alphabet only has to avoid
#: ambiguity for a human typing it into an installer prompt.
PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PAIRING_CODE_CHARS = 12
#: The tag the install wrapper stamps into the MeshCentral agent name. It is
#: derived from the code, so the PC needs nothing but the code to reproduce it.
PAIRING_TAG_PREFIX = "pd-"
PAIRING_TAG_CHARS = 8
#: #6695 PR-4: the per-account install token that travels beside the code. Only
#: its SHA-256 is stored, exactly like the code: the plaintext exists in the
#: issue response and the URL built from it, and nowhere else.
INSTALL_TOKEN_PREFIX = "pt_"
INSTALL_TOKEN_HEX_CHARS = 32
MAX_ROOTS_JSON_CHARS = 8192
MAX_ROOT_PATH_CHARS = 512
MAX_ROOT_LABEL_CHARS = 64
MAX_LINK_LABEL_CHARS = 128

_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,255}$")
_LINK_ID_RE = re.compile(r"^pclink_[0-9a-f]{32}$")
#: A whole drive, the shape the Owner's default scope grants (`C:`).
_DRIVE_ROOT_RE = re.compile(r"[A-Za-z]:")
_CODE_ID_RE = re.compile(r"^pcpair_[0-9a-f]{32}$")
#: The derived install tag: `pd-` plus the eight hex characters this module
#: produces. MeshCentral agent names are operator-editable text, so the tag is
#: found inside them rather than assumed to be them.
_AGENT_TAG_RE = re.compile(
    r"(?<![0-9A-Za-z])" + re.escape(PAIRING_TAG_PREFIX) + r"[0-9a-f]{8}(?![0-9A-Za-z])",
    re.IGNORECASE,
)
#: The install token as the install file stamps it into the agent name, right
#: after the tag. Matched the same careful way the tag is, so a longer word that
#: merely contains the shape is never mistaken for a presented token.
_INSTALL_TOKEN_RE = re.compile(
    r"^" + re.escape(INSTALL_TOKEN_PREFIX) + r"[0-9a-f]{%d}$" % INSTALL_TOKEN_HEX_CHARS
)
_AGENT_TOKEN_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    + re.escape(INSTALL_TOKEN_PREFIX)
    + r"[0-9a-f]{%d}" % INSTALL_TOKEN_HEX_CHARS
    + r"(?![0-9A-Za-z])",
    re.IGNORECASE,
)
#: A link carries up to two names of one machine in one bounded sentence: the
#: name Windows gave the PC, then the alias its owner chose. Both choose the PC.
_NAME_SEPARATOR = " · "
#: The drive list an installing PC writes after its tag in the agent name:
#: single letters inside one bracketed group.
_NAME_DRIVES_RE = re.compile(r"\[\s*([A-Za-z](?:[ \t]+[A-Za-z])*)\s*\]")
_STATE_ACTIVE = "active"
_STATE_PENDING_VERIFICATION = "pending_verification"
_STATE_REVOKED = "revoked"
#: A superseded link keeps `state='revoked'` (the table's own CHECK vocabulary,
#: unchanged by migration 089) and is stamped with `superseded_at`; the public
#: projection names that shape `replaced` so a record can say "a newer link for
#: this same computer took over" without a second state column.
_STATE_REPLACED = "replaced"


class PcPairingError(RuntimeError):
    """Bounded store/refusal reason. Never carries a code, node or path value."""


class PcPairingStore(Protocol):
    """The pairing surface the routes and (from PR-2) the dispatch lane read."""

    async def issue_code(self, *, user_id: str, issued_at: datetime) -> dict[str, Any]: ...

    async def redeem_code(
        self, *, code: str, mesh_node_id: str, label: str | None, now: datetime,
        verified: bool = False, drives: list[str] | None = None,
        install_token: str | None = None,
    ) -> dict[str, Any]: ...

    async def revoke_install_token(
        self, *, user_id: str, code_id: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def reissue_install_token(
        self, *, user_id: str, code_id: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def list_links(self, *, user_id: str) -> list[dict[str, Any]]: ...

    async def list_codes(self, *, user_id: str, now: datetime) -> list[dict[str, Any]]: ...

    async def peek_pairing_code(
        self, *, code: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def revoke_link(self, *, user_id: str, link_id: str, now: datetime) -> bool: ...

    async def set_link_label(
        self, *, user_id: str, link_id: str, label: Any, now: datetime,
    ) -> dict[str, Any]: ...

    async def pause_link(
        self, *, user_id: str, link_id: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def resume_link(
        self, *, user_id: str, link_id: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def approve_root(
        self, *, user_id: str, link_id: str, path: str, now: datetime,
        label: str | None = None,
    ) -> dict[str, Any]: ...

    async def links_for_owner(self, *, user_id: str) -> list[dict[str, Any]]: ...

    async def list_active_device_ids(self) -> list[str]: ...

    async def device_scope(self, *, device_id: Any) -> dict[str, Any] | None: ...

    async def delete_account_pc_data(self, *, user_id: str) -> bool: ...

    async def adopt_link(
        self, *, user_id: str, mesh_node_id: str, root_paths: list[str],
        now: datetime, label: str | None = None, drives: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def resolve_account_ref(self, *, target: str) -> str | None: ...

    async def drive_roots_for_node(
        self, *, mesh_node_id: str, owner_user_id: str | None = None,
    ) -> list[str]: ...

    async def revoke_root(
        self, *, user_id: str, link_id: str, root_ref: str, now: datetime,
    ) -> bool: ...

    async def link_for(
        self, *, user_id: str, mesh_node_id: str,
    ) -> dict[str, Any] | None: ...


    async def is_managed_link(self, *, user_id: str, mesh_node_id: str) -> bool: ...

    async def managed_state(self, *, link_id: str) -> dict[str, Any]: ...

    async def set_managed(
        self, *, link_id: str, by_user_id: str, managed: bool, now: datetime,
    ) -> dict[str, Any]: ...


def _user_id(value: Any) -> str:
    if not isinstance(value, str) or _USER_ID_RE.fullmatch(value) is None:
        raise PcPairingError("user id invalid")
    return value


def _mesh_node_id(value: Any) -> str:
    """One PC identity the Mesh lane can actually address.

    Both canonical forms are accepted, by the Owner's decision on #5573: the
    composed ``node/<domain>/<node>`` and the ``id@domain`` spelling that
    ``meshctrl listdevices`` reports and the deployment ownership map already
    uses as ``node_ref``. Rejecting the second would have made a link name a
    device the file lane can reach but this table could not hold.
    """
    if not is_pc_device_id(value):
        raise PcPairingError("mesh node identity invalid")
    return value


def _stamp(value: Any) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PcPairingError("trusted aware receipt time required")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PcPairingError("link label invalid")
    cleaned = "".join(ch for ch in value.strip() if ch >= " " and ch != "\x7f")
    if not cleaned:
        return None
    if len(cleaned) > MAX_LINK_LABEL_CHARS:
        raise PcPairingError("link label too long")
    return cleaned


def normalize_root_path(value: Any) -> str | None:
    """The approved folder, in the one spelling the Mesh lane addresses.

    Same judgement `_pc_files_approved_root` makes from the other side: a real
    folder at least one component below a drive, or a whole drive - never a
    relative or traversing path. Returns ``None`` for anything else.

    A drive root (``C:``) is a valid grant by the Owner's decision on #5573: a
    connected PC works over its local drives by default, and narrowing to
    folders is a later feature. The other guards - no traversal, no wildcards,
    no control characters, bounded length, absolute shape - stay exactly as they
    were, because they are what makes the grant addressable at all.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 0x7F for ch in text) or "*" in text or "?" in text:
        return None
    normalized = text.replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.rstrip("/")
    if _DRIVE_ROOT_RE.fullmatch(normalized) is not None:
        return normalized.upper()
    segments = [segment for segment in normalized.split("/") if segment]
    if len(segments) < 2:
        return None
    if any(segment in {".", ".."} for segment in segments):
        return None
    if ":" in segments[-1]:
        return None
    if len(normalized) > MAX_ROOT_PATH_CHARS:
        return None
    return normalized


def root_ref_for(path: str) -> str:
    return "pcroot_" + hashlib.sha256(path.lower().encode("utf-8")).hexdigest()[:16]


def normalize_root_label(value: Any) -> str | None:
    """The one name a link uses for one approved folder.

    The model is shown this and never the real path (the CTO's (A) shape), so it
    has to survive being typed back inside a requested path: no separator, no
    control character, no leading or trailing space, bounded.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_ROOT_LABEL_CHARS:
        return None
    if any(ord(ch) < 32 or ord(ch) == 0x7F for ch in cleaned):
        return None
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        return None
    return cleaned


def default_root_label(path: str) -> str:
    """The folder's own name, used when the owner did not name the grant."""
    return path.rsplit("/", 1)[-1]


def drive_root(value: Any) -> str | None:
    """One whole drive, the way the PC names it (`C:\\`, `d:`, `D:/`) → `C:`.

    This is the shape a claiming PC is allowed to report about itself. Nothing
    deeper is accepted here on purpose: a PC may declare which drives it has, it
    may not use that call to name folders it has not been granted.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    while text.endswith("/"):
        text = text[:-1]
    return text.upper() if _DRIVE_ROOT_RE.fullmatch(text) else None


def _root_row(path: str, moment: str) -> dict[str, Any]:
    return {
        "root_ref": root_ref_for(path),
        "label": default_root_label(path),
        "path": path,
        "state": _STATE_ACTIVE,
        "approved_at": moment,
        "revoked_at": None,
    }


def _merge_roots(
    roots: list[dict[str, Any]], paths: list[str], moment: str,
) -> list[dict[str, Any]]:
    """Grant `paths` on top of `roots`, keeping what is already granted.

    One drive letter and one deep folder are the same shape to the store from
    here on: both are absolute grants, normalized or refused.
    """
    merged = list(roots)
    for path in paths:
        normalized = normalize_root_path(path)
        if normalized is None:
            raise PcPairingError("root path invalid")
        if any(existing["path"] == normalized for existing in merged):
            continue
        merged.append(_root_row(normalized, moment))
    return merged


def _roots(value: Any) -> list[dict[str, Any]]:
    """Parse the server-written roots array, refusing anything malformed.

    A malformed column is a hard error rather than an empty list: an approved
    folder must never silently disappear from the authority that guards a read.
    There is no count rule here - how many folders or drives one link carries is
    bounded only by the storage the applied schema already enforces.
    """
    if isinstance(value, str) and len(value) > MAX_ROOTS_JSON_CHARS:
        raise PcPairingError("link roots unreadable")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            raise PcPairingError("link roots unreadable") from None
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise PcPairingError("link roots unreadable")
    roots: list[dict[str, Any]] = []
    for row in parsed:
        if not isinstance(row, dict) or set(row) != {
            "root_ref", "label", "path", "state", "approved_at", "revoked_at",
        }:
            raise PcPairingError("link roots unreadable")
        path = normalize_root_path(row.get("path"))
        if path is None or row.get("root_ref") != root_ref_for(path):
            raise PcPairingError("link roots unreadable")
        label = normalize_root_label(row.get("label"))
        if label is None:
            raise PcPairingError("link roots unreadable")
        if row.get("state") not in (_STATE_ACTIVE, _STATE_REVOKED):
            raise PcPairingError("link roots unreadable")
        approved_at = row.get("approved_at")
        if not isinstance(approved_at, str) or not approved_at:
            raise PcPairingError("link roots unreadable")
        revoked_at = row.get("revoked_at")
        if revoked_at is not None and not isinstance(revoked_at, str):
            raise PcPairingError("link roots unreadable")
        roots.append({
            "root_ref": row["root_ref"],
            "label": label,
            "path": path,
            "state": row["state"],
            "approved_at": approved_at,
            "revoked_at": revoked_at,
        })
    return roots


def _claim_retention_floor(updated_at: str) -> str:
    """One day back, in the store's own stamp shape.

    The window table only needs the current and the previous ten minutes; a day
    is far more than that, so an unreadable value simply skips cleanup.
    """
    try:
        moment = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return updated_at
    return _stamp(moment - timedelta(days=1))


def derive_install_tag(code: str) -> str:
    """The tag an installer stamps into the MeshCentral agent name.

    Derived from the code, so the PC needs nothing beyond the code (R2, R3) and
    the server can recognise the node from the hash it already holds.
    """
    digest = hashlib.sha256(("padiem-pc-pair-tag|" + code).encode("utf-8")).hexdigest()
    return PAIRING_TAG_PREFIX + digest[:PAIRING_TAG_CHARS]


def tag_from_agent_name(value: Any) -> str | None:
    """The one pairing tag inside an observed agent name, or ``None``.

    Exactly one match is required: a name carrying two tags, or a lookalike that
    is not the derived shape, is not a claim and is not guessed at.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return None
    found = [match.group(0).lower() for match in _AGENT_TAG_RE.finditer(value)]
    if len(found) != 1:
        return None
    return found[0]


def install_token_from_agent_name(value: Any) -> str | None:
    """The one install token inside an observed agent name, or ``None``.

    The install file writes `<tag> <token> [drives] <machine>`, so the token and
    the tag arrive on the same channel. Exactly one match is required, the same
    rule the tag follows: a name carrying two tokens is not a claim and is not
    guessed at. A name the double-click program built carries no token, and
    answers ``None`` - that lane is held to the token's binding instead.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return None
    found = [match.group(0).lower() for match in _AGENT_TOKEN_RE.finditer(value)]
    if len(found) != 1:
        return None
    return found[0]


#: One Windows computer name, as the install lane reports it: a single word of
#: letters, digits, dots, underscores or hyphens. An owner's alias ("집 PC",
#: "my office") is not a machine name and never decides sameness.
_MACHINE_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")


def machine_key(value: Any) -> str | None:
    """The sameness key of one Windows computer name, or ``None``.

    Two install lanes produced the two names of one physical computer in
    #6694 (B): the whole DNS name ("PADIEM-COMMAND-CENTER") and the
    15-character NetBIOS form Windows keeps for itself
    ("PADIEM-COMMAND-"). Windows itself folds every computer name into its
    first 15 uppercased characters - the NetBIOS name space - so that same
    fold is what "is this the same machine" compares. A shorter name than
    15 characters compares as itself, which is exactly Windows' own rule.
    Anything that is not shaped like one computer name answers ``None`` and
    decides nothing.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _MACHINE_NAME_RE.fullmatch(text) is None:
        return None
    return text.upper()[:15]


def label_machine_key(value: Any) -> str | None:
    """The sameness key of the machine-name part of a stored link label.

    A label carries up to two names joined by `_NAME_SEPARATOR`; only the
    first (the machine's own) can say which physical computer the row was
    about. An alias-only or absent label answers ``None``.
    """
    if not isinstance(value, str):
        return None
    return machine_key(value.split(_NAME_SEPARATOR)[0])


def drives_from_agent_name(value: Any) -> list[str]:
    """The drive letters one installing PC named beside its tag, or nothing.

    A self-installing PC has no session and no code to post with, so the channel
    that carries its own drive list is the same one that carries the tag: the
    agent name the server observes. The install file writes `[C D]` after the
    tag, and this reads it back as whole-drive grants.

    Deliberately narrow, because the value is free text a machine wrote about
    itself: one bracketed group of single letters, each turned into the same
    `C:` shape a claiming PC posts through `drive_root`. Anything else - no
    brackets, a second group, a folder hiding inside a letter - yields no drives,
    which leaves the link with nothing granted rather than guessing a scope.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return []
    found = _NAME_DRIVES_RE.findall(value)
    if len(found) != 1:
        return []
    letters = found[0].split()
    if not 1 <= len(letters) <= 26:
        return []
    drives: list[str] = []
    for letter in letters:
        single = drive_root(letter + ":")
        if single is None:
            return []
        if single not in drives:
            drives.append(single)
    return drives


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _active(roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the folders that are granted right now.

    Both the browser projection and the authority read drop revoked rows. The
    history stays in the column for re-approval judgement, but a consumer that
    forgets to filter must not be able to treat a withdrawn folder as granted.
    """
    return [root for root in roots if root["state"] == _STATE_ACTIVE]


def _public_link(row: dict[str, Any]) -> dict[str, Any]:
    paused = bool(row.get("paused_at"))
    state = "paused" if paused else row["state"]
    # #6694 (C): a superseded row keeps state='revoked' in the table (the
    # column's CHECK vocabulary is unchanged) and says `replaced` here - the
    # owner's list keeps the record, marked as the computer's older link.
    if row.get("superseded_at") and state == _STATE_REVOKED:
        state = _STATE_REPLACED
    return {
        "link_id": row["link_id"],
        "mesh_node_id": row["mesh_node_id"],
        "label": row.get("label"),
        # A paused link still exists and keeps its folder grants, so the listing
        # names the state the owner is actually looking at. The execution reads
        # (`links_for_owner`, `device_scope`, `link_for`) drop the row instead.
        "state": state,
        "superseded_at": row.get("superseded_at") or None,
        "paused": paused,
        "paused_at": row.get("paused_at"),
        "roots": [
            {
                "root_ref": root["root_ref"],
                "label": root["label"],
                "path": root["path"],
                "state": root["state"],
                "approved_at": root["approved_at"],
            }
            for root in _active(row["roots"])
        ],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }



def mesh_presence_account_cleanup_statements(db: Any, user_id: str) -> list[Any]:
    """Build the shared-owner cleanup statements used by both storage paths."""
    refs_json = (
        "CASE WHEN json_valid(account_refs_json) "
        "THEN account_refs_json ELSE '[]' END"
    )
    return [
        db.prepare(
            "UPDATE mesh_device_presence SET account_refs_json = ("
            " SELECT json_group_array(ref.value) FROM json_each("
            f"{refs_json}) AS ref "
            " WHERE ref.type <> 'text' OR ref.value <> ?"
            ") "
            f"WHERE json_type({refs_json}) = 'array' "
            "AND EXISTS (SELECT 1 FROM json_each("
            f"{refs_json}) AS target "
            "WHERE target.type = 'text' AND target.value = ?) "
            "AND EXISTS (SELECT 1 FROM json_each("
            f"{refs_json}) AS other "
            "WHERE other.type = 'text' AND other.value <> ?)"
        ).bind(user_id, user_id, user_id),
        db.prepare(
            "DELETE FROM mesh_device_presence "
            f"WHERE json_type({refs_json}) = 'array' "
            "AND EXISTS (SELECT 1 FROM json_each("
            f"{refs_json}) AS target "
            "WHERE target.type = 'text' AND target.value = ?) "
            "AND NOT EXISTS (SELECT 1 FROM json_each("
            f"{refs_json}) AS other "
            "WHERE other.type = 'text' AND other.value <> ?)"
        ).bind(user_id, user_id),
    ]


def oracle_mesh_dispatch_identity_cleanup_statements(db: Any, user_id: str) -> list[Any]:
    """Keep the replay-prevention dispatch row, drop the account out of it.

    Migration 047 says an expired or consumed dispatch is never deleted: its
    presence is what refuses a replay. Keeping the row must not keep the person
    in it, so each row is first stopped and then overwritten in one
    irreversible pass.

    * ``user_id``, ``account_ref``, ``workspace_ref``, ``device_id``,
      ``binding_ref``, ``node_ref`` and ``root_ref`` become one random
      ``deleted:<hex>`` token minted for this deletion. It is not a hash of the
      old id, so it cannot be recomputed, and 128 random bits cannot collide
      with another account.
    * ``path_relative`` and ``file_path`` (NOT NULL) become the fixed
      ``deleted`` sentinel, and ``evidence_ref`` and the command body
      ``command_text`` become NULL, so no PC path or typed command survives.

    The replay keys stay byte-for-byte: ``dispatch_id``, ``run_id``,
    ``tool_request_ref``, ``tool_call_ref``, ``request_fingerprint``, the
    nonce, the state and the result digest. The unique indexes of 047 and 063
    still refuse the same run or the same tool call, and a late executor
    submission is still matched by its nonce.

    A row still ``pending`` is handled like the owner's own cancel (#5895): one
    no executor has ever claimed is marked ``failed`` so the poll can never hand
    it out for an account that no longer exists, and one already claimed keeps
    ``pending`` and is told ``termination='cancelled'`` so its result can still
    land through the nonce gate instead of being resent until quarantined.
    """
    token = "deleted:" + secrets.token_hex(16)
    return [
        db.prepare(
            "UPDATE oracle_mesh_dispatch SET state=?, termination=? "
            "WHERE user_id=? AND state=? AND nonce_sha256 IS NULL"
        ).bind("failed", "cancelled", user_id, "pending"),
        db.prepare(
            "UPDATE oracle_mesh_dispatch SET termination=? "
            "WHERE user_id=? AND state=? AND nonce_sha256 IS NOT NULL"
        ).bind("cancelled", user_id, "pending"),
        db.prepare(
            "UPDATE oracle_mesh_dispatch SET user_id=?, account_ref=?, "
            "workspace_ref=?, device_id=?, binding_ref=?, node_ref=?, root_ref=?, "
            "path_relative=?, file_path=?, evidence_ref=NULL, command_text=NULL "
            "WHERE user_id=?"
        ).bind(
            token, token, token, token, token, token, token,
            "deleted", "deleted", user_id,
        ),
    ]


class D1PcPairingStore:
    """Cloudflare D1 adapter over `pc_pairing_codes` + `pc_device_links` (072)."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def is_managed_link(self, *, user_id: str, mesh_node_id: str) -> bool:
        """Read the managed(contract) mark for this pair, if it is live."""
        owner = _user_id(user_id)
        node = _mesh_node_id(mesh_node_id)
        try:
            row = await self._first(
                "SELECT managed_at FROM pc_device_links WHERE user_id=? AND mesh_node_id=? "
                "AND state='active' AND paused_at IS NULL",
                owner, node,
            )
        except Exception:
            # Migration 103 is not applied (the queue schema stops at 102):
            # no column means "not managed", so SYSTEM stays refused.
            return False
        return isinstance(row, dict) and bool(row.get("managed_at"))

    async def managed_state(self, *, link_id: str) -> dict[str, Any]:
        """Admin read: whether one live link carries the managed(contract) mark."""
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        try:
            row = await self._first(
                "SELECT user_id, state, paused_at, managed_at FROM pc_device_links WHERE link_id=?",
                link_id,
            )
        except Exception as exc:
            # Migration 103 is not applied (the queue schema stops at 102):
            # the mark cannot be read yet, same 503 shape as writing it.
            text = str(exc).lower()
            if "no such column" not in text and "has no column named" not in text:
                raise
            raise PcPairingError("managed column missing") from exc
        if not isinstance(row, dict) or not row.get("user_id"):
            raise PcPairingError("link not found")
        if row.get("state") != _STATE_ACTIVE or row.get("paused_at"):
            raise PcPairingError("link not active")
        return {"link_id": link_id, "managed": bool(row.get("managed_at"))}

    async def set_managed(
        self, *, link_id: str, by_user_id: str, managed: bool, now: datetime,
    ) -> dict[str, Any]:
        """Mark or unmark one link; the actor is the verified platform admin."""
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        actor = _user_id(by_user_id)
        if not isinstance(managed, bool):
            raise PcPairingError("managed flag invalid")
        row = await self._first(
            "SELECT user_id, state, paused_at FROM pc_device_links WHERE link_id=?",
            link_id,
        )
        if not isinstance(row, dict) or not row.get("user_id"):
            raise PcPairingError("link not found")
        if row.get("state") != _STATE_ACTIVE or row.get("paused_at"):
            raise PcPairingError("link not active")
        moment = _stamp(now)
        try:
            if managed:
                await self._run(
                    "UPDATE pc_device_links SET managed_at=?, managed_by=?, updated_at=? "
                    "WHERE link_id=? AND state='active'",
                    moment, actor, moment, link_id,
                )
            else:
                await self._run(
                    "UPDATE pc_device_links SET managed_at=NULL, managed_by=NULL, updated_at=? "
                    "WHERE link_id=? AND state='active'",
                    moment, link_id,
                )
        except Exception as exc:
            text = str(exc).lower()
            if "no such column" not in text and "has no column named" not in text:
                raise
            raise PcPairingError("managed column missing") from exc
        stored = await self._read_link(row["user_id"], link_id)
        if stored is None:
            raise PcPairingError("link not stored")
        return {
            **_public_link(stored),
            "managed": managed,
            "managed_at": moment if managed else None,
        }

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def delete_account_pc_data(self, *, user_id: str) -> bool:
        """Remove one account's queue-owned PC rows in a single idempotent batch.

        mesh_device_drives has no user key and can describe a shared PC, so it
        is intentionally left untouched. oracle_mesh_dispatch keeps its
        replay-prevention rows, but every column that names this account or
        carries its PC work is overwritten in the same batch.
        """
        owner = _user_id(user_id)
        statements = [
            self.db.prepare("DELETE FROM pc_install_tokens WHERE user_id = ?").bind(owner),
            self.db.prepare("DELETE FROM pc_device_links WHERE user_id = ?").bind(owner),
            self.db.prepare("DELETE FROM pc_pairing_codes WHERE user_id = ?").bind(owner),
        ]
        statements.extend(
            oracle_mesh_dispatch_identity_cleanup_statements(self.db, owner)
        )
        statements.extend(mesh_presence_account_cleanup_statements(self.db, owner))
        await self.db.batch(statements)
        return True

    # -- pairing codes ------------------------------------------------------

    async def issue_code(self, *, user_id: str, issued_at: datetime) -> dict[str, Any]:
        owner = _user_id(user_id)
        issued = _stamp(issued_at)
        expires = _stamp(issued_at + timedelta(seconds=PAIRING_CODE_TTL_SECONDS))
        # `secrets` over an unambiguous alphabet: the value is a possession
        # proof a human may have to type, and a code is worthless if it can be
        # misread into another account's pending pairing.
        code = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(PAIRING_CODE_CHARS))
        code_id = "pcpair_" + secrets.token_hex(16)
        # #6695 PR-4: the token is minted with the code and lives exactly as long,
        # so there is one possession proof to cancel, not two clocks to reconcile.
        install_token = INSTALL_TOKEN_PREFIX + secrets.token_hex(INSTALL_TOKEN_HEX_CHARS // 2)
        token_id = "pctok_" + secrets.token_hex(16)
        await self._run(
            "INSERT INTO pc_pairing_codes "
            "(code_id, code_sha256, tag_sha256, user_id, state, mesh_node_id, "
            " issued_at, expires_at, claimed_at) "
            "VALUES (?, ?, ?, ?, 'pending', NULL, ?, ?, NULL)",
            code_id, _hash(code), _hash(derive_install_tag(code)), owner, issued, expires,
        )
        await self._run(
            "INSERT INTO pc_install_tokens "
            "(token_id, token_sha256, code_id, user_id, issued_at, expires_at, revoked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            token_id, _hash(install_token), code_id, owner, issued, expires,
        )
        stored = await self._first(
            "SELECT code_id, user_id, state, expires_at FROM pc_pairing_codes WHERE code_id=?",
            code_id,
        )
        if not stored or stored.get("user_id") != owner or stored.get("state") != "pending":
            raise PcPairingError("pairing code not stored")
        token_row = await self._first(
            "SELECT token_id, user_id FROM pc_install_tokens WHERE code_id=?", code_id,
        )
        if (
            not isinstance(token_row, dict)
            or token_row.get("token_id") != token_id
            or token_row.get("user_id") != owner
        ):
            raise PcPairingError("install token not stored")
        return {
            "code_id": code_id,
            "code": code,
            "install_tag": derive_install_tag(code),
            "install_token": install_token,
            "token_id": token_id,
            "issued_at": issued,
            "expires_at": expires,
        }

    async def peek_pairing_code(self, *, code: str, now: datetime) -> dict[str, Any]:
        """What a presented code entitles its holder to, without consuming it.

        The install wrapper needs the tag derived from the code it was handed, so
        it can stamp that tag into the agent name the server will later observe.
        Nothing here writes: a handoff that consumed the code would leave the PC
        installed and unpaired if the download then failed, and a code is a
        10-minute possession proof, not a one-shot download ticket.
        """
        if not isinstance(code, str) or len(code) > 64:
            raise PcPairingError("pairing code invalid")
        moment = _stamp(now)
        row = await self._first(
            "SELECT code_id, state, expires_at FROM pc_pairing_codes WHERE code_sha256=?",
            _hash(code),
        )
        if not isinstance(row, dict) or not row.get("code_id"):
            raise PcPairingError("pairing code unknown")
        if row.get("state") != "pending":
            raise PcPairingError("pairing code used")
        if str(row.get("expires_at") or "") <= moment:
            raise PcPairingError("pairing code expired")
        return {
            "code_id": row["code_id"],
            "install_tag": derive_install_tag(code),
            "expires_at": row["expires_at"],
        }

    async def claim_failure_counts(
        self, *, node_key: str, source_key: str, window_start: str,
    ) -> dict[str, int]:
        """The two counters a claim's ten-minute window has spent so far.

        #7563: the claim surface counts failures per node and per network. The
        keys are opaque hashes; neither a raw node id nor a request address is
        stored here. A missing row is zero, and an unreadable row is zero too -
        the route's own refusal is what protects the code, never this meter.
        """
        rows = await self._all(
            "SELECT key_type, failure_count FROM pc_pairing_claim_attempts "
            "WHERE window_start=? AND ((key_type='node' AND key_hash=?) "
            "OR (key_type='source' AND key_hash=?))",
            window_start, node_key, source_key,
        )
        counts = {"node": 0, "source": 0}
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = row.get("key_type")
            if kind not in counts:
                continue
            try:
                counts[kind] = int(row.get("failure_count") or 0)
            except (TypeError, ValueError):
                counts[kind] = 0
        return counts

    async def record_claim_failure(
        self, *, node_key: str, source_key: str, window_start: str, updated_at: str,
    ) -> None:
        """Count one failed claim against both keys, in the database.

        Both upserts are unconditional and separate: a success never resets the
        other key's failures, and a saturated node counter never stops the
        network counter from moving (or the other way round).
        """
        for kind, key in (("node", node_key), ("source", source_key)):
            await self._run(
                "INSERT INTO pc_pairing_claim_attempts "
                "(key_type, key_hash, window_start, failure_count, updated_at) "
                "VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(key_type, key_hash, window_start) DO UPDATE SET "
                "failure_count=pc_pairing_claim_attempts.failure_count + 1, "
                "updated_at=excluded.updated_at",
                kind, key, window_start, updated_at,
            )
        await self._run(
            "DELETE FROM pc_pairing_claim_attempts WHERE window_start < ?",
            _claim_retention_floor(updated_at),
        )

    async def _owned_code(self, owner: str, code_id: Any) -> dict[str, Any]:
        if not isinstance(code_id, str) or _CODE_ID_RE.fullmatch(code_id) is None:
            raise PcPairingError("pairing code id invalid")
        code = await self._first(
            "SELECT code_id, user_id, state FROM pc_pairing_codes WHERE code_id=?",
            code_id,
        )
        if not isinstance(code, dict) or not code.get("code_id"):
            raise PcPairingError("pairing code unknown")
        if code.get("user_id") != owner:
            raise PcPairingError("pairing code not yours")
        return code

    async def revoke_install_token(
        self, *, user_id: str, code_id: str, now: datetime,
    ) -> dict[str, Any]:
        """Cancel one pending install: the token and its code stop pairing.

        Cancelling is the owner's answer to a file they handed out and no longer
        want used. The token is stamped (never deleted, so a refused claim can
        say why) and a still-pending code is cancelled with it - leaving the
        code alive would let the same install pair through the typed-code path
        with the token's half already withdrawn.
        """
        owner = _user_id(user_id)
        code = await self._owned_code(owner, code_id)
        moment = _stamp(now)
        await self._run(
            "UPDATE pc_install_tokens SET revoked_at=? "
            "WHERE code_id=? AND revoked_at IS NULL",
            moment, code["code_id"],
        )
        if code.get("state") == "pending":
            await self._run(
                "UPDATE pc_pairing_codes SET state='cancelled' "
                "WHERE code_id=? AND state='pending'",
                code["code_id"],
            )
        token = await self._first(
            "SELECT revoked_at FROM pc_install_tokens WHERE code_id=?", code["code_id"],
        )
        stored = await self._first(
            "SELECT state FROM pc_pairing_codes WHERE code_id=?", code["code_id"],
        )
        return {
            "code_id": code["code_id"],
            "revoked_at": (
                token.get("revoked_at") if isinstance(token, dict) else None
            ),
            "code_state": (
                stored.get("state") if isinstance(stored, dict) else code.get("state")
            ),
        }

    async def reissue_install_token(
        self, *, user_id: str, code_id: str, now: datetime,
    ) -> dict[str, Any]:
        """Replace a cancelled or expired install with a fresh code and token.

        Reissue is revoke plus a new mint, in that order: the old pair is
        retired first, so a failure between the two steps leaves nothing usable
        behind rather than two live installs. A code that already built a link
        is not reissued - re-pairing that PC is a new install, not a repair of
        the old one.
        """
        owner = _user_id(user_id)
        code = await self._owned_code(owner, code_id)
        if code.get("state") == "claimed":
            raise PcPairingError("pairing code used")
        await self.revoke_install_token(user_id=owner, code_id=code["code_id"], now=now)
        return await self.issue_code(user_id=owner, issued_at=now)

    async def list_codes(self, *, user_id: str, now: datetime) -> list[dict[str, Any]]:
        owner = _user_id(user_id)
        moment = _stamp(now)
        rows = await self._all(
            "SELECT c.code_id, c.state, c.mesh_node_id, c.issued_at, c.expires_at, "
            "c.claimed_at, t.expires_at AS token_expires_at, "
            "t.revoked_at AS token_revoked_at "
            "FROM pc_pairing_codes c LEFT JOIN pc_install_tokens t ON t.code_id=c.code_id "
            "WHERE c.user_id=? ORDER BY c.issued_at DESC LIMIT 20",
            owner,
        )
        listed: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("code_id"):
                continue
            # #6695 PR-4: the owner's list can say whether this code's install
            # token still stands, so a cancelled install is visible without
            # reading back the token itself (which cannot be read back at all).
            token_state: str | None = None
            if row.get("token_expires_at"):
                if row.get("token_revoked_at"):
                    token_state = "revoked"
                elif str(row["token_expires_at"]) <= moment:
                    token_state = "expired"
                else:
                    token_state = "active"
            listed.append({
                "code_id": row["code_id"],
                "state": (
                    "expired"
                    if row["state"] == "pending" and str(row["expires_at"]) <= moment
                    else row["state"]
                ),
                "install_token_state": token_state,
                "issued_at": row["issued_at"],
                "expires_at": row["expires_at"],
            })
        return listed

    async def _install_token_gate(
        self, *, code_id: str, owner: str, presented: Any, moment: str,
    ) -> None:
        """Refuse a *new* pairing whose install token no longer stands.

        Two answers, one rule. A presented token must be the one minted for this
        code and this account - a valid token from another account is exactly
        the case #6695 PR-4 exists to refuse. A claim that presents nothing is
        held to the binding instead: if the code was minted with a token and
        that token has been revoked or has expired, the claim is refused, and a
        code minted before this table existed has no binding and is claimed the
        way it always was.
        """
        if presented is not None:
            token = presented if isinstance(presented, str) else ""
            if _INSTALL_TOKEN_RE.fullmatch(token) is None:
                raise PcPairingError("install token invalid")
            row = await self._first(
                "SELECT token_sha256, code_id, user_id, expires_at, revoked_at "
                "FROM pc_install_tokens WHERE token_sha256=?",
                _hash(token),
            )
            if not isinstance(row, dict) or not row.get("token_sha256"):
                raise PcPairingError("install token invalid")
            if row.get("code_id") != code_id or row.get("user_id") != owner:
                raise PcPairingError("install token invalid")
            if row.get("revoked_at"):
                raise PcPairingError("install token revoked")
            if str(row.get("expires_at") or "") <= moment:
                raise PcPairingError("install token expired")
            return
        row = await self._first(
            "SELECT expires_at, revoked_at FROM pc_install_tokens WHERE code_id=?",
            code_id,
        )
        if not isinstance(row, dict) or not row.get("expires_at"):
            return
        if row.get("revoked_at"):
            raise PcPairingError("install token revoked")
        if str(row.get("expires_at") or "") <= moment:
            raise PcPairingError("install token expired")

    async def _link_exists(self, owner: str, node: str) -> bool:
        row = await self._first(
            "SELECT link_id FROM pc_device_links WHERE user_id=? AND mesh_node_id=?",
            owner, node,
        )
        return isinstance(row, dict) and bool(row.get("link_id"))

    async def redeem_code(
        self, *, code: str, mesh_node_id: str, label: str | None, now: datetime,
        verified: bool = False, drives: list[str] | None = None,
        install_token: str | None = None,
    ) -> dict[str, Any]:
        """Consume one code and create or refresh the (user, node) link.

        The consumption is the guard: an expired or already-used code never
        reaches the link table. `verified` is what PR-2 sets from the executor's
        own MeshCentral observation; without it the link exists but is not
        usable, because nothing has yet proved the node is real.

        `drives` is what the installing PC reported as its own fixed local
        drives. The Owner's default scope is the whole drive, so a fresh link
        starts granted instead of starting empty and waiting for a hand. An
        existing link is not widened here: a re-claim must not resurrect a
        folder the owner has since withdrawn.
        """
        if not isinstance(code, str) or len(code) > 64:
            raise PcPairingError("pairing code invalid")
        node = _mesh_node_id(mesh_node_id)
        moment = _stamp(now)
        row = await self._first(
            "SELECT code_id, user_id, state, expires_at FROM pc_pairing_codes "
            "WHERE code_sha256=?",
            _hash(code),
        )
        if not isinstance(row, dict) or not row.get("code_id"):
            raise PcPairingError("pairing code unknown")
        owner = _user_id(row.get("user_id"))
        # A `cancelled` row still reaches the token gate below: the owner who
        # cancelled an install deserves to hear that the install was cancelled,
        # and a presented token from another account should never be called
        # "already used" on its way to being refused.
        if row.get("state") not in ("pending", "cancelled"):
            raise PcPairingError("pairing code used")
        if str(row.get("expires_at") or "") <= moment:
            await self._run(
                "UPDATE pc_pairing_codes SET state='cancelled' "
                "WHERE code_id=? AND state='pending'",
                row["code_id"],
            )
            raise PcPairingError("pairing code expired")
        # #6695 PR-4: a link that already exists is untouched by this rule - a
        # PC that paired before tokens existed keeps pairing the way it did.
        if not await self._link_exists(owner, node):
            await self._install_token_gate(
                code_id=row["code_id"], owner=owner,
                presented=install_token, moment=moment,
            )
        if row.get("state") != "pending":
            raise PcPairingError("pairing code used")
        # Single use, decided by the database: two installers racing on one code
        # must not both build a link, so the loser of the UPDATE sees a non-
        # pending row and is refused rather than guessing.
        await self._run(
            "UPDATE pc_pairing_codes SET state='claimed', mesh_node_id=?, claimed_at=? "
            "WHERE code_id=? AND state='pending'",
            node, moment, row["code_id"],
        )
        consumed = await self._first(
            "SELECT state, mesh_node_id FROM pc_pairing_codes WHERE code_id=?", row["code_id"],
        )
        if (
            not isinstance(consumed, dict)
            or consumed.get("state") != "claimed"
            or consumed.get("mesh_node_id") != node
        ):
            raise PcPairingError("pairing code used")
        link = await self._claim_link(
            owner=owner, node=node, label=label, code_id=row["code_id"],
            moment=moment, verified=verified,
            # The claim's label is the PC's own name for itself when it has
            # one; `machine_key` refuses anything that is not shaped like one
            # Windows computer name, so an alias never decides sameness.
            machine=label if isinstance(label, str) else None,
        )
        return await self._seed_drives(owner=owner, link=link, drives=drives, moment=moment)

    async def _seed_drives(
        self, *, owner: str, link: dict[str, Any], drives: list[str] | None, moment: str,
    ) -> dict[str, Any]:
        """Put the drives a PC named for itself onto the link it just claimed.

        The Owner's default scope is a whole drive, so a fresh link starts
        granted instead of starting empty and waiting for a hand. An existing
        grant is never widened here: a re-claim must not resurrect a drive the
        owner has since withdrawn.
        """
        if not drives:
            return link
        granted = [entry["path"] for entry in link["roots"]]
        missing = [path for path in drives if path not in granted]
        if missing:
            await self._write_roots(
                owner, link["link_id"],
                _merge_roots(link["roots"], missing, moment), moment,
            )
            stored = await self._read_link(owner, link["link_id"])
            if stored is not None:
                link = stored
        return link

    async def _claim_link(
        self, *, owner: str, node: str, label: Any, code_id: str, moment: str,
        verified: bool, machine: Any = None,
    ) -> dict[str, Any]:
        """Create or refresh the (owner, node) link for one consumed code.

        Shared by the browser-side claim and the server-side tag completion, so
        the two cannot drift into two different link shapes.

        `machine` is the Windows computer name the claiming PC reported about
        itself, when the channel carried one. It never changes identity - the
        row stays keyed by `(user_id, mesh_node_id)` - it only settles which of
        the owner's older rows for the SAME physical computer this new link
        replaces (#6694 C).
        """
        existing = await self._first(
            "SELECT * FROM pc_device_links WHERE user_id=? AND mesh_node_id=?", owner, node,
        )
        state = _STATE_ACTIVE if verified is True else _STATE_PENDING_VERIFICATION
        promoted = False
        if isinstance(existing, dict) and existing.get("link_id"):
            if existing.get("state") == _STATE_REVOKED:
                # A re-pair after a revoke is a fresh grant: roots do not come
                # back, because the owner revoked them with the link (R5). The
                # supersede stamps clear with the rest: this row is live again.
                await self._run(
                    "UPDATE pc_device_links SET state=?, label=?, roots_json='[]', "
                    "pairing_code_id=?, updated_at=?, revoked_at=NULL, "
                    "superseded_at=NULL, superseded_by=NULL WHERE link_id=?",
                    state, _label(label), code_id, moment, existing["link_id"],
                )
            elif existing.get("state") == _STATE_PENDING_VERIFICATION and verified is True:
                # A second code that only confirms the same pair promotes it; a
                # claim that names no label keeps the label the owner chose.
                # #7563: the promotion is one conditional UPDATE, so two observers
                # racing on the same pending link produce exactly one promotion.
                promoted_rows = await self._all(
                    "UPDATE pc_device_links SET state=?, label=COALESCE(?, label), "
                    "updated_at=?, superseded_at=NULL, superseded_by=NULL "
                    "WHERE link_id=? AND state=? RETURNING link_id",
                    _STATE_ACTIVE, _label(label), moment, existing["link_id"],
                    _STATE_PENDING_VERIFICATION,
                )
                promoted = bool(promoted_rows)
            stored = await self._read_link(owner, existing["link_id"])
        else:
            link_id = "pclink_" + secrets.token_hex(16)
            await self._run(
                "INSERT INTO pc_device_links "
                "(link_id, user_id, mesh_node_id, label, state, roots_json, "
                " pairing_code_id, created_at, updated_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, NULL)",
                link_id, owner, node, _label(label), state, code_id, moment, moment,
            )
            stored = await self._read_link(owner, link_id)
        if stored is None:
            raise PcPairingError("pairing link not stored")
        superseded_mesh_node_ids: list[str] = []
        if machine is not None and (not isinstance(existing, dict) or not existing.get("link_id")):
            # A brand-new link for a computer the owner already had rows for:
            # the older rows become `replaced`, never deleted.
            superseded_mesh_node_ids = await self._supersede_same_machine(
                owner=owner, keep=stored, machine=machine, moment=moment,
            )
            stored = await self._read_link(owner, stored["link_id"]) or stored
        # Internal handoff to Chat's separate preference store. API routes
        # project a closed response and never expose these prior node ids.
        stored["_superseded_mesh_node_ids"] = superseded_mesh_node_ids
        stored["_promoted"] = promoted
        return stored

    async def _supersede_same_machine(
        self, *, owner: str, keep: dict[str, Any], machine: Any, moment: str,
    ) -> list[str]:
        """Mark the owner's older links for this same computer as replaced.

        The sameness criterion is the Windows computer name, folded the way
        Windows itself folds it (`machine_key`): a machine reinstalling its
        agent arrives under a new Mesh node id but the same name, and the old
        row is exactly the ghost the #6694 (A) report showed - "connected"
        with no agent behind it. Only rows that are still live for this owner
        are stamped; another account's link on the same machine is untouched
        (the table is many accounts to one PC by design), and a plain revoked
        row stays revoked without the stamp.
        """
        key = machine_key(machine)
        if key is None:
            return []
        rows = await self._all(
            "SELECT link_id, mesh_node_id, label FROM pc_device_links "
            "WHERE user_id=? AND state IN (?, ?) LIMIT 100",
            owner, _STATE_ACTIVE, _STATE_PENDING_VERIFICATION,
        )
        superseded: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("link_id"):
                continue
            if row["link_id"] == keep["link_id"] or row.get("mesh_node_id") == keep["mesh_node_id"]:
                continue
            if label_machine_key(row.get("label")) != key:
                continue
            await self._run(
                "UPDATE pc_device_links SET state=?, superseded_at=?, "
                "superseded_by=?, updated_at=? WHERE link_id=? AND state IN (?, ?)",
                _STATE_REVOKED, moment, keep["link_id"], moment, row["link_id"],
                _STATE_ACTIVE, _STATE_PENDING_VERIFICATION,
            )
            mesh_node_id = row.get("mesh_node_id")
            if isinstance(mesh_node_id, str) and mesh_node_id:
                superseded.append(mesh_node_id)
        return superseded

    async def _promote_pending_link(
        self, *, owner: str, node: str, code_id: str, agent_name: Any, moment: str,
    ) -> dict[str, Any] | None:
        """Activate the pending link one observation earned, at most once.

        #7563: the promotion is a single conditional UPDATE. Two presence beats
        that observe the same install at the same moment both reach this
        statement, and only the one that still sees `pending_verification`
        changes a row; the other returns ``None``. A link that is already active
        is not touched, so an established PC is never re-verified or demoted.
        """
        rows = await self._all(
            "UPDATE pc_device_links SET state=?, updated_at=?, "
            "superseded_at=NULL, superseded_by=NULL "
            "WHERE user_id=? AND mesh_node_id=? AND pairing_code_id=? AND state=? "
            "RETURNING link_id",
            _STATE_ACTIVE, moment, owner, node, code_id, _STATE_PENDING_VERIFICATION,
        )
        if not rows:
            return None
        first = rows[0]
        link_id = first.get("link_id") if isinstance(first, dict) else first
        if not isinstance(link_id, str) or not link_id:
            return None
        stored = await self._read_link(owner, link_id)
        if stored is None:
            return None
        machine = pc_name_from_agent_name(agent_name)
        if machine and not stored.get("label"):
            await self._run(
                "UPDATE pc_device_links SET label=?, updated_at=? "
                "WHERE user_id=? AND link_id=? "
                "AND (label IS NULL OR label='')",
                machine, moment, owner, link_id,
            )
            stored = await self._read_link(owner, link_id) or stored
        seeded = await self._seed_drives(
            owner=owner, link=stored,
            drives=drives_from_agent_name(agent_name), moment=moment,
        )
        if isinstance(seeded, dict):
            seeded["_promoted"] = True
        return seeded

    async def complete_claim_from_observation(
        self, *, agent_name: Any, mesh_node_id: Any, now: datetime,
    ) -> dict[str, Any] | None:
        """Finish a pairing from what the server side already sees on the Mesh.

        A beta PC cannot name its own composed node identity: that identity is
        what `meshctrl listdevices` reports on the executor host, not what the
        machine knows about itself. So the install wrapper stamps the derived
        tag into the agent's name, the existing presence beat carries that name
        here, and the tag — which only ever existed inside one unexpired
        one-time code — decides the owner. Nothing is asked of the PC beyond the
        code it was handed, and the drives it names beside its tag are the same
        list a claiming PC reports through `redeem_code` — a PC may say which
        drives it has, it may not name folders through this channel.

        Returns ``None`` when the name carries no pairing tag: ordinary devices
        keep reporting presence untouched. It also returns ``None`` when the
        tag is the one this very node already claimed: the install wrapper
        leaves the tag inside the agent name it stamped, so a paired PC repeats
        it on every presence beat, the code has already granted everything it
        had, and the repeat adds nothing. A name that does carry one is
        otherwise a claim attempt, and a failed attempt is refused rather than
        ignored, because silently dropping it would leave an owner staring at a
        card that never resolves. What is kept from the name is the single word
        the machine called itself, and only as this account's own label for the
        link; the tag - the proof - is never written down, and neither is a name
        the owner has already replaced with their own.
        """
        tag = tag_from_agent_name(agent_name)
        if tag is None:
            return None
        node = _mesh_node_id(mesh_node_id)
        moment = _stamp(now)
        row = await self._first(
            "SELECT code_id, user_id, state, expires_at, mesh_node_id FROM pc_pairing_codes "
            "WHERE tag_sha256=?",
            _hash(tag),
        )
        if not isinstance(row, dict) or not row.get("code_id"):
            raise PcPairingError("pairing tag unknown")
        owner = _user_id(row.get("user_id"))
        if row.get("state") not in ("pending", "cancelled"):
            # The tag is exactly as single-use as the code it came from. One
            # repeat is not a replay, though: the claim stamps the claiming
            # node into the code row and the install name keeps the tag, so
            # the very PC this link belongs to re-reports its own tag on every
            # presence beat. That repeat grants nothing and creates nothing,
            # so it ends quietly instead of refusing the owner's own fleet
            # thousands of times a day; a different node naming this spent
            # tag is still refused exactly as before.
            claimed = row.get("mesh_node_id")
            if not (isinstance(claimed, str) and claimed == node):
                raise PcPairingError("pairing code used")
            if str(row.get("expires_at") or "") <= moment:
                raise PcPairingError("pairing code expired")
            # #7563: the typed claim already consumed this code and left a
            # pending link behind. This is the observation that promotes it -
            # once, conditionally, and only for the account that issued it.
            return await self._promote_pending_link(
                owner=owner, node=node, code_id=row["code_id"],
                agent_name=agent_name, moment=moment,
            )
        if str(row.get("expires_at") or "") <= moment:
            await self._run(
                "UPDATE pc_pairing_codes SET state='cancelled' "
                "WHERE code_id=? AND state='pending'",
                row["code_id"],
            )
            raise PcPairingError("pairing code expired")
        # #6695 PR-4: the install file stamps its token into the same name the
        # tag rides in, so a token minted for another account is refused here
        # even though the tag alone would have matched. A name with no token is
        # held to the binding; an existing link is not re-checked at all.
        if not await self._link_exists(owner, node):
            await self._install_token_gate(
                code_id=row["code_id"], owner=owner,
                presented=install_token_from_agent_name(agent_name), moment=moment,
            )
        if row.get("state") != "pending":
            raise PcPairingError("pairing code used")
        await self._run(
            "UPDATE pc_pairing_codes SET state='claimed', mesh_node_id=?, claimed_at=? "
            "WHERE code_id=? AND state='pending'",
            node, moment, row["code_id"],
        )
        consumed = await self._first(
            "SELECT state, mesh_node_id FROM pc_pairing_codes WHERE code_id=?",
            row["code_id"],
        )
        if (
            not isinstance(consumed, dict)
            or consumed.get("state") != "claimed"
            or consumed.get("mesh_node_id") != node
        ):
            raise PcPairingError("pairing code used")
        link = await self._claim_link(
            owner=owner, node=node, label=None, code_id=row["code_id"],
            moment=moment, verified=True,
            # #6694 (B)/(C): the machine word in the observed agent name is
            # the PC's own Windows name - the value that decides which older
            # row of this same computer this fresh link replaces.
            machine=pc_name_from_agent_name(agent_name),
        )
        # A PC that named itself keeps that name; an owner who already renamed
        # it is never overwritten, and a name that was only decoration is no
        # name at all. Preserve the internal replacement handoff across the
        # refreshes below; it is not part of any public response.
        superseded_mesh_node_ids = link.get("_superseded_mesh_node_ids")
        machine = pc_name_from_agent_name(agent_name)
        if machine and not link.get("label"):
            await self._run(
                "UPDATE pc_device_links SET label=?, updated_at=? "
                "WHERE user_id=? AND link_id=? "
                "AND (label IS NULL OR label='')",
                machine, moment, owner, link["link_id"],
            )
            stored = await self._read_link(owner, link["link_id"])
            if stored is not None:
                link = stored
        seeded = await self._seed_drives(
            owner=owner, link=link,
            drives=drives_from_agent_name(agent_name),
            moment=moment,
        )
        if isinstance(seeded, dict):
            if isinstance(superseded_mesh_node_ids, list) and superseded_mesh_node_ids:
                seeded["_superseded_mesh_node_ids"] = superseded_mesh_node_ids
            if link.get("_promoted"):
                seeded["_promoted"] = True
        return seeded

    async def set_link_label(
        self, *, user_id: str, link_id: str, label: Any, now: datetime,
    ) -> dict[str, Any]:
        """Name one linked PC, in the owner's own words.

        A chat request picks a machine with a name ("the office PC's C drive"),
        so a name has to exist before the second PC arrives. It is presentation
        text the owner chooses, never an identity: the row's
        `(user_id, mesh_node_id)` stays the only thing dispatch and revocation
        decide from. Ownership is settled by the row exactly as pause settles
        it, so another account's link is refused without saying whether it
        exists.
        """
        owner = _user_id(user_id)
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        current = await self._first(
            "SELECT label FROM pc_device_links WHERE link_id=?", link_id,
        )
        named = canonical_label(
            current.get("label") if isinstance(current, dict) else None, label,
        )
        if named is None:
            raise PcPairingError("link label invalid")
        named = _label(named)
        if named is None:
            raise PcPairingError("link label invalid")
        moment = _stamp(now)
        row = await self._first(
            "SELECT user_id, state FROM pc_device_links WHERE link_id=?", link_id,
        )
        if not isinstance(row, dict) or not row.get("state"):
            raise PcPairingError("link not found")
        if row.get("user_id") != owner:
            raise PcPairingError("link not yours")
        if row.get("state") == _STATE_REVOKED:
            raise PcPairingError("link not active")
        await self._run(
            "UPDATE pc_device_links SET label=?, updated_at=? "
            "WHERE user_id=? AND link_id=? AND state!='revoked'",
            named, moment, owner, link_id,
        )
        stored = await self._read_link(owner, link_id)
        if stored is None or stored.get("label") != named:
            raise PcPairingError("pairing link not stored")
        return _public_link(stored)

    async def links_for_owner(self, *, user_id: str) -> list[dict[str, Any]]:
        """Every link this account owns that may take work right now.

        The dispatch lane reads this: an empty list is the answer to "this
        account has no PC connected", and more than one link is a choice the
        caller must narrow, never something to guess. A paused link is dropped
        here rather than filtered by each caller, because the Owner's pause has
        to hold even against a consumer that forgets to look at it.
        """
        owner = _user_id(user_id)
        rows = await self._all(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "created_at, updated_at, paused_at FROM pc_device_links WHERE user_id=? "
            "AND state='active' AND paused_at IS NULL ORDER BY created_at DESC LIMIT 100",
            owner,
        )
        links: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("link_id"):
                continue
            row["roots"] = _active(_roots(row.get("roots_json")))
            links.append(row)
        return links

    async def adopt_link(
        self, *, user_id: str, mesh_node_id: str, root_paths: list[str], now: datetime,
        label: str | None = None, drives: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create the link an administrator adopted, with the folders the map already pinned.

        Adoption is a claim the Owner makes for a device this deployment already
        knows about, so it ends in exactly the shape a PC's own claim produces:
        an active `(user, node)` link carrying that device's approved folders. It
        is not a display record - the file lane reads the same table - and it is
        idempotent, because an owner who clicks twice must not end up with two
        grants or a widened one.

        `drives` is what the caller knows of the PC's fixed local drives - the
        same default scope a claiming PC gets from its own report.
        """
        owner = _user_id(user_id)
        node = _mesh_node_id(mesh_node_id)
        existing = await self._link_row_for_node(owner, node)
        if existing is not None:
            # Adoption that already happened is a read. Nothing is written, so
            # the link keeps its timestamps and, more importantly, keeps the
            # folders the owner has since withdrawn - re-adopting must not be a
            # way to resurrect a revoked grant.
            return existing
        moment = _stamp(now)
        roots = _merge_roots([], list(root_paths) + list(drives or []), moment)
        link = await self._claim_link(
            owner=owner, node=node, label=label, code_id=None, moment=moment,
            verified=True,
        )
        # The folders travel with the adoption: an adopted PC with no approved
        # folder would be a link the owner cannot use, and re-adding them by hand
        # is exactly the manual step this surface replaces.
        await self._write_roots(owner, link["link_id"], roots, moment)
        stored = await self._read_link(owner, link["link_id"])
        if stored is None:
            raise PcPairingError("pairing link not stored")
        return stored

    async def resolve_account_ref(self, *, target: str) -> str | None:
        """The account a target address names, or ``None`` when nothing does.

        Adoption may name a customer by the id this deployment already uses or by
        the address they sign in with. Both are answered from the account table
        the same D1 binding holds, and an id is tried before an email so no rule
        about what an address "looks like" decides the outcome. The caller cannot
        name an account that does not exist: a link written against a made-up id
        would be a PC nobody can use.
        """
        value = target.strip() if isinstance(target, str) else ""
        if not value or len(value) > 320:
            raise PcPairingError("adopt target invalid")
        row = await self._first("SELECT id FROM users WHERE id=? LIMIT 1", value)
        if not isinstance(row, dict) or not row.get("id"):
            row = await self._first(
                "SELECT id FROM users WHERE lower(email)=lower(?) LIMIT 1", value,
            )
        if not isinstance(row, dict) or not row.get("id"):
            return None
        return _user_id(row["id"])

    async def drive_roots_for_node(
        self, *, mesh_node_id: str, owner_user_id: str | None = None,
    ) -> list[str]:
        """The whole-drive roots links already record for this PC.

        A claiming PC reports its own fixed drives, and #5981 made those drives
        the default scope. Adoption puts a second account on the same machine, so
        it takes the letters the PC itself reported instead of a folder list
        somebody typed: one authority for what a PC's drives are.

        #6695 PR-2: this is a node-global read. The admin adopt route is the
        only caller allowed to omit ``owner_user_id``; a caller acting for a
        signed-in account must pass that account's id, and the answer then
        covers only the links that account owns — another owner's drive layout
        for the same machine never crosses this seam.
        """
        node = _mesh_node_id(mesh_node_id)
        if owner_user_id is None:
            rows = await self._all(
                "SELECT roots_json FROM pc_device_links WHERE mesh_node_id=? LIMIT 100",
                node,
            )
        else:
            rows = await self._all(
                "SELECT roots_json FROM pc_device_links "
                "WHERE mesh_node_id=? AND user_id=? LIMIT 100",
                node, _user_id(owner_user_id),
            )
        drives: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for root in _roots(row.get("roots_json")):
                single = drive_root(root["path"])
                if single is not None and single not in drives:
                    drives.append(single)
        return drives

    async def list_active_device_ids(self) -> list[str]:
        """Executor inventory targets: active linked PCs, without account data."""
        rows = await self._all(
            "SELECT DISTINCT mesh_node_id FROM pc_device_links "
            "WHERE state='active' AND paused_at IS NULL ORDER BY mesh_node_id"
        )
        return [row["mesh_node_id"] for row in rows
                if isinstance(row, dict) and is_pc_device_id(row.get("mesh_node_id"))]

    async def device_scope(self, *, device_id: Any) -> dict[str, Any] | None:
        """Who owns a reported Mesh identity, from the link directory only.

        A presence beat is keyed by the identity the server named, so an entry
        is accepted only when a link that is active and not paused names exactly
        that node. The
        accounts behind a shared PC are returned as a set: one account resolves
        a Broker credential generation, several do not, and the receipt is still
        recorded as Mesh-only (#5553 requirement 6).
        """
        if not is_pc_device_id(device_id):
            return None
        rows = await self._all(
            "SELECT link_id, user_id, mesh_node_id FROM pc_device_links "
            "WHERE mesh_node_id=? AND state='active' AND paused_at IS NULL LIMIT 100",
            device_id,
        )
        accounts = {
            row.get("user_id") for row in rows
            if isinstance(row, dict) and row.get("link_id")
        }
        if not accounts:
            return None
        return {"device_id": device_id, "account_refs": sorted(accounts)}

    # -- links and roots ----------------------------------------------------

    async def _read_link(self, user_id: str, link_id: str) -> dict[str, Any] | None:
        row = await self._first(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "pairing_code_id, created_at, updated_at, revoked_at, paused_at, "
            "superseded_at, superseded_by "
            "FROM pc_device_links WHERE user_id=? AND link_id=?",
            user_id, link_id,
        )
        if not isinstance(row, dict) or not row.get("link_id"):
            return None
        row["roots"] = _roots(row.get("roots_json"))
        return row

    async def list_links(self, *, user_id: str) -> list[dict[str, Any]]:
        owner = _user_id(user_id)
        rows = await self._all(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "created_at, updated_at, paused_at, superseded_at "
            "FROM pc_device_links WHERE user_id=? "
            "AND (state!='revoked' OR superseded_at IS NOT NULL) "
            "ORDER BY created_at DESC LIMIT 100",
            owner,
        )
        links: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("link_id"):
                continue
            row["roots"] = _roots(row.get("roots_json"))
            links.append(_public_link(row))
        return links

    async def link_for(self, *, user_id: str, mesh_node_id: str) -> dict[str, Any] | None:
        owner = _user_id(user_id)
        node = _mesh_node_id(mesh_node_id)
        row = await self._first(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "created_at, updated_at, paused_at FROM pc_device_links "
            "WHERE user_id=? AND mesh_node_id=? AND state='active' "
            "AND paused_at IS NULL",
            owner, node,
        )
        if not isinstance(row, dict) or not row.get("link_id"):
            return None
        # The authority read carries only granted folders: from PR-2 on, this is
        # the shape dispatch checks a path against.
        row["roots"] = _active(_roots(row.get("roots_json")))
        return row

    async def revoke_link(self, *, user_id: str, link_id: str, now: datetime) -> bool:
        owner = _user_id(user_id)
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        moment = _stamp(now)
        # Roots die with the link in the same statement: R5 asks that deleting
        # a link removes exactly that pair's authority, and a later re-pair must
        # start from no folders at all.
        await self._run(
            "UPDATE pc_device_links SET state='revoked', roots_json='[]', "
            "updated_at=?, revoked_at=? WHERE user_id=? AND link_id=? AND state!='revoked'",
            moment, moment, owner, link_id,
        )
        row = await self._read_link(owner, link_id)
        return row is not None and row["state"] == "revoked" and row["roots"] == []

    async def _link_row_for_node(self, owner: str, node: str) -> dict[str, Any] | None:
        """The live (not revoked) link for one node, pause aside.

        Adoption asks this instead of ``link_for``: a paused pair is still the
        pair that account owns, and treating it as absent would let an adoption
        rewrite the folders of a link the owner deliberately stopped.
        """
        row = await self._first(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "created_at, updated_at, paused_at FROM pc_device_links "
            "WHERE user_id=? AND mesh_node_id=? AND state='active'",
            owner, node,
        )
        if not isinstance(row, dict) or not row.get("link_id"):
            return None
        row["roots"] = _active(_roots(row.get("roots_json")))
        return row

    async def _set_pause(
        self, *, user_id: str, link_id: str, now: datetime, paused: bool,
    ) -> dict[str, Any]:
        owner = _user_id(user_id)
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        moment = _stamp(now)
        # Ownership is settled by the row, not by the caller's claim: the same
        # statement answers "no such link" and "not your link" differently, and
        # only one of the two is a permission failure.
        row = await self._first(
            "SELECT user_id, state FROM pc_device_links WHERE link_id=?", link_id,
        )
        if not isinstance(row, dict) or not row.get("state"):
            raise PcPairingError("link not found")
        if row.get("user_id") != owner:
            raise PcPairingError("link not yours")
        if row.get("state") != _STATE_ACTIVE:
            raise PcPairingError("link not active")
        await self._run(
            "UPDATE pc_device_links SET paused_at=?, updated_at=? "
            "WHERE user_id=? AND link_id=? AND state='active'",
            moment if paused else None, moment, owner, link_id,
        )
        stored = await self._read_link(owner, link_id)
        if stored is None:
            raise PcPairingError("pairing link not stored")
        if bool(stored.get("paused_at")) is not paused:
            raise PcPairingError("pairing link not stored")
        return _public_link(stored)

    async def pause_link(
        self, *, user_id: str, link_id: str, now: datetime,
    ) -> dict[str, Any]:
        """Stop one link from taking work, keeping its folder approvals.

        Idempotent by design: an owner who taps twice, or a retry after a lost
        response, lands on the same single pause stamp rather than an error the
        card would have to explain.
        """
        return await self._set_pause(user_id=user_id, link_id=link_id, now=now, paused=True)

    async def resume_link(
        self, *, user_id: str, link_id: str, now: datetime,
    ) -> dict[str, Any]:
        """Put one paused link back in front of dispatch."""
        return await self._set_pause(user_id=user_id, link_id=link_id, now=now, paused=False)

    async def approve_root(
        self, *, user_id: str, link_id: str, path: str, now: datetime,
        label: str | None = None,
    ) -> dict[str, Any]:
        owner = _user_id(user_id)
        normalized = normalize_root_path(path)
        if normalized is None:
            raise PcPairingError("root path invalid")
        row = await self._require_live_link(owner, link_id)
        roots = row["roots"]
        ref = root_ref_for(normalized)
        moment = _stamp(now)
        requested = normalize_root_label(label) if label is not None else None
        if label is not None and requested is None:
            raise PcPairingError("root label invalid")
        named = requested or default_root_label(normalized)
        for root in roots:
            if root["root_ref"] == ref and root["state"] == _STATE_ACTIVE:
                return root
            if root["state"] == _STATE_ACTIVE and root["label"] == named:
                # Two folders the model cannot tell apart are worse than a
                # refusal: the caller has to name one of them.
                raise PcPairingError("root label exists")
        roots = [root for root in roots if root["root_ref"] != ref]
        roots.append({
            "root_ref": ref,
            "label": named,
            "path": normalized,
            "state": _STATE_ACTIVE,
            "approved_at": moment,
            "revoked_at": None,
        })
        await self._write_roots(owner, link_id, roots, moment)
        stored = next(
            (root for root in (await self._require_live_link(owner, link_id))["roots"]
             if root["root_ref"] == ref),
            None,
        )
        if stored is None:
            raise PcPairingError("root approval not stored")
        return stored

    async def revoke_root(
        self, *, user_id: str, link_id: str, root_ref: str, now: datetime,
    ) -> bool:
        owner = _user_id(user_id)
        if not isinstance(root_ref, str) or re.fullmatch(r"pcroot_[0-9a-f]{16}", root_ref) is None:
            raise PcPairingError("root reference invalid")
        row = await self._require_live_link(owner, link_id)
        moment = _stamp(now)
        found = False
        roots: list[dict[str, Any]] = []
        for root in row["roots"]:
            if root["root_ref"] == root_ref and root["state"] == _STATE_ACTIVE:
                root = {**root, "state": _STATE_REVOKED, "revoked_at": moment}
                found = True
            roots.append(root)
        if not found:
            return False
        await self._write_roots(owner, link_id, roots, moment)
        reread = await self._require_live_link(owner, link_id)
        return not any(
            root["root_ref"] == root_ref and root["state"] == _STATE_ACTIVE
            for root in reread["roots"]
        )

    async def _require_live_link(self, owner: str, link_id: str) -> dict[str, Any]:
        if not isinstance(link_id, str) or _LINK_ID_RE.fullmatch(link_id) is None:
            raise PcPairingError("link id invalid")
        row = await self._read_link(owner, link_id)
        if row is None:
            raise PcPairingError("link not found")
        if row["state"] != _STATE_ACTIVE:
            raise PcPairingError("link not active")
        return row

    async def _write_roots(
        self, owner: str, link_id: str, roots: list[dict[str, Any]], moment: str,
    ) -> None:
        payload = json.dumps(roots, ensure_ascii=False, separators=(",", ":"))
        if len(payload) > MAX_ROOTS_JSON_CHARS:
            raise PcPairingError("link roots too large")
        # A live link only: a revoked pair's roots stay exactly as its owner left
        # them. A link still waiting on its Mesh observation is a real link, and
        # the drives its PC reported have to survive until it verifies - the file
        # lane reads active links, so a pending grant grants nothing yet.
        await self._run(
            "UPDATE pc_device_links SET roots_json=?, updated_at=? "
            "WHERE user_id=? AND link_id=? AND state IN ('active', 'pending_verification')",
            payload, moment, owner, link_id,
        )


def pc_name_from_agent_name(value: Any) -> str | None:
    """The Windows machine name inside an observed agent name, or ``None``.

    An agent reports its own machine name, and the pairing lane decorates that
    name on the way in: the tag that decides the owner, the install token the
    install file presents, and the drive letters the PC declares. Removing all
    three decorations leaves the name Windows chose, which is the label a
    linked PC gets before the owner ever renames it. A name that is nothing but
    decoration has no machine name, and is answered as ``None`` rather than
    with the decoration.
    """
    if not isinstance(value, str):
        return None
    residue = _NAME_DRIVES_RE.sub(" ", value)
    residue = _AGENT_TOKEN_RE.sub(" ", residue)
    residue = _AGENT_TAG_RE.sub(" ", residue)
    # A Windows machine names itself in one word, so the first remaining word is
    # the name and anything a person appended after it is annotation, not name.
    for token in residue.split():
        word = token.strip("()[]{}").rstrip(",.;:")
        if len(word) >= 2:
            return word[:MAX_LINK_LABEL_CHARS]
    return None


def name_tokens(value: Any) -> list[str]:
    """Every name one link answers to, normalised for a request to match.

    `label` carries up to two names of the same machine, joined by
    `_NAME_SEPARATOR`: the PC's own name first (what Windows called it, filled
    when the PC claimed itself) and the owner's alias second. Both choose the
    PC, because both are how a person standing at that machine says its name.
    Case and spacing are the speaker's, not a difference.
    """
    if not isinstance(value, str):
        return []
    tokens: list[str] = []
    for part in value.split(_NAME_SEPARATOR):
        token = " ".join(part.casefold().split())
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def canonical_label(existing: Any, submitted: Any) -> str | None:
    """The one stored form of a link's names, from what it had and what came in.

    The machine name keeps its first position and survives every rename, so an
    alias replaces only the second part. A submitted value that itself carries
    the separator is taken as both names at once - that is how a link created
    before this rule gets its machine name. An alias's own separator becomes a
    dash rather than a second name, so no input can forge more parts than two.
    """
    if not isinstance(submitted, str) or not submitted.strip():
        return None
    text = submitted.replace(_NAME_SEPARATOR, "-").strip()
    previous = [
        " ".join(part.split())
        for part in str(existing or "").split(_NAME_SEPARATOR)
        if part.strip()
    ] if isinstance(existing, str) else []
    if _NAME_SEPARATOR in submitted:
        head, _, tail = submitted.partition(_NAME_SEPARATOR)
        machine = " ".join(head.split())
        alias = " ".join(tail.split()).replace(_NAME_SEPARATOR, "-")
    else:
        machine = previous[0] if previous else None
        alias = text
    parts = [part for part in (machine, alias) if part]
    joined = _NAME_SEPARATOR.join(parts)
    if len(joined) > MAX_LINK_LABEL_CHARS:
        raise PcPairingError("link label too long")
    return joined or None


def link_named_in(text: Any, links: Any) -> str | None:
    """The mesh node id of the one linked PC `text` names, or ``None``.

    An account with several PCs has to be able to say which one it means - by
    the alias it chose or by the name Windows chose, whichever a person is more
    likely to type - and the answer is allowed only when exactly one link
    matches. No match, two matches, and an unnamed link all answer ``None``,
    which leaves the caller's normal "which PC is this?" judgement untouched
    rather than quietly picking the newest or the first.
    """
    if not isinstance(text, str) or not text.strip() or not isinstance(links, (list, tuple)):
        return None
    haystack = " ".join(text.casefold().split())
    if not haystack:
        return None
    matched: list[str] = []
    for link in links:
        if not isinstance(link, Mapping):
            continue
        node = link.get("mesh_node_id")
        if not isinstance(node, str) or not node:
            continue
        if any(token in haystack for token in name_tokens(link.get("label"))):
            if node not in matched:
                matched.append(node)
    return matched[0] if len(matched) == 1 else None


__all__ = [
    "D1PcPairingStore",
    "INSTALL_TOKEN_HEX_CHARS",
    "INSTALL_TOKEN_PREFIX",
    "MAX_ROOTS_JSON_CHARS",
    "MAX_ROOT_LABEL_CHARS",
    "MAX_ROOT_PATH_CHARS",
    "PAIRING_CODE_CHARS",
    "PAIRING_CODE_TTL_SECONDS",
    "PAIRING_TAG_PREFIX",
    "PcPairingError",
    "PcPairingStore",
    "default_root_label",
    "derive_install_tag",
    "drive_root",
    "drives_from_agent_name",
    "install_token_from_agent_name",
    "canonical_label",
    "label_machine_key",
    "link_named_in",
    "machine_key",
    "name_tokens",
    "pc_name_from_agent_name",
    "tag_from_agent_name",
    "normalize_root_label",
    "normalize_root_path",
    "root_ref_for",
]
