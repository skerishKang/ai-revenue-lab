// #7818: PADIEM 공용 처리방침·약관 (auth.padiem.net/privacy · /terms).
// (가) PADIEM 계정 공통 — 코드가 실제로 하는 것만 기술한다. 수집 항목의
// 코드 근거는 PR 본문 표에 둔다. (나) Chat — 기존 chat.padiem.net 문서
// 내용을 이 절로 옮겼다(원문 페이지는 공용 문서를 연결한다). (다) 러브트리 —
// 이슈 #7818 댓글(issuecomment-6903332192) 원문을 문장 그대로 둔다.
const esc = (value) => String(value)
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

const DOC_CSS = `:root{--bg:#f5f6f8;--panel:#fff;--text:#1c1e21;--muted:#5f6368;--primary:#1a73e8;--line:#dadce0;--card:#f0f4f9;color-scheme:light}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Pretendard,'Noto Sans KR',Inter,ui-sans-serif,system-ui,sans-serif;line-height:1.7}main{display:block;max-width:760px;margin:0 auto;padding:40px 24px 64px}h1{font-size:26px;letter-spacing:-.02em;margin:0 0 8px}.meta{color:var(--muted);font-size:13px;margin:0 0 24px}.card{background:var(--card);border-radius:12px;padding:16px 18px;margin:0 0 28px;font-size:14px}.card p{margin:6px 0}nav.toc{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:0 0 32px;font-size:14px}nav.toc strong{display:block;margin-bottom:6px}nav.toc a{color:var(--primary)}h2{font-size:20px;margin:40px 0 12px;padding-top:8px;border-top:1px solid var(--line)}h3{font-size:16px;margin:24px 0 8px}ul,ol{margin:8px 0;padding-left:22px}li{margin:4px 0}table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}th{background:var(--card);font-weight:600}code{font-size:.92em;background:var(--card);padding:1px 5px;border-radius:4px}a{color:var(--primary)}.back{display:inline-block;margin-bottom:16px;font-size:14px}footer.doc-foot{margin-top:48px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}footer.doc-foot nav{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}@media (prefers-color-scheme:dark){:root{--bg:#10151c;--panel:#1a232d;--text:#edf4fa;--muted:#9fb3c3;--primary:#7fb3f0;--line:#2d3a47;--card:#1e2c3a;color-scheme:dark}}`;

const docShell = ({ title, meta, toc, body }) => `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index, follow"><title>${esc(title)} — PADIEM 계정</title><meta name="referrer" content="no-referrer"><style>${DOC_CSS}</style></head><body><main><h1>${esc(title)}</h1><p class="meta">${meta}</p><nav class="toc" aria-label="목차"><strong>목차</strong>${toc}</nav>${body}<footer class="doc-foot"><nav><a href="/privacy">공용 개인정보처리방침</a><a href="/terms">공용 이용약관</a><a href="https://chat.padiem.net/privacy.html">Chat 개인정보처리방침 원문</a><a href="https://chat.padiem.net/terms.html">Chat 이용약관 원문</a></nav><p>PADIEM 계정으로 로그인합니다 · 하나의 계정으로 PADIEM 서비스를 이용할 수 있어요</p></footer></main></body></html>`;

const META_LINE = '시행일: 2026-11-16 · 버전: v1';

