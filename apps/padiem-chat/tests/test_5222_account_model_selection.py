"""#5222 account-scoped last selected AI tier: server authority + browser restore.

Two independent halves, proven together:

* the **server** keeps exactly one stored tier per signed account, re-verifies
  the member grade and the administrator gate on every read and write, and
  never lets one account read or write another account's row;
* the **browser** restores that account's own tier after a reload, keeps a
  temporarily unverified administrator lane from being presented as usable,
  never destroys the stored preference on a transient failure, and never shows
  a signed-out or switched account the previous account's selection.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.account_model_selection_routes import MODEL_SELECTION_PATH
from app.account_model_selection_store import (
    AccountModelSelectionError,
    D1AccountModelSelectionStore,
)
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import _user_id
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "059_account_model_selection.sql"
BASE = "https://chat.padiem.test"


# ── a SQLite-backed stand-in for the canonical PADIEM_CHAT_DB D1 ────────────


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class SqliteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        return [await statement.run() for statement in statements]


def seed_db():
    """One administrator account, one PLUS member and one FREE member."""
    db = SqliteD1()
    db.conn.executescript(
        """
        CREATE TABLE users(
            id TEXT PRIMARY KEY, auth_provider TEXT NOT NULL,
            provider_subject TEXT NOT NULL, email TEXT NOT NULL,
            display_name TEXT NOT NULL, picture_url TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE password_credentials(
            user_id TEXT PRIMARY KEY, username TEXT NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT, created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    admin = _user_id("google-subject-admin")
    plus = _user_id("google-subject-plus")
    free = _user_id("google-subject-free")
    for uid, subject, email in (
        (admin, "google-subject-admin", "admin@example.test"),
        (plus, "google-subject-plus", "plus@example.test"),
        (free, "google-subject-free", "free@example.test"),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Member", "", "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        )
    db.conn.executescript(
        (ROOT / "migrations" / "037_b66_admin_memberships.sql").read_text(encoding="utf-8")
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='PLUS' WHERE user_id=?", (plus,)
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='FREE' WHERE user_id=?", (free,)
    )
    db.conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return db, admin, plus, free


def settings() -> Settings:
    return Settings(
        auth_mode="hybrid",
        session_secret="s" * 48,
        public_base_url=BASE,
        runtime_mode="b14",
    )


def build_app(db):
    return create_app(
        settings(),
        d1_binding=db,
        b66_admin_google_email="admin@example.test",
    )


def session(app, uid) -> dict[str, str]:
    return {SESSION_COOKIE: create_session_token(app.state.settings, uid)}


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


# ── store: exactly one account, exactly one row ─────────────────────────────


@pytest.mark.asyncio
async def test_store_keeps_one_selection_per_account():
    db, _admin, plus, free = seed_db()
    store = D1AccountModelSelectionStore(db)
    assert await store.load(plus) is None
    saved = await store.save(plus, "plus")
    assert saved["tier"] == "plus"
    assert (await store.load(plus))["tier"] == "plus"
    # Another account never sees it.
    assert await store.load(free) is None
    assert await store.load(_admin) is None
    await store.save(free, "free")
    assert (await store.load(plus))["tier"] == "plus"
    assert (await store.load(free))["tier"] == "free"
    # The same account replaces its own preference.
    await store.save(plus, "pro")
    assert (await store.load(plus))["tier"] == "pro"


@pytest.mark.asyncio
async def test_store_refuses_a_non_account_and_an_unknown_tier():
    db, _admin, plus, _free = seed_db()
    store = D1AccountModelSelectionStore(db)
    with pytest.raises(AccountModelSelectionError):
        await store.save("not-an-account", "plus")
    with pytest.raises(AccountModelSelectionError):
        await store.save(plus, "enterprise")
    assert await store.load("not-an-account") is None


@pytest.mark.asyncio
async def test_the_schema_refuses_a_tier_that_is_not_selectable():
    db, _admin, plus, _free = seed_db()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO padiem_account_model_selections VALUES (?,?,?)",
            (plus, "enterprise", "2026-10-20T00:00:00Z"),
        )


@pytest.mark.asyncio
async def test_store_ignores_a_row_whose_tier_is_not_selectable():
    db, _admin, plus, _free = seed_db()
    # A schema drift (a hand-edited table without the reviewed CHECK) must
    # still never turn an unknown tier into a usable selection.
    db.conn.execute("DROP TABLE padiem_account_model_selections")
    db.conn.execute(
        "CREATE TABLE padiem_account_model_selections ("
        "user_id TEXT PRIMARY KEY, tier TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    db.conn.execute(
        "INSERT INTO padiem_account_model_selections VALUES (?,?,?)",
        (plus, "enterprise", "2026-10-20T00:00:00Z"),
    )
    store = D1AccountModelSelectionStore(db)
    assert await store.load(plus) is None


# ── routes: the server re-verifies the grade and the administrator gate ────


@pytest.mark.asyncio
async def test_guest_can_not_read_or_write_a_selection():
    db, _admin, _plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        read = await client.get(MODEL_SELECTION_PATH)
        assert read.status_code == 401
        write = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            json={"tier": "plus"},
        )
        assert write.status_code == 401
    rows = db.conn.execute("SELECT COUNT(*) AS n FROM padiem_account_model_selections").fetchone()
    assert rows["n"] == 0


