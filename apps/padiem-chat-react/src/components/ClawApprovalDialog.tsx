import { clawApproval } from "../api/clawApi";
import { Modal } from "./Modal";
import { useLocale } from "../i18n/LocaleProvider";

interface ClawApprovalDialogProps {
  orchestration: unknown;
  onDecide: (outcome: "approved" | "denied") => void;
  onCancel: () => void;
}

/**
 * #5298 — the Claw approval surface.
 *
 * The operational product pauses a run that needs a decision and the trusted
 * server/control-plane adapter authenticates the actor. The browser only sends
 * an intent, and that intent is built by the operational orchestration module.
 * This dialog therefore owns the buttons and nothing else.
 */
export function ClawApprovalDialog({
  orchestration,
  onDecide,
  onCancel,
}: ClawApprovalDialogProps) {
  const { tOr } = useLocale();
  const model = clawApproval.viewModel(orchestration);
  const approval = model?.approval ?? null;
  const summary =
    approval && typeof approval.summary === "string" ? approval.summary : null;

  return (
    <Modal
      open
      onClose={onCancel}
      className="auth-dialog"
      labelledBy="clawApprovalTitle"
    >
      <div className="auth-panel">
        <div className="auth-header">
          <div>
            <p>Padiem Claw</p>
            <h2 id="clawApprovalTitle">
              {tOr("claw-approval-title", "계속하기 전에 확인이 필요합니다.")}
            </h2>
          </div>
        </div>
        <div className="auth-form">
          <p>
            {tOr(
              "claw-approval-hint",
              "이 작업은 승인 없이는 진행되지 않습니다. 확인하면 서버가 권한과 대상 컴퓨터를 다시 검증한 뒤 재개합니다.",
            )}
          </p>
          {summary ? <p className="auth-handoff-note">{summary}</p> : null}
          <div className="auth-handoff-actions">
            <button
              className="auth-primary"
              id="clawApprovalApprove"
              type="button"
              onClick={() => onDecide("approved")}
            >
              {tOr("claw-approval-approve", "승인하고 계속")}
            </button>
            <button
              className="auth-google"
              id="clawApprovalDeny"
              type="button"
              onClick={() => onDecide("denied")}
            >
              {tOr("claw-approval-deny", "거부")}
            </button>
            <button
              className="auth-google"
              id="clawApprovalCancel"
              type="button"
              onClick={onCancel}
            >
              {tOr("cancel", "취소")}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
