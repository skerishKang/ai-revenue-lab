import { useEffect, useRef, useState } from "react";
import { composerCore } from "../lib/composer-core";
import { attachmentCapabilities } from "../lib/attachment-capabilities";
import { ClawDeviceManager } from "./ClawDeviceManager";
import { ComposerPcStatus } from "./ComposerPcStatus";
import { Popover } from "./Popover";
import type { ModelChoice, PendingAttachment } from "../data/types";

/** The clearance contract the operational product publishes on the document root. */
const MIN_CONVERSATION_CLEARANCE = 230;
const COMPOSER_CLEARANCE_GAP = 64;

interface ComposerProps {
  modelChoices: ModelChoice[];
  selectedModelId: string;
  pendingAttachment: PendingAttachment | null;
  streaming: boolean;
  pcState: "unknown" | "check" | "disconnected" | "connected";
  /** The API probe has not answered yet, so the source of an answer is unknown. */
  probing: boolean;
  onSelectModel: (modelId: string) => void;
  onSend: (prompt: string) => void;
  onAttach: (file: File) => void;
  onClearAttachment: () => void;
  onRefreshPcState: () => void;
  onConnectPc: () => void;
  /** The server-reported computer list for the Claw product. */
  clawDevices: {
    device_id: string;
    name?: string;
    platform?: string;
    online?: boolean;
    state?: string;
    revoked?: boolean;
    expired?: boolean;
  }[];
  selectedDeviceId: string | null;
  onSelectDevice: (deviceId: string) => void;
}

/**
 * #5298 — message composer.
 *
 * The composer DOM mirrors `apps/padiem-chat/static/index.html`. The input
 * behaviour is not re-implemented: the IME composition guard, the Enter-to-send
 * rule and the textarea growth all come from the canonical shared composer
 * core in `packages/padiem-conversation-ui/composer-core.js`.
 */
