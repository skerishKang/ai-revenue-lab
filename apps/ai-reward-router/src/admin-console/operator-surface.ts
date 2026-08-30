import type { AdminConsoleState, AdminRoute } from './domain.js';
import { buildOpportunityReview, renderAdminRoute } from './read-model.js';

function escapeAttribute(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function injectBeforeBody(html: string, fragment: string): string {
  const marker = '</body>';
  const index = html.lastIndexOf(marker);
  if (index < 0) return `${html}${fragment}`;
  return `${html.slice(0, index)}${fragment}${html.slice(index)}`;
}

export function renderOperatorAdminRoute(
  state: AdminConsoleState,
  route: AdminRoute,
  selectedId?: string,
): string {
  const base = renderAdminRoute(state, route, selectedId);
  if (route !== 'OPPORTUNITY_REVIEW') return base;

  const targetId = selectedId ?? state.reviewQueue.find((item) => item.state !== 'RESOLVED')?.offerVersionId;
  if (!targetId) return base;

  const detail = buildOpportunityReview(state, targetId);
  if (!detail.review) {
    return injectBeforeBody(base, '<section id="operator-actions"><h2>Operator actions</h2><p>No open review action is available for this version.</p></section>');
  }

  const reviewQueueId = escapeAttribute(detail.review.id);
  const versionId = escapeAttribute(detail.version.id);
  const nextVersionSuggestion = escapeAttribute(`${detail.version.id}-reviewed`);
  const form = `<section id="operator-actions"><h2>Operator actions</h2><p>Authenticated role and actor identity are supplied by the server, not by editable form fields.</p><form method="post" action="?route=OPPORTUNITY_REVIEW" data-b64-review-form="true"><input type="hidden" name="kind" value="REVIEW"><input type="hidden" name="reviewQueueId" value="${reviewQueueId}"><input type="hidden" name="selectedId" value="${versionId}"><label>Review reason <textarea name="reason" required></textarea></label><details><summary>MODIFY + APPROVE fields</summary><label>Resulting immutable version ID <input name="resultingVersionId" value="${nextVersionSuggestion}"></label><label>Evidence-backed JSON patch <textarea name="patchJson" placeholder='{"title":"Corrected evidence-backed title"}'></textarea></label></details><div><button type="submit" name="action" value="APPROVE">APPROVE</button> <button type="submit" name="action" value="MODIFY_APPROVE">MODIFY + APPROVE</button> <button type="submit" name="action" value="REJECT">REJECT</button> <button type="submit" name="action" value="RE_EXTRACT">SEND BACK / RE-EXTRACT</button></div></form></section>`;
  return injectBeforeBody(base, form);
}