const commonPrivacy = `
<section id="common" aria-labelledby="common-title">
<h2 id="common-title">가. PADIEM 계정 공통</h2>
<div class="card"><p>PADIEM 계정은 Chat·러브트리 등 PADIEM 서비스가 함께 쓰는 하나의 로그인 계정입니다. 이 절은 계정을 만들고 쓸 때 PADIEM 인증 서버(auth.padiem.net)가 실제로 수집·처리하는 범위만을 기술합니다. 서비스별(아래 나·다 절)로 추가로 남는 기록은 각 절을 따릅니다.</p></div>
<h3>수집·처리하는 항목</h3>
<table>
<tr><th>항목</th><th>내용</th></tr>
<tr><td>이메일 주소</td><td>로그인 식별자로 사용합니다. 이메일 가입·로그인 입력값은 Chat 인증 확인 절차로 전달됩니다.</td></tr>
<tr><td>이름(선택)</td><td>이메일 가입 화면에서 직접 입력한 경우에만 Chat 인증 확인 절차로 함께 전달됩니다. 입력하지 않아도 가입할 수 있습니다.</td></tr>
<tr><td>비밀번호</td><td>평문으로 저장하지 않습니다. 입력값은 Chat 인증 확인 절차로 전달해 검증하는 데만 쓰고, PADIEM 인증 저장소(계정 데이터베이스)에는 기록하지 않습니다.</td></tr>
<tr><td>Google 계정 정보</td><td>Google 로그인을 고른 경우 Google이 보내 주는 이메일, 이름, 프로필 사진 URL을 받아 계정을 만듭니다. 허용된 항목만 암호화하여 보관합니다.</td></tr>
<tr><td>만 14세 이상 확인 기록</td><td>가입 화면에서 ‘만 14세 이상입니다’에 체크한 시각을 계정 기록과 함께 저장합니다.</td></tr>
<tr><td>접속 주소(IP) 요약값</td><td>주소를 그대로 저장하지 않고 일방향 요약값으로 바꿔 로그인·가입 속도 제한(남용 방지)에만 사용합니다.</td></tr>
<tr><td>브라우저 쿠키 1종(<code>__Host-padiem-auth-state</code>)</td><td>로그인 진행 상태를 확인하는 용도로 약 10분간 유지됩니다. 광고·추적용 쿠키는 사용하지 않습니다.</td></tr>
</table>
<h3>이용 목적</h3>
<ul>
<li>회원 식별과 로그인 유지, PADIEM 서비스 제공을 위한 계정 확인</li>
<li>남용·보안 사고 방지(속도 제한, 오류 기록)</li>
<li>회원이 요청한 작업의 실행과 그 결과 전달, 문의 대응</li>
</ul>
<h3>만 14세 이상 가입</h3>
<ul>
<li>PADIEM 서비스는 만 14세 이상부터 가입할 수 있습니다. 만 14세 미만은 가입할 수 없습니다.</li>
<li>이메일 가입 화면에서 ‘만 14세 이상입니다’에 체크해야 가입이 진행됩니다. 체크하지 않고 제출하거나 ‘만 14세 미만’을 고르면 계정이 만들어지지 않습니다.</li>
</ul>
<h3>보관 기간 및 파기</h3>
<ul>
<li>로그인 진행 상태·인증 코드는 정해진 만료 시각이 지나면 사용할 수 없으며, 소진된 코드는 재사용할 수 없습니다.</li>
<li>속도 제한 기록은 해당 시간대가 지나면 버려지고, 별도 조치가 없어도 다음 시간대에 다시 시도할 수 있습니다.</li>
<li>계정 삭제가 끝나면 인증 서버의 계정 기록(로그인 연결·인증 기록 포함)을 삭제하고, 삭제 처리 사실은 되살아나지 않게 막는 데만 필요한 기간 뒤에 지웁니다.</li>
<li>일부 보안·감사 기록은 법령이 요구한 기간 동안만 별도 보관 후 파기합니다.</li>
</ul>
<h3>문의</h3>
<ul>
<li>계정·개인정보 관련 문의: <a href="mailto:ceo@padiem.net">ceo@padiem.net</a></li>
</ul>
</section>`;

