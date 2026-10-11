/* B66 CGI quotation template v2.
   Source-owned layout candidate derived from the approved CGI sample form.
   Business/company facts stay in CompanyProfile/Saved Quote Skill;
   all amounts stay QuoteCore-authoritative. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-template.js"));
  } else {
    root.B66CgiTemplateV2 = factory(root.QuoteTemplate);
  }
})(typeof self !== "undefined" ? self : this, function (Template) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");

  var TEMPLATE_ID = "cgi-v2";
  var TEMPLATE_NAME = "(주)시지아이 견적서 v2";

  var CONTENT = {
    layoutVersion: 2,
    layoutVariant: "cgi-v2",
    page: { size: "A4", margin: "10mm", orientation: "portrait" },
    sections: ["title","meta","parties","project","writtenTotal","items","totals","memo","mark"],
    title: { text: "견 적 서" },
    meta: {
      quoteNoPrefix: "", issueDatePrefix: "", validityPrefix: "", validUntilPrefix: "",
      taxPrefix: "", validityUnit: "일", taxReviewText: "확인 필요",
      issueDateFormat: "yyyy. mm. dd."
    },
    sender: {
      heading: "", repPrefix: "", bizNoPrefix: "", contactSeparator: "   ",
      contactPrefix: "", contactPersonPrefix: ""
    },
    recipient: { heading: "", personPrefix: "" },
    project: { prefix: "" },
    writtenTotal: { prefix: "합계금액 : 일금 ", suffix: "원정" },
    items: {
      columns: [
        { key: "no", label: "NO", width: "5.3%", align: "center" },
        { key: "name", label: "품 명", width: "23.9%", align: "left" },
        { key: "spec", label: "규 격", width: "18.6%", align: "center" },
        { key: "unit", label: "단위", width: "5.7%", align: "center" },
        { key: "qty", label: "수량", width: "5.7%", align: "right" },
        { key: "unitPrice", label: "단 가", width: "15.4%", align: "right" },
        { key: "amount", label: "금 액", width: "17.1%", align: "right" },
        { key: "note", label: "비고", width: "8.4%", align: "center" }
      ],
      emptyNameText: "",
      minRows: 7
    },
    totals: {
      supplyLabel: "소 계",
      grandLabel: "합 계",
      vatLabels: { EXCLUSIVE: "부가세", INCLUSIVE: "부가세", EXEMPT: "부가세" },
      provisional: {
        subtotalLabel: "소 계", vatLabel: "부가세", vatText: "확인 필요",
        grandLabel: "합 계", grandText: "확인 필요"
      }
    },
    memo: { heading: "", emptyText: "" },
    mark: { text: "" },
    slots: { logo: "", stamp: "" },
    style: {
      accent: "#111111",
      titleRule: "0 solid #111111",
      tableHeaderRule: "1px solid #111111",
      tableRowRule: "1px solid #111111",
      partyRule: "1px solid #111111",
      memoRule: "0 solid #111111",
      headerAlignment: "center",
      metaAlignment: "left",
      numericAlignment: "right",
      textAlignment: "left",
      totalsWidth: "100%"
    },
    cgiV2: {
      slogan: "We experess the Creation of God through Industry",
      fax: "",
      bank: "",
      terms: [
        "상기의 견적 내역은 현장 조건에 따라 변경될 수 있습니다.",
        "세부 결제조건: 현금",
        "견적유효기간은 {validityText} 입니다."
      ],
      underfillText: "********************  이 하 여 백  ********************",
      underfillAfterRows: 4
    },
    fallbackText: "-"
  };

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function cleanPrivatePresentation(raw) {
    var source = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    return {
      fax: typeof source.fax === "string" ? source.fax.slice(0, 160) : "",
      bank: typeof source.bank === "string" ? source.bank.slice(0, 240) : ""
    };
  }

  function cleanSlotRefs(raw) {
    var source = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    var pattern = /^b66asset_[0-9a-f]{32}$/;
    return {
      logo: typeof source.logo === "string" && pattern.test(source.logo) ? source.logo : "",
      stamp: typeof source.stamp === "string" && pattern.test(source.stamp) ? source.stamp : ""
    };
  }

  function content(privatePresentation, slotRefs) {
    var out = clone(CONTENT);
    var privateValues = cleanPrivatePresentation(privatePresentation);
    var slots = cleanSlotRefs(slotRefs);
    out.cgiV2.fax = privateValues.fax;
    out.cgiV2.bank = privateValues.bank;
    out.slots.logo = slots.logo;
    out.slots.stamp = slots.stamp;
    return out;
  }

  function candidate(privatePresentation, slotRefs) {
    return Template.buildProfile({
      id: TEMPLATE_ID, name: TEMPLATE_NAME, builtin: false, isDefault: false,
      approval: null, createdAt: "", updatedAt: "",
      content: content(privatePresentation, slotRefs)
    });
  }

  function approvedProfile(meta) {
    var info = meta && typeof meta === "object" ? meta : {};
    var candidateProfile = candidate(info.privatePresentation, info.slotRefs);
    if (!candidateProfile || !candidateProfile.fingerprint) return null;
    return Template.buildProfile({
      id: TEMPLATE_ID,
      name: TEMPLATE_NAME,
      builtin: false,
      isDefault: false,
      approval: {
        schemaVersion: Template.APPROVAL_SCHEMA_VERSION,
        status: "approved",
        contentFingerprint: candidateProfile.fingerprint,
        approvedBy: String(info.approvedBy || ""),
        approvedAt: String(info.approvedAt || ""),
        approvalRef: String(info.approvalRef || "")
      },
      createdAt: String(info.createdAt || info.approvedAt || ""),
      updatedAt: String(info.updatedAt || info.approvedAt || ""),
      content: content(info.privatePresentation, info.slotRefs)
    });
  }

  return Object.freeze({
    TEMPLATE_ID: TEMPLATE_ID,
    TEMPLATE_NAME: TEMPLATE_NAME,
    content: content,
    candidate: candidate,
    approvedProfile: approvedProfile
  });
});
