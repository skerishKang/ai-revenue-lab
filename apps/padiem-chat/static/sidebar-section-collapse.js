/* #4890 follow-up: presentation-only collapse for Projects and Recent Chats.
 * No changes to server state, conversation/project handlers, or their contents.
 * Browser local storage retains only booleans; failures fall back to expanded.
 */
(function (root, doc) {
  "use strict";
  if (!doc) return;
  const groups = [
    ["projectsSection", "projectsToggleButton", "projects"],
    ["historySection", "historyToggleButton", "history"],
  ];
  const korean = () => (doc.documentElement.lang || "ko").toLowerCase().startsWith("ko");
  function setup(sectionId, buttonId, kind) {
    const section = doc.getElementById(sectionId);
    const button = doc.getElementById(buttonId);
    if (!section || !button) return;
    const key = "padiem.sidebar.section." + kind + ".collapsed.v1";
    let collapsed = false;
    try { collapsed = root.localStorage?.getItem(key) === "1"; } catch (_) {}
    function apply() {
      section.classList.toggle("is-collapsed", collapsed);
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      const name = kind === "projects"
        ? (korean() ? "프로젝트" : "Projects")
        : (korean() ? "최근 대화" : "Recent conversations");
      const action = collapsed
        ? (korean() ? "펼치기" : "Expand")
        : (korean() ? "접기" : "Collapse");
      button.setAttribute("aria-label", name + " " + action);
      button.title = name + " " + action;
    }
    button.addEventListener("click", () => {
      collapsed = !collapsed;
      // Closing the history area also closes an open three-dot popup.
      if (collapsed && kind === "history") {
        section.querySelectorAll(".history-actions[open]").forEach((node) => { node.open = false; });
      }
      apply();
      try { root.localStorage?.setItem(key, collapsed ? "1" : "0"); } catch (_) {}
    });
    apply();
  }
  groups.forEach(([sectionId, buttonId, kind]) => setup(sectionId, buttonId, kind));
})(typeof window !== "undefined" ? window : null, typeof document !== "undefined" ? document : null);
