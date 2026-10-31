import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale } from "../i18n/LocaleProvider";
import type { Conversation, ProductMode } from "../data/types";

interface SidebarProps {
  conversations: Conversation[];
  visibleConversations: Conversation[];
  activeConversationId: string | null;
  searchQuery: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onNewChat: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onSearchQuery: (query: string) => void;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
  onOpenMode: (mode: ProductMode) => void;
  /** The workspace surface that is open, in the product's own names. */
  activeView: "chat" | "library" | "automation" | "calendar" | "meeting";
  onOpenView: (view: "chat" | "library" | "automation" | "calendar" | "meeting") => void;
  /** The API answered and reports a signed-in account. */
  authenticated: boolean;
  /** The API answered, so a sign-in is possible. */
  apiAvailable: boolean;
  onOpenLogin: () => void;
}

/** The operational product's own row icons, rebuilt as React nodes. */
function MoreIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="5" r="1.65" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.65" fill="currentColor" stroke="none" />
      <circle cx="12" cy="19" r="1.65" fill="currentColor" stroke="none" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4 6h16M9 6V4h6v2M6 6l1 15h10l1-15M10 10v7M14 10v7" />
    </svg>
  );
}

/**
 * #5298 — sidebar.
 *
 * The element ids, class names and accessible names mirror
 * `apps/padiem-chat/static/index.html` so the clone can be compared with the
 * operational product element by element. The operational account and model
 * surfaces stay in the same place they occupy in the product.
 */
