import { ThemePicker } from "./ThemePicker";
import type { ThemeName } from "../theme/theme";
import type { ApiMode } from "../state/chatStore";

interface TopBarProps {
  theme: ThemeName;
  collapsed: boolean;
  apiMode: ApiMode;
  onSelectTheme: (theme: ThemeName) => void;
  onOpenMobile: () => void;
  onRestoreSidebar: () => void;
}

/**
 * #5298 — top bar.
 *
 * The operational top bar owns the mobile menu and the sidebar restore
 * button. The clone keeps both and adds the theme switcher on the right, which
 * is the only addition in this PR.
 *
 * The badge states which source answers are coming from: the real Chat API or
 * the local fixture. It is never hidden, because a fixture answer must not be
 * readable as a live product answer.
 */
export function TopBar({
  theme,
  collapsed,
  apiMode,
  onSelectTheme,
  onOpenMobile,
  onRestoreSidebar,
}: TopBarProps) {
  const badge =
    apiMode === "api"
      ? { className: "clone-api-badge", text: "실제 API 연결" }
      : apiMode === "probing"
        ? { className: "clone-probe-badge", text: "API 확인 중" }
        : { className: "clone-fixture-badge", text: "복제본 미리보기" };

  return (
    <header className="topbar">
      <button
        className="mobile-menu"
        id="mobileMenu"
        type="button"
        aria-controls="sidebar"
        aria-expanded="false"
        aria-label="메뉴 열기"
        onClick={onOpenMobile}
      >
        ☰
      </button>
      <button
        className="sidebar-restore-button"
        id="sidebarRestoreButton"
        type="button"
        aria-controls="sidebar"
        aria-expanded={collapsed ? "false" : "true"}
        aria-label="사이드바 펼치기"
        title="사이드바 펼치기"
        onClick={onRestoreSidebar}
      >
        <span aria-hidden="true">☰</span>
      </button>
      <div className="clone-topbar-actions">
        <span
          className={badge.className}
          title={
            apiMode === "api"
              ? "실제 Chat API에 연결되어 있습니다."
              : "API에 연결할 수 없어 로컬 fixture로 응답합니다."
          }
        >
          {badge.text}
        </span>
        <ThemePicker theme={theme} onSelect={onSelectTheme} />
      </div>
    </header>
  );
}
