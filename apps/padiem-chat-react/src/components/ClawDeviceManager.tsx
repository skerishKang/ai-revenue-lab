import { useState } from "react";
import type { ConnectorState } from "../data/types";
import type { ClawDevice } from "../api/clawApi";

interface ClawDeviceManagerProps {
  /** The server-owned state. `unknown` mirrors the operational product before it answered. */
  state: ConnectorState;
  devices: ClawDevice[];
  selectedDeviceId: string | null;
  onRefresh: () => void;
  onSelect: (deviceId: string) => void;
  onConnect: () => void;
}

function deviceStateLabel(device: ClawDevice): string {
  if (device.revoked === true) return "연결 해제";
  if (device.expired === true) return "인증 만료";
  if (device.online === true) return "온라인 · 작업 승인 필요";
  return "오프라인";
}

/**
 * #5298 — the computer connection panel.
 *
 * The device list is the server's own directory read. The operational product
 * shows the same list, and the execution-target choice is only a hint: the
 * server re-verifies it against the current authority and connection.
 */
export function ClawDeviceManager({
  state,
  devices,
  selectedDeviceId,
  onRefresh,
  onSelect,
  onConnect,
}: ClawDeviceManagerProps) {
  const [open, setOpen] = useState(false);

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
            id="clawDeviceManagerRefresh"
            type="button"
            onClick={onRefresh}
          >
            연결 상태 새로고침
          </button>
        </div>
        <p className="claw-device-manager-status" id="clawDeviceManagerStatus" role="status" aria-live="polite"></p>
        <ul className="claw-device-manager-list" id="clawDeviceManagerList" hidden={devices.length === 0}>
          {devices.map((device) => (
            <li key={device.device_id} data-device-id={device.device_id}>
              <strong>{device.name ?? device.device_id}</strong>
              <small>
                {device.platform ? `${device.platform} · ` : ""}
                {deviceStateLabel(device)}
              </small>
              <button
                type="button"
                data-device-select={device.device_id}
                aria-pressed={device.device_id === selectedDeviceId ? "true" : "false"}
                onClick={() => onSelect(device.device_id)}
              >
                {device.device_id === selectedDeviceId ? "선택됨" : "작업 대상 후보로 선택"}
              </button>
            </li>
          ))}
        </ul>
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
