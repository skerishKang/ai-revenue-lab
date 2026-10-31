import { useEffect, useRef } from "react";

export type PcConnectionState = "unknown" | "check" | "disconnected" | "connected";

interface ComposerPcStatusProps {
  state: PcConnectionState;
  onOpen: () => void;
}

const COPY = {
  connect: "컴퓨터 연결",
  connected: "PC 연결됨",
  check: "PC 연결 확인",
  connectHint: "컴퓨터가 연결되어 있지 않습니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
  connectedHint: "컴퓨터가 연결되어 있습니다. 클릭하면 연결된 컴퓨터 정보를 확인합니다.",
  checkHint: "컴퓨터 연결 상태를 확인하지 못했습니다. 클릭하면 연결 상태를 다시 확인합니다.",
  checkingHint: "컴퓨터 연결 상태를 확인하는 중입니다. 클릭하면 컴퓨터 연결 안내를 엽니다.",
} as const;

/**
 * #5298 — computer connection status inside the shared composer.
 *
 * The operational product added this control in #5328 and renders it from
 * `apps/padiem-chat/static/claw-composer-connection-status.js`. The clone
 * mirrors that element, its state names and its measured layout: the control
 * sits on the textarea's own top-right corner and the reserved text gutter is
 * measured from the control, never guessed.
 *
 * The state comes from the server in the product. The clone has no server, so
 * it stays in the "unknown" state and never claims a connected computer.
 */
export function ComposerPcStatus({ state, onOpen }: ComposerPcStatusProps) {
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const button = buttonRef.current;
    if (!button) return;
    const form = document.getElementById("composerForm");
    const input = document.getElementById("messageInput");
    if (!form || !input) return;

    const syncLayout = () => {
      const top = input.offsetTop + 6;
      button.style.top = Math.max(0, Math.round(top)) + "px";
      const box = button.getBoundingClientRect();
      const width = Math.ceil(box.width);
      form.style.setProperty(
        "--composer-pc-status-gutter",
        (width > 0 ? width + 10 : 0) + "px",
      );
    };

    syncLayout();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(syncLayout);
    observer.observe(form);
    window.addEventListener("resize", syncLayout);
    const settle = window.setTimeout(syncLayout, 120);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncLayout);
      window.clearTimeout(settle);
    };
  }, []);

  // The label and the hint follow the operational product's own mapping.
  const label =
    state === "connected" ? COPY.connected : state === "check" ? COPY.check : COPY.connect;
  const hint =
    state === "connected"
      ? COPY.connectedHint
      : state === "check"
        ? COPY.checkHint
        : state === "disconnected"
          ? COPY.connectHint
          : COPY.checkingHint;

  return (
    <button
      ref={buttonRef}
      type="button"
      id="composerPcStatus"
      className="composer-pc-status"
      data-state={state}
      aria-label={hint}
      data-padiem-tooltip={hint}
      onClick={onOpen}
    >
      <span className="composer-pc-status-face">
        <span className="composer-pc-status-dot" aria-hidden="true"></span>
        <span className="composer-pc-status-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            focusable="false"
            aria-hidden="true"
          >
            <rect x="3" y="4" width="18" height="13" rx="2" />
            <path d="M8 21h8M12 17v4" />
          </svg>
        </span>
        <span className="composer-pc-status-label" aria-live="polite">
          {label}
        </span>
      </span>
    </button>
  );
}
