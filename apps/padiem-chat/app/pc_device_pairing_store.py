"""#5573 PC pairing store: who owns which PC, and which folders that link allows.

Two tables from migration 072 and nothing else. The rules this module owns are
narrow on purpose:

* A pairing code is a **possession proof**, never an identity. Only its SHA-256
  and the SHA-256 of the install tag derived from it are stored; the plaintext
  code exists only in the response that hands it to the browser and the install
  link built from it. A code is single use and short lived.
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
from typing import Any, Protocol

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
MAX_ROOTS_PER_LINK = 32
MAX_ROOT_PATH_CHARS = 512
MAX_ROOT_LABEL_CHARS = 64
MAX_LINK_LABEL_CHARS = 128

_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,255}$")
_LINK_ID_RE = re.compile(r"^pclink_[0-9a-f]{32}$")
_CODE_ID_RE = re.compile(r"^pcpair_[0-9a-f]{32}$")
#: The derived install tag: `pd-` plus the eight hex characters this module
#: produces. MeshCentral agent names are operator-editable text, so the tag is
#: found inside them rather than assumed to be them.
_AGENT_TAG_RE = re.compile(
    r"(?<![0-9A-Za-z])" + re.escape(PAIRING_TAG_PREFIX) + r"[0-9a-f]{8}(?![0-9A-Za-z])",
    re.IGNORECASE,
)
_STATE_ACTIVE = "active"
_STATE_PENDING_VERIFICATION = "pending_verification"
_STATE_REVOKED = "revoked"


class PcPairingError(RuntimeError):
    """Bounded store/refusal reason. Never carries a code, node or path value."""


class PcPairingStore(Protocol):
    """The pairing surface the routes and (from PR-2) the dispatch lane read."""

    async def issue_code(self, *, user_id: str, issued_at: datetime) -> dict[str, Any]: ...

    async def redeem_code(
        self, *, code: str, mesh_node_id: str, label: str | None, now: datetime,
        verified: bool = False,
    ) -> dict[str, Any]: ...

    async def list_links(self, *, user_id: str) -> list[dict[str, Any]]: ...

    async def list_codes(self, *, user_id: str, now: datetime) -> list[dict[str, Any]]: ...

    async def peek_pairing_code(
        self, *, code: str, now: datetime,
    ) -> dict[str, Any]: ...

    async def revoke_link(self, *, user_id: str, link_id: str, now: datetime) -> bool: ...

    async def approve_root(
        self, *, user_id: str, link_id: str, path: str, now: datetime,
        label: str | None = None,
    ) -> dict[str, Any]: ...

    async def links_for_owner(self, *, user_id: str) -> list[dict[str, Any]]: ...


    async def device_scope(self, *, device_id: Any) -> dict[str, Any] | None: ...

    async def revoke_root(
        self, *, user_id: str, link_id: str, root_ref: str, now: datetime,
    ) -> bool: ...

    async def link_for(
        self, *, user_id: str, mesh_node_id: str,
    ) -> dict[str, Any] | None: ...


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
    folder at least one component below a drive, never a bare drive root, never
    a relative or traversing path. Returns ``None`` for anything else.
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


def _roots(value: Any) -> list[dict[str, Any]]:
    """Parse the server-written roots array, refusing anything malformed.

    A malformed column is a hard error rather than an empty list: an approved
    folder must never silently disappear from the authority that guards a read.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            raise PcPairingError("link roots unreadable") from None
    else:
        parsed = value
    if not isinstance(parsed, list) or len(parsed) > MAX_ROOTS_PER_LINK:
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
    return {
        "link_id": row["link_id"],
        "mesh_node_id": row["mesh_node_id"],
        "label": row.get("label"),
        "state": row["state"],
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


class D1PcPairingStore:
    """Cloudflare D1 adapter over `pc_pairing_codes` + `pc_device_links` (072)."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

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
        await self._run(
            "INSERT INTO pc_pairing_codes "
            "(code_id, code_sha256, tag_sha256, user_id, state, mesh_node_id, "
            " issued_at, expires_at, claimed_at) "
            "VALUES (?, ?, ?, ?, 'pending', NULL, ?, ?, NULL)",
            code_id, _hash(code), _hash(derive_install_tag(code)), owner, issued, expires,
        )
        stored = await self._first(
            "SELECT code_id, user_id, state, expires_at FROM pc_pairing_codes WHERE code_id=?",
            code_id,
        )
        if not stored or stored.get("user_id") != owner or stored.get("state") != "pending":
            raise PcPairingError("pairing code not stored")
        return {
            "code_id": code_id,
            "code": code,
            "install_tag": derive_install_tag(code),
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

    async def list_codes(self, *, user_id: str, now: datetime) -> list[dict[str, Any]]:
        owner = _user_id(user_id)
        moment = _stamp(now)
        rows = await self._all(
            "SELECT code_id, state, mesh_node_id, issued_at, expires_at, claimed_at "
            "FROM pc_pairing_codes WHERE user_id=? ORDER BY issued_at DESC LIMIT 20",
            owner,
        )
        return [
            {
                "code_id": row["code_id"],
                "state": (
                    "expired"
                    if row["state"] == "pending" and str(row["expires_at"]) <= moment
                    else row["state"]
                ),
                "issued_at": row["issued_at"],
                "expires_at": row["expires_at"],
            }
            for row in rows
            if isinstance(row, dict) and row.get("code_id")
        ]

    async def redeem_code(
        self, *, code: str, mesh_node_id: str, label: str | None, now: datetime,
        verified: bool = False,
    ) -> dict[str, Any]:
        """Consume one code and create or refresh the (user, node) link.

        The consumption is the guard: an expired or already-used code never
        reaches the link table. `verified` is what PR-2 sets from the executor's
        own MeshCentral observation; without it the link exists but is not
        usable, because nothing has yet proved the node is real.
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
        if row.get("state") != "pending":
            raise PcPairingError("pairing code used")
        if str(row.get("expires_at") or "") <= moment:
            await self._run(
                "UPDATE pc_pairing_codes SET state='cancelled' "
                "WHERE code_id=? AND state='pending'",
                row["code_id"],
            )
            raise PcPairingError("pairing code expired")
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
        return await self._claim_link(
            owner=owner, node=node, label=label, code_id=row["code_id"],
            moment=moment, verified=verified,
        )

    async def _claim_link(
        self, *, owner: str, node: str, label: Any, code_id: str, moment: str,
        verified: bool,
    ) -> dict[str, Any]:
        """Create or refresh the (owner, node) link for one consumed code.

        Shared by the browser-side claim and the server-side tag completion, so
        the two cannot drift into two different link shapes.
        """
        existing = await self._first(
            "SELECT * FROM pc_device_links WHERE user_id=? AND mesh_node_id=?", owner, node,
        )
        state = _STATE_ACTIVE if verified is True else _STATE_PENDING_VERIFICATION
        if isinstance(existing, dict) and existing.get("link_id"):
            if existing.get("state") == _STATE_REVOKED:
                # A re-pair after a revoke is a fresh grant: roots do not come
                # back, because the owner revoked them with the link (R5).
                await self._run(
                    "UPDATE pc_device_links SET state=?, label=?, roots_json='[]', "
                    "pairing_code_id=?, updated_at=?, revoked_at=NULL WHERE link_id=?",
                    state, _label(label), code_id, moment, existing["link_id"],
                )
            elif existing.get("state") == _STATE_PENDING_VERIFICATION and verified is True:
                # A second code that only confirms the same pair promotes it; a
                # claim that names no label keeps the label the owner chose.
                await self._run(
                    "UPDATE pc_device_links SET state=?, label=COALESCE(?, label), "
                    "updated_at=? WHERE link_id=?",
                    _STATE_ACTIVE, _label(label), moment, existing["link_id"],
                )
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
        return stored

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
        code it was handed.

        Returns ``None`` when the name carries no pairing tag: ordinary devices
        keep reporting presence untouched. A name that does carry one is a
        claim attempt, and a failed attempt is refused rather than ignored,
        because silently dropping it would leave an owner staring at a card that
        never resolves. The agent name itself is never stored — the link already
        holds the node identity, and a Mesh device name can be renamed by its
        owner at any time.
        """
        tag = tag_from_agent_name(agent_name)
        if tag is None:
            return None
        node = _mesh_node_id(mesh_node_id)
        moment = _stamp(now)
        row = await self._first(
            "SELECT code_id, user_id, state, expires_at FROM pc_pairing_codes "
            "WHERE tag_sha256=?",
            _hash(tag),
        )
        if not isinstance(row, dict) or not row.get("code_id"):
            raise PcPairingError("pairing tag unknown")
        owner = _user_id(row.get("user_id"))
        if row.get("state") != "pending":
            # The tag is exactly as single-use as the code it came from.
            raise PcPairingError("pairing code used")
        if str(row.get("expires_at") or "") <= moment:
            await self._run(
                "UPDATE pc_pairing_codes SET state='cancelled' "
                "WHERE code_id=? AND state='pending'",
                row["code_id"],
            )
            raise PcPairingError("pairing code expired")
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
        return await self._claim_link(
            owner=owner, node=node, label=None, code_id=row["code_id"],
            moment=moment, verified=True,
        )

    async def links_for_owner(self, *, user_id: str) -> list[dict[str, Any]]:
        """Every active link this account owns, with its granted folders.

        The dispatch lane reads this: an empty list is the answer to "this
        account has no PC connected", and more than one link is a choice the
        caller must narrow, never something to guess.
        """
        owner = _user_id(user_id)
        rows = await self._all(
            "SELECT link_id, user_id, mesh_node_id, label, state, roots_json, "
            "created_at, updated_at FROM pc_device_links WHERE user_id=? "
            "AND state='active' ORDER BY created_at DESC LIMIT 100",
            owner,
        )
        links: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("link_id"):
                continue
            row["roots"] = _active(_roots(row.get("roots_json")))
            links.append(row)
        return links

    async def device_scope(self, *, device_id: Any) -> dict[str, Any] | None:
        """Who owns a reported Mesh identity, from the link directory only.

        A presence beat is keyed by the identity the server named, so an entry
        is accepted only when an active link names exactly that node. The
        accounts behind a shared PC are returned as a set: one account resolves
        a Broker credential generation, several do not, and the receipt is still
        recorded as Mesh-only (#5553 requirement 6).
        """
        if not is_pc_device_id(device_id):
            return None
        rows = await self._all(
            "SELECT link_id, user_id, mesh_node_id FROM pc_device_links "
            "WHERE mesh_node_id=? AND state='active' LIMIT 100",
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
            "pairing_code_id, created_at, updated_at, revoked_at "
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
            "created_at, updated_at FROM pc_device_links WHERE user_id=? "
            "AND state!='revoked' ORDER BY created_at DESC LIMIT 100",
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
            "created_at, updated_at FROM pc_device_links "
            "WHERE user_id=? AND mesh_node_id=? AND state='active'",
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
        if len([root for root in roots if root["state"] == _STATE_ACTIVE]) >= MAX_ROOTS_PER_LINK:
            raise PcPairingError("too many approved roots")
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
        if len(payload) > 8192:
            raise PcPairingError("link roots too large")
        await self._run(
            "UPDATE pc_device_links SET roots_json=?, updated_at=? "
            "WHERE user_id=? AND link_id=? AND state='active'",
            payload, moment, owner, link_id,
        )


__all__ = [
    "D1PcPairingStore",
    "MAX_ROOTS_PER_LINK",
    "MAX_ROOT_LABEL_CHARS",
    "MAX_ROOT_PATH_CHARS",
    "PAIRING_CODE_CHARS",
    "PAIRING_CODE_TTL_SECONDS",
    "PAIRING_TAG_PREFIX",
    "PcPairingError",
    "PcPairingStore",
    "default_root_label",
    "derive_install_tag",
    "tag_from_agent_name",
    "normalize_root_label",
    "normalize_root_path",
    "root_ref_for",
]
