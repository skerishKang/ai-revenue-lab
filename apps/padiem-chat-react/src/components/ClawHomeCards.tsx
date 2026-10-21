import type { ReactElement } from "react";
import type { ConnectorCard, ConnectorId } from "../data/types";

interface ClawHomeCardsProps {
  connectors: ConnectorCard[];
  onOpenConnector: (connectorId: ConnectorId) => void;
}

const CONNECTOR_ICONS: Record<ConnectorId, ReactElement> = {
  pc: (
    <svg
      className="claw-card-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  ),
  drive: (
    <svg
      className="claw-card-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 3h6l8 14-3 5h-6L5 8z" />
      <path d="M8 3 1 17l3 5h15M5 8l8 14M1 17h21" />
    </svg>
  ),
  github: (
    <svg
      className="claw-card-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 19c-4 1-4-2-6-2m12 4v-3.4c0-1 .1-1.4-.5-2a6.2 6.2 0 0 0 1.8-4.4 6 6 0 0 0-1.5-4.1c0-1 .1-2-.3-3-1.5 0-2.5 1-3 1.5a11 11 0 0 0-6 0c-.5-.5-1.5-1.5-3-1.5-.4 1-.3 3-.3 3A6 6 0 0 0 1 11.2a6.2 6.2 0 0 0 1.8 4.4c-.6.6-.5 1-.5 2V21" />
    </svg>
  ),
  web: (
    <svg
      className="claw-card-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
    </svg>
  ),
};

/**
 * #5298 — Claw destination cards.
 *
 * The connection state is a fixture in this PR. The card keeps the
 * operational contract: an explicit status line, a destination button, and a
 * connection toggle whose state is reported truthfully instead of being
 * turned on optimistically.
 */
export function ClawHomeCards({ connectors, onOpenConnector }: ClawHomeCardsProps) {
  return (
    <>
      {connectors.map((connector) => {
        const stateLabel =
          connector.state === "connected"
            ? "연결됨"
            : connector.state === "disconnected"
              ? "연결 안 됨"
              : "연결 확인 필요";
        return (
          <div className="claw-home-card" key={connector.id} data-claw-card={connector.id}>
            <span className="claw-card-status" role="status" aria-live="polite">
              {stateLabel}
            </span>
            <button
              type="button"
              className="starter claw-workspace-starter"
              id={`claw${connector.id}Workspace`}
              onClick={() => onOpenConnector(connector.id)}
            >
              <span className="starter-icon" aria-hidden="true">
                {CONNECTOR_ICONS[connector.id]}
              </span>
              <span>
                <strong>{connector.label}</strong>
                <small>{connector.description}</small>
              </span>
            </button>
            <button
              type="button"
              className="claw-connection-toggle"
              data-claw-connection={connector.id}
              aria-pressed={connector.state === "connected" ? "true" : "false"}
              data-connection-state={connector.state}
              aria-label={`${connector.label} 연결 상태 확인 불가`}
              onClick={() => onOpenConnector(connector.id)}
            >
              <span className="claw-connection-track" aria-hidden="true">
                <span className="claw-state-on">ON</span>
                <span className="claw-state-off">OFF</span>
              </span>
              <span className="claw-connection-label" hidden>
                {stateLabel}
              </span>
            </button>
          </div>
        );
      })}
      <div className="claw-home-card" data-claw-card="web">
        <button
          type="button"
          className="starter claw-workspace-starter"
          id="clawWebWorkspace"
          onClick={() => onOpenConnector("web")}
        >
          <span className="starter-icon" aria-hidden="true">
            <svg
              className="claw-card-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
            </svg>
          </span>
          <span>
            <strong>웹에서 하기</strong>
            <small>웹에서 바로 작업하기</small>
          </span>
        </button>
      </div>
    </>
  );
}
