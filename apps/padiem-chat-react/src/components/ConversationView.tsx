import { useLocale } from "../i18n/LocaleProvider";
import { ClawHomeCards } from "./ClawHomeCards";
import { MessageList } from "./MessageList";
import type { ConnectorCard, ConnectorId, Conversation, ProductMode } from "../data/types";

interface ConversationViewProps {
  conversation: Conversation | null;
  mode: ProductMode;
  connectors: ConnectorCard[];
  onPrompt: (prompt: string) => void;
  onOpenConnector: (connectorId: ConnectorId) => void;
  onRetry: (messageId: string) => void;
}

const STARTERS = [
  {
    key: "explain",
    icon: "☺",
    titleKey: "easy-title",
    copyKey: "easy-copy",
    prompt: "AI를 처음 쓰는 사람에게 AI가 뭔지 아주 쉽게 설명해줘",
  },
  {
    key: "plan",
    icon: "⌂",
    titleKey: "life-title",
    copyKey: "life-copy",
    prompt: "이번 주말 가족과 집 근처에서 할 만한 일을 추천해줘",
  },
];

const WRITING_STARTER = {
  key: "auto",
  icon: "✎",
  titleKey: "writing-starter-title",
  copyKey: "writing-starter-copy",
  prompt: "목적과 읽는 사람에 맞는 이메일이나 문장 초안을 작성해줘",
};

/**
 * #5298 — first screen.
 *
 * The operational first screen is one conversation panel that shows either the
 * introductory block or the turns. The clone keeps that structure: the
 * introductory block stays in the DOM and is hidden once turns exist, exactly
 * like the operational product, so the layout does not jump between the two
 * states.
 */
export function ConversationView({
  conversation,
  mode,
  connectors,
  onPrompt,
  onOpenConnector,
  onRetry,
}: ConversationViewProps) {
  const { t } = useLocale();
  const messages = conversation?.messages ?? [];
  const hasTurns = messages.length > 0;
  const isClaw = mode === "claw";
  const productLabel = isClaw ? "Padiem Claw" : "Padiem Chat";

  return (
    <section className="conversation" aria-live="polite">
      <div className="empty-state" id="emptyState" hidden={hasTurns}>
        <p className="eyebrow">
          <span className="chat-hero-eyebrow">Padiem Chat</span>
          <span className="claw-hero-eyebrow">Padiem Claw</span>
        </p>
        <h1>
          <span className="chat-hero-line">{t("hello")}</span>
          <br className="chat-hero-line" />
          <span className="chat-hero-line">{t("ask")}</span>
          <span className="claw-hero-line">클로입니다.</span>
          <br className="claw-hero-line" />
          <span className="claw-hero-line">어디에서 작업할까요?</span>
        </h1>
        <p className="empty-copy chat-hero-line">{t("copy")}</p>
        <div className="starter-grid" aria-label="추천 질문">
          {STARTERS.map((starter) => (
            <button
              type="button"
              className="starter"
              key={starter.key}
              data-prompt={starter.prompt}
              data-skill={starter.key}
              onClick={() => onPrompt(starter.prompt)}
            >
              <span className="starter-icon" aria-hidden="true">
                {starter.icon}
              </span>
              <span>
                <strong>{t(starter.titleKey)}</strong>
                <small>{t(starter.copyKey)}</small>
              </span>
            </button>
          ))}
          <div className="document-starter-shell">
            <button type="button" className="starter" id="documentStarterButton">
              <span className="starter-icon" aria-hidden="true">
                ▤
              </span>
              <span>
                <strong>{t("document-upload-title")}</strong>
                <small>{t("document-upload-copy")}</small>
              </span>
            </button>
            <button
              type="button"
              id="documentFormatsToggle"
              className="document-formats-toggle"
              aria-expanded="false"
              aria-controls="documentFormatsPanel"
              aria-label="지원 형식"
            >
              지원 형식
            </button>
            <div id="documentFormatsPanel" className="document-formats-panel" role="note" hidden>
              <strong>지원 형식</strong>
              <p>지원 형식은 추후 안내합니다.</p>
            </div>
          </div>
          <button
            type="button"
            className="starter"
            id="writingStarterButton"
            key={WRITING_STARTER.key}
            data-prompt={WRITING_STARTER.prompt}
            data-skill={WRITING_STARTER.key}
            onClick={() => onPrompt(WRITING_STARTER.prompt)}
          >
            <span className="starter-icon" aria-hidden="true">
              {WRITING_STARTER.icon}
            </span>
            <span>
              <strong>{t(WRITING_STARTER.titleKey)}</strong>
              <small>{t(WRITING_STARTER.copyKey)}</small>
            </span>
          </button>
          <button
            type="button"
            className="starter"
            id="webSearchStarterButton"
            disabled
            aria-disabled="true"
            aria-pressed="false"
            hidden
          >
            <span className="starter-icon" aria-hidden="true">
              ⌕
            </span>
            <span>
              <strong>{t("web-starter-title")}</strong>
              <small>{t("web-starter-copy")}</small>
            </span>
          </button>
          <ClawHomeCards connectors={connectors} onOpenConnector={onOpenConnector} />
        </div>
        <button
          type="button"
          className="claw-history-shortcut"
          id="clawPreviousConversations"
          aria-controls="historySection"
        >
          이전 대화 보기 →
        </button>
      </div>

      <div className="message-list" id="messageList" hidden={!hasTurns}>
        <MessageList
          messages={messages}
          productLabel={productLabel}
          onRetry={onRetry}
        />
      </div>
    </section>
  );
}
