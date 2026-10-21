import { ThemePicker } from "./ThemePicker";
import type { ThemeName } from "../theme/theme";

interface TopBarProps {
  theme: ThemeName;
  collapsed: boolean;
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
 */
export function TopBar({
  theme,
  collapsed,
  onSelectTheme,
  onOpenMobile,
  onRestoreSidebar,
}: TopBarProps) {
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
          className="clone-fixture-badge"
          title="복제본 미리보기입니다. 답변은 로컬 fixture에서 생성되며 실제 모델 호출은 하지 않습니다."
        >
          복제본 미리보기
        </span>
        <ThemePicker theme={theme} onSelect={onSelectTheme} />
      </div>
    </header>
  );
}
