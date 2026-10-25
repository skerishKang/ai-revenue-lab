/*
 * #5786 의원 시네마틱 블로그 래퍼 렌더러.
 *
 * 이 파일이 하는 일은 두 개뿐입니다.
 *   1) ./brands/<id>.json 의 공개 브랜딩 설정을 이 문서의 기존 노드에 그립니다.
 *   2) GET /api/auth/status 서버 응답으로 하단 관리 경로의 열림 여부만 결정합니다.
 * 생성·저장·다운로드·로그인·모델 경로는 구현하지 않습니다. 전부 기존 PADIEM Chat이
 * 소유합니다(/api/chat, /api/projects, /auth/*, util-menu.js).
 */
(() => {
  "use strict";

  const BRAND_ID_RE = /^[a-z0-9][a-z0-9-]{1,31}$/;
  const DEFAULT_BRAND = "miraen";
  const STATUS_ENDPOINT = "../api/auth/status";
  const CHAT_ROOT = "../";
  // 미디어는 R2 공개 도메인만 받습니다. 브랜딩 파일은 사람이 편집하는 자료이므로
  // 임의 URL을 그대로 <video>/<img> 에 넣지 않습니다.
  const MEDIA_HOSTS = Object.freeze(["media.padiem.net"]);
  // 의원3종은 기존 util 화면의 소유입니다. 프래그먼트는 목적지 표식이고,
  // 실제로 화면을 여는 쪽은 util-menu.js 입니다.
  const TOOLS = Object.freeze([
    Object.freeze({ tool: "speech", href: CHAT_ROOT + "#padiem-util/speech", title: "축사·인사말" }),
    Object.freeze({ tool: "sns", href: CHAT_ROOT + "#padiem-util/sns", title: "SNS 홍보" }),
    Object.freeze({ tool: "meeting", href: CHAT_ROOT + "#padiem-util/meeting", title: "회의정리·활동집" }),
  ]);
  const PLACEHOLDER_NOTE = "이 화면은 시제품입니다. 대표 영상과 사진은 확보되는 대로 이 자리에 표시됩니다.";
  // 테마는 Chat이 이미 쓰는 값 두 개만 사용합니다(기본 Light, 선택 Dark).
  const THEMES = Object.freeze(["light", "dark"]);
  const DEFAULT_THEME = "light";
  const THEME_COLOR = Object.freeze({ light: "#f8f8fb", dark: "#131417" });

  const refs = {};
  let brand = null;

  function id(name) { return document.getElementById(name); }

  function collectRefs() {
    [
      "brandMark", "brandName", "stageBadge", "themeToggle", "motionToggle", "adminTopLink",
      "cineHero", "cinePoster", "cineVideo", "heroEyebrow", "heroName", "heroLead",
      "heroFacts", "heroMediaNote", "heroCue", "profileFacts", "profileBio",
      "activitySource", "activityFeed", "featureVideo", "featureKind", "featureTitle",
      "featureNote", "mediaTiles", "mediaLinks", "mediaSource", "notesFeed", "snsSource", "snsChips",
      "adminStatus", "adminGate", "adminGateBody", "adminSignIn", "adminTools",
      "adminNote", "toolCards", "footerPrototype", "footerSource",
    ].forEach((key) => { refs[key] = id(key); });
  }

  function text(node, value) {
    if (!node) return;
    node.textContent = value === null || value === undefined ? "" : String(value);
  }

  // 스크립트 실행이나 데이터 삽입을 유발하는 주소는 링크로 만들지 않습니다.
  function safeHref(raw) {
    const value = String(raw || "").trim();
    if (!value) return null;
    let parsed = null;
    try { parsed = new URL(value, document.baseURI); } catch (_) { return null; }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    return parsed.href;
  }

  function link(node, raw) {
    const href = safeHref(raw);
    if (!node) return;
    if (href) node.setAttribute("href", href);
    else node.removeAttribute("href");
  }

  // 동일 출처 상대 경로, 또는 허용된 R2 호스트의 https 주소만 미디어로 받습니다.
  function mediaUrl(raw) {
    const value = String(raw || "").trim();
    if (!value) return null;
    if (/^(?:\.?\/)[A-Za-z0-9._/-]+$/.test(value)) return value;
    let parsed = null;
    try { parsed = new URL(value); } catch (_) { return null; }
    if (parsed.protocol !== "https:") return null;
    return MEDIA_HOSTS.indexOf(parsed.hostname) === -1 ? null : parsed.href;
  }

  function attachMedia(node, rawSources) {
    if (!node) return false;
    node.removeAttribute("data-has-source");
    node.replaceChildren();
    const sources = Array.isArray(rawSources) ? rawSources : [rawSources];
    let attached = false;
    sources.forEach((raw) => {
      const src = mediaUrl(raw);
      if (!src) return;
      if (node.tagName === "VIDEO") {
        const source = document.createElement("source");
        source.setAttribute("src", src);
        node.appendChild(source);
      } else {
        node.setAttribute("src", src);
      }
      attached = true;
    });
    if (attached) node.setAttribute("data-has-source", "1");
    return attached;
  }

  // ── motion ──────────────────────────────────────────────────────────
  // 표현 설정은 URL 상태만 사용합니다. theme/locale과 같은 근거로 브라우저
  // 저장소에는 어떤 값도 남기지 않습니다.
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

  function motionOff() {
    return document.documentElement.getAttribute("data-cine-motion") === "off";
  }

  function applyMotion(mode) {
    document.documentElement.setAttribute("data-cine-motion", mode);
    if (refs.motionToggle) {
      const off = mode === "off";
      refs.motionToggle.setAttribute("aria-pressed", off ? "true" : "false");
      text(refs.motionToggle, off ? "움직임 켜기" : "움직임 줄이기");
    }
    if (mode === "off") pauseHeroVideo();
    else playHeroVideo();
  }

  function wireMotion() {
    applyMotion(readMotionPreference());
    if (refs.motionToggle) {
      refs.motionToggle.addEventListener("click", () => {
        const next = motionOff() ? "on" : "off";
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

  // ── theme ────────────────────────────────────────────────────────────
  // 부팅 시 ?theme= 없음은 councillor-theme-default.js 가 light 로 채우고
  // theme-init.js 가 해석합니다. 여기서는 그 결과를 다시 로드 없이 뒤집기만 합니다
  // — 스크롤 위치·재생 중인 영상·콘텐츠가 초기화되지 않습니다.
  function currentTheme() {
    const value = document.documentElement.getAttribute("data-theme");
    return THEMES.indexOf(value) === -1 ? DEFAULT_THEME : value;
  }

  function writeTheme(next) {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("theme", next);
      window.history.replaceState(window.history.state, "",
        window.location.pathname + "?" + params.toString() + (window.location.hash || ""));
    } catch (_) { /* URL 갱신 실패는 이번 화면 세션에서만 반영 */ }
  }

  function applyTheme(next) {
    document.documentElement.setAttribute("data-theme", next);
    const scheme = document.querySelector('meta[name="color-scheme"]');
    if (scheme) scheme.setAttribute("content", next === "dark" ? "dark" : "light dark");
    const accent = document.querySelector('meta[name="theme-color"]');
    if (accent) accent.setAttribute("content", THEME_COLOR[next] || THEME_COLOR[DEFAULT_THEME]);
    if (refs.themeToggle) {
      const dark = next === "dark";
      refs.themeToggle.setAttribute("aria-pressed", dark ? "true" : "false");
      text(refs.themeToggle, dark ? "밝게" : "어둡게");
      refs.themeToggle.setAttribute("aria-label", dark ? "밝은 테마로 전환" : "어두운 테마로 전환");
    }
    writeTheme(next);
  }

  function wireTheme() {
    if (!refs.themeToggle) return;
    applyTheme(currentTheme());
    refs.themeToggle.addEventListener("click", () => {
      applyTheme(currentTheme() === "dark" ? "light" : "dark");
    });
  }

  // ── hero media ───────────────────────────────────────────────────────
  function pauseHeroVideo() {
    const video = refs.cineVideo;
    if (!video) return;
    video.hidden = true;
    try { video.pause(); } catch (_) {}
  }

  function heroHasSource() {
    const video = refs.cineVideo;
    return !!(video && video.getAttribute("data-has-source") === "1");
  }

  // autoplay 거부는 정상 경로입니다. 포스터로, 포스터도 없으면 CSS 필름으로 갑니다.
  function playHeroVideo() {
    const video = refs.cineVideo;
    if (!video || motionOff()) return;
    if (!heroHasSource()) { showHeroFallback(); return; }
    video.hidden = false;
    const attempt = video.play();
    if (attempt && typeof attempt.catch === "function") {
      attempt.catch(() => showHeroFallback());
    }
  }

  function showHeroFallback() {
    pauseHeroVideo();
    const poster = refs.cinePoster;
    if (poster && poster.getAttribute("data-has-source") === "1") poster.hidden = false;
  }

  function paintHero() {
    const hero = (brand && brand.hero) || {};
    text(refs.heroEyebrow, hero.eyebrow || (brand && brand.kicker) || "");
    text(refs.heroName, (brand && brand.name) || "");
    text(refs.heroLead, hero.lead || (brand && brand.lead) || "");

    const poster = refs.cinePoster;
    if (poster) {
      poster.hidden = true;
      poster.removeAttribute("data-has-source");
      if (attachMedia(poster, hero.poster)) {
        poster.setAttribute("alt", hero.posterAlt || "");
      } else {
        poster.removeAttribute("src");
      }
    }
    if (refs.cineVideo) {
      refs.cineVideo.hidden = true;
      attachMedia(refs.cineVideo, hero.videoSources);
      refs.cineVideo.addEventListener("error", showHeroFallback);
    }

    if (refs.heroFacts) {
      refs.heroFacts.replaceChildren();
      (Array.isArray(hero.facts) ? hero.facts : []).forEach((fact) => {
        const wrap = document.createElement("div");
        wrap.className = "cine-hero-fact";
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = String((fact && fact.label) || "");
        dd.textContent = String((fact && fact.value) || "");
        wrap.append(dt, dd);
        refs.heroFacts.appendChild(wrap);
      });
    }

    const mediaKind = String(hero.mediaKind || "PLACEHOLDER").toUpperCase();
    text(refs.heroMediaNote, mediaKind === "CONFIRMED" ? (hero.credit || "") : PLACEHOLDER_NOTE);
    playHeroVideo();
  }

  // ── feature (소개 영상) ──────────────────────────────────────────────
  function paintFeature() {
    const feature = brand.feature || {};
    const node = refs.featureVideo;
    if (!node) return;
    node.hidden = !attachMedia(node, feature.sources);
    if (node.hidden) node.removeAttribute("src");
    text(refs.featureKind, feature.kind || "");
    text(refs.featureTitle, feature.title || "");
    text(refs.featureNote, feature.note || "");
  }

  // ── sections ─────────────────────────────────────────────────────────
  function emptyTo(node, message, itemTag) {
    if (!node) return;
    const item = document.createElement(itemTag || "li");
    item.className = "cine-empty";
    item.textContent = message;
    node.appendChild(item);
  }

  function paintProfile() {
    const facts = refs.profileFacts;
    if (facts) {
      facts.replaceChildren();
      (Array.isArray(brand.profile) ? brand.profile : []).forEach((fact) => {
        const wrap = document.createElement("div");
        wrap.className = "cine-fact";
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = String((fact && fact.label) || "");
        dd.textContent = String((fact && fact.value) || "");
        wrap.append(dt, dd);
        facts.appendChild(wrap);
      });
      if (!facts.children.length) emptyTo(facts, "확인된 프로필 자료가 없습니다.", "div");
    }
    const bio = refs.profileBio;
    if (bio) {
      bio.replaceChildren();
      const paragraphs = String(brand.bio || "").split("\n\n").filter(Boolean);
      paragraphs.forEach((line) => {
        const p = document.createElement("p");
        p.textContent = line;
        bio.appendChild(p);
      });
      if (!paragraphs.length) emptyTo(bio, "소개 자료가 없습니다.", "p");
    }
  }

  function paintActivity() {
    text(refs.activitySource, (brand.activity && brand.activity.source) || "");
    const feed = refs.activityFeed;
    if (!feed) return;
    feed.replaceChildren();
    const items = (brand.activity && Array.isArray(brand.activity.items)) ? brand.activity.items : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cine-timeline-item";
      const date = document.createElement("p");
      date.className = "cine-timeline-date";
      date.textContent = String(item.date || "");
      const body = document.createElement("div");
      if (item.tag) {
        const tag = document.createElement("p");
        tag.className = "cine-timeline-tag";
        tag.textContent = String(item.tag);
        body.appendChild(tag);
      }
      const href = safeHref(item.url);
      const withLink = Boolean(item.url && href);
      const title = document.createElement(withLink ? "a" : "span");
      title.className = "cine-timeline-link" + (withLink ? "" : " is-plain");
      title.textContent = String(item.title || "");
      if (withLink) {
        title.setAttribute("href", href);
        title.setAttribute("target", "_blank");
        title.setAttribute("rel", "noopener noreferrer");
      }
      body.appendChild(title);
      if (item.body) {
        const detail = document.createElement("p");
        detail.className = "cine-timeline-body";
        detail.textContent = String(item.body);
        body.appendChild(detail);
      }
      li.append(date, body);
      feed.appendChild(li);
    });
    if (!items.length) emptyTo(feed, "공개된 최근 소식이 아직 연결되지 않았습니다.");
  }

  function paintMedia() {
    text(refs.mediaSource, (brand.media && brand.media.source) || "");
    const media = brand.media || {};
    const tiles = refs.mediaTiles;
    if (tiles) {
      tiles.replaceChildren();
      (Array.isArray(media.tiles) ? media.tiles : []).forEach((item) => {
        const li = document.createElement("li");
        li.className = "cine-tile";
        const kind = document.createElement("p");
        kind.className = "cine-tile-kind";
        kind.textContent = String(item.kind || "LINK");
        const title = document.createElement("p");
        title.className = "cine-tile-title";
        const href = safeHref(item.url);
        if (item.url && href) {
          const a = document.createElement("a");
          a.setAttribute("href", href);
          a.setAttribute("target", "_blank");
          a.setAttribute("rel", "noopener noreferrer");
          a.textContent = String(item.title || "");
          title.appendChild(a);
        } else {
          title.classList.add("is-unlinked");
          title.textContent = String(item.title || "");
        }
        li.append(kind, title);
        (Array.isArray(item.notes) ? item.notes : []).forEach((note) => {
          const p = document.createElement("p");
          p.className = "cine-tile-note";
          p.textContent = String(note);
          li.appendChild(p);
        });
        tiles.appendChild(li);
      });
      if (!tiles.children.length) emptyTo(tiles, "링크 가능한 공식 자료가 없습니다.");
    }
    // 잔카드를 늘리지 않도록 나머지 공식 기록은 한 개의 목록으로 묶어 그립니다.
    const links = refs.mediaLinks;
    if (links) {
      links.replaceChildren();
      (Array.isArray(media.links) ? media.links : []).forEach((item) => {
        const li = document.createElement("li");
        li.className = "cine-link-row";
        const kind = document.createElement("span");
        kind.className = "cine-link-kind";
        kind.textContent = String(item.kind || "");
        const a = document.createElement("a");
        a.className = "cine-link-title";
        a.textContent = String(item.title || "");
        const href = safeHref(item.url);
        if (href) {
          a.setAttribute("href", href);
          a.setAttribute("target", "_blank");
          a.setAttribute("rel", "noopener noreferrer");
        } else {
          a.classList.add("is-unlinked");
        }
        const arrow = document.createElement("span");
        arrow.className = "cine-link-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "↗";
        li.append(kind, a, arrow);
        links.appendChild(li);
      });
    }
  }

  function paintNotes() {
    const feed = refs.notesFeed;
    if (!feed) return;
    feed.replaceChildren();
    const items = Array.isArray(brand.notes) ? brand.notes : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "cine-note";
      const date = document.createElement("p");
      date.className = "cine-note-date";
      date.textContent = String(item.date || "");
      const title = document.createElement("p");
      title.className = "cine-note-title";
      title.textContent = String(item.title || "");
      const body = document.createElement("p");
      body.className = "cine-note-body";
      body.textContent = String(item.body || "");
      li.append(date, title, body);
      feed.appendChild(li);
    });
    if (!items.length) emptyTo(feed, "알려드릴 사항이 없습니다.");
  }

  function paintSns() {
    text(refs.snsSource, (brand.sns && brand.sns.source) || "");
    const chips = refs.snsChips;
    if (!chips) return;
    chips.replaceChildren();
    const items = (brand.sns && Array.isArray(brand.sns.channels)) ? brand.sns.channels : [];
    items.forEach((item) => {
      const li = document.createElement("li");
      const href = safeHref(item.url);
      const withLink = Boolean(item.confirmed && href);
      const chip = document.createElement(withLink ? "a" : "span");
      chip.className = "cine-chip" + (withLink ? "" : " is-unverified");
      if (withLink) {
        chip.setAttribute("href", href);
        chip.setAttribute("target", "_blank");
        chip.setAttribute("rel", "noopener noreferrer");
      }
      const name = document.createElement("span");
      name.textContent = String(item.label || "");
      chip.appendChild(name);
      if (!item.confirmed) {
        const flag = document.createElement("span");
        flag.className = "cine-chip-flag";
        flag.textContent = "운영 확인 필요";
        chip.appendChild(flag);
      }
      li.appendChild(chip);
      chips.appendChild(li);
    });
    if (!items.length) emptyTo(chips, "확인된 공식 채널이 없습니다.");
  }

  function paintChrome() {
    text(refs.brandName, brand.pageTitle || (brand.name ? brand.name + " 의원" : "Padiem"));
    text(refs.brandMark, brand.mark || ((brand.name || "P").slice(0, 1)));
    document.title = refs.brandName.textContent || "의원 시네마틱 블로그";
    text(refs.stageBadge, brand.stage || "시제품");
    text(refs.footerPrototype, brand.prototypeNotice || "");
    text(refs.footerSource, brand.sourceNotice || "");
    link(refs.adminTopLink, CHAT_ROOT);
    link(refs.adminSignIn, CHAT_ROOT);
  }

  // ── scroll ──────────────────────────────────────────────────────────
  function wireScroll() {
    const topbar = document.querySelector(".councillor-topbar");
    const onScroll = () => {
      if (topbar) topbar.classList.toggle("is-anchored", window.scrollY > 24);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    if (refs.heroCue) {
      refs.heroCue.addEventListener("click", () => {
        const target = id("sectionProfile");
        if (target) target.scrollIntoView({ behavior: motionOff() ? "auto" : "smooth", block: "start" });
      });
    }
    const sections = Array.prototype.slice.call(document.querySelectorAll(".cine-section"));
    if (!("IntersectionObserver" in window) || motionOff()) {
      sections.forEach((section) => section.classList.add("is-in"));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-in");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.06 });
    sections.forEach((section) => observer.observe(section));
  }

  // ── 관리 경로 (fail-closed) ──────────────────────────────────────────
  // The three existing PADIEM utility views are public navigation.
  // Server-side generation and durable storage permissions remain authoritative.
  function paintUtilLinks(name) {
    if (refs.adminGate) refs.adminGate.hidden = true;
    if (refs.adminTools) refs.adminTools.hidden = false;
    text(refs.adminStatus, name ? "의정3종 · " + name : "의정3종");
    text(refs.adminNote, "축사·인사말, SNS 홍보, 회의정리·활동집 바로가기");
    const list = refs.toolCards;
    if (!list) return;
    list.replaceChildren();
    TOOLS.forEach((tool) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.setAttribute("href", tool.href);
      a.textContent = tool.title;
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  async function readSession() {
    // Authentication is used only for optional display personalization.
    // A network failure must not hide public navigation.
    try {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 10000);
      try {
        const res = await fetch(STATUS_ENDPOINT, { credentials: "include", signal: controller.signal });
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.authenticated === true) {
          const user = data.user || {};
          paintUtilLinks(user.name || user.display_name || user.email || null);
        }
      } finally {
        window.clearTimeout(timer);
      }
    } catch (_) { /* public utility navigation remains available */ }
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
    // 방문자에게는 안내만, 진단 값은 개발자 콘솔로 보냅니다(이슈에서 관리).
    const main = id("councillorMain");
    if (!main) return;
    const p = document.createElement("p");
    p.className = "cine-error";
    p.textContent = "표시할 자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
    main.prepend(p);
    if (window.console && window.console.error) window.console.error("[5786]", message);
  }

  async function start() {
    collectRefs();
    wireTheme();
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
    paintFeature();
    paintProfile();
    paintActivity();
    paintMedia();
    paintNotes();
    paintSns();
    paintUtilLinks(null);
    wireScroll();
    void readSession();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    void start();
  }
})();