const chatPrivacy = `
<section id="chat" aria-labelledby="chat-title">
<h2 id="chat-title">나. PADIEM Chat (chat.padiem.net)</h2>
<div class="card"><p>아래는 AI 업무 도우미 서비스 PADIEM Chat의 문서 내용입니다. 원문 페이지는 <a href="https://chat.padiem.net/privacy.html">chat.padiem.net/privacy.html</a>에 있으며 같은 내용을 유지합니다.</p></div>
<h3>1. 수집·처리하는 개인정보</h3>
<h3>1-1. 계정 및 로그인</h3>
<ul>
<li>이메일 로그인: 로그인 식별자로 이메일 주소를 사용하며, 비밀번호는 평문으로 저장하지 않습니다.</li>
<li>Google 로그인: Google 계정의 이메일, 이름, 프로필 사진 URL을 받아 계정을 만듭니다.</li>
<li>보관 위치: 서비스 계정 정보(이메일·프로필)는 회사가 운영하는 데이터베이스에 저장합니다.</li>
</ul>
<h3>1-2. 대화 기록</h3>
<ul>
<li>회원이 입력한 질문과 서비스가 생성한 답변을 계정별로 저장합니다. 저장된 대화는 화면의 대화 목록에서 다시 보거나 검색·삭제할 수 있습니다.</li>
<li>답변 생성을 위해 입력 내용은 AI 처리 위탁 업체로 전달됩니다. 첨부한 문서·이미지도 답변 생성에만 사용됩니다.</li>
</ul>
<h3>1-3. PC 연결</h3>
<ul>
<li>회원이 PC를 서비스에 연결하면 기기 식별 정보(기기 ID, 페어링 상태)를 저장합니다.</li>
<li>연결된 PC의 파일 목록 조회·파일 읽기·브라우저 동작 등의 동작은 <strong>회원이 그 대화에서 요청한 경우에만</strong> 실행되며, 실행 전에 매번 계정·기기 권한을 다시 확인합니다.</li>
<li>파일 저장·수정·삭제 같은 변경 동작은 회원의 요청에 그 대상이 담긴 경우에만 선언되고, 실행은 별도 확인 절차를 거칩니다.</li>
</ul>
<h3>1-4. Google Drive · Google Calendar 읽기</h3>
<ul>
<li>연결한 회원에 한해 <strong>읽기 전용</strong>으로만 접근합니다 — Drive: <code>drive.readonly</code>, Calendar: <code>calendar.readonly</code>. 쓰기·삭제 권한은 요청하거나 저장하지 않습니다.</li>
<li>읽은 결과(파일 목록·일정)는 회원의 질문에 답하는 데만 사용되고, 다른 회원과 공유되지 않습니다.</li>
<li>Google에서 받은 접근 토큰·갱신 토큰은 별도 OAuth 서버에 암호화(봉인)하여 보관하고, 도구 실행 시에는 단기 접근 권한만 발급해 전달합니다. 채팅 화면·모델·로그로 토큰이 노출되지 않습니다.</li>
<li>연결을 끊거나 권한을 뺏으면(계정 삭제 포함) 저장된 권한 정보와 봉인 토큰은 더 이상 사용할 수 없습니다.</li>
</ul>
<h3>1-5. 웹 푸시 알림</h3>
<ul>
<li>알림 수신을 동의한 기기의 구독 정보(엔드포인트 URL, 암호화 키)를 서버에만 저장합니다. 구독 정보는 화면 응답·로그에 노출되지 않고, 식별 불가능한 요약값으로만 관리됩니다.</li>
</ul>
<h3>1-6. 쿠키 · 세션</h3>
<ul>
<li>로그인 상태 유지를 위해 인증 쿠키(<code>padiem_session</code>) 1종을 사용합니다. 광고·추적용 쿠키는 사용하지 않습니다.</li>
</ul>
<h3>2. 개인정보의 이용 목적</h3>
<ul>
<li>회원 식별과 로그인 유지, 서비스 제공(대화 답변, PC 작업, Drive·Calendar 조회, 알림)</li>
<li>회원이 요청한 작업의 실행과 그 결과 전달, 문의 대응</li>
<li>서비스 안정성 확보(남용·보안 사고 방지, 오류 기록)</li>
</ul>
<h3>3. 보관 기간 및 파기</h3>
<ul>
<li>대화 기록: 회원이 대화를 삭제하면 목록과 검색에서 즉시 사라지고, 30일 동안 보관된 뒤 서버에서 완전히 삭제됩니다(첨부한 원본 파일 포함). 회원 탈퇴 시에는 대화를 포함한 계정 데이터가 즉시 삭제됩니다.</li>
<li>계정 삭제: 계정 삭제 기능(<strong>설정 → 계정 삭제</strong>)를 제공합니다. 마지막 확인 절차(가입 이메일과 동일한 입력) 후 대화 기록, 캘린더 기록 등 해당 회원 소유 데이터를 일괄 삭제하고 로그인 계정도 삭제합니다.</li>
<li>연결 해제: Drive 연결 해제 시 저장된 Drive 권한 정보를 즉시 무효화합니다.</li>
<li>일부 보안·감사 기록은 법령이 요구한 기간 동안만 별도 보관 후 파기합니다.</li>
</ul>
<h3>4. 개인정보의 제3자 제공 및 처리 위탁</h3>
<ul>
<li>회사는 회원의 사전 동의나 법령 근거 없이 개인정보를 제3자에게 제공하지 않습니다.</li>
<li>처리 위탁: (가) 서비스 호스팅·데이터 저장, (나) AI 답변 생성(입력 내용·첨부 문서의 처리), (다) Google 로그인·Drive·Calendar 연동은 각각 위탁 업체를 통해 수행됩니다. 위탁 업체와 업무 내용·보유 기간은 호스팅·데이터 저장은 Cloudflare, Google Cloud에 위탁합니다. AI 답변 생성은 “AI 응답 생성을 위한 처리 위탁”이며 위탁 업체명은 본 방침에 기재하지 않습니다(요청 시 고지).</li>
<li>AI 답변 생성 위탁 업체는 회사가 정한 범위(요청 처리) 외의 목적으로 회원 내용을 사용하지 않도록 계약으로 제한합니다.</li>
</ul>
<h3>5. Google 사용자 데이터의 제한적 사용 (Limited Use)</h3>
<div class="card">
<p>Padiem 앱의 Google API로부터 받은 사용자 정보의 사용 및 다른 앱으로의 전송은 제한적 사용 요건을 포함하여 Google API 서비스 사용자 데이터 정책을 준수합니다.</p>
<p lang="en">Padiem's use and transfer to any other app of information received from Google APIs will adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy" rel="noopener">Google API Services User Data Policy</a>, including the Limited Use requirements.</p>
</div>
<h3>6. 이용자 권리</h3>
<ul>
<li>회원은 언제든 자신의 개인정보를 열람하고, 잘못된 정보를 정정하고, 삭제를 요구할 수 있습니다. 화면의 대화 삭제·계정 삭제 기능으로 직접 처리할 수 있으며, 그 외 요청은 아래 연락처로 해 주세요.</li>
</ul>
<h3>7. 개인정보 보호책임자</h3>
<div class="card"><ul>
<li>성명: 강혜림(대표)</li>
<li>연락처: <a href="mailto:ceo@padiem.net">ceo@padiem.net</a></li>
</ul></div>
<h3>8. 방침 변경</h3>
<p>본 방침을 변경하면 시행일과 함께 이 페이지에 게시합니다. 중요한 변경은 서비스 안내로 알립니다.</p>
<section lang="en" aria-label="Privacy Policy — Summary (English)">
<h3>Privacy Policy — Summary (English)</h3>
<ul>
<li><strong>Account:</strong> email (or Google sign-in: email, name, profile photo URL) stored to create your account.</li>
<li><strong>Conversations:</strong> your questions and the assistant's answers are stored per account; you can delete each conversation or your whole account (Settings → Delete account).</li>
<li><strong>Connected PC:</strong> device identifiers for a paired computer. File listing, reading, browser actions and writes run <strong>only when you ask for them in a conversation</strong>, with ownership re-verified each time.</li>
<li><strong>Google Drive &amp; Calendar:</strong> read-only access (<code>drive.readonly</code>, <code>calendar.readonly</code>) for users who connect them. Tokens are stored sealed on a separate OAuth server; tool execution receives only short-lived access leases.</li>
<li><strong>Web push:</strong> for opted-in devices, the subscription endpoint and keys are stored server-side only and never echoed to screens or logs.</li>
<li><strong>Cookies:</strong> one authentication cookie (<code>padiem_session</code>). No advertising or tracking cookies.</li>
<li><strong>Processors:</strong> hosting/storage is delegated to Cloudflare and Google Cloud; AI answer generation is delegated under contract (“AI 응답 생성을 위한 처리 위탁”, processor not named); Google sign-in/Drive/Calendar integration runs through Google. No personal data is sold or shared without a legal basis.</li>
<li><strong>Limited Use:</strong> Padiem's use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements.</li>
<li><strong>Operator:</strong> PADIEM(파디엠), CEO 강혜림 — contact ceo@padiem.net. Privacy officer: 강혜림 (CEO). Effective date: 2026-11-10.</li>
</ul>
</section>
</section>`;