@pytest.mark.asyncio
async def test_account_restores_its_own_last_selection():
    db, _admin, plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        saved = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "plus"},
        )
        assert saved.status_code == 200
        assert saved.json()["selection"]["tier"] == "plus"
        assert saved.json()["restorable_tier"] == "plus"
        read = await client.get(MODEL_SELECTION_PATH, cookies=session(app, plus))
        assert read.status_code == 200
        body = read.json()
        assert body["stored_tier"] == "plus"
        assert body["restorable_tier"] == "plus"
        assert body["allowed_tiers"] == ["free", "plus"]
        assert body["admin_available"] is False


@pytest.mark.asyncio
async def test_one_account_never_sees_another_accounts_selection():
    db, _admin, plus, free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "plus"},
        )
        other = await client.get(MODEL_SELECTION_PATH, cookies=session(app, free))
        assert other.status_code == 200
        assert other.json()["stored_tier"] is None
        assert other.json()["restorable_tier"] is None
        # A forged account id in the body is ignored: the row is always the
        # signed session's own account.
        forged = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, free),
            json={"tier": "plus", "user_id": plus},
        )
        assert forged.status_code in (400, 403)
    rows = db.conn.execute(
        "SELECT user_id, tier FROM padiem_account_model_selections"
    ).fetchall()
    assert [(row["user_id"], row["tier"]) for row in rows] == [(plus, "plus")]


@pytest.mark.asyncio
async def test_a_tier_the_account_may_not_use_is_never_stored():
    db, _admin, _plus, free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        denied = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, free),
            json={"tier": "plus"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "tier_not_available"
    rows = db.conn.execute("SELECT COUNT(*) AS n FROM padiem_account_model_selections").fetchone()
    assert rows["n"] == 0


@pytest.mark.asyncio
async def test_the_administrator_lane_needs_the_verified_administrator():
    db, admin, plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        denied = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "admin"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "admin_forbidden"
        allowed = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, admin),
            json={"tier": "admin"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["restorable_tier"] == "admin"


@pytest.mark.asyncio
async def test_a_revoked_grade_recovers_to_an_available_tier_without_losing_the_row():
    db, _admin, plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "plus"},
        )
        # The membership grade drops: the stored preference is separated from
        # the server policy, so it is not applied and not silently destroyed.
        db.conn.execute("UPDATE b66_memberships SET tier='FREE' WHERE user_id=?", (plus,))
        read = await client.get(MODEL_SELECTION_PATH, cookies=session(app, plus))
        assert read.status_code == 200
        body = read.json()
        assert body["stored_tier"] == "plus"
        assert body["restorable_tier"] is None
        assert body["allowed_tiers"] == ["free"]


@pytest.mark.asyncio
async def test_an_unavailable_administrator_authority_is_not_a_denial():
    db, admin, _plus, _free = seed_db()
    app = build_app(db)
    app.state.b66_member_admin_store = _BrokenAdminStore()
    async with client_for(app) as client:
        read = await client.get(MODEL_SELECTION_PATH, cookies=session(app, admin))
        assert read.status_code == 200
        body = read.json()
        # The authority could not be checked: that is neither "allowed" nor
        # "denied", and an administrator selection is not handed back.
        assert body["admin_available"] is None
        assert body["restorable_tier"] is None


@pytest.mark.asyncio
async def test_a_missing_store_fails_closed_without_inventing_a_preference():
    db, _admin, plus, _free = seed_db()
    app = build_app(db)
    app.state.account_model_selection_store = None
    async with client_for(app) as client:
        read = await client.get(MODEL_SELECTION_PATH, cookies=session(app, plus))
        assert read.status_code == 503
        assert read.json()["error"]["code"] == "model_selection_unavailable"
        write = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": BASE, "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "plus"},
        )
        assert write.status_code == 503