export function Sidebar({
  conversations,
  visibleConversations,
  activeConversationId,
  searchQuery,
  collapsed,
  mobileOpen,
  onNewChat,
  onSelectConversation,
  onDeleteConversation,
  onSearchQuery,
  onToggleCollapse,
  onCloseMobile,
  onOpenMode,
  activeView,
  onOpenView,
  authenticated,
  apiAvailable,
  onOpenLogin,
}: SidebarProps) {
  const { t } = useLocale();
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (searchOpen) {
      searchInputRef.current?.focus();
    }
  }, [searchOpen]);

  const hasConversations = conversations.length > 0;
  const visibleIds = useMemo(
    () => visibleConversations.map((conversation) => conversation.id).join(","),
    [visibleConversations],
  );

  return (
    <aside
      className="sidebar"
      id="sidebar"
      data-locale-aria-label="main-menu"
      aria-label="주요 메뉴"
      hidden={false}
    >
      <div className="brand-row">
        <button
          className="mobile-close"
          id="mobileClose"
          type="button"
          aria-label="메뉴 닫기"
          onClick={onCloseMobile}
        >
          ×
        </button>
        <a className="brand" href="/" aria-label="Padiem Chat 홈">
          <span className="brand-mark" aria-hidden="true">
            P
          </span>
          <span>Padiem Chat</span>
        </a>
        <button
          className="sidebar-collapse-button"
          id="sidebarCollapseButton"
          type="button"
          aria-controls="sidebar"
          aria-expanded={collapsed ? "false" : "true"}
          aria-label="사이드바 접기"
          title="사이드바 접기"
          onClick={onToggleCollapse}
        >
          <span aria-hidden="true">⇤</span>
        </button>
      </div>

      <div className="sidebar-chat-claw-group">
        <div
          className="sidebar-actions-row sidebar-unified-row"
          role="group"
          aria-label="새 채팅과 대화 검색"
        >
          <button
            className="new-chat"
            id="newChatButton"
            type="button"
            onClick={() => {
              onOpenView("chat");
              onNewChat();
            }}
          >
            <span aria-hidden="true">＋</span>
            <span data-locale-key="new-chat">{t("new-chat")}</span>
          </button>
          <button
            className="side-item sidebar-search-item"
            id="sidebarSearchButton"
            type="button"
            aria-label="대화 검색"
            aria-pressed={searchOpen ? "true" : "false"}
            aria-controls="conversationSearchPanel"
            onClick={() => setSearchOpen((open) => !open)}
          >
            <span className="side-icon" aria-hidden="true">
              ⌕
            </span>
            <span className="visually-hidden" data-locale-key="search">
              검색
            </span>
          </button>
        </div>
        <nav className="side-nav" aria-label="채팅 메뉴">
          <button
            className="side-item"
            id="clawNavButton"
            type="button"
            aria-current={activeView === "chat" ? "page" : "false"}
            data-mode-hint="업무·파일"
            onClick={() => {
              onOpenMode("claw");
              onOpenView("chat");
            }}
          >
            <span className="side-icon" aria-hidden="true">
              ◆
            </span>
            <span data-locale-key="nav-claw">{t("nav-claw")}</span>
          </button>
        </nav>
      </div>

      <nav className="side-nav" id="workspaceNav" aria-label="워크스페이스 메뉴">
        <button
          className="side-item"
          id="meetingNavButton"
          type="button"
          aria-controls="meetingView"
          aria-current={activeView === "meeting" ? "page" : "false"}
          onClick={() => onOpenView("meeting")}
        >
          <span className="side-icon" aria-hidden="true">
            ▥
          </span>
          <span data-locale-key="nav-meeting">{t("nav-meeting")}</span>
        </button>
        <button
          className="side-item"
          id="automationNavButton"
          type="button"
          aria-controls="automationView"
          aria-current={activeView === "automation" ? "page" : "false"}
          onClick={() => onOpenView("automation")}
        >
          <span className="side-icon" aria-hidden="true">
            ◷
          </span>
          <span data-locale-key="nav-automation">{t("nav-automation")}</span>
        </button>
        <button
          className="side-item"
          id="filesNavButton"
          type="button"
          aria-controls="libraryView"
          aria-current={activeView === "library" ? "page" : "false"}
          onClick={() => onOpenView("library")}
        >
          <span className="side-icon" aria-hidden="true">
            ▤
          </span>
          <span data-locale-key="nav-files">{t("nav-files")}</span>
        </button>
        <button
          className="side-item"
          id="calendarNavButton"
          type="button"
          aria-controls="calendarView"
          aria-current={activeView === "calendar" ? "page" : "false"}
          onClick={() => onOpenView("calendar")}
        >
          <span className="side-icon" aria-hidden="true">
            ▨
          </span>
          <span data-locale-key="nav-calendar">{t("nav-calendar")}</span>
        </button>
      </nav>

      <nav className="side-nav" aria-label="도구 및 연결">
        <button className="side-item" id="connectorsNavButton" type="button" aria-current="false">
          <span className="side-icon" aria-hidden="true">
            ⇄
          </span>
          <span data-locale-key="nav-connectors">{t("nav-connectors")}</span>
        </button>
      </nav>

      <section className="recent-section" id="historySection" aria-labelledby="historyTitle">
        <div className="section-heading-row">
          <h2 id="historyTitle" data-locale-key="history-title">
            {t("history-title")}
          </h2>
          <button
            className="sidebar-section-toggle"
            id="historyToggleButton"
            type="button"
            aria-controls="historyList historyEmpty"
            aria-expanded="true"
            aria-label="최근 대화 접기"
            title="최근 대화 접기"
          >
            <span aria-hidden="true"></span>
          </button>
        </div>

        {searchOpen ? (
          <div className="conversation-search-panel" id="conversationSearchPanel">
            <input
              ref={searchInputRef}
              type="search"
              id="conversationSearchInput"
              className="conversation-search-input"
              maxLength={80}
              autoComplete="off"
              placeholder="대화 검색"
              aria-label="대화 검색어 입력"
              value={searchQuery}
              onChange={(event) => onSearchQuery(event.target.value)}
            />
            <p
              className="history-empty"
              id="conversationSearchStatus"
              aria-live="polite"
              hidden={searchQuery.trim().length > 0}
            >
              대화 제목을 입력하세요.
            </p>
            <div className="conversation-search-results" id="conversationSearchResults">
              {searchQuery.trim().length > 0 && visibleConversations.length === 0 ? (
                <p className="history-empty">검색 결과가 없습니다.</p>
              ) : null}
              {visibleConversations.map((conversation) => (
                <div
                  key={conversation.id}
                  className="recent-item history-item conversation-search-hit"
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectConversation(conversation.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectConversation(conversation.id);
                    }
                  }}
                >
                  <span className="conversation-search-title">{conversation.title}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div id="historyList" data-visible-ids={visibleIds} hidden={searchOpen}>
          {visibleConversations.map((conversation) => (
            <div className="history-row" key={conversation.id}>
              <button
                type="button"
                className="recent-item history-item"
                aria-current={conversation.id === activeConversationId ? "true" : undefined}
                onClick={() => onSelectConversation(conversation.id)}
              >
                {conversation.product === "claw" ? `Claw · ${conversation.title}` : conversation.title}
              </button>
              <details className="history-actions">
                <summary className="history-more" aria-label={`관리: ${conversation.title}`}>
                  <MoreIcon />
                </summary>
                <div className="history-actions-menu">
                  <button
                    type="button"
                    className="history-delete history-menu-delete"
                    aria-label={`대화 삭제: ${conversation.title}`}
                    onClick={() => onDeleteConversation(conversation.id)}
                  >
                    <TrashIcon />
                    삭제
                  </button>
                </div>
              </details>
            </div>
          ))}
        </div>
        <p className="history-empty" id="historyEmpty" hidden={hasConversations}>
          {t("history-empty")}
        </p>
      </section>

      <div className="sidebar-footer">
        <span className="preview-dot" aria-hidden="true"></span>
        <span data-locale-key="footer">{t("footer")}</span>
      </div>

      <div className="sidebar-bottom" aria-label="서비스, 계정 및 설정">
        {/* The product hides the sidebar settings entry on purpose
            (`.sidebar-bottom > #settingsButton`), and opens the same dialog
            from the account profile. The clone has no account panel, so its
            settings entry lives in the top bar instead. */}
        {/* The clone runs without a signed-in session, so the account controls
            stay hidden exactly like the operational product before login. */}
        <div className="sidebar-account account-controls" hidden={authenticated || !apiAvailable}>
          <span className="account-avatar" id="accountAvatar" aria-hidden="true">
            ?
          </span>
          <span className="account-name" id="accountName" hidden></span>
          <button
            className="login-button"
            id="loginButton"
            type="button"
            title="Google 계정으로 로그인"
            onClick={onOpenLogin}
          >
            {t("auth-login")}
          </button>
        </div>
        <a
          className="home-link"
          href="https://padiem.net/"
          target="_blank"
          rel="noopener"
          aria-label="Padiem Home 열기"
        >
          <span className="home-link-mark" aria-hidden="true">
            ↗
          </span>
          <span data-locale-key="home-link">{t("home-link")}</span>
        </a>
      </div>
      <span hidden data-mobile-open={mobileOpen ? "true" : "false"} />
    </aside>
  );
}