// #7818 PR 1 원문: 이슈 #7818 댓글(issuecomment-6903332192) '러브트리 절
// 전문(확정, 2026-11-16)'. 문장 그대로 둔다.
const lovetreePrivacy = `
<section id="lovetree" aria-labelledby="lovetree-title">
<h2 id="lovetree-title">다. 러브트리</h2>
<h3>1. 내가 남기는 기록(트리·순간)</h3>
<p>① 받는 것: 트리 이름, 순간마다 영상·웹 주소, 제목, 메모, 감정, 날짜, 꼬리표, 순간끼리의 연결, 보드 배치.</p>
<p>② 쓰는 곳: 책·보드·지도·그래프로 다시 보여 주기, 꼬리표 정리 제안(내 기기 안에서 규칙으로 계산 — 외부 AI로 보내지 않음).</p>
<p>③ 보이는 사람: 기본은 나만. 공유 링크를 만들면 링크를 받은 사람. 둘러보기에 소개를 켜면 누구나(기본 꺼짐, 무료로 켜고 끔). 공개 화면에는 내 이름·아이디·이메일을 보여 주지 않음.</p>
<p>④ 지우는 때: 순간·트리를 지우면 바로. 탈퇴하면 전부.</p>
<h3>2. 올린 사진</h3>
<p>① 받는 것: 순간에 올린 사진 파일(사진 1장 최대 8MB).</p>
<p>② 쓰는 곳: 내 순간에 보여 주기.</p>
<p>③ 보이는 사람: 나만. 공유 링크·둘러보기·미리보기 카드에는 쓰지 않음.</p>
<p>④ 지우는 때: 사진을 지우면 바로. 탈퇴하면 계정의 사진 보관함 전체.</p>
<h3>3. 공유 링크</h3>
<p>① 받는 것: 공유를 만든 트리와 공유 주소.</p>
<p>② 쓰는 곳: 링크를 받은 사람이 로그인 없이 감상. 카카오톡 등에 붙이면 트리 제목·순간 수·영상 썸네일로 미리보기 카드를 만듦.</p>
<p>③ 보이는 사람: 링크를 가진 사람. 공유를 취소하면 그 즉시 열리지 않음.</p>
<p>④ 지우는 때: 공유 취소 또는 탈퇴 때.</p>
<h3>4. 둘러보기 활동(반응·댓글·즐겨찾기·신고·차단)</h3>
<p>① 받는 것: 다른 트리에 남긴 반응·댓글·즐겨찾기, 신고와 그 사유, 차단 목록.</p>
<p>② 쓰는 곳: 둘러보기 표시, 신고 검토(운영진).</p>
<p>③ 보이는 사람: 반응·댓글은 그 트리를 보는 사람. 신고·차단은 운영진만.</p>
<p>④ 지우는 때: 탈퇴하면 전부.</p>
<h3>5. 의견 보내기</h3>
<p>① 받는 것: 의견 내용, 분류, 함께 보낼 정보(보던 화면·화면 크기·테마·버전·로그인 여부·트리 번호 — 보낼 때 고를 수 있음). 내용 속 전화번호·이메일 같은 개인정보는 저장 전에 가림.</p>
<p>② 쓰는 곳: 운영진이 읽고 답하고 고치기.</p>
<p>③ 보이는 사람: 나와 운영진.</p>
<p>④ 지우는 때: 탈퇴하면 로그인해 보낸 의견과 답글 전부. 로그인 없이 보낸 의견은 계정과 이어지지 않으며, 받은 날부터 6개월 뒤 자동으로 지웁니다.</p>
<h3>6. AI 명예회원</h3>
<p>러브트리는 운영진이 만든 ‘AI 명예회원’(서비스를 미리 써 보는 시험 고객) 계정을 둡니다. 이 계정의 트리는 둘러보기에 ‘AI 명예회원’ 표시가 붙고, 이 계정이 쓴 사용 일지·의견은 서비스 개선에만 씁니다. 실제 사람의 개인정보는 들어 있지 않습니다.</p>
<h3>7. 밖으로 나가는 곳</h3>
<ul>
<li>YouTube: 영상 주소를 넣으면 제목을 가져오려고 영상 주소를 YouTube에 물음(서버). 썸네일은 내 브라우저가 YouTube 그림 서버에서 직접 불러오고(주소 출처 정보 보내지 않음), 재생은 youtube-nocookie 주소로 함.</li>
<li>Cloudflare: 화면 파일 전달과 요청 중계.</li>
<li>기록 저장: PADIEM이 직접 운영하는 서버.</li>
</ul>
<h3>8. 운영 기록</h3>
<p>요청 처리 기록, 역할 변경 기록, 신고 처리 기록은 90일 뒤 자동으로 지웁니다. 탈퇴 처리 사실(되돌릴 수 없게 바꾼 계정 번호와 탈퇴 시각)은 지운 기록이 되살아나지 않게 막는 데만 쓰고, 탈퇴 후 90일 뒤 자동으로 지웁니다.</p>
<h3>9. 내 기기에 저장하는 것</h3>
<p>테마, 마지막으로 보던 위치, 보기 방식, 첫 안내를 봤는지, 영상 상태 같은 화면 설정을 브라우저 저장소에 둠. 서버로 보내지 않으며 브라우저에서 지울 수 있음.</p>
</section>`;

