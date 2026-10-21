/**
 * #5298 — Claw workspace shell.
 *
 * The operational product renders `#clawWorkspace` as a sibling *before* the
 * conversation panel, and the operational stylesheet selects the Claw first
 * screen through that relationship
 * (`.app-shell[data-state="claw"] .claw-workspace[data-view="general"] ~ .conversation …`).
 * The clone keeps the same element, attribute and sibling order so the
 * operational CSS produces the same Claw first screen.
 */
export function ClawWorkspace({ visible }: { visible: boolean }) {
  return (
    <section
      className="claw-workspace"
      id="clawWorkspace"
      data-view="general"
      hidden={!visible}
    >
      <header className="claw-workspace-header">
        <div className="claw-workspace-identity">
          <p className="claw-workspace-kicker">Padiem Claw</p>
          <h2 className="claw-workspace-title" id="clawWorkspaceTitle">
            Padiem Claw
          </h2>
        </div>
        <p className="claw-workspace-chip">미리보기 + 실제 실행</p>
      </header>
      <p className="claw-workspace-tagline">
        카톡, 문자, 이메일로 받은 요청을 붙여넣으면 견적서·발주서·답장 초안을 준비하는 업무 에이전트
      </p>
      <p className="claw-workspace-help">
        미리보기는 바로 확인하는 임시 결과, 실제 실행은 AI가 완성해 문서까지 준비합니다.
      </p>
    </section>
  );
}
