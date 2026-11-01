# 쉬운 오류 문구 2차 점검 후보

정적 검색으로 찾은 오류 코드·메시지 전달 후보다. 내부 분기와 이미 안전하게 매핑된 코드도 포함하며, 각 행이 실제 노출이라는 뜻은 아니다. 1차의 chat-transport.js와 app.js 스트리밍 구간은 제외했다. 미검토 행은 별도 확인이 필요하다.

| 위치 | 검색된 코드 |
| --- | --- |
| apps/padiem-chat/static/admin-models.js:493 | "실행 경로 원장을 사용할 수 없습니다. (" + String(err.message) + ")", "placeholder")); |
| apps/padiem-chat/static/admin-models.js:565 | alertMessage("실행 경로 저장 실패: " + String(err.message)); |
| apps/padiem-chat/static/admin-models.js:601 | throw new Error(typeof data?.error?.code === "string" ? data.error.code : "http_" + response.status); |
| apps/padiem-chat/static/admin-models.js:744 | root.replaceChildren(node("small", "이력 조회 불가: " + String(err.message))); |
| apps/padiem-chat/static/admin-models.js:765 | alertMessage("정책 저장 실패: " + String(err.message)); |
| apps/padiem-chat/static/admin-models.js:786 | alertMessage("롤백 미리보기 실패: " + String(err.message)); |
| apps/padiem-chat/static/app.js:305 | return error && error.code === "upstream_timeout" ? MESSAGE_LIFECYCLE.TIMED_OUT : MESSAGE_LIFECYCLE.FAILED; |
| apps/padiem-chat/static/app.js:895 | setNote(error instanceof Error ? error.message : uiT("file-read-failed"), "error"); |
| apps/padiem-chat/static/app.js:1119 | projectFormError.textContent = error instanceof Error ? error.message : uiT("project-files-load-failed"); |
| apps/padiem-chat/static/app.js:1172 | const message = data && data.error && typeof data.error.message === "string" ? data.error.message : uiT("project-file-save-failed"); |
| apps/padiem-chat/static/app.js:1177 | projectFormError.textContent = error instanceof Error ? error.message : uiT("project-file-save-failed"); |
| apps/padiem-chat/static/app.js:1197 | projectFormError.textContent = error instanceof Error ? error.message : uiT("project-file-delete-failed"); |
| apps/padiem-chat/static/app.js:1332 | const message = data && data.error && typeof data.error.message === "string" ? data.error.message : uiT("project-save-failed"); |
| apps/padiem-chat/static/app.js:1344 | projectFormError.textContent = error instanceof Error ? error.message : uiT("project-save-failed"); |
| apps/padiem-chat/static/app.js:1375 | ? data.error.message |
| apps/padiem-chat/static/app.js:1394 | projectFormError.textContent = error instanceof Error ? error.message : uiT("project-delete-failed"); |
| apps/padiem-chat/static/app.js:1959 | error instanceof Error && error.message ? error.message : uiT("auth-android-error") |
| apps/padiem-chat/static/app.js:2038 | ? data.error.message |
| apps/padiem-chat/static/app.js:2041 | error.code = data.error && typeof data.error.code === "string" ? data.error.code : "auth_error"; |
| apps/padiem-chat/static/app.js:2073 | error instanceof Error ? error.message : uiT("auth-error-generic"), |
| apps/padiem-chat/static/app.js:2097 | error instanceof Error ? error.message : uiT("auth-error-generic"), |
| apps/padiem-chat/static/app.js:2222 | error instanceof Error ? error.message : uiT("auth-error-generic"), |
| apps/padiem-chat/static/app.js:2264 | error instanceof Error ? error.message : uiT("auth-error-generic"), |
| apps/padiem-chat/static/app.js:2328 | error instanceof Error ? error.message : uiT("auth-error-generic"), |
| apps/padiem-chat/static/app.js:2506 | ? data.error.message |
| apps/padiem-chat/static/app.js:2519 | setNote(error instanceof Error ? error.message : uiT("conversation-delete-failed"), "error"); |
| apps/padiem-chat/static/app.js:2628 | setNote(error instanceof Error ? error.message : uiT("conversation-load-failed"), "error"); |
| apps/padiem-chat/static/app.js:4273 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:4506 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:4825 | const code = data && typeof data.code === "string" ? data.code : ""; |
| apps/padiem-chat/static/app.js:4953 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:5044 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:5161 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:5751 | ? data.error.code |
| apps/padiem-chat/static/app.js:6031 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:6104 | status.textContent = error instanceof Error ? error.message : clawT("claw-approval-error"); |
| apps/padiem-chat/static/app.js:6377 | data && data.error && typeof data.error.code === "string" ? data.error.code : "", |
| apps/padiem-chat/static/app.js:6459 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:6541 | setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error"); |
| apps/padiem-chat/static/app.js:6564 | setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error"); |
| apps/padiem-chat/static/app.js:6674 | setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error"); |
| apps/padiem-chat/static/app.js:6709 | setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error"); |
| apps/padiem-chat/static/app.js:6772 | const code = data && data.error && typeof data.error.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/app.js:7026 | setClawRunHistoryStatus(error instanceof Error ? error.message : clawT("claw-runs-error")); |
| apps/padiem-chat/static/calendar.js:1134 | function showError(code, serverCode = "") { |
| apps/padiem-chat/static/calendar.js:1147 | note.textContent = (korean() ? "참고 코드: " : "Reference code: ") + serverCode; |
| apps/padiem-chat/static/calendar.js:1360 | ? data.error.code.slice(0, 80) : ""; |
| apps/padiem-chat/static/calendar.js:1361 | showError(response.status, serverCode); |
| apps/padiem-chat/static/claw-home-choices.js:127 | const code = denial?.error?.code; |
| apps/padiem-chat/static/claw-office-chooser.js:39 | const code = body?.error?.code; |
| apps/padiem-chat/static/claw-office-chooser.js:119 | setMessage(error.message); |
| apps/padiem-chat/static/claw-office-chooser.js:151 | setMessage(error.message); |
| apps/padiem-chat/static/claw-office-chooser.js:180 | setMessage(error.message); |
| apps/padiem-chat/static/claw-office-chooser.js:247 | setMessage(error.message); |
| apps/padiem-chat/static/claw-pc-enrollment-consent.js:519 | typeof error.code === "string" ? error.code : "", |
| apps/padiem-chat/static/claw-web-xlsx-sources.js:174 | const reason = data?.error?.code; |
| apps/padiem-chat/static/claw-web-xlsx-sources.js:1009 | report(error.message); |
| apps/padiem-chat/static/claw-web-xlsx-sources.js:1064 | report(error.message); |
| apps/padiem-chat/static/claw-web-xlsx-sources.js:1102 | report(error.message); |
| apps/padiem-chat/static/claw-web-xlsx-sources.js:1144 | report(error.message); |
| apps/padiem-chat/static/councillor/councillor.js:666 | fail(error && error.message ? error.message : String(error)); |
| apps/padiem-chat/static/file-lane.js:35 | if (!ticketResponse.ok \|\| !ticket?.ok) throw new Error(ticket?.error?.message \|\| "파일 업로드를 준비하지 못했습니다."); |
| apps/padiem-chat/static/meeting-capture.js:307 | catch (error) { say(error.message === "live_transcription_not_supported" ? "이 브라우저는 실시간 받아쓰기를 지원하지 않습니다." : statuses.meeting_start_failed); } |
| apps/padiem-chat/static/meeting-capture.js:368 | throw new Error((data && data.error && data.error.code) \|\| "ledger_unavailable"); |
| apps/padiem-chat/static/meeting-capture.js:558 | const code = error?.code \|\| ""; |
| apps/padiem-chat/static/message-lifecycle.js:947 | note.textContent = error instanceof Error ? error.message : "확인 요청을 처리하지 못했습니다."; |
| apps/padiem-chat/static/outputs.js:483 | const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "답변을 저장하지 못했습니다."; |
| apps/padiem-chat/static/outputs.js:519 | setStatus(error instanceof Error ? error.message : "저장한 답변을 불러오지 못했습니다.", "error"); |
| apps/padiem-chat/static/outputs.js:551 | setStatus(error instanceof Error ? error.message : "제목을 바꾸지 못했습니다.", "error"); |
| apps/padiem-chat/static/outputs.js:574 | setStatus(error instanceof Error ? error.message : "저장한 답변을 삭제하지 못했습니다.", "error"); |
| apps/padiem-chat/static/pc-connect-flow.js:150 | const code = body?.error?.code; |
| apps/padiem-chat/static/pc-connect-flow.js:194 | code = typeof refused?.error?.code === "string" ? refused.error.code : null; |
| apps/padiem-chat/static/pc-pairing-card.js:193 | const code = body?.error?.code; |
| apps/padiem-chat/static/pc-pairing-card.js:248 | code = typeof refused?.error?.code === "string" ? refused.error.code : null; |
| apps/padiem-chat/static/product-capabilities.js:745 | ? text(data.error.message, 200) |
| apps/padiem-chat/static/util-menu.js:39 | const message = known \|\| (error && error.message === GEN_OFFLINE_COPY ? GEN_OFFLINE_COPY : GEN_ERROR_FALLBACK); |
| apps/padiem-chat/static/util-menu.js:98 | error.code = typeof data?.error?.code === "string" ? data.error.code : ""; |
| apps/padiem-chat/static/util-menu.js:102 | return (data && data.answer) ? data.answer : (data && data.message ? data.message : JSON.stringify(data)); |
| apps/padiem-chat/static/util-menu.js:578 | ? refused.error.code : ""; |
| apps/padiem-chat/static/util-menu.js:1412 | const matched = /^http_(\d+)$/.exec(String((error && error.message) \|\| "")); |
| reference/business-66-padiem-quote-v1/admin-inquiries.js:19 | throw new Error(payload?.error?.code \|\| "request_failed"); |
| reference/business-66-padiem-quote-v1/admin-saved-skill-candidates.js:43 | const error = new Error(payload?.error?.code \|\| "request_failed"); |
| reference/business-66-padiem-quote-v1/admin-saved-skill-candidates.js:119 | statusLine.textContent = "승인 결정 실패: " + safeText(error.message); |
| reference/business-66-padiem-quote-v1/admin-saved-skill-candidates.js:174 | statusLine.textContent = "상세 조회 실패: " + safeText(error.message); |
| reference/business-66-padiem-quote-v1/admin-saved-skill-candidates.js:200 | statusLine.textContent = "조회 실패: " + safeText(error.message); |
| reference/business-66-padiem-quote-v1/admin-saved-skill-candidates.js:227 | access.textContent = error.message === "admin_forbidden" ? "관리자 권한이 없습니다." : "관리자 계정으로 로그인해 주세요."; |
| reference/business-66-padiem-quote-v1/admin.js:23 | const code = payload?.error?.code; |
| reference/business-66-padiem-quote-v1/admin.js:204 | id("policyStatus").textContent = error.message \|\| "모델 정책을 불러오지 못했습니다."; |
| reference/business-66-padiem-quote-v1/admin.js:234 | id("policyStatus").textContent = error.message \|\| "모델 설정을 저장하지 못했습니다."; |
| reference/business-66-padiem-quote-v1/admin.js:303 | id("access").textContent = error.message \|\| "관리자 권한을 확인하지 못했습니다."; |
| reference/business-66-padiem-quote-v1/admin.js:328 | } catch (error) { id("noticeStatus").textContent = error.message; } |
| reference/business-66-padiem-quote-v1/app.js:1103 | const message = result ? TEMPLATE_RESULT_MESSAGES[result.code] : null; |
| reference/business-66-padiem-quote-v1/app.js:1397 | toast(result && result.message ? result.message : "PDF 다운로드에 실패했습니다. 잠시 후 다시 시도해 주세요.", 4200); |
| reference/business-66-padiem-quote-v1/b66-voice-wiring.js:273 | if (!response.ok) { const code = payload && payload.error && payload.error.code; throw new Error(code \|\| ERROR_CODES.TRANSCRIBE_FAILED); } |
| reference/business-66-padiem-quote-v1/company-profile-settings.js:350 | var code = result.data && result.data.error ? result.data.error.code : null; |
| reference/business-66-padiem-quote-v1/easy-mode.js:1111 | ? bridge.errorText(result.code) |
| reference/business-66-padiem-quote-v1/easy-mode.js:1310 | ? bridge.errorText(result.code) |
| reference/business-66-padiem-quote-v1/guided-draft-server.js:15 | return { ok: false, status: response.status, error: payload?.error?.code \|\| "guided_state_unavailable" }; |
| reference/business-66-padiem-quote-v1/guided-draft-server.js:33 | return { ok: false, error: data?.error?.code \|\| "guided_history_unavailable" }; |
| reference/business-66-padiem-quote-v1/member-inquiry.js:39 | const code = result?.error?.code; |
| reference/business-66-padiem-quote-v1/quote-drive-client.js:372 | var message = data && data.error && typeof data.error.message === "string" ? data.error.message : null; |
| reference/business-66-padiem-quote-v1/quote-drive-contract.js:440 | return { ok: false, code: (err && err.code) === "unsafe_json_key" ? "unsafe_json_key" : "invalid_json" }; |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:353 | setStatus(result.message \|\| "B66 계정이 변경되어 Google 계정 연결을 취소했습니다.", "warn"); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:361 | setStatus(result.message \|\| "Google 계정 연결에 실패했습니다.", "error"); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:425 | setStatus(outcome.message \|\| "계정 변경으로 저장을 중단했습니다.", "warn"); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:435 | setStatus(outcome.message, "warn"); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:438 | setStatus("저장에 실패했습니다. 잠시 후 다시 시도해 주세요.", "error", outcome.code); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:472 | setStatus(outcome.message, "warn"); |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:477 | setStatus(outcome.code === "pending_pair_stale" |
| reference/business-66-padiem-quote-v1/quote-drive-ui.js:564 | setStatus(typeof opened.code === "string" && /^(template_\|saved_skill_)/.test(opened.code) |
| reference/business-66-padiem-quote-v1/quote-embed-bridge.js:218 | code: result && typeof result.code === "string" ? result.code : "render_model_failed" |
| reference/business-66-padiem-quote-v1/quote-embed-bridge.js:244 | code: result && typeof result.code === "string" ? result.code : "render_failed" |
| reference/business-66-padiem-quote-v1/quote-extraction.js:295 | error: err && typeof err.code === "string" ? err.code : "invalid_extraction" |
| reference/business-66-padiem-quote-v1/quote-skill-assisted.js:197 | lines.push("양식 후보: 준비 실패 (" + (outcome.code \|\| "candidate_unavailable") + ")"); |
| reference/business-66-padiem-quote-v1/quote-skill-assisted.js:276 | ? data.error.code |
| reference/business-66-padiem-quote-v1/quote-skill-assisted.js:294 | code: result && result.code ? result.code : "candidate_unavailable" |
| reference/business-66-padiem-quote-v1/quote-skill-assisted.js:589 | state.analysis = { ok: false, code: result && result.code ? result.code : "analysis_failed" }; |
| reference/business-66-padiem-quote-v1/quote-skill-auto.js:726 | code: result.ok ? "" : result.code, |
| reference/business-66-padiem-quote-v1/quote-skill-auto.js:727 | message: result.ok ? "" : result.message |
| reference/business-66-padiem-quote-v1/quote-skill-auto.js:787 | state.analysis = { ok: false, code: result && result.code ? result.code : "analysis_failed" }; |
| reference/business-66-padiem-quote-v1/quote-skill-manual.js:426 | ? data.error.code |
| reference/business-66-padiem-quote-v1/quote-skill-ui.js:247 | ? payload.error.code |
