/* B66 canonical browser render bridge (#3310).
   No storage, file intake, network access, model calls, or duplicate math.
   The bridge delegates all quote semantics to canonical SavedQuoteSkill,
   QuoteCore and QuoteTemplateRenderer modules already loaded by embed.html. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66QuoteEmbedBridge = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var REQUEST_TYPE = "b66.embed.render.v1";
  var RESPONSE_TYPE = "b66.embed.rendered.v1";
  var ERROR_TYPE = "b66.embed.error.v1";
  var PRINT_TYPE = "b66.embed.print.v1";
  var MAX_MESSAGE_JSON_CHARS = 1024 * 1024;
  var REQUEST_REF_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  var ASSET_ID_RE = /^b66asset_[0-9a-f]{32}$/;
  var DATA_IMAGE_RE = /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;
  var MAX_ASSET_DATA_URL_CHARS = 384 * 1024;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function requestRef(value) {
    return typeof value === "string" && REQUEST_REF_RE.test(value) ? value : null;
  }

  function jsonSizeOkay(value) {
    try {
      return JSON.stringify(value).length <= MAX_MESSAGE_JSON_CHARS;
    } catch (_) {
      return false;
    }
  }

  function normalizeAssetEntry(value) {
    if (!isPlainObject(value) || Object.keys(value).some(function (key) {
      return ["assetId", "dataUrl"].indexOf(key) === -1;
    })) return null;
    if (typeof value.assetId !== "string" || !ASSET_ID_RE.test(value.assetId)) return null;
    if (
      typeof value.dataUrl !== "string" ||
      value.dataUrl.length > MAX_ASSET_DATA_URL_CHARS ||
      !DATA_IMAGE_RE.test(value.dataUrl)
    ) return null;
    return { assetId: value.assetId, dataUrl: value.dataUrl };
  }

  function normalizeAssets(value) {
    if (value === undefined || value === null) return {};
    if (!isPlainObject(value) || Object.keys(value).some(function (key) {
      return ["logo", "stamp"].indexOf(key) === -1;
    })) return null;
    var output = {};
    ["logo", "stamp"].forEach(function (key) {
      if (value[key] === undefined || value[key] === null) return;
      var normalized = normalizeAssetEntry(value[key]);
      if (normalized) output[key] = normalized;
      else output = null;
    });
    return output;
  }

  function declaredAssetId(skill, key) {
    var template = isPlainObject(skill) ? skill.internalTemplate : null;
    var content = isPlainObject(template) ? template.content : null;
    var slots = isPlainObject(content) ? content.slots : null;
    var value = slots && typeof slots[key] === "string" ? slots[key] : "";
    return ASSET_ID_RE.test(value) ? value : "";
  }

  function slotSourcesForSkill(skill, assets) {
    var source = isPlainObject(assets) ? assets : {};
    var output = {};
    var valid = true;
    ["logo", "stamp"].forEach(function (key) {
      var declared = declaredAssetId(skill, key);
      var supplied = source[key];
      if (!declared) {
        if (supplied) valid = false;
        return;
      }
      if (!supplied || supplied.assetId !== declared) {
        valid = false;
        return;
      }
      output[key] = supplied;
    });
    return valid ? output : null;
  }

  function normalizeRenderMessage(value) {
    if (!isPlainObject(value) || value.type !== REQUEST_TYPE) return null;
    if (Object.keys(value).some(function (key) {
      return ["type", "requestId", "skill", "candidate", "assets"].indexOf(key) === -1;
    })) return null;
    var id = requestRef(value.requestId);
    var assets = normalizeAssets(value.assets);
    if (!id || !isPlainObject(value.skill) || !isPlainObject(value.candidate) || assets === null) return null;
    if (!jsonSizeOkay(value.skill) || !jsonSizeOkay(value.candidate) || !jsonSizeOkay(assets)) return null;
    return {
      type: REQUEST_TYPE,
      requestId: id,
      skill: value.skill,
      candidate: value.candidate,
      assets: assets
    };
  }

  function buildStructuredInput(candidate, core) {
    if (!isPlainObject(candidate) || !core || typeof core.createDefaultDraft !== "function") {
      return null;
    }
    var defaults = core.createDefaultDraft();
    if (!defaults || !defaults.meta) return null;
