/* B66 - Quote Beta - quote-account-scope.js
   browser-local private quote state account boundary (#3480).
   (no DOM - runs in browser and Node)

   Rules:
   - The only source of the owner marker is the opaque user.id from the
     canonical authenticated projection (GET /api/padiem/auth/status).
     Display name / email / username are not authority and are not accepted.
   - The marker is a privacy-preserving bounded digest. Raw user ids, session
     tokens and credentials are never stored, returned or printed here.
   - While signed out, or while the owner cannot be established, private state
     is never read (fail closed). Data may stay on disk only so that the same
     account can resume it on a later sign-in. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.QuoteAccountScope = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var OWNER_STORAGE_KEY = "quoteBeta.owner.v1";
  var OWNER_MARKER_PATTERN = /^qb1:[0-9a-f]{32}$/;
  var MAX_OWNER_ID_CHARS = 200;
  var MAX_MARKER_CHARS = 40;
  var HASH_SEEDS = [0x811c9dc5, 0x01000193, 0x9e3779b9, 0x85ebca6b];
  var OWNER_ID_CONTROL_PATTERN = /[\s\u0000-\u001f\u007f]/;

  var SCOPE_ACTIONS = {
    UNRESOLVED: "unresolved",
    SIGNED_OUT: "signed_out_private_state_hidden",
    OWNER_BOUND: "owner_bound",
    SAME_ACCOUNT_RESUME: "same_account_resume",
    QUARANTINED_FOREIGN_OWNER: "quarantined_foreign_owner",
    QUARANTINED_MALFORMED_OWNER: "quarantined_malformed_owner",
    OWNER_UNUSABLE: "authenticated_owner_unusable"
  };

  /* Without a storage object (private mode, blocked storage) every read fails closed. */
  var gate = { readable: false, action: SCOPE_ACTIONS.UNRESOLVED };

  function fail(code) {
    return {
      ok: false,
      code: code,
      action: null,
      marker: null,
      authenticated: false,
      privateStateReadable: false
    };
  }

  /* Canonical opaque id only: whitespace/control characters are display text, not an id. */
  function normalizeOwnerId(raw) {
    if (typeof raw !== "string") return null;
    var value = raw.trim();
    if (!value || value.length > MAX_OWNER_ID_CHARS) return null;
    if (OWNER_ID_CONTROL_PATTERN.test(value)) return null;
    return value;
  }

  /* Non-reversible bounded local discriminator. Not a credential, and it never
     replaces server-side authorization. */
  function fnv1a32(text, seed) {
    var hash = seed >>> 0;
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      hash = Math.imul(hash ^ (code & 0xff), 0x01000193) >>> 0;
      hash = Math.imul(hash ^ ((code >>> 8) & 0xff), 0x01000193) >>> 0;
    }
    return hash >>> 0;
  }

  function deriveOwnerMarker(rawOwnerId) {
    var ownerId = normalizeOwnerId(rawOwnerId);
    if (!ownerId) return null;
    var digest = HASH_SEEDS.map(function (seed) {
      return ("00000000" + fnv1a32(ownerId, seed).toString(16)).slice(-8);
    }).join("");
    return "qb1:" + digest;
  }

  function validMarker(raw) {
    if (typeof raw !== "string") return null;
    var value = raw.trim();
    if (!value || value.length > MAX_MARKER_CHARS) return null;
    return OWNER_MARKER_PATTERN.test(value) ? value : null;
  }

  /* readable=false means the storage object itself could not be read (blocked/quota/privacy
     mode). That must never be confused with an absent marker, which is a bindable state. */
  function readOwnerMarker(storage) {
    if (!storage || typeof storage.getItem !== "function") {
      return { ok: false, marker: null, present: false, readable: false };
    }
    var raw;
    try {
      raw = storage.getItem(OWNER_STORAGE_KEY);
    } catch (err) {
      return { ok: false, marker: null, present: false, readable: false };
    }
    if (raw === null || raw === undefined || raw === "") {
      return { ok: false, marker: null, present: false, readable: true };
    }
    var marker = validMarker(raw);
    if (!marker) return { ok: false, marker: null, present: true, readable: true };
    return { ok: true, marker: marker, present: true, readable: true };
  }

  function writeOwnerMarker(storage, marker) {
    if (!storage || typeof storage.setItem !== "function") return false;
    if (!validMarker(marker)) return false;
    try {
      storage.setItem(OWNER_STORAGE_KEY, marker);
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearOwnerMarker(storage) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    try {
      storage.removeItem(OWNER_STORAGE_KEY);
      return true;
    } catch (err) {
      return false;
    }
  }

  function keyList(keys) {
    var seen = Object.create(null);
    var unique = [];
    (Array.isArray(keys) ? keys : []).forEach(function (key) {
      if (typeof key !== "string" || !key || seen[key]) return;
      seen[key] = true;
      unique.push(key);
    });
    return unique;
  }

  /* Every B66 browser-local key that can hold prior-account private quote facts.
     Values come from the owning module constants, never from a literal copy. */
  function privateKeys(deps) {
    var d = deps || {};
    return keyList([
      d.Core && d.Core.DRAFT_STORAGE_KEY,
      d.Core && d.Core.SENDER_STORAGE_KEY,
      d.History && d.History.HISTORY_STORAGE_KEY,
      d.History && d.History.SEQUENCE_STORAGE_KEY,
      d.taxReviewKey,
      d.TemplateStore && d.TemplateStore.TEMPLATE_STORAGE_KEY,
      d.TemplateSelection && d.TemplateSelection.SELECTION_STORAGE_KEY,
      d.SkillStore && d.SkillStore.STORAGE_KEY
    ]);
  }

  function removePrivateKeys(storage, keys) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    var list = keyList(keys);
    var removed = true;
    list.forEach(function (key) {
      try {
        storage.removeItem(key);
      } catch (err) {
        removed = false;
      }
    });
    return removed;
  }

  function applyAccountScope(storage, projection, keys) {
    var proj = projection && typeof projection === "object" ? projection : {};
    var list = keyList(keys);

    if (!storage || typeof storage.getItem !== "function") {
      gate.readable = false;
      gate.action = SCOPE_ACTIONS.UNRESOLVED;
      return fail("storage_unavailable");
    }

    if (proj.authenticated !== true) {
      /* Signed out: private state may stay on disk for a same-account resume,
         but nothing may read or render it. */
      gate.readable = false;
      gate.action = SCOPE_ACTIONS.SIGNED_OUT;
      return {
        ok: true,
        code: "signed_out",
        action: SCOPE_ACTIONS.SIGNED_OUT,
        marker: readOwnerMarker(storage).marker,
        authenticated: false,
        privateStateReadable: false
      };
    }

    var marker = deriveOwnerMarker(proj.userId);
    if (!marker) {
      /* Authenticated but the owner cannot be established: no private exposure. */
      gate.readable = false;
      gate.action = SCOPE_ACTIONS.OWNER_UNUSABLE;
      return {
        ok: true,
        code: "owner_unusable",
        action: SCOPE_ACTIONS.OWNER_UNUSABLE,
        marker: null,
        authenticated: true,
        privateStateReadable: false
      };
    }

    var current = readOwnerMarker(storage);
    if (current.readable !== true) {
      /* storage read itself failed: no owner can be proven, so nothing is exposed. */
      gate.readable = false;
      gate.action = SCOPE_ACTIONS.UNRESOLVED;
      return fail("storage_unreadable");
    }

    var result = {
      ok: true,
      code: null,
      action: null,
      marker: marker,
      authenticated: true,
      privateStateReadable: true
    };

    /* Quarantine only rebinds the marker when every private key was really removed.
       A partial removal must never hand the previous owner's bytes to this account. */
    function quarantine(code, action) {
      if (!removePrivateKeys(storage, list)) {
        gate.readable = false;
        gate.action = SCOPE_ACTIONS.OWNER_UNUSABLE;
        return fail("quarantine_incomplete");
      }
      if (action === SCOPE_ACTIONS.QUARANTINED_MALFORMED_OWNER) clearOwnerMarker(storage);
      writeOwnerMarker(storage, marker);
      result.code = code;
      result.action = action;
      return result;
    }

    if (!current.present) {
      /* Pre-#3480 local state has no marker yet: bind it to the canonical account
         so the existing same-account experience is preserved. */
      writeOwnerMarker(storage, marker);
      result.code = "owner_bound";
      result.action = SCOPE_ACTIONS.OWNER_BOUND;
    } else if (!current.ok) {
      quarantine("malformed_owner_quarantined", SCOPE_ACTIONS.QUARANTINED_MALFORMED_OWNER);
    } else if (current.marker !== marker) {
      quarantine("foreign_owner_quarantined", SCOPE_ACTIONS.QUARANTINED_FOREIGN_OWNER);
    } else {
      result.code = "same_account_resume";
      result.action = SCOPE_ACTIONS.SAME_ACCOUNT_RESUME;
    }

    gate.readable = result.privateStateReadable === true;
    gate.action = result.action;
    return result;
  }

  /* Explicit browser-data reset / quarantine path. The owner marker is the account
     binding, not private quote data, so it is kept. */
  function clearPrivateState(storage, keys) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    return removePrivateKeys(storage, keys);
  }

  function privateStateReadable() {
    return gate.readable === true;
  }

  function currentAction() {
    return gate.action;
  }

  return {
    OWNER_STORAGE_KEY: OWNER_STORAGE_KEY,
    OWNER_MARKER_PATTERN: OWNER_MARKER_PATTERN,
    MAX_OWNER_ID_CHARS: MAX_OWNER_ID_CHARS,
    MAX_MARKER_CHARS: MAX_MARKER_CHARS,
    SCOPE_ACTIONS: SCOPE_ACTIONS,
    normalizeOwnerId: normalizeOwnerId,
    deriveOwnerMarker: deriveOwnerMarker,
    readOwnerMarker: readOwnerMarker,
    writeOwnerMarker: writeOwnerMarker,
    clearOwnerMarker: clearOwnerMarker,
    keyList: keyList,
    privateKeys: privateKeys,
    removePrivateKeys: removePrivateKeys,
    applyAccountScope: applyAccountScope,
    clearPrivateState: clearPrivateState,
    privateStateReadable: privateStateReadable,
    currentAction: currentAction
  };
});