const commonTerms = `
<section id="common" aria-labelledby="common-title">
<h2 id="common-title">가. PADIEM 계정 공통</h2>
<div class="card"><p>이 약관은 PADIEM 계정(Chat·러브트리 등 PADIEM 서비스가 함께 쓰는 하나의 로그인 계정)의 공통 이용 조건과 서비스별 이용 조건으로 구성됩니다. 하나의 계정으로 PADIEM 서비스를 이용할 수 있습니다.</p></div>
<h3>1. 나이 조건</h3>
<ul>
<li>PADIEM 서비스는 만 14세 이상부터 가입할 수 있습니다. 만 14세 미만은 가입할 수 없습니다.</li>
<li>가입 화면에서 ‘만 14세 이상입니다’에 체크한 경우에만 계정이 만들어집니다.</li>
</ul>
<h3>2. 계정</h3>
<ul>
<li>PADIEM 계정은 이메일 또는 Google 계정으로 로그인하는 회원제로 운영됩니다.</li>
<li>계정과 비밀번호는 회원이 관리 책임을 부담합니다.</li>
<li>회원은 언제든 계정을 삭제할 수 있으며, 삭제 시 소유 데이터는 공용 개인정보처리방침 가 절의 보관 기준에 따라 처리됩니다.</li>
</ul>
<h3>3. 약관의 변경</h3>
<p>약관을 변경하면 시행일과 함께 이 페이지에 게시합니다. 변경된 약관은 게시 시점부터 적용됩니다.</p>
<h3>4. 준거법 · 분쟁 해결</h3>
<ul>
<li>준거법: 대한민국 법.</li>
<li>서비스 이용 관련 문의: <a href="mailto:ceo@padiem.net">ceo@padiem.net</a></li>
</ul>
</section>`;

