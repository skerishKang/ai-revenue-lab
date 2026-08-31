(() => {
  "use strict";
  const labels = {
    ko: {
      "new-chat": "새 채팅", "search": "검색", "projects": "프로젝트", "saved": "저장한 답변", "recent": "추천 질문",
      "easy": "AI를 쉽게 설명해줘", "trip": "제주도 여행 계획", "dinner": "저녁 메뉴 추천", "close-menu": "메뉴 닫기", "open-menu": "메뉴 열기",
      "mode": "기본 대화", "theme": "테마", "light": "Light", "dark": "Dark", "cinematic": "Cinematic", "home-theme": "Padiem Home",
      "home-link": "Padiem Home", "settings": "설정", "settings-kicker": "PADIEM CHAT", "appearance": "APPEARANCE", "language": "LANGUAGE", "language-choice": "언어", "done": "완료",
      "korean": "한국어", "english": "English", "login": "로그인", "hello": "안녕하세요.", "ask": "무엇을 도와드릴까요?",
      "copy": "궁금한 것을 평소 말하듯 편하게 물어보세요.", "easy-title": "쉽게 설명해줘", "easy-copy": "어려운 내용도 쉬운 말로",
      "life-title": "생활 도움", "life-copy": "일상 질문과 계획 세우기", "document-title": "문서와 대화", "document-copy": "TXT·Markdown·CSV·JSON",
      "input": "무엇이든 물어보세요", "file": "파일", "web": "웹 검색", "research": "심층 리서치",
      "note": "사진과 TXT·Markdown·CSV·JSON 문서 한 개를 첨부할 수 있습니다. PDF·Office 문서는 아직 지원하지 않습니다.", "footer": "편하게 질문해 보세요"
    },
    en: {
      "new-chat": "New chat", "search": "Search", "projects": "Projects", "saved": "Saved answers", "recent": "Suggested questions",
      "easy": "Explain AI simply", "trip": "Plan a Jeju trip", "dinner": "Suggest dinner", "close-menu": "Close menu", "open-menu": "Open menu",
      "mode": "Standard chat", "theme": "Theme", "light": "Light", "dark": "Dark", "cinematic": "Cinematic", "home-theme": "Padiem Home",
      "home-link": "Padiem Home", "settings": "Settings", "settings-kicker": "PADIEM CHAT", "appearance": "APPEARANCE", "language": "LANGUAGE", "language-choice": "Language", "done": "Done",
      "korean": "한국어", "english": "English", "login": "Log in", "hello": "Hello.", "ask": "What can I help you with?",
      "copy": "Ask anything in your own words.", "easy-title": "Explain simply", "easy-copy": "Make difficult ideas easy",
      "life-title": "Everyday help", "life-copy": "Questions and planning", "document-title": "Chat with documents", "document-copy": "TXT · Markdown · CSV · JSON",
      "input": "Ask anything", "file": "File", "web": "Web search", "research": "Deep research",
      "note": "Attach one photo or TXT, Markdown, CSV, or JSON document. PDF and Office files are not supported yet.", "footer": "Ask comfortably"
    }
  };
  const text = (key, lang) => labels[lang][key] || labels.ko[key] || key;
  const setText = (selector, key, lang) => { const element = document.querySelector(selector); if (element) element.textContent = text(key, lang); };
  function apply(lang) {
    lang = lang === "en" ? "en" : "ko";
    document.documentElement.lang = lang;
    const map = [
      ["#newChatButton span:last-child", "new-chat"], [".side-item:nth-child(1) span:nth-child(2)", "search"], ["#projectsNavButton span:nth-child(2)", "projects"],
      ["#outputsNavButton span:nth-child(2)", "saved"], ["#recentTitle", "recent"], [".recent-item:nth-of-type(1)", "easy"], [".recent-item:nth-of-type(2)", "trip"], [".recent-item:nth-of-type(3)", "dinner"],
      [".model-pill span:last-child", "mode"], [".theme-picker-label", "theme"], ["#loginButton", "login"], [".empty-state h1", "ask"], [".empty-copy", "copy"],
      [".starter:nth-child(1) strong", "easy-title"], [".starter:nth-child(1) small", "easy-copy"], [".starter:nth-child(2) strong", "life-title"], [".starter:nth-child(2) small", "life-copy"],
      [".starter:nth-child(3) strong", "document-title"], [".starter:nth-child(3) small", "document-copy"], ["#attachmentButton span:last-child", "file"], ["#runtimeNote", "note"], [".sidebar-footer span:last-child", "footer"]
    ];
    map.forEach(([selector, key]) => setText(selector, key, lang));
    document.querySelectorAll("[data-locale-key]").forEach((element) => {
      const key = element.dataset.localeKey;
      if (key) element.textContent = text(key, lang);
    });
    const input = document.getElementById("messageInput"); if (input) input.placeholder = text("input", lang);
    const web = document.querySelector('.composer-tools .tool-button:nth-of-type(2)'); if (web) web.querySelector("span:last-child").textContent = text("web", lang);
    const research = document.getElementById("deepResearchButton"); if (research) research.querySelector("span:last-child").textContent = text("research", lang);
    document.querySelectorAll("[data-locale-value]").forEach((button) => { const active = button.dataset.localeValue === lang; button.setAttribute("aria-pressed", String(active)); });
    window.dispatchEvent(new CustomEvent("padiem:localechange", { detail: { lang } }));
  }
  function init() {
    apply("ko");
    document.getElementById("languagePicker")?.addEventListener("click", (event) => { const button = event.target.closest("[data-locale-value]"); if (button) apply(button.dataset.localeValue); });
  }
  window.__padiemLocale = { apply, getCurrent: () => document.documentElement.lang === "en" ? "en" : "ko" };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
