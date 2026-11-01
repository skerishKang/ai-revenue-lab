(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const COPY = {
    ko: {
      launcher: "내 견적서",
      title: "내 견적서 만들기",
      description: "거래처, 품목, 수량, 단가만 편하게 말해 주세요.",
      requestLabel: "견적 요청",
      requestPlaceholder: "예: ABC건설에 배관 20개, 개당 3만원으로 견적서 만들어줘",
      generate: "견적서 만들기",
      close: "닫기",
      selectLabel: "견적서 양식",
      signinHint: "로그인하면 내 양식과 등급을 고를 수 있어요",
      signinAction: "로그인",
      idle: "내용을 입력하면 배정된 견적서 양식으로 바로 만듭니다.",
      working: "견적 내용을 정리하고 있습니다.",
      missing: "거래처와 품목·수량·단가를 조금 더 알려 주세요.",
      companyIdentityMissing: "견적서에 넣을 회사명을 확인해 주세요.",
      companyDefaultsMissing: "회사 기본 유효기간을 확인해 주세요.",
      ready: "견적서가 준비되었습니다. 아래에서 확인하거나 PDF로 저장하세요.",
      failed: "견적서를 만들지 못했습니다. 입력 내용을 확인해 주세요.",
      pcToggle: "내 컴퓨터 · 연결 상태",
      pcHelp: "Padiem Connect 설치와 같은 계정 로그인 기능은 준비 중입니다. 파일 작업은 바로 진행되고, 덮어쓰기·삭제 전에는 자동으로 백업돼요.",
      pcRefresh: "상태 새로고침",
      pcLoading: "서버에서 연결 상태를 확인하고 있습니다.",
      pcAuth: "Padiem 계정에 로그인한 뒤 확인해 주세요.",
      pcUnavailable: "PC 연결 서비스가 아직 준비되지 않았습니다. 연결이 완료됐다고 표시하지 않습니다.",
      pcFailed: "PC 연결 상태를 확인하지 못했습니다.",
      pcEmpty: "현재 계정에 등록된 컴퓨터가 없습니다.",
      pcReady: "확인된 컴퓨터 목록입니다. 이 화면에서는 파일에 접근하거나 작업을 실행하지 않습니다.",
      pcOnline: "온라인 · 바로 작업",
      pcOffline: "오프라인",
      pcRevoked: "연결 해제",
      pcTxtTitle: "PC 파일 읽기 (TXT)",
      pcConversation: "결과를 반환할 B66 대화",
      pcConversationPlaceholder: "대화를 선택하세요",
      pcConversationEmpty: "사용 가능한 B66 대화가 없습니다.",
      pcConversationGone: "선택한 대화를 찾을 수 없습니다. 목록을 새로고침해 주세요.",
      pcPath: "TXT 파일 상대 경로",
      pcPathPlaceholder: "예: memo.txt",
      pcRequest: "TXT 읽기 요청",
      pcInvalid: "TXT 파일 상대 경로(.txt)를 입력하고 대화를 선택해 주세요.",
      pcRequestFailed: "PC 읽기 요청을 전달하지 못했습니다.",
      pcRunPending: "PC에서 읽는 중입니다.",
      pcRunDone: "읽기 완료. 결과가 요청한 B66 대화에 반환됐습니다.",
      pcRunFailed: "PC 읽기에 실패했습니다. 입력과 연결 상태를 확인해 주세요."
    },
    en: {
      launcher: "My quote",
      title: "Create my quote",
      description: "Tell me the customer, item, quantity, and unit price.",
      requestLabel: "Quote request",
      requestPlaceholder: "Example: Quote 20 pipes at 30,000 each for ABC Construction",
      generate: "Create quote",
      close: "Close",
      selectLabel: "Quote template",
      signinHint: "Sign in to pick your template and AI tier.",
      signinAction: "Sign in",
      idle: "Enter the changing values and your assigned template will be used.",
      working: "Preparing the quote values.",
      missing: "Please add the customer and item, quantity, and unit price.",
      companyIdentityMissing: "Please confirm the company name to use on the quote.",
      companyDefaultsMissing: "Please confirm your company's default quote validity period.",
      ready: "Your quote is ready. Review it below or save it as PDF.",
      failed: "The quote could not be created. Check your request and try again.",
      pcToggle: "My computers · connection status",
      pcHelp: "Padiem Connect installation and same-account sign-in are not ready yet. File work runs right away, and overwrites and deletes are backed up automatically first.",
      pcRefresh: "Refresh status",
      pcLoading: "Checking connection status with the server.",
      pcAuth: "Sign in to your Padiem account first.",
      pcUnavailable: "The PC connection service is not ready. No connection is claimed.",
      pcFailed: "Could not verify PC connection status.",
      pcEmpty: "No computers are registered for this account.",
      pcReady: "Server-confirmed computers. This view cannot read files or execute tasks.",
      pcOnline: "Online · approval required",
      pcOffline: "Offline",
      pcRevoked: "Disconnected",
      pcTxtTitle: "Read a TXT file from the PC",
      pcConversation: "B66 conversation for the result",
      pcConversationPlaceholder: "Select a conversation",
      pcConversationEmpty: "No B66 conversations available.",
      pcConversationGone: "The selected conversation was not found. Refresh the list.",
      pcPath: "TXT file relative path",
      pcPathPlaceholder: "Example: memo.txt",
      pcRequest: "Request TXT read",
      pcInvalid: "Enter a TXT relative path (.txt) and select a conversation.",
      pcRequestFailed: "Could not send the PC read request.",
      pcRunPending: "Reading on the PC…",
      pcRunDone: "Read complete. The result was returned to the requesting B66 conversation.",
      pcRunFailed: "The PC read failed. Check the input and connection."
    }
  };

  let runtime = null;
  let skills = [];
  // #5895: an account with a linked PC reaches the quote screen through its own
  // Excel form even before it has saved a skill.
  let pcAccountLinked = false;
  // #6100: the capability event's own word on whether this browser is signed
  // in. The selects' data belongs to a signed-in account, so the logged-out
  // dialog says so instead of showing three empty controls.
  let signedIn = false;
  let modelIds = [];
  let selectedModelByTier = {};
  let reasoningByModel = {};
  let initialized = false;
  let refreshPromise = null;
  let currentRequestId = null;
  let frameLoadedUrl = "";
  let pcQuerySequence = 0;
  let pcTxtSequence = 0;
  let pcOnlineDeviceId = "";
  const PC_DIRECTORY_PATH = "/api/b66/connect/devices";
  const PC_DIALOGUES_PATH = "/api/b66/ai/dialogues?limit=20";
  const PC_TXT_READ_PATH = "/api/b66/connect/txt-reads/request";
  const PC_RESULT_PATH_PREFIX = "/api/b66/runs/";
  // #5895: the quote screen's own PC Excel form. Chat exchanges ids and the model's
  // cell mapping only; the workbook itself is read and filled in COM2.
  const PC_QUOTE_FILL_PATH = "/api/b66/pc-quote/fill";
  const PC_SAVE_PATH = "/api/pc/save";
  const PC_RESULT_PATH = "/api/pc/result";
  const PC_PAIRINGS_PATH = "/api/pc/pairings";
  const PC_EXCHANGE_SCRIPT = "./pc-file-exchange.js";
  const PC_EXCHANGE_CSS = "./pc-file-exchange.css";
  const PC_RESULT_PATH_SUFFIX = "/pc-result";
  // #5895-D: no client byte gate on the owner's own same-origin reads. The
  // closed projection below governs what gets rendered; a raw-length gate
  // only silently turned real folder lists and run results into "empty".
  const B66_ASSET_ID = /^b66asset_[0-9a-f]{32}$/;
  const PRIVATE_ASSET_MEDIA = new Set(["image/png", "image/jpeg", "image/webp"]);
  const MAX_PRIVATE_ASSET_BYTES = 256 * 1024;

  function copy() {
    return COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function validRuntime(data) {
    if (!data || data.ok !== true || data.enabled !== true) return null;
    if (typeof data.embed_url !== "string" || typeof data.origin !== "string") return null;
    try {
      const embed = new URL(data.embed_url);
      const origin = new URL(data.origin);
      if (embed.protocol !== "https:" || origin.protocol !== "https:") return null;
      if (embed.origin !== origin.origin || data.origin !== origin.origin) return null;
      // The embed must be a different origin. A same-origin iframe with
      // allow-scripts + allow-same-origin can remove its own sandbox.
      if (embed.origin === window.location.origin) return null;
      if (!embed.pathname.endsWith("/embed.html")) return null;
      // The canonical product permission gate must set this explicitly.
      // Existing B66 runtime-config does not issue it: default stays OFF.
      return Object.freeze({
        embedUrl: embed.href,
        origin: origin.origin,
        pcDirectoryEnabled: data.pc_device_list_enabled === true
      });
    } catch (_) {
      return null;
    }
  }

  function safeSkills(data) {
    if (!data || data.ok !== true || !Array.isArray(data.skills)) return [];
    return data.skills.filter((item) => (
      item && typeof item === "object" &&
      typeof item.saved_skill_id === "string" &&
      /^b66skill_[0-9a-f]{32}$/.test(item.saved_skill_id) &&
      typeof item.skill_name === "string" &&
      item.skill_name.trim()
    )).slice(0, 20);
  }

  // #3180 ③: the saved-quote list holds two kinds. A `pc_form` entry is the
  // owner's own workbook on their own PC, never a certified skill: the fill
  // lane writes into a copy of it and the sheet's formulas do the arithmetic.
  function skillById(savedSkillId) {
    return skills.find((item) => item && item.saved_skill_id === savedSkillId) || null;
  }

  function isPcForm(skill) {
    return Boolean(skill && skill.skill_kind === "pc_form"
      && typeof skill.form_path === "string" && skill.form_path);
  }

  function companyProfileForRender(profile) {
    if (profile === null || profile === undefined) {
      return { ok: true, code: "absent", profile: null };
    }
    if (typeof profile !== "object" || Array.isArray(profile)) {
      return { ok: false, code: "invalid", profile: null };
    }
    if (typeof profile.company !== "string" || !profile.company.trim()) {
      return { ok: false, code: "missing_company", profile: null };
    }
    if (!Number.isInteger(profile.defaultValidityDays) || profile.defaultValidityDays < 0 || profile.defaultValidityDays > 3650) {
      return { ok: false, code: "missing_validity", profile: null };
    }
    return {
      ok: true,
      code: "ready",
      profile: {
        company: profile.company,
        representative: profile.representative,
        contactPerson: profile.contactPerson,
        businessNumber: profile.businessNumber,
        address: profile.address,
        phone: profile.phone,
        email: profile.email,
        defaultValidityDays: profile.defaultValidityDays,
        defaultTaxMode: profile.defaultTaxMode
      }
    };
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  let pcExchangePromise = null;
  // Set once the dialog exists: the saved-form repeat path renders through the
  // same review list, so it needs the PC form section's own nodes.
  let pcFormBridge = null;

  function pcCopy() {
    if (document.documentElement.lang === "en") {
      return {
        pick: "Bring an Excel form from my PC", make: "Make a quote from this form",
        save: "Save to my PC", chosen: "Form:", needRequest: "Write what the quote is for first.",
        made: "The quote is ready. Save it next to your form.",
        choosing: "Choose your form on your PC…", filling: "Making the quote from your form…",
        saving: "Saving to your PC…", saved: "Saved to your PC.",
        failed: "That did not work. Please try again in a moment.",
        noPc: "Connect your PC to bring your own form.", connect: "Connect this PC",
        entry: "Quote from my PC Excel form",
        reviewClient: "Customer:", reviewTitle: "What was filled into your form",
        reviewEmpty: "No cell was filled. Check the request and the form.",
        reviewExtend: "Item rows added by copying the form's own row:",
        reviewTotals: "Totals and tax come from your form's own formulas. Check each value and cell before saving.",
        remember: "Save this form as my quote form", remembering: "Saving the form…",
        remembered: "Saved. Pick it from the quote form list next time.",
        rememberFailed: "The form could not be saved. Please try again in a moment.",
        pcFormSuffix: " (my PC form)", repeatFill: "Filling your saved form from the PC…",
      };
    }
    return {
      pick: "내 PC 엑셀 양식 가져오기", make: "이 양식으로 견적서 만들기",
      save: "내 PC에 저장", chosen: "양식:", needRequest: "견적 내용을 먼저 적어 주세요.",
      made: "견적서를 만들었습니다. 양식이 있던 폴더에 저장해 주세요.",
      choosing: "PC에서 양식을 골라 주세요…", filling: "양식으로 견적서를 만드는 중…",
      saving: "PC에 저장하는 중…", saved: "PC에 저장했습니다.",
      failed: "지금은 되지 않았어요. 잠시 후 다시 시도해 주세요.",
      noPc: "PC를 연결하면 내 양식을 가져올 수 있습니다.", connect: "이 PC 연결",
      entry: "내 PC 엑셀 양식으로 견적서",
      reviewClient: "거래처:", reviewTitle: "양식에 채운 값",
      reviewEmpty: "채운 셀이 없습니다. 요청과 양식을 확인해 주세요.",
      reviewExtend: "양식의 품목 행 서식을 복사해 늘린 행:",
      reviewTotals: "합계·세금은 양식의 수식이 계산합니다. 저장 전에 값과 셀 위치를 확인해 주세요.",
      remember: "이 양식을 내 견적서로 저장", remembering: "양식을 저장하는 중…",
      remembered: "저장했습니다. 다음부터는 견적서 양식 목록에서 고를 수 있습니다.",
      rememberFailed: "양식을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      pcFormSuffix: " (내 PC 양식)", repeatFill: "저장한 양식을 PC에서 다시 읽어 채우는 중…",
    };
  }

  function loadPcExchange() {
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangePromise) return pcExchangePromise;
    pcExchangePromise = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector('link[href="' + PC_EXCHANGE_CSS + '"]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = PC_EXCHANGE_CSS;
        head.append(css);
      }
      const script = document.createElement("script");
      script.src = PC_EXCHANGE_SCRIPT;
      script.addEventListener("load", () => {
        if (window.PadiemPcFileExchange) resolve(window.PadiemPcFileExchange);
        else reject(new Error("pc_exchange_unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("pc_exchange_unavailable")), { once: true });
      head.append(script);
    });
    return pcExchangePromise;
  }

  async function pcLinkedNow() {
    if (window.PadiemAuthGate?.authenticated() === false) return null;
    try {
      const response = await nativeFetch(PC_PAIRINGS_PATH, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } });
      if (!response.ok) return null;
      const body = await response.json().catch(() => null);
      const links = body && Array.isArray(body.links) ? body.links : [];
      return links.some((link) => link && link.state === "active");
    } catch (_) {
      return null;
    }
  }

  function openPcConnect() {
    // #5573 step 1: the PC-request guidance connects through the one connect
    // flow (modal + download + self-closing wait) instead of walking the
    // person into the Connectors dialog. The dialog path stays as the fallback
    // for a page where the connect-flow module did not load.
    const flow = window.PadiemPcConnectFlow;
    if (flow && typeof flow.open === "function") {
      void flow.open();
      return;
    }
    const opener = document.getElementById("connectorsNavButton");
    if (!opener) return;
    opener.click();
    const card = document.getElementById("connectorComputerCard");
    if (!card) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    if (typeof card.focus === "function") card.focus({ preventScroll: true });
    if (typeof card.scrollIntoView === "function") card.scrollIntoView({ block: "nearest" });
  }

  // #5895: pick → fill → save, all through the shared part and the COM2 lane. The
  // screen itself never opens a workbook and never guesses a cell.
  function wirePcForm(nodes) {
    let template = null;
    let filled = null;
    let savedFormId = null;
    const say = (text) => {
      nodes.status.textContent = text || "";
      nodes.status.hidden = !text;
    };
    // #3180: the dialog used to go straight from "the model filled it" to
    // "save to my PC", so the owner never saw which cell received which value.
    // The fill answer already carries the mapping; showing it is the review
    // step, and the check belongs before a file lands on someone's disk.
    const clearReview = () => {
      if (!nodes.review) return;
      nodes.review.replaceChildren();
      nodes.review.hidden = true;
    };
    const renderReview = (body) => {
      const review = nodes.review;
      if (!review) return;
      review.replaceChildren();
      const mapping = body && body.mapping && typeof body.mapping === "object" ? body.mapping : null;
      const rows = [];
      Object.keys(mapping || {}).forEach((sheet) => {
        const cells = mapping[sheet];
        if (!cells || typeof cells !== "object") return;
        Object.keys(cells).forEach((address) => {
          const raw = cells[address];
          const text = typeof raw === "number" ? String(raw)
            : String(raw === null || raw === undefined ? "" : raw);
          rows.push(String(sheet) + "!" + String(address) + " ← "
            + (text.length > 60 ? text.slice(0, 60) + "…" : text));
        });
      });
      if (body && body.client) {
        review.append(el("p", "b66-quote-pcform-review-lead",
          pcCopy().reviewClient + " " + String(body.client)));
      }
      if (!rows.length) {
        review.append(el("p", "b66-quote-pcform-review-empty", pcCopy().reviewEmpty));
        review.hidden = false;
        return;
      }
      review.append(el("p", "b66-quote-pcform-review-title", pcCopy().reviewTitle));
      const list = document.createElement("ul");
      list.className = "b66-quote-pcform-review-list";
      rows.forEach((text) => list.appendChild(el("li", "", text)));
      review.append(list);
      const extend = Array.isArray(body && body.extend) ? body.extend : [];
      if (extend.length) {
        const added = extend.reduce((sum, item) => {
          const count = item && Number(item.count) > 0 ? Math.floor(Number(item.count)) : 0;
          return sum + count;
        }, 0);
        review.append(el("p", "b66-quote-pcform-review-extend",
          pcCopy().reviewExtend + " " + String(added)));
      }
      review.append(el("p", "b66-quote-pcform-review-note", pcCopy().reviewTotals));
      review.hidden = false;
    };
    const text = (key) => window.__padiemLocale?.text?.(key) || key;
    const roleKeys = ["item", "quantity", "unit_price", "amount", "subtotal", "tax", "total", "date", "recipient"];
    let selection = 0;
    async function reviewTemplate(picked, generation) {
      say(text("quote-map-loading"));
      nodes.make.hidden = true;
      nodes.mapping.replaceChildren();
      nodes.mapping.hidden = false;
      try {
        const res = await readJson("/api/b66/pc-quote/forms", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_id: picked.fileId, name: (picked.name || "Form").replace(/\.xlsx$/i, "") || "Form", analyze_only: true }),
        });
        if (generation !== selection) return;
        if (!res.response.ok || !res.data?.analysis || !res.data?.structure) throw new Error("analysis");
        const {analysis, structure} = res.data;
        const missing = roleKeys.filter((role) => !(analysis[role]?.candidates || []).length);
        let ai = {};
        if (missing.length) {
          const tier = window.PadiemTierSelection?.get?.() || "free";
          const prompt = "Find the cell addresses for these roles only: " + JSON.stringify(missing) +
            ". Return JSON object mapping each role to {sheet,cell}; omit unknown roles. Workbook: " + JSON.stringify(structure);
          try {
            const reply = await nativeFetch("/api/chat", { method:"POST", credentials:"same-origin",
              headers:{"Content-Type":"application/json"}, body:JSON.stringify({messages:[{role:"user",content:prompt}],tier}) });
            const json = await reply.json();
            const answer = String(json?.answer || "");
            const begin = answer.indexOf("{"), end = answer.lastIndexOf("}");
            if (reply.ok && begin >= 0 && end > begin) ai = JSON.parse(answer.slice(begin, end + 1));
          } catch (_) { ai = {}; }
        }
        if (generation !== selection) return;
        const heading = el("h4", "", text("quote-map-title"));
        nodes.mapping.append(heading);
        if (structure.truncated) nodes.mapping.append(el("p", "", text("quote-map-truncated")));
        const mapping = {};
        const resolved = new Set();
        const names = new Set((structure.sheets || []).map((sheet) => sheet.name));
        roleKeys.forEach((role) => {
          const item = analysis[role] || {candidates:[], requires_confirmation:true};
          const candidates = Array.isArray(item.candidates) ? item.candidates : [];
          const proposed = candidates[0] || ai[role];
          const safe = proposed && names.has(proposed.sheet) && /^[A-Z]{1,3}[1-9][0-9]*$/.test(proposed.cell);
          const line = el("div", "b66-quote-map-row");
          const label = text("quote-map-" + role);
          if (!item.requires_confirmation && safe && !structure.truncated) {
            mapping[role] = {sheet:proposed.sheet, cell:proposed.cell};
            resolved.add(role);
            line.append(el("span", "", "✓ " + label + " · " + proposed.sheet + "!" + proposed.cell));
          } else {
            line.append(el("p", "", text("quote-map-confirm").replace("{role}", label)));
            const sheet = document.createElement("select");
            sheet.setAttribute("aria-label", label + " " + text("quote-map-sheet"));
            (structure.sheets || []).forEach((entry) => {
              const option = document.createElement("option");
              option.value = entry.name; option.textContent = entry.name; sheet.append(option);
            });
            if (safe) sheet.value = proposed.sheet;
            const address = document.createElement("input");
            address.setAttribute("aria-label", label + " " + text("quote-map-cell"));
            address.value = safe ? proposed.cell : "";
            const yes = el("button", "", text("quote-map-yes")); yes.type = "button";
            const other = el("button", "", text("quote-map-other")); other.type = "button";
            const none = el("button", "", text("quote-map-none")); none.type = "button";
            const status = el("span", "", "");
            yes.addEventListener("click", () => {
              if (!names.has(sheet.value) || !/^[A-Z]{1,3}[1-9][0-9]*$/.test(address.value.trim())) {
                status.textContent = text("quote-map-choose"); return;
              }
              mapping[role] = {sheet:sheet.value, cell:address.value.trim()};
              resolved.add(role);
              status.textContent = "✓";
            });
            none.addEventListener("click", () => { delete mapping[role]; resolved.add(role); status.textContent = text("quote-map-none"); });
            other.addEventListener("click", () => { delete mapping[role]; resolved.delete(role); status.textContent = ""; address.focus(); });
            address.addEventListener("input", () => { delete mapping[role]; resolved.delete(role); status.textContent = ""; });
            sheet.addEventListener("change", () => { delete mapping[role]; resolved.delete(role); status.textContent = ""; });
            line.append(sheet, address, yes, other, none, status);
          }
          nodes.mapping.append(line);
        });
        const save = el("button", "", text("quote-map-save")); save.type = "button";
        save.addEventListener("click", async () => {
          if (roleKeys.some((role) => !resolved.has(role)) || !Object.keys(mapping).length) { say(text("quote-map-choose")); return; }
          save.disabled = true;
          try {
            const result = await readJson("/api/b66/pc-quote/forms", {
              method:"POST", headers:{"Content-Type":"application/json"},
              body:JSON.stringify({file_id:picked.fileId, name:(picked.name || "Form").replace(/\.xlsx$/i, "") || "Form", mapping}),
            });
            if (!result.response.ok || !result.data?.form?.saved_skill_id) throw new Error("save");
            if (generation !== selection) return;
            savedFormId = result.data.form.saved_skill_id;
            nodes.mapping.hidden = true;
            nodes.make.hidden = false;
            say("");
            void refresh();
          } catch (_) { say(text("quote-map-failed")); }
          finally { save.disabled = false; }
        });
        nodes.mapping.append(save);
        say("");
      } catch (_) {
        if (generation === selection) say(text("quote-map-failed"));
      }
    }
    nodes.pick.addEventListener("click", async () => {
      say(pcCopy().choosing);
      let component = null;
      try {
        component = await loadPcExchange();
      } catch (_) {
        component = null;
      }
      if (!component || typeof component.open !== "function") {
        say(pcCopy().failed);
        return;
      }
      component.open({
        onSelect: (picked) => {
          if (!picked || typeof picked.fileId !== "string" || !picked.fileId) {
            say(pcCopy().failed);
            return;
          }
          template = {
            name: picked.name || "견적서 양식.xlsx",
            path: String(picked.path || picked.name || ""),
            fileId: picked.fileId,
          };
          filled = null;
          savedFormId = null;
          const generation = ++selection;
          nodes.save.hidden = true;
          nodes.pdf.hidden = true;
          if (nodes.remember) nodes.remember.hidden = true;
          clearReview();
          nodes.chosen.textContent = pcCopy().chosen + " " + template.name;
          nodes.chosen.hidden = false;
          const previous = skills.find((skill) => isPcForm(skill) && skill.form_mapping_confirmed === true
            && String(skill.form_path).replace(/\\/g, "/") === template.path.replace(/\\/g, "/"));
          if (previous) {
            savedFormId = previous.saved_skill_id;
            nodes.mapping.hidden = true;
            nodes.make.hidden = false;
            say("");
          } else {
            nodes.make.hidden = true;
            void reviewTemplate(picked, generation);
          }
        },
      });
    });
    nodes.make.addEventListener("click", async () => {
      if (!template) return;
      const request = String(nodes.request() || "").trim();
      if (!request) {
        say(pcCopy().needRequest);
        return;
      }
      say(pcCopy().filling);
      clearReview();
      try {
        const response = await nativeFetch(PC_QUOTE_FILL_PATH, {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ file_id: template.fileId, request, ...(savedFormId ? {form_id: savedFormId} : {}) }),
        });
        const body = await response.json().catch(() => null);
        if (!response.ok || !body || body.ok !== true || typeof body.filled_file_id !== "string") {
          throw new Error("fill_failed");
        }
        filled = body;
        nodes.save.hidden = false;
        nodes.pdf.hidden = false;
        // #3180 ③: the fill this owner just reviewed can become their saved
        // quote form, so the next quote starts from the list instead of a
        // fresh picker trip.
        if (nodes.remember) nodes.remember.hidden = savedFormId !== null;
        renderReview(body);
        say(pcCopy().made);
      } catch (_) {
        say(pcCopy().failed);
      }
    });
    nodes.pdf.addEventListener("click", async () => {
      if (!filled || !filled.filled_file_id) return;
      nodes.pdf.disabled = true;
      say("PDF를 만드는 중입니다.");
      try {
        const response = await nativeFetch("/api/b66/pc-quote/pdf?file_id=" + encodeURIComponent(filled.filled_file_id), {
          credentials: "same-origin", cache: "no-store",
        });
        if (!response.ok) throw new Error("pdf_unavailable");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = (filled.filled_name || "quote.xlsx").replace(/\.xlsx$/i, "") + ".pdf";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        say("PDF를 내려받았습니다.");
      } catch (_) {
        say("PDF를 만들지 못했습니다. 엑셀 파일을 저장한 뒤 다시 시도해 주세요.");
      } finally {
        nodes.pdf.disabled = false;
      }
    });
    nodes.save.addEventListener("click", async () => {
      if (!filled || !template) return;
      say(pcCopy().saving);
      const folder = template.path.replace(/\\/g, "/").replace(/\/+[^/]*$/, "");
      const target = (folder ? folder + "/" : "") + filled.filled_name;
      try {
        const response = await nativeFetch(PC_SAVE_PATH, {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ file_id: filled.filled_file_id, path: target }),
        });
        const body = await response.json().catch(() => null);
        if (!response.ok || !body || body.ok !== true) throw new Error("save_failed");
        const saved = await waitPcResult(body.dispatch_id);
        say(saved ? pcCopy().saved : pcCopy().failed);
        if (saved) nodes.save.hidden = true;
      } catch (_) {
        say(pcCopy().failed);
      }
    });
    async function waitPcResult(dispatchId) {
      for (;;) {
        let response = null;
        let body = null;
        try {
          response = await nativeFetch(PC_RESULT_PATH + "?dispatch_id=" + encodeURIComponent(dispatchId), {
            credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" },
          });
          body = await response.json().catch(() => null);
        } catch (_) {
          body = null;
        }
        if (body && body.state === "ready") return body.ok === true;
        if (body && body.state === "cancelled") return false;
        if (response && response.status !== 200) return false;
        const seconds = body && Number(body.poll_seconds) > 0 ? Number(body.poll_seconds) : 2;
        await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
      }
    }
    if (nodes.remember) nodes.remember.addEventListener("click", async () => {
      if (!template || typeof template.fileId !== "string" || !template.fileId) return;
      say(pcCopy().remembering);
      try {
        const saved = await readJson("/api/b66/pc-quote/forms", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ file_id: template.fileId, name: template.name.replace(/\.[^.]+$/, "") }),
        });
        if (!saved.response.ok || !saved.data || saved.data.ok !== true) throw new Error("remember_failed");
        nodes.remember.hidden = true;
        say(pcCopy().remembered);
        void refresh();
      } catch (_) {
        say(pcCopy().rememberFailed);
      }
    });
    void pcLinkedNow().then((linked) => {
      if (linked !== false) return;
      nodes.pick.hidden = true;
      nodes.note.textContent = pcCopy().noPc + " ";
      const connect = el("button", "b66-quote-pcform-connect", pcCopy().connect);
      connect.type = "button";
      connect.addEventListener("click", openPcConnect);
      nodes.note.append(connect);
      nodes.note.hidden = false;
    });

    return {
      // A repeat fill already knows its form: no picker, and nothing new to
      // register — the same review list still runs before saving.
      repeatFromSavedForm(skill, fileId, body) {
        savedFormId = skill.saved_skill_id;
        template = {
          name: skill.form_filename || "견적서 양식.xlsx",
          path: skill.form_path, fileId,
        };
        filled = body;
        nodes.chosen.textContent = pcCopy().chosen + " " + template.name;
        nodes.chosen.hidden = false;
        nodes.make.hidden = false;
        nodes.save.hidden = false;
        nodes.pdf.hidden = false;
        if (nodes.remember) nodes.remember.hidden = true;
        renderReview(body);
        say(pcCopy().made);
      },
    };
  }

  function ensureUi() {
    if (initialized) return;
    initialized = true;
    const firstNav = document.querySelector(".side-nav");
    if (!firstNav) return;

    const launcher = el("button", "side-item b66-quote-launcher");
    launcher.id = "b66QuoteNavButton";
    launcher.type = "button";
    launcher.hidden = true;
    launcher.setAttribute("aria-haspopup", "dialog");
    launcher.setAttribute("aria-controls", "b66QuoteDialog");
    launcher.setAttribute("aria-expanded", "false");
    const icon = el("span", "side-icon", "₩");
    icon.setAttribute("aria-hidden", "true");
    const label = el("span", "", copy().launcher);
    label.dataset.b66QuoteLauncherLabel = "true";
    launcher.append(icon, label);
    const claw = document.getElementById("clawNavButton");
    firstNav.insertBefore(launcher, claw || null);

    const dialog = document.createElement("dialog");
    dialog.id = "b66QuoteDialog";
    dialog.className = "b66-quote-dialog";
    dialog.setAttribute("aria-labelledby", "b66QuoteDialogTitle");

    const panel = el("section", "b66-quote-panel");
    const header = el("div", "b66-quote-header");
    const headingWrap = el("div");
    const title = el("h2", "", copy().title);
    title.id = "b66QuoteDialogTitle";
    title.dataset.b66QuoteTitle = "true";
    const description = el("p", "", copy().description);
    description.dataset.b66QuoteDescription = "true";
    headingWrap.append(title, description);
    const close = el("button", "b66-quote-close", "×");
    close.id = "b66QuoteClose";
    close.type = "button";
    close.setAttribute("aria-label", copy().close);
    header.append(headingWrap, close);

    // #4428: opt-in READ-ONLY cross-product PC presence. The server's existing
    // owner/workspace-scoped Broker projection is the only source of ONLINE.
    // No installer URL, pairing challenge, PC action or execution authority.
    const pcSection = el("section", "b66-quote-connect");
    pcSection.hidden = true; // No cross-product exposure until server grant exists.
    const pcToggle = el("button", "b66-quote-connect-toggle", copy().pcToggle);
    pcToggle.id = "b66QuotePcToggle";
    pcToggle.type = "button";
    pcToggle.setAttribute("aria-controls", "b66QuotePcPanel");
    pcToggle.setAttribute("aria-expanded", "false");
    const pcPanel = el("div", "b66-quote-connect-panel");
    pcPanel.id = "b66QuotePcPanel";
    pcPanel.hidden = true;
    const pcHelp = el("p", "b66-quote-connect-help", copy().pcHelp);
    pcHelp.id = "b66QuotePcHelp";
    const pcRefresh = el("button", "b66-quote-connect-refresh", copy().pcRefresh);
    pcRefresh.id = "b66QuotePcRefresh";
    pcRefresh.type = "button";
    const pcStatus = el("p", "b66-quote-connect-status", "");
    pcStatus.id = "b66QuotePcStatus";
    pcStatus.setAttribute("role", "status");
    pcStatus.setAttribute("aria-live", "polite");
    const pcList = el("ul", "b66-quote-connect-list");
    pcList.id = "b66QuotePcList";
    pcPanel.append(pcHelp, pcRefresh, pcStatus, pcList);
    // #4434 follow-up: minimal TXT read request for the verified PC. The
    // browser only names a server-listed conversation, a .txt relative path
    // and a server-listed device; run id, root and approval stay server-side.
    const pcTxt = el("div", "b66-quote-connect-txt");
    pcTxt.id = "b66QuotePcTxt";
    pcTxt.hidden = true;
    const pcTxtTitle = el("p", "b66-quote-connect-txt-title", copy().pcTxtTitle);
    pcTxtTitle.id = "b66QuotePcTxtTitle";
    const pcConversationLabel = el("label", "b66-quote-connect-field");
    const pcConversationText = el("span", "", copy().pcConversation);
    pcConversationText.id = "b66QuotePcConversationLabel";
    const pcConversation = document.createElement("select");
    pcConversation.id = "b66QuotePcConversation";
    pcConversation.disabled = true;
    pcConversationLabel.append(pcConversationText, pcConversation);
    const pcPathLabel = el("label", "b66-quote-connect-field");
    const pcPathText = el("span", "", copy().pcPath);
    pcPathText.id = "b66QuotePcPathLabel";
    const pcPath = document.createElement("input");
    pcPath.id = "b66QuotePcPath";
    pcPath.type = "text";
    pcPath.autocomplete = "off";
    pcPath.maxLength = 256;
    pcPath.placeholder = copy().pcPathPlaceholder;
    pcPathLabel.append(pcPathText, pcPath);
    const pcRequest = el("button", "b66-quote-connect-request", copy().pcRequest);
    pcRequest.id = "b66QuotePcRequest";
    pcRequest.type = "button";
    const pcRunStatus = el("p", "b66-quote-connect-run-status", "");
    pcRunStatus.id = "b66QuotePcRunStatus";
    pcRunStatus.setAttribute("role", "status");
    pcRunStatus.setAttribute("aria-live", "polite");
    pcTxt.append(pcTxtTitle, pcConversationLabel, pcPathLabel, pcRequest, pcRunStatus);
    pcPanel.append(pcTxt);
    pcSection.append(pcToggle, pcPanel);

    const form = el("form", "b66-quote-form");
    form.id = "b66QuoteForm";
    const selectLabel = el("label", "b66-quote-field");
    selectLabel.id = "b66QuoteSkillField";
    const selectText = el("span", "", copy().selectLabel);
    selectText.dataset.b66QuoteSelectLabel = "true";
    const select = document.createElement("select");
    select.id = "b66QuoteSkillSelect";
    selectLabel.append(selectText, select);

    const messageLabel = el("label", "b66-quote-field");
    const messageText = el("span", "", copy().requestLabel);
    messageText.dataset.b66QuoteRequestLabel = "true";
    const message = document.createElement("textarea");
    message.id = "b66QuoteRequest";
    message.rows = 4;
    message.autocomplete = "off";
    message.placeholder = copy().requestPlaceholder;
    messageLabel.append(messageText, message);

    const modelLabel = el("label", "b66-quote-field");
    modelLabel.id = "b66QuoteModelField";
    const modelText = el("span", "", document.documentElement.lang === "en" ? "AI tier" : "AI 등급");
    modelText.dataset.b66QuoteModelLabel = "true";
    const modelSelect = document.createElement("select");
    modelSelect.id = "b66QuoteModelSelect";
    modelSelect.required = true;
    modelLabel.append(modelText, modelSelect);

    // #3906: per-model reasoning level. Options come only from
    // /api/b66/quote/models, so the control never offers a level the selected
    // model does not actually support. The provider default is first.
    const reasoningLabel = el("label", "b66-quote-field");
    reasoningLabel.id = "b66QuoteReasoningField";
    const reasoningText = el("span", "", document.documentElement.lang === "en"
      ? "Reasoning level" : "추론 수준");
    reasoningText.dataset.b66QuoteReasoningLabel = "true";
    const reasoningSelect = document.createElement("select");
    reasoningSelect.id = "b66QuoteReasoningSelect";
    reasoningLabel.append(reasoningText, reasoningSelect);

    // #6100: the logged-out stand-in for the three selects above — one line
    // and the product's own login entry (#loginButton), which the account
    // area already owns. On sign-in the same capability event that runs
    // refresh() brings the selects back; nothing after login changes.
    const signinHint = el("p", "b66-quote-signin-hint", "");
    signinHint.id = "b66QuoteSigninHint";
    signinHint.hidden = true;
    const signinText = el("span", "b66-quote-signin-text", copy().signinHint);
    signinText.dataset.b66QuoteSigninText = "true";
    const signinButton = el("button", "b66-quote-signin-button", copy().signinAction);
    signinButton.id = "b66QuoteSigninButton";
    signinButton.type = "button";
    signinButton.addEventListener("click", () => {
      document.getElementById("loginButton")?.click();
    });
    signinHint.append(signinText, signinButton);

    // #5895: "내 PC 엑셀 양식 가져오기" — the owner's own form, filled as a new quote.
    const pcForm = el("section", "b66-quote-pcform");
    const pcPick = el("button", "b66-quote-pcform-pick", pcCopy().pick);
    pcPick.id = "b66QuotePcPick";
    pcPick.type = "button";
    const pcChosen = el("p", "b66-quote-pcform-chosen", "");
    pcChosen.id = "b66QuotePcChosen";
    pcChosen.hidden = true;
    const pcNote = el("p", "b66-quote-pcform-note", "");
    pcNote.id = "b66QuotePcNote";
    pcNote.hidden = true;
    const pcMake = el("button", "b66-quote-pcform-make", pcCopy().make);
    pcMake.id = "b66QuotePcMake";
    pcMake.type = "button";
    pcMake.hidden = true;
    const pcMapping = el("section", "b66-quote-pcform-mapping");
    pcMapping.id = "b66QuotePcMapping";
    pcMapping.hidden = true;
    const pcReview = el("section", "b66-quote-pcform-review");
    pcReview.id = "b66QuotePcReview";
    pcReview.setAttribute("aria-live", "polite");
    pcReview.hidden = true;
    const pcRemember = el("button", "b66-quote-pcform-remember", pcCopy().remember);
    pcRemember.id = "b66QuotePcRemember";
    pcRemember.type = "button";
    pcRemember.hidden = true;
    const pcSave = el("button", "b66-quote-pcform-save", pcCopy().save);
    pcSave.id = "b66QuotePcSave";
    pcSave.type = "button";
    pcSave.hidden = true;
    const pcPdf = el("button", "b66-quote-pcform-pdf", "PDF 내려받기");
    pcPdf.id = "b66QuotePcPdf";
    pcPdf.type = "button";
    pcPdf.hidden = true;
    const pcFormStatus = el("p", "b66-quote-pcform-status", "");
    pcFormStatus.id = "b66QuotePcFormStatus";
    pcFormStatus.setAttribute("role", "status");
    pcFormStatus.setAttribute("aria-live", "polite");
    pcFormStatus.hidden = true;
    pcForm.append(pcPick, pcChosen, pcNote, pcMapping, pcMake, pcReview, pcRemember, pcSave, pcPdf, pcFormStatus);
    // #5895: the section rides the form's own append below. Calling after() on
    // the still-detached pair was a per-DOM no-op, so the dialog shipped
    // without the PC form its launcher promises.
    pcFormBridge = wirePcForm({
      pick: pcPick, chosen: pcChosen, note: pcNote, make: pcMake, save: pcSave, pdf: pcPdf, mapping: pcMapping,
      review: pcReview, remember: pcRemember, status: pcFormStatus,
      request: () => message.value,
    });

    const submit = el("button", "b66-quote-generate", copy().generate);
    submit.id = "b66QuoteGenerate";
    submit.type = "submit";

    const status = el("p", "b66-quote-status", copy().idle);
    status.id = "b66QuoteStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    // Do not construct a hidden iframe on Chat startup. The cross-origin
    // preview is created only after a successful, user-requested quote.
    form.append(selectLabel, modelLabel, reasoningLabel, signinHint, messageLabel, pcForm, submit, status);
    panel.append(header, pcSection, form);
    dialog.append(panel);
    document.body.append(dialog);

    launcher.addEventListener("click", () => {
      syncCopy();
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      launcher.setAttribute("aria-expanded", "true");
      message.focus();
    });
    close.addEventListener("click", () => closeDialog());
    pcToggle.addEventListener("click", () => {
      if (!pcPanel.hidden) {
        resetPcDirectory();
        return;
      }
      pcPanel.hidden = false;
      pcToggle.setAttribute("aria-expanded", "true");
      void loadPcDirectory();
    });
    pcRefresh.addEventListener("click", () => { void loadPcDirectory(); });
    pcRequest.addEventListener("click", () => { void requestPcTxtRead(); });
    dialog.addEventListener("close", () => {
      launcher.setAttribute("aria-expanded", "false");
      resetPcDirectory();
    });
    dialog.addEventListener("cancel", () => {
      launcher.setAttribute("aria-expanded", "false");
      resetPcDirectory();
    });
    form.addEventListener("submit", generate);
    window.addEventListener("message", receiveEmbedMessage);
  }


  function resetPcDirectory() {
    pcQuerySequence += 1; // discard all in-flight responses after account/visibility changes
    pcTxtSequence += 1; // cancel an in-flight TXT run poll on the same grounds
    const section = document.getElementById("b66QuotePcPanel");
    const toggle = document.getElementById("b66QuotePcToggle");
    const list = document.getElementById("b66QuotePcList");
    const status = document.getElementById("b66QuotePcStatus");
    if (section) section.hidden = true;
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (list) list.replaceChildren();
    if (status) status.textContent = "";
    resetPcTxt();
  }


  function resetPcTxt() {
    pcOnlineDeviceId = "";
    const block = document.getElementById("b66QuotePcTxt");
    const conversation = document.getElementById("b66QuotePcConversation");
    const path = document.getElementById("b66QuotePcPath");
    const runStatus = document.getElementById("b66QuotePcRunStatus");
    if (block) block.hidden = true;
    if (conversation) {
      conversation.replaceChildren();
      conversation.disabled = true;
    }
    if (path) path.value = "";
    if (runStatus) {
      runStatus.textContent = "";
      runStatus.dataset.state = "";
    }
  }


  function validConversationId(value) {
    return typeof value === "string" && /^chat_[0-9a-f]{32}$/.test(value);
  }


  function validTxtPath(value) {
    if (typeof value !== "string") return null;
    const text = value.trim();
    if (!text || text.length > 1024) return null;
    if (text.includes("\x00") || text.includes("\r") || text.includes("\n")) return null;
    if (!text.toLowerCase().endsWith(".txt")) return null;
    return text;
  }


  async function loadPcConversations(current, isCurrent) {
    const c = copy();
    const block = document.getElementById("b66QuotePcTxt");
    const conversation = document.getElementById("b66QuotePcConversation");
    if (!block || !conversation) return false;
    conversation.replaceChildren();
    conversation.disabled = true;
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = c.pcConversationPlaceholder;
    conversation.append(placeholder);
    let response;
    try {
      response = await nativeFetch(PC_DIALOGUES_PATH, {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }
      });
    } catch (_) {
      if (!isCurrent()) return false;
      const runStatus = document.getElementById("b66QuotePcRunStatus");
      if (runStatus) runStatus.textContent = c.pcConversationEmpty;
      block.hidden = false;
      return false;
    }
    if (!isCurrent()) return false;
    if (response.status === 401 || response.status === 403) {
      const runStatus = document.getElementById("b66QuotePcRunStatus");
      if (runStatus) runStatus.textContent = c.pcAuth;
      block.hidden = false;
      return false;
    }
    let data = null;
    try {
      const raw = await response.text();
      data = JSON.parse(raw);
    } catch (_) {
      data = null;
    }
    if (!isCurrent()) return false;
    const items = data && data.ok === true && Array.isArray(data.conversations)
      ? data.conversations : null;
    if (!items) {
      const runStatus = document.getElementById("b66QuotePcRunStatus");
      if (runStatus) runStatus.textContent = c.pcConversationEmpty;
      block.hidden = false;
      return false;
    }
    let usable = 0;
    for (const item of items.slice(0, 20)) {
      if (!item || typeof item !== "object") continue;
      if (!validConversationId(item.conversation_id)) continue;
      const option = document.createElement("option");
      option.value = item.conversation_id;
      // textContent only: titles are untrusted owner data, never HTML.
      const title = typeof item.title === "string" && item.title.trim()
        ? item.title.trim().slice(0, 80) : item.conversation_id;
      option.textContent = title;
      conversation.append(option);
      usable += 1;
    }
    if (!usable) {
      const runStatus = document.getElementById("b66QuotePcRunStatus");
      if (runStatus) runStatus.textContent = c.pcConversationEmpty;
    }
    conversation.disabled = usable === 0;
    block.hidden = false;
    return usable > 0;
  }


  function setRunStatus(text, state) {
    const node = document.getElementById("b66QuotePcRunStatus");
    if (!node) return;
    node.textContent = text;
    node.dataset.state = state || "";
    // #5453: the sweep only rides a state the run is really in.
    node.classList?.toggle?.("padiem-activity-sweep", state === "working");
  }


  async function requestPcTxtRead() {
    const c = copy();
    const current = ++pcTxtSequence;
    const isCurrent = () => current === pcTxtSequence &&
      !document.getElementById("b66QuotePcTxt").hidden;
    const conversation = document.getElementById("b66QuotePcConversation");
    const path = document.getElementById("b66QuotePcPath");
    const requestButton = document.getElementById("b66QuotePcRequest");
    if (!conversation || !path || !requestButton) return;
    const conversationId = conversation.value;
    const pathRelative = validTxtPath(path.value);
    if (!validConversationId(conversationId) || !pathRelative) {
      setRunStatus(c.pcInvalid, "error");
      return;
    }
    requestButton.disabled = true;
    setRunStatus(c.pcRunPending, "working");
    const payload = { conversation_id: conversationId, path_relative: pathRelative };
    const deviceId = pcOnlineDeviceId;
    if (deviceId.length > 0 && deviceId.length <= 128) {
      payload.device_id = deviceId;
    }
    let response = null;
    let data = null;
    try {
      response = await nativeFetch(PC_TXT_READ_PATH, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const raw = await response.text();
      data = JSON.parse(raw);
    } catch (_) {
      data = null;
    }
    if (!isCurrent()) return;
    if (!response || !response.ok || !data || data.ok !== true ||
        typeof data.run_id !== "string" || !/^run_[A-Za-z0-9]{12,80}$/.test(data.run_id)) {
      requestButton.disabled = false;
      if (response && (response.status === 401 || response.status === 403)) {
        setRunStatus(c.pcAuth, "error");
      } else if (response && response.status === 404) {
        setRunStatus(c.pcConversationGone, "error");
      } else if (response && (response.status === 422 || response.status === 400)) {
        setRunStatus(c.pcInvalid, "error");
      } else {
        setRunStatus(c.pcRequestFailed, "error");
      }
      return;
    }
    await pollPcRunResult(data.run_id, isCurrent);
    if (isCurrent()) requestButton.disabled = false;
  }


  async function pollPcRunResult(runId, isCurrent) {
    const c = copy();
    const url = PC_RESULT_PATH_PREFIX + encodeURIComponent(runId) + PC_RESULT_PATH_SUFFIX;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (attempt > 0) await new Promise((resolve) => window.setTimeout(resolve, 3000));
      if (!isCurrent()) return;
      let response = null;
      let data = null;
      try {
        response = await nativeFetch(url, {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "Accept": "application/json", "Content-Type": "application/json" },
          body: "{}"
        });
        const raw = await response.text();
        data = JSON.parse(raw);
      } catch (_) {
        data = null;
      }
      if (!isCurrent()) return;
      if (response && (response.status === 401 || response.status === 403)) {
        setRunStatus(c.pcAuth, "error");
        return;
      }
      if (response && response.ok && data && data.ok === true) {
        if (data.status === "completed") {
          setRunStatus(c.pcRunDone, "ready");
          return;
        }
        if (data.status === "failed") {
          setRunStatus(c.pcRunFailed + (typeof data.reason === "string" && data.reason
            ? " (" + data.reason.slice(0, 120) + ")" : ""), "error");
          return;
        }
        setRunStatus(c.pcRunPending, "working");
        continue;
      }
      if (response && (response.status === 404 || response.status === 409)) {
        setRunStatus(c.pcRunFailed, "error");
        return;
      }
      // 503 and transport failures stay inside the bounded poll budget;
      // anything terminal above already returned.
      if (!isCurrent()) return;
      setRunStatus(c.pcRunPending, "working");
    }
    if (isCurrent()) setRunStatus(c.pcRunFailed, "error");
  }

  async function loadPcDirectory() {
    const section = document.getElementById("b66QuotePcPanel");
    const list = document.getElementById("b66QuotePcList");
    const status = document.getElementById("b66QuotePcStatus");
    if (!section || section.hidden || !list || !status) return;
    const current = ++pcQuerySequence;
    const isCurrent = () => current === pcQuerySequence && !section.hidden;
    const c = copy();
    list.replaceChildren();
    status.textContent = c.pcLoading;
    const derive = window.PadiemClawLocalHandoff?.deriveDeviceDirectory;
    if (typeof derive !== "function") {
      status.textContent = c.pcUnavailable;
      return;
    }
    try {
      const response = await nativeFetch(PC_DIRECTORY_PATH, {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!isCurrent()) return;
      if (response.status === 401 || response.status === 403) {
        status.textContent = c.pcAuth;
        return;
      }
      if (response.status === 404 || response.status === 501 ||
          response.status === 503) {
        status.textContent = c.pcUnavailable;
        return;
      }
      if (!response.ok) {
        status.textContent = c.pcFailed;
        return;
      }
      // Parse the whole response and reuse the existing closed, read-only Claw
      // projection, never render raw server HTML/credentials or invent ONLINE.
      const raw = await response.text();
      if (!isCurrent()) return;
      const payload = JSON.parse(raw);
      if (!payload || payload.ok !== true || payload.available !== true ||
          payload.ownerScoped !== true) {
        status.textContent = c.pcUnavailable;
        return;
      }
      const directory = derive(payload, null);
      if (!directory || directory.available !== true) {
        status.textContent = c.pcFailed;
        return;
      }
      status.textContent = directory.devices.length ? c.pcReady : c.pcEmpty;
      for (const device of directory.devices) {
        const item = el("li", "b66-quote-connect-item");
        const name = el("strong", "", device.deviceName || device.deviceId);
        const stateKey = device.revoked ? "pcRevoked" :
          device.online ? "pcOnline" : "pcOffline";
        const state = el("span", "b66-quote-connect-state", c[stateKey]);
        state.dataset.state = device.online ? "online" : "offline";
        item.append(name, state);
        list.append(item);
      }
      // The TXT request names only a server-listed, usable device. No device
      // means no request surface: the panel stays status-only.
      const usable = directory.devices.find((device) => device && device.online === true &&
        device.revoked !== true && typeof device.deviceId === "string" &&
        device.deviceId.length > 0 && device.deviceId.length <= 128);
      pcOnlineDeviceId = usable ? usable.deviceId : "";
      if (directory.devices.length > 0) {
        await loadPcConversations(current, isCurrent);
      } else {
        resetPcTxt();
      }
    } catch (_) {
      if (!isCurrent()) return;
      list.replaceChildren();
      status.textContent = c.pcFailed;
    }
  }

  function closeDialog() {
    const dialog = document.getElementById("b66QuoteDialog");
    const launcher = document.getElementById("b66QuoteNavButton");
    if (!dialog) return;
    resetPcDirectory();
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
    if (launcher) launcher.setAttribute("aria-expanded", "false");
  }

  function syncCopy() {
    const c = copy();
    const map = [
      ["[data-b66-quote-launcher-label]", "launcher"],
      ["[data-b66-quote-title]", "title"],
      ["[data-b66-quote-description]", "description"],
      ["[data-b66-quote-select-label]", "selectLabel"],
      ["[data-b66-quote-signin-text]", "signinHint"],
      ["[data-b66-quote-request-label]", "requestLabel"]
    ];
    map.forEach(([selector, key]) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = c[key];
    });
    const message = document.getElementById("b66QuoteRequest");
    const submit = document.getElementById("b66QuoteGenerate");
    const close = document.getElementById("b66QuoteClose");
    const frame = document.getElementById("b66QuoteFrame");
    const entryOnly = skills.length === 0 && pcAccountLinked;
    const launcherLabel = document.querySelector('[data-b66-quote-launcher-label="true"]');
    if (launcherLabel && entryOnly) launcherLabel.textContent = pcCopy().entry;
    if (message) message.placeholder = c.requestPlaceholder;
    if (submit) submit.textContent = c.generate;
    const signinButton = document.getElementById("b66QuoteSigninButton");
    if (signinButton) signinButton.textContent = c.signinAction;
    if (close) close.setAttribute("aria-label", c.close);
    if (frame) frame.title = c.title;
    const pcToggle = document.getElementById("b66QuotePcToggle");
    const pcHelp = document.getElementById("b66QuotePcHelp");
    const pcRefresh = document.getElementById("b66QuotePcRefresh");
    if (pcToggle) pcToggle.textContent = c.pcToggle;
    if (pcHelp) pcHelp.textContent = c.pcHelp;
    if (pcRefresh) pcRefresh.textContent = c.pcRefresh;
    const pcTxtTitle = document.getElementById("b66QuotePcTxtTitle");
    const pcConversationText = document.getElementById("b66QuotePcConversationLabel");
    const pcPathText = document.getElementById("b66QuotePcPathLabel");
    const pcPath = document.getElementById("b66QuotePcPath");
    const pcRequest = document.getElementById("b66QuotePcRequest");
    if (pcTxtTitle) pcTxtTitle.textContent = c.pcTxtTitle;
    if (pcConversationText) pcConversationText.textContent = c.pcConversation;
    if (pcPathText) pcPathText.textContent = c.pcPath;
    if (pcPath) pcPath.placeholder = c.pcPathPlaceholder;
    if (pcRequest) pcRequest.textContent = c.pcRequest;
  }

  function setStatus(text, state) {
    const node = document.getElementById("b66QuoteStatus");
    if (!node) return;
    node.textContent = text;
    node.dataset.state = state || "";
    // #5453: the sweep only rides a state the run is really in.
    node.classList?.toggle?.("padiem-activity-sweep", state === "working");
  }

  async function refreshModels() {
    const select = document.getElementById("b66QuoteModelSelect");
    if (!select) return;
    modelIds = [];
    selectedModelByTier = {};
    reasoningByModel = {};
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = document.documentElement.lang === "en"
      ? "Select a model" : "\uBAA8\uB378\uC744 \uC120\uD0DD\uD558\uC138\uC694";
    select.append(placeholder);
    select.disabled = true;
    const response = await readJson("/api/b66/quote/models");
    if (!response.response.ok || !response.data || !Array.isArray(response.data.tiers)) return;
    const safe = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
    const grades = new Set(["free", "plus", "pro", "max"]);
    response.data.tiers.forEach((record) => {
      if (!record || !grades.has(record.tier) || modelIds.includes(record.tier) ||
          typeof record.model_id !== "string" || !safe.test(record.model_id) ||
          typeof record.name !== "string") return;
      const option = document.createElement("option");
      option.value = record.tier;
      option.textContent = record.name;
      select.append(option);
      modelIds.push(record.tier);
      selectedModelByTier[record.tier] = record.model_id;
      reasoningByModel[record.tier] = Array.isArray(record.reasoning_levels)
        ? record.reasoning_levels.filter((level) => level &&
            typeof level.value === "string" &&
            /^[a-z0-9-]{1,32}$/.test(level.value) &&
            typeof level.label === "string")
        : [];
    });
    const configured = response.data.default_tier;
    select.value = typeof configured === "string" && modelIds.includes(configured)
      ? configured : "";
    select.disabled = modelIds.length === 0;
    syncReasoningOptions();
    select.addEventListener("change", syncReasoningOptions);
  }

  // #3906: only levels the selected model actually supports are offered, and a
  // model switch re-validates the current choice so an unsupported level can
  // never be submitted. No recommended level is auto-applied.
  function reasoningOptionsForModel(modelId) {
    if (typeof modelId !== "string" || !modelIds.includes(modelId)) return [];
    const levels = reasoningByModel[modelId];
    if (!Array.isArray(levels) || !levels.length) return [];
    return levels;
  }

  function syncReasoningOptions() {
    const modelSelect = document.getElementById("b66QuoteModelSelect");
    const reasoningSelect = document.getElementById("b66QuoteReasoningSelect");
    if (!modelSelect || !reasoningSelect) return;
    const options = reasoningOptionsForModel(modelSelect.value);
    reasoningSelect.replaceChildren();
    options.forEach((level) => {
      const option = document.createElement("option");
      option.value = level.value;
      option.textContent = level.label;
      reasoningSelect.append(option);
    });
    reasoningSelect.value = options.length ? options[0].value : "";
    reasoningSelect.disabled = options.length === 0;
  }

  // #3906: the reasoning choice actually offered for this exact model, or ""
  // when the control has none so the request keeps its pre-#3906 shape.
  function selectedReasoningLevel(modelId) {
    const reasoningSelect = document.getElementById("b66QuoteReasoningSelect");
    if (!reasoningSelect) return "";
    const options = reasoningOptionsForModel(modelId);
    const current = reasoningSelect.value;
    return options.some((level) => level.value === current) ? current : "";
  }

  function populateSkills() {
    const select = document.getElementById("b66QuoteSkillSelect");
    const launcher = document.getElementById("b66QuoteNavButton");
    const pcSection = document.querySelector(".b66-quote-connect");
    if (!select || !launcher) return;
    select.replaceChildren();
    skills.forEach((skill) => {
      const option = document.createElement("option");
      option.value = skill.saved_skill_id;
      option.textContent = skill.skill_name + (isPcForm(skill) ? pcCopy().pcFormSuffix : "");
      select.append(option);
    });
    // #5895: a linked PC is enough to reach the quote screen; the form itself is the
    // template, so the saved-skill controls only exist when a skill does.
    const entryOnly = skills.length === 0 && pcAccountLinked;
    launcher.hidden = !(runtime && (skills.length > 0 || pcAccountLinked));
    launcher.disabled = launcher.hidden;
    const launcherLabel = launcher.querySelector('[data-b66-quote-launcher-label="true"]');
    if (launcherLabel) launcherLabel.textContent = entryOnly ? pcCopy().entry : copy().launcher;
    const selectLabelNode = document.querySelector('[data-b66-quote-select-label]');
    if (selectLabelNode) selectLabelNode.hidden = entryOnly;
    const generateButton = document.getElementById("b66QuoteGenerate");
    if (generateButton) generateButton.hidden = entryOnly;
    // #6100: logged out, the selects hide and the one-line hint stands in;
    // signed in, the fields come back exactly as before (the entry-only span
    // hiding above is untouched). The capability event flips signedIn, so a
    // login lands here through the same refresh() that fills the selects.
    const signinHint = document.getElementById("b66QuoteSigninHint");
    const quoteFields = [
      document.getElementById("b66QuoteSkillField"),
      document.getElementById("b66QuoteModelField"),
      document.getElementById("b66QuoteReasoningField"),
    ];
    if (!signedIn) {
      quoteFields.forEach((field) => { if (field) field.hidden = true; });
      if (signinHint) signinHint.hidden = false;
    } else {
      quoteFields.forEach((field) => { if (field) field.hidden = false; });
      if (signinHint) signinHint.hidden = true;
    }
    launcher.setAttribute("aria-disabled", launcher.hidden ? "true" : "false");
    const pcEnabled = !launcher.hidden && runtime?.pcDirectoryEnabled === true;
    if (pcSection) pcSection.hidden = !pcEnabled;
    if (!pcEnabled) resetPcDirectory();
    if (launcher.hidden) closeDialog();
  }

  async function readJson(url, options) {
    const response = await nativeFetch(url, Object.assign({
      headers: { "Accept": "application/json" },
      cache: "no-store"
    }, options || {}));
    const data = await response.json().catch(() => null);
    return { response, data };
  }

  function declaredAssetRefs(skill) {
    const template = skill && typeof skill === "object" ? skill.internalTemplate : null;
    const content = template && typeof template === "object" ? template.content : null;
    const slots = content && typeof content === "object" ? content.slots : null;
    const refs = {};
    ["logo", "stamp"].forEach((key) => {
      const value = slots && typeof slots[key] === "string" ? slots[key] : "";
      if (value && !B66_ASSET_ID.test(value)) throw new Error("invalid_private_asset_ref");
      if (value) refs[key] = value;
    });
    return refs;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const parts = [];
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
      let binary = "";
      for (let i = 0; i < chunk.length; i += 1) binary += String.fromCharCode(chunk[i]);
      parts.push(binary);
    }
    return window.btoa(parts.join(""));
  }

  async function readPrivateAsset(assetId) {
    if (!B66_ASSET_ID.test(assetId || "")) throw new Error("invalid_private_asset_ref");
    const response = await nativeFetch("/api/b66/assets/" + encodeURIComponent(assetId), {
      method: "GET",
      headers: { "Accept": "image/png,image/jpeg,image/webp" },
      cache: "no-store",
      credentials: "same-origin"
    });
    if (!response.ok) throw new Error("private_asset_unavailable");
    const mediaType = String(response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
    if (!PRIVATE_ASSET_MEDIA.has(mediaType)) throw new Error("private_asset_media_invalid");
    const rawLength = Number(response.headers.get("content-length") || "0");
    if (Number.isFinite(rawLength) && rawLength > MAX_PRIVATE_ASSET_BYTES) {
      throw new Error("private_asset_too_large");
    }
    const buffer = await response.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > MAX_PRIVATE_ASSET_BYTES) {
      throw new Error("private_asset_too_large");
    }
    return {
      assetId,
      dataUrl: "data:" + mediaType + ";base64," + arrayBufferToBase64(buffer)
    };
  }

  async function loadPrivateAssets(skill) {
    const refs = declaredAssetRefs(skill);
    const assets = {};
    for (const key of ["logo", "stamp"]) {
      if (refs[key]) assets[key] = await readPrivateAsset(refs[key]);
    }
    return assets;
  }

  async function refreshPcAccount() {
    const linked = await pcLinkedNow();
    const next = linked === true;
    if (next === pcAccountLinked) return;
    pcAccountLinked = next;
    populateSkills();
  }

  async function refresh() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      ensureUi();
      try {
        const configResult = await readJson("/api/b66/runtime-config");
        if (!configResult.response.ok) {
          runtime = null;
          skills = [];
          populateSkills();
          return false;
        }
        runtime = validRuntime(configResult.data);
        if (!runtime) {
          skills = [];
          populateSkills();
          return false;
        }
        const listResult = await readJson("/api/b66/saved-skills?limit=20");
        if (!listResult.response.ok) {
          skills = [];
          populateSkills();
          return false;
        }
        skills = safeSkills(listResult.data);
        populateSkills();
        void refreshPcAccount();
        await refreshModels();
        return skills.length > 0;
      } catch (_) {
        runtime = null;
        skills = [];
        populateSkills();
        return false;
      }
    })().finally(() => { refreshPromise = null; });
    return refreshPromise;
  }

  function requestId() {
    return "b66-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  function ensurePreviewFrame() {
    let frame = document.getElementById("b66QuoteFrame");
    if (frame) return frame;
    const panel = document.querySelector("#b66QuoteDialog .b66-quote-panel");
    if (!panel) throw new Error("preview_panel_missing");
    frame = document.createElement("iframe");
    frame.id = "b66QuoteFrame";
    frame.className = "b66-quote-frame";
    frame.hidden = true;
    frame.title = copy().title;
    frame.referrerPolicy = "no-referrer";
    // Retain the actual B66 embed origin for authenticated postMessage
    // verification. validRuntime() rejects same-origin embeds above.
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-modals");
    panel.append(frame);
    return frame;
  }

  function waitForFrame(frame, url) {
    if (frameLoadedUrl === url && frame.contentWindow) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("embed_timeout")), 10000);
      frame.addEventListener("load", () => {
        window.clearTimeout(timer);
        frameLoadedUrl = url;
        resolve();
      }, { once: true });
      frame.src = url;
    });
  }

  // One finished PC file read, polled to its staged result. The same
  // `/api/pc/fetch` + `/api/pc/result` pair the PC menu already uses; no new PC
  // authority, and the bytes only ever travel for this one fill.
  async function waitForPcFile(dispatchId) {
    for (;;) {
      let response = null;
      let body = null;
      try {
        const result = await readJson("/api/pc/result?dispatch_id=" + encodeURIComponent(dispatchId));
        response = result.response;
        body = result.data;
      } catch (_) {
        body = null;
      }
      if (body && body.state === "ready") return body.ok === true ? dispatchId : null;
      if (body && body.state === "cancelled") return null;
      if (response && response.status !== 200) return null;
      const seconds = body && Number(body.poll_seconds) > 0 ? Number(body.poll_seconds) : 2;
      await new Promise((resolve) => window.setTimeout(resolve, seconds * 1000));
    }
  }

  async function fillFromSavedForm(skill, requestText) {
    setStatus(pcCopy().repeatFill, "working");
    const fetched = await readJson("/api/pc/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ path: skill.form_path }),
    });
    if (!fetched.response.ok || !fetched.data || fetched.data.ok !== true
        || typeof fetched.data.dispatch_id !== "string") {
      throw new Error("pc_fetch_failed");
    }
    const fileId = await waitForPcFile(fetched.data.dispatch_id);
    if (!fileId) throw new Error("pc_fetch_failed");
    const filled = await readJson("/api/b66/pc-quote/fill", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ file_id: fileId, request: requestText, form_id: skill.saved_skill_id }),
    });
    if (!filled.response.ok || !filled.data || filled.data.ok !== true
        || typeof filled.data.filled_file_id !== "string") {
      throw new Error("fill_failed");
    }
    if (!pcFormBridge || typeof pcFormBridge.repeatFromSavedForm !== "function") {
      throw new Error("pc_form_missing");
    }
    pcFormBridge.repeatFromSavedForm(skill, fileId, filled.data);
    setStatus(pcCopy().made, "ready");
  }

  async function generate(event) {
    event.preventDefault();
    const c = copy();
    const select = document.getElementById("b66QuoteSkillSelect");
    const message = document.getElementById("b66QuoteRequest");
    const submit = document.getElementById("b66QuoteGenerate");
    const existingFrame = document.getElementById("b66QuoteFrame");
    if (!runtime || !select || !message || !submit) return;
    const savedSkillId = select.value;
    const modelSelect = document.getElementById("b66QuoteModelSelect");
    const selectedTier = modelSelect && modelSelect.value;
    const modelId = selectedModelByTier[selectedTier];
    const requestText = message.value.trim();
    const savedSkill = skillById(savedSkillId);
    if (isPcForm(savedSkill)) {
      // #3180 ③: a saved PC form is not interpreted through the model at all;
      // the PC's own workbook is re-read and filled in the lane.
      if (!requestText) {
        setStatus(c.failed, "error");
        return;
      }
      submit.disabled = true;
      try {
        await fillFromSavedForm(savedSkill, requestText);
      } catch (_) {
        setStatus(c.failed, "error");
      } finally {
        submit.disabled = false;
      }
      return;
    }
    if (!/^b66skill_[0-9a-f]{32}$/.test(savedSkillId) || !requestText ||
        !modelId || !modelIds.includes(selectedTier)) {
      setStatus(c.failed, "error");
      return;
    }

    submit.disabled = true;
    if (existingFrame) existingFrame.hidden = true;
    setStatus(c.working, "working");
    try {
      // #3906: forward the explicit reasoning choice with the exact model. The
      // field is omitted when the control offers none, preserving the
      // pre-#3906 request shape.
      const payload = { saved_skill_id: savedSkillId, message: requestText, tier: selectedTier, model_id: modelId };
      const reasoningLevel = selectedReasoningLevel(selectedTier);
      if (reasoningLevel) payload.reasoning_level = reasoningLevel;
      const interpreted = await readJson("/api/b66/quote/interpret", {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!interpreted.response.ok || !interpreted.data || interpreted.data.ok !== true) {
        throw new Error("interpret_failed");
      }
      const candidate = interpreted.data.candidate;
      if (!candidate || !Array.isArray(candidate.missing)) throw new Error("candidate_invalid");
      if (candidate.missing.length > 0) {
        setStatus(c.missing, "missing");
        return;
      }

      const detail = await readJson("/api/b66/saved-skills/" + encodeURIComponent(savedSkillId));
      const skill = detail.data && detail.data.saved_skill && detail.data.saved_skill.skill;
      if (!detail.response.ok || !skill || typeof skill !== "object") throw new Error("skill_unavailable");

      const profileResult = companyProfileForRender(interpreted.data.company_profile);
      if (!profileResult.ok) {
        setStatus(
          profileResult.code === "missing_company" ? c.companyIdentityMissing : c.companyDefaultsMissing,
          "missing"
        );
        return;
      }
      const assets = await loadPrivateAssets(skill);

      const frame = ensurePreviewFrame();
      await waitForFrame(frame, runtime.embedUrl);
      const id = requestId();
      currentRequestId = id;
      frame.contentWindow.postMessage({
        type: "b66.embed.render.v1",
        requestId: id,
        skill,
        candidate,
        assets,
        companyProfile: profileResult.profile
      }, runtime.origin);
    } catch (_) {
      currentRequestId = null;
      setStatus(c.failed, "error");
    } finally {
      submit.disabled = false;
    }
  }

  function receiveEmbedMessage(event) {
    if (!runtime) return;
    const frame = document.getElementById("b66QuoteFrame");
    if (!frame || event.source !== frame.contentWindow || event.origin !== runtime.origin) return;
    const data = event.data;
    if (!data || typeof data !== "object" || data.requestId !== currentRequestId) return;
    if (data.type === "b66.embed.rendered.v1" && data.ok === true) {
      currentRequestId = null;
      frame.hidden = false;
      setStatus(copy().ready, "ready");
      return;
    }
    if (data.type === "b66.embed.error.v1") {
      currentRequestId = null;
      frame.hidden = true;
      setStatus(copy().failed, "error");
    }
  }

  window.addEventListener("padiem:capabilitychange", (event) => {
    const auth = event && event.detail && event.detail.auth;
    // #6100: the event fires at startup too (after /api/auth/status), so the
    // logged-out hint is decided by the product's own signal, never guessed.
    signedIn = !!(auth && auth.authenticated === true);
    if (signedIn) refresh();
    else {
      resetPcDirectory();
      runtime = null;
      skills = [];
      ensureUi();
      populateSkills();
    }
  });
  for (const eventName of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
    window.addEventListener(eventName, resetPcDirectory);
  }
  window.addEventListener("padiem:localechange", syncCopy);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      ensureUi();
    }, { once: true });
  } else {
    ensureUi();
  }
})();