const chatTerms = `
<section id="chat" aria-labelledby="chat-title">
<h2 id="chat-title">나. PADIEM Chat (chat.padiem.net)</h2>
<div class="card"><p>아래는 AI 업무 도우미 서비스 PADIEM Chat의 약관 내용입니다. 원문 페이지는 <a href="https://chat.padiem.net/terms.html">chat.padiem.net/terms.html</a>에 있으며 같은 내용을 유지합니다.</p></div>
<h3>1. 서비스의 내용</h3>
<ul>
<li>회원은 대화로 질문하고 AI 답변을 받습니다. 첨부한 문서·이미지의 내용도 답변에 활용될 수 있습니다.</li>
<li>회원이 자신의 PC를 연결하면, 회원이 그 대화에서 요청한 경우에 한해 파일 조회·파일 읽기·브라우저 확인 같은 PC 작업을 실행합니다. 파일 변경 동작은 별도 확인 절차를 거칩니다.</li>
<li>회원이 Google Drive·Google Calendar를 연결하면 읽기 전용(<code>drive.readonly</code>, <code>calendar.readonly</code>)으로 내용을 조회해 답변에 활용합니다. 쓰기·삭제는 하지 않습니다.</li>
<li>알림 수신에 동의한 회원에게 웹 푸시로 알림을 보낼 수 있습니다.</li>
</ul>
<h3>2. 계정</h3>
<ul>
<li>서비스는 이메일 또는 Google 계정으로 로그인하는 회원제로 운영됩니다.</li>
<li>계정과 비밀번호는 회원이 관리 책임을 부담하며, 계정으로 이루어진 작업(PC 작업 포함)은 해당 회원의 요청으로 봅니다.</li>
<li>회원은 언제든 설정에서 계정을 삭제할 수 있으며, 삭제 시 소유 데이터는 개인정보처리방침 3조에 따라 처리됩니다(삭제 후 같은 이메일로 재가입할 수 있습니다).</li>
</ul>
<h3>3. 이용자의 금지행위</h3>
<ul>
<li>타인의 계정·PC·Google 데이터에 대한 무단 접근 또는 접근 시도</li>
<li>법령 위반 행위, 타인의 권리 침해, 서비스나 인프라에 대한 과부하·침입 시도</li>
<li>서비스가 제공하는 권한 범위(Drive·Calendar 읽기 전용 등)를 벗어난 사용 시도</li>
<li>위반 시 이용 제한·계정 삭제 등 조치할 수 있고, 법적 조치 대상이 될 수 있습니다.</li>
</ul>
<h3>4. AI 답변에 대하여</h3>
<ul>
<li>AI 답변은 부정확할 수 있습니다. 중요한 판단(법률·의료·금전·계약 등)은 답변만 믿고 하지 마세요.</li>
<li>PC 작업·Drive·Calendar 조회 결과는 실행 시점의 상태를 반영합니다.</li>
</ul>
<h3>5. 서비스의 변경 · 중단</h3>
<ul>
<li>회사는 서비스 품질 향상을 위해 기능을 변경할 수 있으며, 중요한 변경은 서비스 내 공지합니다.</li>
<li>설비 점검·천재지변 등 부득이한 사유로 서비스가 일시 중단될 수 있습니다.</li>
</ul>
<h3>6. 책임 제한</h3>
<ul>
<li>회사는 무료로 제공되는 서비스 범위에서 법령이 허용하는 한도 내에서 책임을 부담합니다.</li>
<li>회원이 요청해 실행한 PC 작업의 결과는 회원이 지정한 대상·범위에 따르며, 회원의 요청 내용과 다르게 확정된 작업은 실행 전 확인 절차에서 걸러집니다.</li>
<li>회원의 고의·과실로 인한 계정 도용 등의 피해에 대해 회사는 책임지지 않습니다.</li>
</ul>
<h3>7. 약관의 변경</h3>
<p>약관을 변경하면 시행일과 함께 이 페이지에 게시합니다. 변경된 약관은 게시 시점부터 적용됩니다.</p>
<h3>8. 준거법 · 분쟁 해결</h3>
<ul>
<li>준거법: 대한민국 법.</li>
<li>서비스 이용 관련 문의: <a href="mailto:ceo@padiem.net">ceo@padiem.net</a></li>
</ul>
<section lang="en" aria-label="Terms of Service — Summary (English)">
<h3>Terms of Service — Summary (English)</h3>
<ul>
<li>Padiem is an AI work assistant: ask questions, get answers, connect your PC (actions run only on your in-conversation request), and optionally connect Google Drive/Calendar <strong>read-only</strong>.</li>
<li>Accounts are email- or Google-based; you can delete your account and data at any time from Settings.</li>
<li>Do not access other people's accounts, PCs or data, or attempt to exceed the service's granted (read-only) scopes.</li>
<li>AI answers can be wrong — verify important decisions.</li>
<li>The service may change or pause; liability is limited to the extent permitted by law for a service of this kind.</li>
<li><strong>Operator:</strong> PADIEM(파디엠), CEO 강혜림 — contact ceo@padiem.net. Governing law: the Republic of Korea.</li>
</ul>
</section>
</section>`;

const privacyToc = `<a href="#common">가. PADIEM 계정 공통</a> · <a href="#chat">나. PADIEM Chat</a> · <a href="#lovetree">다. 러브트리</a>`;
const termsToc = `<a href="#common">가. PADIEM 계정 공통</a> · <a href="#chat">나. PADIEM Chat</a>`;

export function privacyPage() {
  return docShell({ title: '개인정보처리방침', meta: META_LINE, toc: privacyToc, body: commonPrivacy + chatPrivacy + lovetreePrivacy });
}

export function termsPage() {
  return docShell({ title: '이용약관', meta: META_LINE, toc: termsToc, body: commonTerms + chatTerms });
}
