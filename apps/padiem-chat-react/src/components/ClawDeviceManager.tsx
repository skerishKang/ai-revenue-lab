import { useState } from "react";
import type { ConnectorState } from "../data/types";

interface ClawDeviceManagerProps {
  /** The server-owned state. `unknown` mirrors the operational product before it answered. */
  state: ConnectorState;
  onRefresh: () => void;
  onConnect: () => void;
}

/**
 * #5298 — computer connection entry.
 *
 * The operational product renders this block inside the composer wrap with the
 * same ids and classes, so the first screen keeps the same height and the
 * same reading order. The connection state comes from a fixture in this PR:
 * the block never claims a computer is connected while the clone cannot prove
 * it.
 */
export function ClawDeviceManager({ state, onRefresh, onConnect }: ClawDeviceManagerProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("");

  const stateLabel =
    state === "connected"
      ? "온라인 · 작업 승인 필요"
      : state === "disconnected"
        ? "오프라인"
        : state === "check"
          ? "연결 확인 필요"
          : "";

  return (
    <section className="claw-device-manager" id="clawDeviceManager">
      <button
        className="claw-device-manager-toggle"
        id="clawDeviceManagerToggle"
        type="button"
        aria-controls="clawDeviceManagerPanel"
        aria-expanded={open ? "true" : "false"}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="claw-device-manager-toggle-title">컴퓨터와 연결해 보세요</span>
        <span className="claw-device-manager-state" hidden={!stateLabel}>
          {stateLabel}
        </span>
      </button>
      <section
        className="claw-device-manager-panel"
        id="clawDeviceManagerPanel"
        aria-labelledby="clawDeviceManagerTitle"
        hidden={!open}
      >
        <div className="claw-device-manager-head">
          <h2 id="clawDeviceManagerTitle">연결된 내 컴퓨터</h2>
          <button
            className="claw-device-manager-close"
            type="button"
            onClick={() => setOpen(false)}
          >
            닫기
          </button>
        </div>
        <p className="claw-device-manager-help">
          연결된 컴퓨터를 확인합니다. PC 작업은 별도의 승인이 필요합니다.
        </p>
        <div className="claw-device-manager-actions">
          <button
            className="claw-device-manager-refresh"
            type="button"
            onClick={() => {
              onRefresh();
              setStatus(
                "컴퓨터 연결 서비스가 아직 준비되지 않았습니다. 연결된 PC를 확인할 수 없습니다.",
              );
            }}
          >
            연결 상태 새로고침
          </button>
        </div>
        <p
          className="claw-device-manager-status"
          id="clawDeviceManagerStatus"
          role="status"
          aria-live="polite"
        >
          {status}
        </p>
        <ul className="claw-device-manager-list" id="clawDeviceManagerList" hidden></ul>
        <div className="claw-device-manager-connect" id="clawDeviceManagerConnect">
          <h3 className="claw-device-manager-connect-title">컴퓨터와 연결해 보세요</h3>
          <p className="claw-device-manager-connect-copy">
            내 컴퓨터의 파일과 프로그램을 Padiem에서 사용할 수 있어요.
          </p>
          <button
            className="claw-device-manager-connect-action"
            id="clawDeviceManagerConnectAction"
            type="button"
            onClick={onConnect}
          >
            컴퓨터 연결하기
          </button>
        </div>
      </section>
    </section>
  );
}