export function Composer({
  modelChoices,
  selectedModelId,
  pendingAttachment,
  streaming,
  pcState,
  probing,
  onSelectModel,
  onSend,
  onAttach,
  onClearAttachment,
  onRefreshPcState,
  onConnectPc,
  clawDevices,
  selectedDeviceId,
  onSelectDevice,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const guardRef = useRef(composerCore.createCompositionGuard());
  const modelButtonRef = useRef<HTMLButtonElement | null>(null);
  const wrapRef = useRef<HTMLElement | null>(null);

  // The operational product publishes the real composer height as a CSS
  // variable so the conversation column keeps the last turn above the fixed
  // input. The clone measures the same element with the same formula.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const sync = () => {
      const height = wrap.getBoundingClientRect().height;
      const clearance = Math.max(
        MIN_CONVERSATION_CLEARANCE,
        Math.ceil((Number.isFinite(height) ? height : 0) + COMPOSER_CLEARANCE_GAP),
      );
      document.documentElement.style.setProperty(
        "--padiem-composer-clearance",
        `${clearance}px`,
      );
      wrap.dataset.conversationClearance = String(clearance);
    };
    sync();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(sync);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, []);

  // The operational product grows the input to fit its placeholder on load.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    composerCore.resizeTextarea(textarea, { minHeight: 50, maxHeight: 180 });
  }, []);

  const selectedModel =
    modelChoices.find((choice) => choice.id === selectedModelId) ?? modelChoices[0];

  const growTextarea = () => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    composerCore.resizeTextarea(textarea, { minHeight: 50, maxHeight: 180 });
  };

  const submit = () => {
    const prompt = value.trim();
    if (!prompt || probing) return;
    onSend(prompt);
    setValue("");
    requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (textarea) {
        textarea.style.height = "auto";
        textarea.style.overflowY = "hidden";
      }
    });
  };

  return (
    <section className="composer-wrap" aria-label="메시지 작성" ref={wrapRef}>
      <ClawDeviceManager
        state={pcState}
        devices={clawDevices}
        selectedDeviceId={selectedDeviceId}
        onRefresh={onRefreshPcState}
        onSelect={onSelectDevice}
        onConnect={onConnectPc}
      />
        <form
          className="composer"
          id="composerForm"
          data-pc-status="ready"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
        <div className="attachment-tray" id="attachmentTray" hidden={!pendingAttachment}>
          <div className="attachment-preview">
            {pendingAttachment?.kind === "image" ? (
              <img id="attachmentThumb" alt="선택한 사진 미리보기" />
            ) : (
              <span className="document-attachment-icon" id="attachmentKind" aria-hidden="true">
                DOC
              </span>
            )}
            <div className="attachment-copy">
              <strong id="attachmentName">{pendingAttachment?.name ?? ""}</strong>
              <small id="attachmentSize">{pendingAttachment?.sizeLabel ?? ""}</small>
            </div>
            <button
              id="removeAttachment"
              className="attachment-remove"
              type="button"
              aria-label="첨부 파일 제거"
              onClick={onClearAttachment}
            >
              ×
            </button>
          </div>
        </div>

        <label className="sr-only" htmlFor="messageInput">
          메시지 입력
        </label>
        <textarea
          id="messageInput"
          ref={textareaRef}
          rows={1}
          placeholder="무엇이든 물어보세요"
          autoComplete="off"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            growTextarea();
          }}
          onCompositionStart={() => guardRef.current.start()}
          onCompositionUpdate={() => guardRef.current.update()}
          onCompositionEnd={() => guardRef.current.end()}
          onKeyDown={(event) => {
            if (!composerCore.shouldSubmitOnEnter(event.nativeEvent, guardRef.current)) return;
            event.preventDefault();
            submit();
          }}
        />

          <p id="composerInlineHint" className="composer-inline-hint" role="status" aria-live="polite" aria-atomic="true" hidden></p>
          <p id="voiceStatus" className="voice-status sr-only" role="status" aria-live="polite" aria-atomic="true">
            음성 입력은 아직 연결되지 않았습니다.
          </p>
          <div className="composer-actions">
          <div className="composer-tools tier-control-host">
            <button
              className="model-pill composer-tier-trigger"
              type="button"
              data-mode-control="true"
              aria-label="AI 등급"
              aria-haspopup="true"
              aria-expanded={modelOpen ? "true" : "false"}
              aria-controls="cloneModelPicker"
              data-padiem-tooltip="모델 선택"
              ref={modelButtonRef}
              onClick={() => setModelOpen((open) => !open)}
            >
              <span className="status-spark" aria-hidden="true">
                ✦
              </span>
              <span>{selectedModel?.label ?? "Padiem Plus"}</span>
            </button>
            {modelOpen ? (
              <Popover
                anchorRef={modelButtonRef}
                className="clone-popover--model"
                onClose={() => setModelOpen(false)}
              >
                <div id="cloneModelPicker" role="listbox" aria-label="모델 선택">
                  {modelChoices.map((choice) => (
                    <button
                      key={choice.id}
                      type="button"
                      role="option"
                      className="clone-model-option"
                      aria-selected={choice.id === selectedModelId ? "true" : "false"}
                      onClick={() => {
                        onSelectModel(choice.id);
                        setModelOpen(false);
                      }}
                    >
                      <strong>{choice.label}</strong>
                      <small>{choice.description}</small>
                    </button>
                  ))}
                </div>
              </Popover>
            ) : null}
            <input
              id="attachmentFileInput"
              ref={fileInputRef}
              type="file"
              hidden
              accept={attachmentCapabilities.accept}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onAttach(file);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              className="tool-button"
              id="attachmentButton"
              aria-label="파일 첨부"
              title={attachmentCapabilities.copy("ko").fileButtonTitle}
              data-padiem-tooltip="파일 첨부"
              onClick={() => fileInputRef.current?.click()}
            >
              <span aria-hidden="true">＋</span>
              <span>파일</span>
            </button>
            <button
              type="button"
              className="tool-button"
              disabled
              id="webSearchButton"
              aria-disabled="true"
              aria-label="웹 검색"
              aria-pressed="false"
              data-padiem-tooltip="웹 검색"
              hidden
            >
              <span aria-hidden="true">⌕</span>
              <span>웹 검색</span>
            </button>
            <button
              type="button"
              className="tool-button"
              disabled
              id="deepResearchButton"
              aria-disabled="true"
              aria-pressed="false"
              data-padiem-tooltip="심층 리서치"
              hidden
            >
              <span aria-hidden="true">✦</span>
              <span>심층 리서치</span>
            </button>
          </div>
          <button
            id="voiceMicButton"
            type="button"
            className="voice-mic-button"
            aria-pressed="false"
            aria-disabled="true"
            data-voice-state="unavailable"
            aria-label="음성 입력 시작"
            data-padiem-tooltip="음성 입력"
            disabled
          >
            <span aria-hidden="true">◉</span>
            <span data-locale-key="voice-mic">음성 입력</span>
          </button>
          <button
            type="button"
            id="voiceWaveformButton"
            className="voice-waveform-button"
            aria-label="음성 모드"
            aria-expanded="false"
            aria-haspopup="menu"
            aria-pressed="false"
            data-voice-mode="basic"
            disabled
          >
            <svg
              aria-hidden="true"
              focusable="false"
              width="20"
              height="20"
              viewBox="0 0 24 24"
            >
              <path
                d="M7 16v2a6 6 0 0 0 12 0v-2M12 20v1M7 10v2a4 4 0 0 0 8 0v-2M12 14v1M7 4v2a2 2 0 0 0 4 0v-2M12 8v1"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
            <span className="sr-only">음성 모드</span>
          </button>
          <button className="cancel-stream-button" id="cancelStreamButton" type="button" hidden>
            취소
          </button>
          <button
            className="send-button"
            id="sendButton"
            type="submit"
            aria-label="메시지 보내기"
            data-padiem-tooltip="메시지 전송"
            disabled={streaming || probing}
          >
            <svg
              className="send-arrow-icon"
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              focusable="false"
            >
              <path
                d="M12 19V5m-6 6 6-6 6 6"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <ComposerPcStatus
          state={pcState}
          onOpen={() => document.getElementById("clawDeviceManagerToggle")?.click()}
        />
      </form>
      <p className="composer-note" id="runtimeNote">
        {attachmentCapabilities.copy("ko").idleNote}
      </p>
    </section>
  );
}
