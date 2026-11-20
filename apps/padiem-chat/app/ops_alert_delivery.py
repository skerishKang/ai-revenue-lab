"""#8105: 새 의견·회차 점수 알림 — B66 알림 채널을 그대로 재사용한다.

채널 판정·발송은 `B66SignupNotifier`(telegram·discord·email)가 이미 하는 일을
그대로 쓴다. 새 비밀값은 없다 — 컴2 환경의 B66_ALERT_* 이름을 그대로 읽는다.

문구에는 종류·분류·대상 번호·운영센터 링크만 넣는다. 의견 본문·이메일·회원
이름·회원 id는 넣지 않는다(외부 서비스 경유). 실패해도 의견·점수 저장은
성공하고, 대기함에 남아 다음 접수나 운영센터의 다시 보내기로 재시도된다.
"""
from __future__ import annotations

from typing import Any

#: 운영센터 링크는 서버가 정한다 — 요청 값에서 만들지 않는다.
OPS_CENTER_PATH = "/admin#ops-inbox"
KIND_LABELS = {
    "product_feedback": "새 의견",
    "site_feedback": "사이트 의견",
    "round_score": "회차 점수",
}
SUBJECTS = {
    "product_feedback": "[운영센터] 새 의견 접수",
    "site_feedback": "[운영센터] 사이트 의견 접수",
    "round_score": "[운영센터] 회차 점수 입력",
}


def alert_message(entry: dict, *, base_url: str) -> str:
    """종류·분류·번호·링크만. 본문·이메일·회원 정보는 절대 넣지 않는다."""
    kind = entry.get("kind")
    title = KIND_LABELS.get(kind, "운영 알림")
    label = str(entry.get("label") or "")
    lines = ["[운영센터] " + title]
    if label:
        lines.append("분류: " + label)
    lines.append("번호: " + str(entry.get("target_id") or ""))
    lines.append("운영센터: " + base_url.rstrip("/") + OPS_CENTER_PATH)
    return "\n".join(lines)


async def deliver_alert(store: Any, notifier: Any, entry: dict, *,
                        base_url: str) -> dict:
    """채널별 영수증으로 한 번만 보낸다(B66 deliver_inquiry와 같은 방식)."""
    result = {"sent": 0, "failed": 0}
    if notifier is None or not getattr(notifier, "channels", None):
        return result
    alert_id = entry["alert_id"]
    message = alert_message(entry, base_url=base_url)
    subject = SUBJECTS.get(entry.get("kind"), "[운영센터] 알림")
    for channel in tuple(notifier.channels):
        if await store.receipt_exists(alert_id, channel):
            continue
        if await notifier._send(channel, message=message, subject=subject):
            await store.record_success(alert_id, channel)
            result["sent"] += 1
        else:
            await store.record_failure(alert_id, channel)
            result["failed"] += 1
    await store.complete(alert_id, tuple(notifier.channels))
    return result


async def enqueue_and_deliver(request: Any, *, kind: str, target_id: str,
                              label: str) -> None:
    """저장 성공 뒤 부르는 알림 다리 — 실패가 저장 결과를 바꾸지 않는다.

    채널 값이 없으면 쌓아만 둔다(지금 B66과 같은 동작). 어떤 예외도 밖으로
    내보내지 않는다.
    """
    store = getattr(request.app.state, "ops_alert_store", None)
    if store is None:
        return
    try:
        entry = await store.enqueue(kind=kind, target_id=target_id, label=label)
        if entry is None:
            return
        notifier = getattr(request.app.state, "b66_signup_notifier", None)
        base_url = str(getattr(getattr(request.app.state, "settings", None),
                               "public_base_url", "") or "")
        await deliver_alert(store, notifier, entry, base_url=base_url)
    except Exception:
        return


async def retry_pending_alerts(request: Any, *, limit: int = 5) -> dict:
    store = getattr(request.app.state, "ops_alert_store", None)
    notifier = getattr(request.app.state, "b66_signup_notifier", None)
    summary = {"sent": 0, "failed": 0, "processed": 0}
    if store is None or notifier is None or not getattr(notifier, "channels", None):
        return summary
    base_url = str(getattr(getattr(request.app.state, "settings", None),
                           "public_base_url", "") or "")
    for entry in await store.pending(limit=limit):
        result = await deliver_alert(store, notifier, entry, base_url=base_url)
        summary["sent"] += result["sent"]
        summary["failed"] += result["failed"]
        summary["processed"] += 1
    return summary