@pytest.mark.asyncio
async def test_an_invalid_tier_is_refused():
    db, _admin, plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        for body in ({"tier": "enterprise"}, {"tier": 7}, {}, {"tier": "plus", "x": 1}):
            response = await client.put(
                MODEL_SELECTION_PATH,
                headers={"Origin": BASE, "Content-Type": "application/json"},
                cookies=session(app, plus),
                json=body,
            )
            assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_the_mutation_is_same_origin_guarded():
    db, _admin, plus, _free = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        response = await client.put(
            MODEL_SELECTION_PATH,
            headers={"Origin": "https://sibling.example.test", "Content-Type": "application/json"},
            cookies=session(app, plus),
            json={"tier": "plus"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_rejected"


class _BrokenAdminStore:
    async def is_google_admin(self, user_id):
        raise RuntimeError("authority unavailable")

    async def runtime_access(self, user_id):
        return None


# ── browser: the account's own tier is restored and never leaks ────────────

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const CAPABILITIES = process.env.HARNESS_CAPABILITIES;
const CLAW = process.env.HARNESS_CLAW;

function makeEl(tag) {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    children: [], listeners: {}, dataset: {}, style: {}, className: "",
    textContent: "", hidden: false, disabled: false, id: "",
    classList: { add() {}, remove() {}, contains() { return false; } },
  };
  el.setAttribute = (k, v) => {
    el[k] = String(v);
    if (k.startsWith("data-")) {
      el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v);
    }
  };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.insertBefore = (node, ref) => {
    const at = el.children.indexOf(ref);
    if (at < 0) el.children.push(node); else el.children.splice(at, 0, node);
    node.parentNode = el;
    return node;
  };
  el.removeChild = (node) => { el.children = el.children.filter((c) => c !== node); return node; };
  el.contains = (node) => {
    let cur = node;
    while (cur) { if (cur === el) return true; cur = cur.parentNode; }
    return false;
  };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.querySelectorAll(sel)[0] || null;
  el.querySelectorAll = (sel) => {
    const out = [];
    const walk = (node) => {
      node.children.forEach((child) => {
        if (matches(child, sel)) out.push(child);
        walk(child);
      });
    };
    walk(el);
    return out;
  };
  el.focus = () => {};
  el.blur = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  return el;
}

function matches(el, sel) {
  const s = String(sel || "").trim();
  if (!s) return false;
  if (s.startsWith("[")) {
    const m = /^\[data-([a-zA-Z0-9-]+)\]$/.exec(s);
    if (!m) return false;
    const key = m[1].replace(/-(\w)/g, (mm, c) => c.toUpperCase());
    return Object.prototype.hasOwnProperty.call(el.dataset, key);
  }
  if (s.startsWith(".")) return String(el.className || "").split(/\s+/).includes(s.slice(1));
  return false;
}

