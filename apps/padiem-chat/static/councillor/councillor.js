/*
 * #5786 의원 시네마틱 블로그 래퍼 렌더러.
 *
 * 이 파일이 하는 일은 두 개뿐입니다.
 *   1) ./brands/<id>.json 의 공개 브랜딩 설정을 이 문서의 기존 노드에 그립니다.
 *   2) GET /api/auth/status 서버 응답으로 관리자 진입 링크의 표시 여부만 결정.
 * 생성·저장·다운로드·로그인·모델 경로는 하나도 구현하지 않습니다. 전부 기존
 * PADIEM Chat(/index.html, /api/chat, /api/projects, /auth/*)이 소유합니다.
 */
(() => {
  "use strict";

  const BRAND_ID_RE = /^[a-z0-9][a-z0-9-]{1,31}$/;
  const DEFAULT_BRAND = "miraen";
  const STATUS_ENDPOINT = "../api/auth/status";
  const CHAT_ROOT = "../";
  // 의원3종은 기존 util 화면의 소유입니다. 프래그먼트는 그 화면으로 가는
  // 목적지 표식이고, 실제로 화면을 여는 쪽은 util-menu.js 입니다.
  const TOOLS = Object.freeze([
    Object.freeze({ tool: "speech", href: CHAT_ROOT + "#padiem-util/speech", title: "축사·인사말", note: "기존 축사 작성 화면에서 생성·편집·저장·다운로드를 그대로 사용합니다." }),
    Object.freeze({ tool: "sns", href: CHAT_ROOT + "#padiem-util/sns", title: "SNS 홍보", note: "기존 블로그·Facebook·Instagram 작성 화면과 사진 기능을 그대로 사용합니다." }),
    Object.freeze({ tool: "meeting", href: CHAT_ROOT + "#padiem-util/meeting", title: "회의정리·활동집", note: "기존 회의정리 작성·저장·아카이브 화면을 그대로 사용합니다." }),
  ]);

  const refs = {};
  let brand = null;

  function id(name) { return document.getElementById(name); }
  function collectRefs() {
    [
      "brandMark", "brandName", "stageBadge", "motionToggle", "adminTopLink",
      "cineHero", "cineFilm", "cinePoster", "cineVideo", "heroEyebrow", "heroName",
      "heroLead", "heroMediaNote", "heroCue", "profileFacts", "profileBio",
      "activitySource", "activityFeed", "mediaSource", "mediaCards", "notesFeed",
      "snsSource", "snsChips", "adminStatus", "adminGate", "adminGateBody",
      "adminSignIn", "adminTools", "adminNote", "toolCards",
      "footerPrototype", "footerSource",
    ].forEach((k) => { refs[k] = id(k); });
  }

  function text(node, value) {
    if (!node) return;
    node.textContent = value === null || value === undefined ? "" : String(value);
  }

  // 설정 파일은 사람이 편집하는 자료지만, 링크만은 프로토콜을 확인합니다.
  // javascript: / data: URI 가 href 로 들어오면 링크를 만들지 않습니다.
  function safeHref(raw) {
    const value = String(raw || "").trim();
    if (!value) return null;
    let parsed = null;
    try { parsed = new URL(value, document.baseURI); } catch (_) { return null; }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    return parsed.href;
  }

  function setLink(node, raw) {
    const href = safeHref(raw);
    if (!node) return;
    if (href) node.setAttribute("href", href);
    else node.removeAttribute("href");
  }

  // ── motion ───────────────────────────────────────────────────────────
  // 표현 설정은 URL 상태만 사용합니다. PADIEM Chat의 browser-persistence privacy
  // 계약(theme/locale)과 같은 근거로 localStorage·sessionStorage 에 쓰지 않습니다.
  function motionParam() {
    try {
      const value = new URLSearchParams(window.location.search).get("motion");
      if (value === "off" || value === "on") return value;
    } catch (_) { /* 쿼리 해석 실패는 OS 설정으로 */ }
    return null;
  }

  function readMotionPreference() {
    const explicit = motionParam();
    if (explicit) return explicit;
    const prefersReduced = window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    return prefersReduced ? "off" : "on";
  }

  function writeMotionPreference(mode) {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("motion", mode);
      window.history.replaceState(window.history.state, "",
        window.location.pathname + "?" + params.toString() + (window.location.hash || ""));
    } catch (_) { /* replaceState 미지원 브라우저는 이번 화면 세션에서만 적용 */ }
  }

  function applyMotion(mode) {
    document.documentElement.setAttribute("data-cine-motion", mode);
    if (refs.motionToggle) {
      const off = mode === "off";
      refs.motionToggle.setAttribute("aria-pressed", off ? "true" : "false");
      text(refs.motionToggle, off ? "움직임 켜기" : "움직임 줄이기");
    }
    if (mode === "off") pauseHeroVideo();
    else void playHeroVideo();
  }

  function wireMotion() {
    applyMotion(readMotionPreference());
    if (refs.motionToggle) {
      refs.motionToggle.addEventListener("click", () => {
        const next = document.documentElement.getAttribute("data-cine-motion") === "off" ? "on" : "off";
        writeMotionPreference(next);
        applyMotion(next);
      });
    }
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      const onChange = () => { if (!motionParam()) applyMotion(mq.matches ? "off" : "on"); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }
  }

  // ── scroll reveal ────────────────────────────────────────────────────
  function wireScroll() {
    if (refs.heroCue) {
      refs.heroCue.addEventListener("click", () => {
        const target = id("sectionProfile");
        if (target) target.scrollIntoView({
          behavior: document.documentElement.getAttribute("data-cine-motion") === "off" ? "auto" : "smooth",
          block: "start",
        });
      });
    }
    const sections = Array.prototype.slice.call(document.querySelectorAll(".cine-section"));
    if (!("IntersectionObserver" in window)
      || document.documentElement.getAttribute("data-cine-motion") === "off") {
      sections.forEach((s) => s.classList.add("is-in"));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.08 });
    sections.forEach((s) => observer.observe(s));
  }

  // ── hero media ───────────────────────────────────────────────────────
  function pauseHeroVideo() {
    if (!refs.cineVideo) return;
    refs.cineVideo.hidden = true;
    try { refs.cineVideo.pause(); } catch (_) {}
  }

  // autoplay 거부는 정상 경로입니다. 포스터(또는 CSS 필름 레이어)로 넘어갑니다.
  function playHeroVideo() {
    const video = refs.cineVideo;
    if (!video) return;
    if (document.documentElement.getAttribute("data-cine-motion") === "off") return;
    if (!hasUsableVideoSource()) { showHeroFallback(); return; }
    video.hidden = false;
    const attempt = video.play();
    if (attempt && typeof attempt.catch === "function") {
      attempt.catch(() => showHeroFallback());
    }
  }

  function hasUsableVideoSource() {
    const video = refs.cineVideo;
    return !!(video && video.querySelector("source") && video.getAttribute("data-has-source") === "1");
  }

  function showHeroFallback() {
    pauseHeroVideo();
    if (refs.cinePoster && refs.cinePoster.getAttribute("data-has-src") === "1") {
      refs.cinePoster.hidden = false;
      return;
    }
  }

  function paintHero() {
    const hero = (brand && brand.hero) || {};
    text(refs.heroEyebrow, hero.eyebrow || brand && brand.kicker || "");
    text(refs.heroName, brand && brand.name ? brand.name : "");
    text(refs.heroLead, hero.lead || (brand && brand.lead) || "");

    const mediaKind = String(hero.mediaKind || "PLACEHOLDER").toUpperCase();
    const video = refs.cineVideo;
    if (video) {
      video.removeAttribute("data-has-source");
      video.replaceChildren();
      video.addEventListener("error", showHeroFallback);
      // 시네마틱 원본은 동일 출처 정적 파일만 허용합니다(CSP media 기본 'self').
      (Array.isArray(hero.videoSources) ? hero.videoSources : []).forEach((src) => {
        const value = String(src || "").trim();
        if (!/^\.\?\/[A-Za-z0-9._/-]+$|^\/[A-Za-z0-9._/-]+$/.test(value)) return;
        const node = document.createElement("source");
        node.setAttribute("src", value);
        video.appendChild(node);
      });
      if (video.querySelector("source")) video.setAttribute("data-has-source", "1");
    }
    if (refs.cinePoster) {
      const poster = String(hero.poster || "").trim();
      if (/^\.\?\/[A-Za-z0-9._/-]+$|^\/[A-Za-z0-9._/-]+$/.test(poster)) {
        refs.cinePoster.setAttribute("src", poster);
        refs.cinePoster.setAttribute("alt", hero.posterAlt || "");
        refs.cinePoster.setAttribute("data-has-src", "1");
        refs.cinePoster.hidden = true;
      } else {
        refs.cinePoster.removeAttribute("data-has-src");
        refs.cinePoster.hidden = true;
      }
    }
    text(refs.heroMediaNote, mediaKind === "CONFIRMED"
      ? (hero.credit || "")
      : "시제품 화면 · 실제 의원 영상·사진 미확보. 이 배경은 임시 자료이며 의원 자료로 표시하지 않습니다.");
  }

  // ── sections ─────────────────────────────────────────────────────────
  function emptyTo(node, message) {
    if (!node) return;
    const li = document.createElement("li");
    li.className = "cine-empty";
    li.textContent = message;
    node.appendChild(li);
  }

  function paintProfile() {
    if (refs.profileFacts) {
      refs.profileFacts.replaceChildren();
      (Array.isArray(brand.profile) ? brand.profile : []).forEach((fact) => {
        const wrap = document.createElement("div");
        wrap.className = "cine-fact";
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = fact && fact.label ? String(fact.label) : "";
        dd.textContent = fact && fact.value ? String(fact.value) : "";
        wrap.append(dt, dd);
        refs.profileFacts.appendChild(wrap);
      });
      if (!refs.profileFacts.children.length) {
        const li = document.createElement("div");
        li.className = "cine-empty";
        li.textContent = "확인된 프로필 자료가 없습니다.";
        refs.profileFacts.appendChild(li);
      }
    }
    text(refs.profileBio, brand.bio || "");
  }

  function paintActivity() {
    text(refs.activitySource, brand.activity && brand.activity.source ? brand.activity.source : "");
    const feed = refs.activityFeed;
    if (!feed) return;
    feed.replaceChildren();
    const items = (brand.activity && Array.isArray(brand.activity.items)) ? brand.activity.items : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cine-feed-item";
      const meta = document.createElement("p");
      meta.className = "cine-feed-meta";
      meta.textContent = [item.date, item.tag].filter(Boolean).map(String).join(" · ");
      const titleNode = document.createElement(item.url ? "a" : "span");
      titleNode.className = "cine-feed-link";
      titleNode.textContent = String(item.title || "");
      if (item.url) {
        const href = safeHref(item.url);
        if (href) {
          titleNode.setAttribute("href", href);
          titleNode.setAttribute("target", "_blank");
          titleNode.setAttribute("rel", "noopener noreferrer");
        }
      }
      li.append(meta, titleNode);
      if (item.body) {
        const p = document.createElement("p");
        p.className = "cine-feed-body";
        p.textContent = String(item.body);
        li.appendChild(p);
      }
      feed.appendChild(li);
    });
    if (!items.length) emptyTo(feed, "공개된 최근 소식이 아직 연결되지 않았습니다.");
  }

  function paintMedia() {
    text(refs.mediaSource, brand.media && brand.media.source ? brand.media.source : "");
    const cards = refs.mediaCards;
    if (!cards) return;
    cards.replaceChildren();
    const items = (brand.media && Array.isArray(brand.media.items)) ? brand.media.items : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cine-card";
      const kind = document.createElement("p");
      kind.className = "cine-card-kind";
      kind.textContent = String(item.kind || "LINK");
      const titleNode = document.createElement("p");
      titleNode.className = "cine-card-title";
      const href = safeHref(item.url);
      if (href && item.url) {
        const a = document.createElement("a");
        a.setAttribute("href", href);
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
        a.textContent = String(item.title || "");
        titleNode.appendChild(a);
      } else {
        titleNode.classList.add("cine-card-unlinked");
        titleNode.textContent = String(item.title || "");
      }
      li.append(kind, titleNode);
      (Array.isArray(item.notes) ? item.notes : []).forEach((note) => {
        const p = document.createElement("p");
        p.className = "cine-card-note";
        p.textContent = String(note);
        li.appendChild(p);
      });
      cards.appendChild(li);
    });
    if (!items.length) emptyTo(cards, "링크 가능한 공식 자료가 없습니다.");
  }

  function paintNotes() {
    const feed = refs.notesFeed;
    if (!feed) return;
    feed.replaceChildren();
    const items = Array.isArray(brand.notes) ? brand.notes : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cine-feed-item";
      const meta = document.createElement("p");
      meta.className = "cine-feed-meta";
      meta.textContent = String(item.date || "");
      const titleNode = document.createElement("span");
      titleNode.className = "cine-feed-link";
      titleNode.textContent = String(item.title || "");
      const body = document.createElement("p");
      body.className = "cine-feed-body";
      body.textContent = String(item.body || "");
      li.append(meta, titleNode, body);
      feed.appendChild(li);
    });
    if (!items.length) emptyTo(feed, "공개 글·공지가 없습니다.");
  }

  function paintSns() {
    text(refs.snsSource, brand.sns && brand.sns.source ? brand.sns.source : "");
    const chips = refs.snsChips;
    if (!chips) return;
    chips.replaceChildren();
    const items = (brand.sns && Array.isArray(brand.sns.channels)) ? brand.sns.channels : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      const href = safeHref(item.url);
      const label = document.createElement(item.confirmed && href ? "a" : "span");
      label.className = "cine-chip";
      if (item.confirmed && href) {
        label.setAttribute("href", href);
        label.setAttribute("target", "_blank");
        label.setAttribute("rel", "noopener noreferrer");
      } else {
        label.style.opacity = ".62";
      }
      const name = document.createElement("span");
      name.textContent = String(item.label || "");
      label.appendChild(name);
      if (!item.confirmed) {
        const flag = document.createElement("span");
        flag.className = "cine-chip-flag";
        flag.textContent = "운영 확인 필요";
        label.appendChild(flag);
      }
      li.appendChild(label);
      chips.appendChild(li);
    });
    if (!items.length) emptyTo(chips, "확인된 공식 채널이 없습니다.");
  }

  function paintChrome() {
    text(refs.brandName, brand.pageTitle || (brand.name ? brand.name + " 의원" : "Padiem"));
    text(refs.brandMark, (brand.mark || (brand.name || "P").slice(0, 1)));
    document.title = refs.brandName.textContent || "의원 시네마틱 블로그";
    text(refs.stageBadge, brand.stage || "시제품");
    text(refs.footerPrototype, brand.prototypeNotice || "");
    text(refs.footerSource, brand.sourceNotice || "");
    setLink(refs.adminTopLink, CHAT_ROOT);
    setLink(refs.adminSignIn, CHAT_ROOT);
  }

  // ── admin surface (fail-closed) ──────────────────────────────────────
  function paintAdminSignedOut(reason) {
    if (refs.adminGate) refs.adminGate.hidden = false;
    if (refs.adminTools) refs.adminTools.hidden = true;
    text(refs.adminGateBody, reason === "unavailable"
      ? "세션 상태를 확인할 수 없습니다. PADIEM Chat에서 로그인한 뒤 다시 열어 주십시오."
      : "의정3종 작성 화면은 로그인 세션에서만 열립니다. 공개 방문자에게는 관리자 메뉴가 표시되지 않습니다.");
    text(refs.adminStatus, "확인된 세션: 없음");
  }

  function paintAdminSignedIn(name) {
    if (refs.adminGate) refs.adminGate.hidden = true;
    if (refs.adminTools) refs.adminTools.hidden = false;
    text(refs.adminStatus, "확인된 세션: " + (name || "로그인됨"));
    text(refs.adminNote, "아래 진입로는 기존 PADIEM 화면을 그대로 엽니다. 이 블로그는 화면을 복제하지 않습니다.");
    const cards = refs.toolCards;
    if (!cards) return;
    cards.replaceChildren();
    TOOLS.forEach((tool) => {
      const li = document.createElement("li");
      li.className = "cine-card";
      const kind = document.createElement("p");
      kind.className = "cine-card-kind";
      kind.textContent = "PADIEM 의정3종";
      const titleNode = document.createElement("p");
      titleNode.className = "cine-card-title";
      const a = document.createElement("a");
      a.setAttribute("href", tool.href);
      a.textContent = tool.title;
      titleNode.appendChild(a);
      const note = document.createElement("p");
      note.className = "cine-card-note";
      note.textContent = tool.note;
      li.append(kind, titleNode, note);
      cards.appendChild(li);
    });
  }

  async function readSession() {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(STATUS_ENDPOINT, { credentials: "include", signal: controller.signal });
      if (!res.ok) { paintAdminSignedOut("unavailable"); return; }
      const data = await res.json();
      if (data && data.authenticated === true) {
        const user = data.user || {};
        paintAdminSignedIn(user.name || user.display_name || user.email || null);
      } else {
        paintAdminSignedOut("guest");
      }
    } catch (_) {
      paintAdminSignedOut("unavailable");
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function loadBrand() {
    let requested = DEFAULT_BRAND;
    try {
      const param = new URLSearchParams(window.location.search).get("brand");
      if (param && BRAND_ID_RE.test(param)) requested = param;
    } catch (_) { /* 쿼리 해석 실패는 기본 브랜드로 계속 */ }
    const res = await fetch("./brands/" + requested + ".json", { cache: "no-store" });
    if (!res.ok) throw new Error("brand " + requested + " -> HTTP " + res.status);
    return res.json();
  }

  function fail(message) {
    const main = id("councillorMain");
    if (!main) return;
    const p = document.createElement("p");
    p.className = "cine-error";
    p.textContent = "블로그 자료를 불러오지 못했습니다. " + message;
    main.prepend(p);
  }

  async function start() {
    collectRefs();
    wireMotion();
    try {
      brand = await loadBrand();
    } catch (error) {
      text(refs.heroName, "임미란");
      fail(error && error.message ? error.message : String(error));
      void readSession();
      return;
    }
    paintChrome();
    paintHero();
    paintProfile();
    paintActivity();
    paintMedia();
    paintNotes();
    paintSns();
    paintAdminSignedOut("guest");
    wireScroll();
    void readSession();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    void start();
  }
})();
