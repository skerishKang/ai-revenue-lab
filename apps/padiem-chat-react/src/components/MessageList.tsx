import type { ChatMessage } from "../data/types";

interface MessageListProps {
  messages: ChatMessage[];
  productLabel: string;
  onRetry: (messageId: string) => void;
}

/**
 * #5298 — conversation turns.
 *
 * The turn structure mirrors the operational templates
 * (`#userMessageTemplate` / `#assistantMessageTemplate`): the user turn keeps
 * name → avatar order with always-visible copy/edit affordances, and the
 * answer turn carries its completion time. A restored turn never shows one.
 */
export function MessageList({ messages, productLabel, onRetry }: MessageListProps) {
  return (
    <>
      {messages.map((message) =>
        message.role === "user" ? (
          <article className="message user-message" key={message.id}>
            <div className="message-bubble">{message.content}</div>
            <span className="user-profile-chip"></span>
            <span className="user-avatar" aria-hidden="true">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="8" r="3.6" />
                <path d="M5 19.5c1.2-3.2 3.9-5 7-5s5.8 1.8 7 5" />
              </svg>
            </span>
            <div className="user-actions" role="group" aria-label="내 메시지 작업">
              <time className="user-action-time" dateTime={message.completedAt ?? undefined}>
                {message.completedAt ? formatTime(message.completedAt) : ""}
              </time>
              <button type="button" className="user-action user-action-copy" aria-label="복사">
                <span aria-hidden="true">⧉</span>
              </button>
              <button type="button" className="user-action user-action-edit" aria-label="편집">
                <span aria-hidden="true">✎</span>
              </button>
            </div>
          </article>
        ) : (
          <article className="message assistant-message" key={message.id}>
            <div className="assistant-avatar" aria-hidden="true">
              P
            </div>
            <div className="assistant-body">
              <div className="assistant-meta">
                <span data-assistant-product>{productLabel}</span>
                {message.runtimeLabel ? (
                  <span data-runtime-label>{message.runtimeLabel}</span>
                ) : null}
                {message.state === "streaming" ? (
                  <span className="demo-label" data-runtime-label data-locale-key="answer-preparing">
                    답변 준비 중
                  </span>
                ) : null}
                {message.fixture && message.state !== "streaming" ? (
                  <span className="demo-label" data-locale-key="answer-fixture">
                    fixture 응답
                  </span>
                ) : null}
              </div>
              {message.state === "error" ? (
                <div className="error-box">
                  <p>{message.errorMessage}</p>
                  <button
                    type="button"
                    className="retry-button"
                    onClick={() => onRetry(message.id)}
                  >
                    다시 시도
                  </button>
                </div>
              ) : (
                <div className="assistant-content">
                  {message.state === "streaming" ? (
                    <span className="typing" aria-hidden="true">
                      <i></i>
                      <i></i>
                      <i></i>
                    </span>
                  ) : (
                    <p>{message.content}</p>
                  )}
                </div>
              )}
              {message.completedAt && message.state === "complete" ? (
                <div className="answer-action-time">{formatTime(message.completedAt)}</div>
              ) : null}
            </div>
          </article>
        ),
      )}
    </>
  );
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}