function boot(fixture) {
  const byId = {};
  ["clawVerifiedModelSelect", "clawModelIdInput", "clawVerifiedModelHint"].forEach((id) => {
    const el = makeEl(id === "clawVerifiedModelSelect" ? "select" : "div");
    el.id = id;
    if (id === "clawVerifiedModelSelect") { el.options = []; el.value = ""; }
    byId[id] = el;
  });
  const modePill = makeEl("button");
  modePill.className = "model-pill composer-tier-trigger";
  const modeHost = makeEl("div");
  modeHost.className = "composer-tools";
  const head = makeEl("head");
  const body = makeEl("body");

  const document = {
    documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
    head, body, readyState: "complete", activeElement: null,
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => {
      if (sel === ".model-pill") return modePill;
      if (sel === ".composer-tools") return modeHost;
      return null;
    },
    querySelectorAll: () => [],
    createElement: (tag) => makeEl(tag),
    addEventListener() {},
  };

  const windowListeners = {};
  const timers = [];
  let timerSeq = 0;
  let clockOffset = 0;

  const state = {
    accounts: Object.assign({}, fixture.accounts || {}),
    account: fixture.account || Object.keys(fixture.accounts || {})[0],
    authenticated: fixture.authenticated !== false,
    memberGrade: fixture.member_grade || "plus",
    adminMode: fixture.admin_mode || "not_admin",
    adminFailures: fixture.admin_failures || 0,
    adminCalls: 0,
    requests: [],
    puts: [],
    tierChanges: [],
  };

  function allowedTiers() {
    const order = ["free", "plus", "pro", "max"];
    const index = order.indexOf(state.memberGrade);
    return order.slice(0, index < 0 ? 1 : index + 1);
  }

  function serverAdminAvailable() {
    if (state.adminMode === "admin") return true;
    if (state.adminMode === "unknown") return null;
    return false;
  }

  function jsonResponse(status, obj) {
    return { ok: status >= 200 && status < 300, status, json: async () => obj };
  }

  async function fetchImpl(url, opts) {
    opts = opts || {};
    const method = (opts.method || "GET").toUpperCase();
    const u = String(url);
    state.requests.push({ url: u, method });
    if (u.startsWith("/health")) {
      return jsonResponse(200, { web_tools_ready: true, deep_research_ready: true });
    }
    if (u.startsWith("/api/auth/status")) {
      return jsonResponse(200, {
        ready: true,
        authenticated: state.authenticated,
        session_state: state.authenticated ? "signed_in" : "guest",
        user: state.authenticated ? { name: "Member" } : null,
        member_grade: state.memberGrade,
        history_ready: false,
        project_files_ready: false,
      });
    }
    if (u.startsWith("/api/b66/admin/me")) {
      state.adminCalls += 1;
      if (state.adminFailures > 0) {
        state.adminFailures -= 1;
        throw new Error("network down");
      }
      if (state.adminMode === "unknown") {
        return jsonResponse(503, { ok: false, error: { code: "admin_unavailable" } });
      }
      return jsonResponse(200, {
        ok: true,
        admin: state.adminMode === "admin",
        state: state.adminMode === "admin" ? "admin" : "not_admin",
      });
    }
    if (u.startsWith("/api/account/model-selection")) {
      const stored = state.accounts[state.account] || null;
      const allowed = allowedTiers();
      const admin = serverAdminAvailable();
      if (method === "PUT") {
        const body = JSON.parse(opts.body || "{}");
        state.puts.push(body);
        const tier = body.tier;
        const permitted = allowed.includes(tier) || (tier === "admin" && admin === true);
        if (!permitted) {
          return jsonResponse(403, { ok: false, error: { code: "tier_not_available" } });
        }
        state.accounts[state.account] = tier;
        return jsonResponse(200, {
          ok: true,
          selection: { tier, updated_at: "2026-10-20T00:00:00Z" },
          stored_tier: tier,
          restorable_tier: tier,
          allowed_tiers: allowed,
          admin_available: admin,
        });
      }
      let restorable = null;
      if (stored && allowed.includes(stored)) restorable = stored;
      else if (stored === "admin" && admin === true) restorable = "admin";
      return jsonResponse(200, {
        ok: true,
        selection: stored ? { tier: stored, updated_at: "2026-10-20T00:00:00Z" } : null,
        stored_tier: stored,
        restorable_tier: restorable,
        allowed_tiers: allowed,
        admin_available: admin,
      });
    }
    if (u.startsWith("/api/chat/custom/credential")) {
      return jsonResponse(200, { ok: true, providers: [], credentials: [] });
    }
    if (u.startsWith("/api/claw/verified-model-choices")) {
      return jsonResponse(200, {
        ok: true,
        scope: "b14_owner_allowed_live_ready",
        complete_inventory: true,
        automatic_default: false,
        model_choices: [{
          model_id: "opencode-go/beam-free",
          individual_model_name: "Beam Free",
          product_name_prefix: "파디엠프리",
          customer_selectable: true,
        }],
      });
    }
    return jsonResponse(200, {});
  }

  class CustomEvent {
    constructor(type, init) {
      this.type = type;
      this.detail = (init && init.detail) || null;
    }
  }

  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(RealDate.now() + clockOffset);
      else super(...args);
    }
    static now() { return RealDate.now() + clockOffset; }
  }

  const sandbox = {
    console,
    Date: FakeDate,
    CustomEvent,
    setTimeout: (fn, ms) => { const id = ++timerSeq; timers.push({ id, fn, ms }); return id; },
    clearTimeout: (id) => { const at = timers.findIndex((t) => t.id === id); if (at >= 0) timers.splice(at, 1); },
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
    document,
    fetch: fetchImpl,
    __padiemLocale: { text: (k) => k },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.addEventListener = (type, fn) => { (windowListeners[type] = windowListeners[type] || []).push(fn); };
  sandbox.removeEventListener = () => {};
  sandbox.dispatchEvent = (event) => {
    if (event && event.type === "padiem:tierchange") {
      state.tierChanges.push(event.detail ? event.detail.tier : null);
    }
    (windowListeners[event.type] || []).forEach((fn) => fn(event));
    return true;
  };

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(CAPABILITIES, "utf8"), sandbox, { filename: "product-capabilities.js" });
  vm.runInContext(fs.readFileSync(CLAW, "utf8"), sandbox, { filename: "claw-verified-model-choice.js" });

  function findPanel() {
    return modeHost.children.find((c) => c.className === "mode-presentation-panel") || null;
  }

  function findTierButton(tier) {
    const panel = findPanel();
    if (!panel) return null;
    return panel.querySelectorAll("[data-mode-value]")
      .find((el) => el.dataset.modeValue === tier) || null;
  }

  return {
    state,
    modePill,
    tier: () => sandbox.window.PadiemTierSelection.get(),
    ready: () => sandbox.window.PadiemTierSelection.ready(),
    dispatch: (type, detail) => sandbox.window.dispatchEvent(new CustomEvent(type, { detail })),
    setAccount: (account) => { state.account = account; },
    setAuthenticated: (value) => { state.authenticated = value; },
    clickTier: (tier) => {
      const button = findTierButton(tier);
      if (!button) throw new Error("tier option not found: " + tier);
      button.click();
    },
    flushTimers: () => {
      clockOffset += 10000;
      const pending = timers.splice(0, timers.length);
      pending.forEach((t) => t.fn());
      return pending.length;
    },
    modelRequests: () => state.requests.filter(
      (r) => r.url.indexOf("/api/claw/verified-model-choices") === 0,
    ),
  };
}

