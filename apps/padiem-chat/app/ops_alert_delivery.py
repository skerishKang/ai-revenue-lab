"""#8105: 새 의견·회차 점수 알림 — B66 알림 채널을 그대로 재사용한다.

채널 판정·발송은 `B66SignupNotifier`(telegram·discord·email)가 이미 하는 일을
그대로 쓴다. 새 비밀값은 없다 — 컴2 환경의 B66_ALERT_* 이름을 그대로 읽는다.
발송기는 `app.state.ops_alert_notifier` 하나만 읽는다(B66 회원 알림의 설정
여부와 서로 영향을 주지 않는다).

문구에는 종류·분류·대상 번호·운영센터 링크만 넣는다. 의견 본문·이메일·회원
이름·회원 id는 넣지 않는다(외부 서비스 경유).

요청 안에서는 **대기함 적재까지만** 한다. 발송은 백그라운드 작업으로 돌리므로
느리거나 멈춘 채널이 접수 응답을 붙잡지 않는다. 작업 참조는 app.state의 set에
보관했다가 끝나면 지운다(작업이 중간에 사라지지 않게). 같은 흐름에서 오래된
대기분 최대 5개도 함께 보내 자동 재시도가 된다. 실패해도 의견·점수 저장은
성공하고, 남은 건은 다음 접수나 운영센터의 다시 보내기로 이어진다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .ops_notify_event import SITE_LINKS

logger = logging.getLogger(__name__)

#: 운영센터 링크는 서버가 정한다 — 요청 값에서 만들지 않는다.
OPS_CENTER_PATH = "/admin#ops-inbox"
#: 새 알림을 적재할 때 같은 흐름에서 함께 보낼 오래된 대기분 상한.
RETRY_BATCH = 5
KIND_LABELS = {
    "product_feedback": "새 의견",
    "site_feedback": "사이트 의견",
    "round_score": "회차 점수",
    "agent_stall": "PC 에이전트 응답 없음",
}
SUBJECTS = {
    "product_feedback": "[운영센터] 새 의견 접수",
    "site_feedback": "[운영센터] 사이트 의견 접수",
    "round_score": "[운영센터] 회차 점수 입력",
    "agent_stall": "[운영센터] PC 에이전트 응답 없음",
}


def alert_message(entry: dict, *, base_url: str) -> str:
    """종류·분류·번호·링크만. 본문·이메일·회원 정보는 절대 넣지 않는다."""
    site = entry.get("notify_site")
    if site in SITE_LINKS:
        if entry.get("notify_audience") == "summary":
            return (
                f"[운영센터] {site} 일일 요약 ({entry['notify_day']})\n"
                f"AI 이벤트: {entry['notify_count']}건\n운영센터: {SITE_LINKS[site]}"
            )
        return "\n".join((
            f"[운영센터] {site} {entry['notify_kind']}",
            f"제목: {entry['notify_title']}",
            f"번호: {entry['notify_source_id']}",
            "운영센터: " + SITE_LINKS[site],
        ))
    kind = entry.get("kind")
    title = KIND_LABELS.get(kind, "운영 알림")
    label = str(entry.get("label") or "")
    lines = ["[운영센터] " + title]
    if label:
        lines.append("분류: " + label)
    lines.append("번호: " + str(entry.get("target_id") or ""))
    lines.append("운영센터: " + base_url.rstrip("/") + OPS_CENTER_PATH)
    return "\n".join(lines)


def notifier_of(state: Any) -> Any:
    """운영센터 알림 발송기 하나만 읽는다."""
    return getattr(state, "ops_alert_notifier", None)


def base_url_of(state: Any) -> str:
    return str(getattr(getattr(state, "settings", None), "public_base_url", "") or "")


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
        if await store.channel_abandoned(alert_id, channel):
            continue
        try:
            sent = await notifier._send(channel, message=message, subject=subject)
        except Exception as exc:
            # 채널 코드와 예외 종류만 남긴다 — 본문·주소·키는 절대 넣지 않는다.
            logger.warning("ops_alert_send_failed channel=%s error=%s",
                           channel, type(exc).__name__)
            sent = False
        if sent:
            await store.record_success(alert_id, channel)
            result["sent"] += 1
        else:
            await store.record_failure(alert_id, channel)
            result["failed"] += 1
    await store.complete(alert_id, tuple(notifier.channels))
    return result


async def retry_pending_alerts(state: Any, *, limit: int = RETRY_BATCH,
                               preferred: str | None = None) -> dict:
    """대기함을 다시 보낸다 — 이미 보낸 채널로는 다시 가지 않는다."""
    store = getattr(state, "ops_alert_store", None)
    notifier = notifier_of(state)
    summary = {"sent": 0, "failed": 0, "processed": 0}
    if store is None or notifier is None or not getattr(notifier, "channels", None):
        return summary
    base_url = base_url_of(state)
    await store.materialize_due_summaries()
    for entry in await store.pending(limit=limit, preferred=preferred):
        result = await deliver_alert(store, notifier, entry, base_url=base_url)
        summary["sent"] += result["sent"]
        summary["failed"] += result["failed"]
        summary["processed"] += 1
    return summary


def _lock_of(state: Any) -> asyncio.Lock:
    """발송 흐름을 한 번에 하나만 돌게 하는 락. 처음 쓸 때 만든다.

    단일 프로세스 기준이다. 접수 두 건이 거의 동시에 들어와 백그라운드 작업
    두 개가 같은 대기분을 집으면, 영수증 확인과 발송 사이 틈 때문에 같은
    채널로 두 번 갈 수 있다. 락이 그 틈을 없앤다.
    CPython에서는 dispatch_pending_alerts가 프로세스 간 파일 락도 잡는다.
    """
    lock = getattr(state, "ops_alert_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        state.ops_alert_lock = lock
    return lock


async def _deliver_in_background(state: Any, *, preferred: str | None = None) -> None:
    """적재된 건과 오래된 대기분을 함께 보낸다. 예외는 밖으로 내지 않는다.

    전체를 락 안에서 돈다 — 동시에 뜬 두 작업이 같은 대기분을 함께 집어
    같은 채널로 두 번 보내는 일을 막는다(CPython은 프로세스 간 락도 사용).
    """
    try:
        await dispatch_pending_alerts(state, preferred=preferred)
    except Exception as exc:
        logger.warning("ops_alert_dispatch_failed stage=background error=%s",
                       type(exc).__name__)
        return


async def dispatch_pending_alerts(state: Any, *, limit: int = RETRY_BATCH,
                                  preferred: str | None = None, sleep=asyncio.sleep) -> dict:
    async with _lock_of(state):
        process_lock = getattr(state, "ops_alert_process_lock", None)
        if process_lock is None:
            return await retry_pending_alerts(state, limit=limit, preferred=preferred)
        # The CPython host may have several workers on one SQLite outbox.
        # Do not block the event loop or leave a lock acquired by a cancelled thread.
        while not process_lock.acquire(wait=False):
            await sleep(0.1)
        try:
            return await retry_pending_alerts(state, limit=limit, preferred=preferred)
        finally:
            process_lock.release()


async def daily_summary_loop(state: Any, *, sleep=asyncio.sleep) -> None:
    """Check on startup, then hourly; only closed KST days become summaries."""
    while True:
        await _deliver_in_background(state)
        await sleep(3600)


def install_daily_summary_timer(app: Any, *, process_lock: Any) -> None:
    """CPython lifespan owns one timer; stop it before database shutdown."""
    task = None

    async def start():
        nonlocal task
        app.state.ops_alert_process_lock = process_lock
        if notifier_of(app.state) is not None:
            task = asyncio.create_task(daily_summary_loop(app.state))

    async def stop():
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await drain_alert_tasks(app.state)
        process_lock.release()

    app.router.on_startup.append(start)
    app.router.on_shutdown.insert(0, stop)


def schedule_event_delivery(state: Any, *, alert_id: str) -> None:
    if notifier_of(state) is not None:
        _spawn(state, preferred=alert_id)


def _spawn(state: Any, *, preferred: str | None = None) -> None:
    """발송을 요청 응답 밖으로 뺀다.

    느리거나 멈춘 채널이 접수 응답을 붙잡지 않게 백그라운드 작업으로 돌린다.
    작업 참조를 app.state의 set에 보관했다가 끝나면 지운다 — 참조를 잃으면
    실행 중인 작업이 중간에 사라질 수 있다. 이벤트 루프가 없는 동기 호출
    경로(시험 대역 등)에서는 조용히 넘어가고, 건은 대기함에 남는다.
    """
    try:
        task = asyncio.create_task(_deliver_in_background(state, preferred=preferred))
    except RuntimeError:
        return
    tasks = getattr(state, "ops_alert_tasks", None)
    if tasks is None:
        tasks = set()
        state.ops_alert_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def enqueue_and_deliver(request: Any, *, kind: str, target_id: str,
                              label: str) -> None:
    """저장 성공 뒤 부르는 알림 다리 — 요청 안에서는 적재까지만 한다.

    채널 값이 없으면 쌓아만 둔다(지금 B66과 같은 동작). 어떤 예외도 밖으로
    내보내지 않는다. 발송은 백그라운드에서 이어진다.
    """
    state = request.app.state
    store = getattr(state, "ops_alert_store", None)
    if store is None:
        return
    try:
        entry = await store.enqueue(kind=kind, target_id=target_id, label=label)
    except Exception:
        return
    if entry is None:
        return
    if notifier_of(state) is None:
        return
    _spawn(state, preferred=entry["alert_id"])


async def drain_alert_tasks(state: Any) -> None:
    """시험·종료 경로가 백그라운드 발송을 기다릴 때 쓴다(요청 경로 아님)."""
    tasks = tuple(getattr(state, "ops_alert_tasks", ()) or ())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)