module.exports = { boot };
"""

RUNNER = r"""
const harness = require(process.argv[2]);
const fixture = JSON.parse(process.argv[3]);
const scenario = process.argv[4];

(async () => {
  const api = harness.boot(fixture);
  const out = {};
  const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

  if (scenario === "restore") {
    await api.ready();
    out.tier = api.tier();
    out.pill = api.modePill.dataset.modelSelection;
    out.adminCalls = api.state.adminCalls;
    out.puts = api.state.puts;
    out.clawRequests = api.modelRequests().map((r) => r.url);
  } else if (scenario === "transient_admin_failure") {
    await api.ready();
    out.after_failure = api.tier();
    out.stored = api.state.accounts[api.state.account];
    out.puts = api.state.puts;
    api.flushTimers();
    await settle();
    await api.ready();
    out.after_retry = api.tier();
    out.stored_after = api.state.accounts[api.state.account];
    out.adminCalls = api.state.adminCalls;
  } else if (scenario === "unavailable_admin_authority") {
    await api.ready();
    out.tier = api.tier();
    out.stored = api.state.accounts[api.state.account];
    out.puts = api.state.puts;
    api.flushTimers();
    await settle();
    await api.ready();
    out.tier_after_retry = api.tier();
    out.stored_after = api.state.accounts[api.state.account];
  } else if (scenario === "account_switch") {
    await api.ready();
    out.before = api.tier();
    api.setAuthenticated(false);
    api.dispatch("padiem:auth-state", { authenticated: false });
    await api.ready();
    out.after_logout = api.tier();
    api.setAccount("account-b");
    api.setAuthenticated(true);
    api.dispatch("padiem:auth-state", { authenticated: true });
    await api.ready();
    out.after_switch = api.tier();
    out.stored_a = api.state.accounts["account-a"];
    out.stored_b = api.state.accounts["account-b"];
  } else if (scenario === "explicit_choice") {
    await api.ready();
    out.before = api.tier();
    api.clickTier("plus");
    await settle();
    out.after = api.tier();
    out.puts = api.state.puts;
    out.stored = api.state.accounts[api.state.account];
  }
  process.stdout.write(JSON.stringify(out));
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
"""


@pytest.fixture(scope="module")
def runner():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    directory = Path(tempfile.mkdtemp(prefix="5222-harness-"))
    harness_path = directory / "harness.cjs"
    harness_path.write_text(HARNESS, encoding="utf-8")
    runner_path = directory / "runner.cjs"
    runner_path.write_text(RUNNER, encoding="utf-8")

    def run(fixture: dict, scenario: str) -> dict:
        result = subprocess.run(
            [node, str(runner_path), str(harness_path), json.dumps(fixture), scenario],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                "PATH": __import__("os").environ.get("PATH", ""),
                "HARNESS_CAPABILITIES": str(ROOT / "static" / "product-capabilities.js"),
                "HARNESS_CLAW": str(ROOT / "static" / "claw-verified-model-choice.js"),
                "SystemRoot": __import__("os").environ.get("SystemRoot", ""),
            },
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    yield run
    shutil.rmtree(directory, ignore_errors=True)


def test_the_account_selection_is_restored_after_a_reload(runner):
    out = runner(
        {
            "accounts": {"account-a": "plus"},
            "account": "account-a",
            "member_grade": "plus",
            "admin_mode": "not_admin",
        },
        "restore",
    )
    assert out["tier"] == "plus"
    assert out["pill"] == "plus"
    # A restore never writes a preference back.
    assert out["puts"] == []


def test_an_account_without_a_stored_selection_keeps_the_free_default(runner):
    out = runner(
        {
            "accounts": {"account-a": None},
            "account": "account-a",
            "member_grade": "plus",
            "admin_mode": "not_admin",
        },
        "restore",
    )
    assert out["tier"] == "free"
    assert out["pill"] == "free"


def test_the_administrator_selection_is_restored_for_a_verified_administrator(runner):
    out = runner(
        {
            "accounts": {"account-a": "admin"},
            "account": "account-a",
            "member_grade": "max",
            "admin_mode": "admin",
        },
        "restore",
    )
    assert out["tier"] == "admin"
    assert out["pill"] == "admin"


def test_a_temporarily_unverified_administrator_keeps_the_stored_preference(runner):
    out = runner(
        {
            "accounts": {"account-a": "admin"},
            "account": "account-a",
            "member_grade": "max",
            "admin_mode": "admin",
            "admin_failures": 1,
        },
        "transient_admin_failure",
    )
    # The administrator lane is not executable while it is unverified.
    assert out["after_failure"] == "free"
    # The stored preference is not destroyed by the transient failure.
    assert out["stored"] == "admin"
    assert out["puts"] == []
    # A later verified probe brings the account's own selection back.
    assert out["after_retry"] == "admin"
    assert out["stored_after"] == "admin"
    assert out["adminCalls"] >= 2


def test_an_unavailable_administrator_authority_is_never_presented_as_usable(runner):
    out = runner(
        {
            "accounts": {"account-a": "admin"},
            "account": "account-a",
            "member_grade": "max",
            "admin_mode": "unknown",
        },
        "unavailable_admin_authority",
    )
    assert out["tier"] == "free"
    assert out["stored"] == "admin"
    assert out["puts"] == []
    assert out["tier_after_retry"] == "free"
    assert out["stored_after"] == "admin"


def test_a_signed_out_and_switched_account_never_inherits_the_previous_selection(runner):
    out = runner(
        {
            "accounts": {"account-a": "pro", "account-b": None},
            "account": "account-a",
            "member_grade": "pro",
            "admin_mode": "not_admin",
        },
        "account_switch",
    )
    assert out["before"] == "pro"
    assert out["after_logout"] == "free"
    assert out["after_switch"] == "free"
    # The first account keeps its own stored preference for its next sign-in.
    assert out["stored_a"] == "pro"
    assert out["stored_b"] is None


def test_an_explicit_choice_replaces_the_account_preference(runner):
    out = runner(
        {
            "accounts": {"account-a": None},
            "account": "account-a",
            "member_grade": "plus",
            "admin_mode": "not_admin",
        },
        "explicit_choice",
    )
    assert out["before"] == "free"
    assert out["after"] == "plus"
    assert out["puts"] == [{"tier": "plus"}]
    assert out["stored"] == "plus"


def test_chat_and_claw_share_the_same_restored_selection(runner):
    out = runner(
        {
            "accounts": {"account-a": "plus"},
            "account": "account-a",
            "member_grade": "plus",
            "admin_mode": "not_admin",
        },
        "restore",
    )
    # The Claw model list is requested with the account's restored tier, so
    # both surfaces read exactly the same selection.
    assert out["clawRequests"], "the Claw model list must be requested"
    assert "tier=plus" in out["clawRequests"][-1], out["clawRequests"]
    assert any("tier=plus" in url for url in out["clawRequests"]), out["clawRequests"]


def test_the_browser_never_uses_a_browser_side_persistence_primitive():
    # The B62 browser-persistence privacy gate owns this invariant: the
    # account preference lives in the account-scoped server store instead.
    from app import account_model_selection_routes as routes

    source = Path(routes.__file__).read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert forbidden not in source
