/*
 * #7460 · Unified Util tool manifest (single source of truth).
 *
 * Cards on the Util first screen, chips on every tool screen, the expandable
 * Util submenu in the left sidebar, the form inputs, and Stage 2 (#7461)
 * conversational intake in Chat all read from this one frozen registry.
 *
 * File boundary: Util code lives only in static/util-*.js and util-*.css;
 * app.js gains no logic (R5 #7216). No DOM sinks, no external origins, no
 * browser storage.
 */
(() => {
  "use strict";

  const ROUTE_PREFIX = "#util";

  function deepFreeze(value) {
    if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
    Object.keys(value).forEach((key) => {
      deepFreeze(value[key]);
    });
    return Object.freeze(value);
  }

  function makeField(spec) {
    return deepFreeze({
      key: spec.key,
      type: spec.type || "text",
      required: Boolean(spec.required),
      advanced: Boolean(spec.advanced),
      label: spec.label,
      placeholder: spec.placeholder || { ko: "", en: "" },
      question: spec.question,
      rows: spec.rows || 0,
      maxLength: spec.maxLength || 0,
      accept: spec.accept || "",
      defaultValue: spec.defaultValue !== undefined ? spec.defaultValue : "",
      options: Array.isArray(spec.options) ? spec.options : [],
    });
  }

  function makeTool(spec) {
    const route = ROUTE_PREFIX + "/" + spec.id;
    return deepFreeze({
      id: spec.id,
      name: spec.name,
      chip: spec.chip,
      desc: spec.desc,
      ko: { title: spec.name.ko, chip: spec.chip.ko, desc: spec.desc.ko },
      en: { title: spec.name.en, chip: spec.chip.en, desc: spec.desc.en },
      icon: spec.icon,
      category: spec.category,
      route: route,
      requiredTier: spec.requiredTier || "free",
      authRequired: spec.authRequired !== false,
      serverPath: spec.serverPath !== undefined ? spec.serverPath : null,
      slashCommand: spec.slashCommand || "",
      fields: spec.fields.map(makeField),
    });
  }

  const CATEGORIES = deepFreeze([
    { id: "writing", label: { ko: "문서·홍보 작성", en: "Writing & promo" } },
    { id: "document", label: { ko: "기록·문서 변환", en: "Notes & conversion" } },
    { id: "business", label: { ko: "견적·실무 문서", en: "Quotes & spreadsheets" } },
  ]);

  const TOOLS = deepFreeze([
    makeTool({
      id: "speech",
      icon: "✎",
      category: "writing",
      requiredTier: "free",
      serverPath: "/api/chat/stream",
      slashCommand: "/축사",
      name: { ko: "축사·인사말", en: "Congratulatory address" },
      chip: { ko: "축사·인사말", en: "Address" },
      desc: { ko: "행사 축사·인사말 초안 생성·저장", en: "Draft and save an address for an event" },
      fields: [
        {
          key: "event",
          type: "text",
          required: true,
          advanced: false,
          label: { ko: "행사명", en: "Event name" },
          placeholder: { ko: "예: 제78주년 광복절 기념식", en: "e.g. 78th Liberation Day Ceremony" },
          question: { ko: "어떤 행사의 축사·인사말인가요? 행사명을 알려 주세요.", en: "Which event is this address for? Please share the event name." },
        },
        {
          key: "audience",
          type: "text",
          required: false,
          advanced: false,
          label: { ko: "참석 대상", en: "Audience" },
          placeholder: { ko: "예: 지역 주민 200명", en: "e.g. 200 local residents" },
          question: { ko: "주로 누가 참석하나요?", en: "Who will attend the event?" },
        },
        {
          key: "author",
          type: "text",
          required: false,
          advanced: false,
          label: { ko: "직책과 이름", en: "Title & speaker name" },
          placeholder: { ko: "예: 지역구 국회의원 김의민", en: "e.g. Council member Kim" },
          question: { ko: "인사말을 전하는 분의 직책과 이름은 무엇인가요?", en: "What are the speaker's title and name?" },
        },
        {
          key: "length",
          type: "select",
          required: false,
          advanced: false,
          defaultValue: "medium",
          label: { ko: "분량", en: "Length" },
          question: { ko: "분량은 1분·3분·5분 중 어느 정도가 좋을까요?", en: "How long should it be (1, 3, or 5 minutes)?" },
          options: [
            { value: "short", label: { ko: "1분", en: "1 min" } },
            { value: "medium", label: { ko: "3분", en: "3 min" } },
            { value: "long", label: { ko: "5분", en: "5 min" } },
          ],
        },
        {
          key: "date",
          type: "date",
          required: false,
          advanced: true,
          label: { ko: "행사 날짜", en: "Event date" },
          question: { ko: "행사 날짜가 언제인가요?", en: "When is the event?" },
        },
        {
          key: "place",
          type: "text",
          required: false,
          advanced: true,
          label: { ko: "장소", en: "Venue" },
          placeholder: { ko: "예: 시청 대강당", en: "e.g. City Hall Auditorium" },
          question: { ko: "행사가 열리는 장소는 어디인가요?", en: "Where is the event held?" },
        },
        {
          key: "nature",
          type: "text",
          required: false,
          advanced: true,
          label: { ko: "행사 성격", en: "Event type" },
          placeholder: { ko: "예: 지역 행사", en: "e.g. Community gathering" },
          question: { ko: "행사의 성격이나 분위기를 간단히 알려 주세요.", en: "What kind of event or atmosphere is it?" },
        },
        {
          key: "message",
          type: "textarea",
          rows: 3,
          required: false,
          advanced: true,
          label: { ko: "주요 메시지", en: "Key message" },
          placeholder: { ko: "예: 함께 성장하는 지역사회", en: "e.g. Growing together as one community" },
          question: { ko: "꼭 담고 싶은 핵심 메시지가 있나요?", en: "Is there a core message you want to include?" },
        },
        {
          key: "emphasis",
          type: "textarea",
          rows: 3,
          required: false,
          advanced: true,
          label: { ko: "강조 내용", en: "Points to emphasize" },
          placeholder: { ko: "예: 상생과 배려", en: "e.g. Mutual care and cooperation" },
          question: { ko: "특별히 강조하고 싶은 내용이 있나요?", en: "Any points you want emphasized?" },
        },
        {
          key: "tone",
          type: "select",
          required: false,
          advanced: true,
          defaultValue: "formal",
          label: { ko: "말투", en: "Tone" },
          question: { ko: "말투는 공식·따뜻한·간결 중 어떤 느낌으로 작성할까요?", en: "Which tone fits best: formal, warm, or concise?" },
          options: [
            { value: "formal", label: { ko: "공식", en: "Formal" } },
            { value: "warm", label: { ko: "따뜻한", en: "Warm" } },
            { value: "concise", label: { ko: "간결", en: "Concise" } },
          ],
        },
        {
          key: "style",
          type: "textarea",
          rows: 4,
          required: false,
          advanced: true,
          label: { ko: "기존 축사 샘플 (말투 반영)", en: "Sample address (style reference)" },
          placeholder: { ko: "기존 축사/인사말 원문 붙여넣기", en: "Paste a previous address to match its style" },
          question: { ko: "말투에 참고할 기존 축사·인사말 원문이 있다면 붙여넣어 주세요.", en: "Do you have a sample address whose style we should match?" },
        },
      ],
    }),
    makeTool({
      id: "sns",
      icon: "✦",
      category: "writing",
      requiredTier: "free",
      serverPath: "/api/chat/stream",
      slashCommand: "/홍보",
      name: { ko: "SNS 홍보", en: "SNS promo" },
      chip: { ko: "SNS 홍보", en: "SNS promo" },
      desc: { ko: "블로그·페이스북·인스타그램 초안", en: "Drafts for a blog, Facebook or Instagram" },
      fields: [
        {
          key: "event",
          type: "text",
          required: true,
          advanced: false,
          label: { ko: "행사명", en: "Topic / event" },
          placeholder: { ko: "예: 주민 정원 사업 설명회", en: "e.g. Community garden briefing" },
          question: { ko: "홍보할 행사나 소식 이름을 알려 주세요.", en: "What event or topic would you like to promote?" },
        },
        {
          key: "whenwhere",
          type: "text",
          required: false,
          advanced: false,
          label: { ko: "날짜·장소", en: "Date & place" },
          placeholder: { ko: "예: 10월 30일 오후 2시, 구청 소회의실", en: "e.g. Oct 30 2 PM, District Hall Room 2" },
          question: { ko: "일시와 장소 정보가 있다면 알려 주세요.", en: "When and where does it take place?" },
        },
        {
          key: "content",
          type: "textarea",
          rows: 4,
          required: true,
          advanced: false,
          label: { ko: "주요 내용", en: "Key details" },
          placeholder: { ko: "예: 정원 사업 신청 방법과 지원 금액 안내", en: "e.g. How to apply and subsidy details" },
          question: { ko: "게시글에 꼭 들어갈 주요 내용을 알려 주세요.", en: "What key details must be included in the post?" },
        },
        {
          key: "audience",
          type: "text",
          required: false,
          advanced: false,
          label: { ko: "대상 독자", en: "Target readers" },
          placeholder: { ko: "예: 구내 상인", en: "e.g. Local shop owners" },
          question: { ko: "주로 누구에게 보여줄 홍보글인가요?", en: "Who is the target audience?" },
        },
        {
          key: "memo",
          type: "textarea",
          rows: 4,
          required: false,
          advanced: false,
          label: { ko: "메모", en: "Extra notes" },
          placeholder: { ko: "예: 참석자에게 강조할 한 가지", en: "e.g. One highlight to emphasize" },
          question: { ko: "추가로 덧붙일 메모나 안내가 있나요?", en: "Any extra note or highlight to add?" },
        },
        {
          key: "tone",
          type: "select",
          required: false,
          advanced: false,
          defaultValue: "professional",
          label: { ko: "문체", en: "Tone" },
          question: { ko: "문체는 캐주얼·전문적·감성적 중 무엇이 좋을까요?", en: "Which tone works best: casual, professional, or emotional?" },
          options: [
            { value: "casual", label: { ko: "캐주얼", en: "Casual" } },
            { value: "professional", label: { ko: "전문적", en: "Professional" } },
            { value: "emotional", label: { ko: "감성적", en: "Emotional" } },
          ],
        },
        {
          key: "platform",
          type: "choice",
          required: false,
          advanced: false,
          defaultValue: "blog",
          label: { ko: "게시할 곳", en: "Where it goes" },
          question: { ko: "블로그·페이스북·인스타그램 중 어디에 올릴 게시글인가요?", en: "Which platform is this post for: blog, Facebook, or Instagram?" },
          options: [
            { value: "blog", label: { ko: "블로그", en: "Blog" } },
            { value: "facebook", label: { ko: "페이스북", en: "Facebook" } },
            { value: "instagram", label: { ko: "인스타그램", en: "Instagram" } },
          ],
        },
      ],
    }),
    makeTool({
      id: "meeting",
      icon: "▥",
      category: "document",
      requiredTier: "free",
      serverPath: "/api/chat/stream",
      slashCommand: "/회의정리",
      name: { ko: "회의정리·활동집", en: "Meeting notes" },
      chip: { ko: "회의정리", en: "Meeting" },
      desc: { ko: "회의 요약·책/활동집 누적 생성", en: "Summaries and an accumulating activity book" },
      fields: [
        {
          key: "title",
          type: "text",
          required: true,
          advanced: false,
          label: { ko: "회의명", en: "Meeting title" },
          placeholder: { ko: "예: 10월 주민 민원 회의", en: "e.g. October community review" },
          question: { ko: "정리할 회의 이름을 알려 주세요.", en: "What is the title of the meeting?" },
        },
        {
          key: "when",
          type: "datetime-local",
          required: false,
          advanced: false,
          label: { ko: "회의 일시", en: "Date & time" },
          question: { ko: "회의 일시는 언제였나요?", en: "When did the meeting take place?" },
        },
        {
          key: "attendees",
          type: "text",
          required: false,
          advanced: false,
          label: { ko: "참석자", en: "Attendees" },
          placeholder: { ko: "예: 비서실장, 지역 담당", en: "e.g. Chief of staff, regional lead" },
          question: { ko: "참석자는 누구였나요?", en: "Who attended the meeting?" },
        },
        {
          key: "content",
          type: "textarea",
          rows: 8,
          required: true,
          advanced: false,
          label: { ko: "회의 내용", en: "Meeting notes / transcript" },
          placeholder: { ko: "회의에서 오간 내용을 그대로 적어 주세요", en: "Paste or write what was discussed in the meeting" },
          question: { ko: "정리할 회의 내용을 붙여넣거나 말씀해 주세요.", en: "Please share the meeting notes or transcript to summarize." },
        },
      ],
    }),
    makeTool({
      id: "pdfmd",
      icon: "⇩",
      category: "document",
      requiredTier: "free",
      serverPath: "/api/document-conversions",
      slashCommand: "/pdf",
      name: { ko: "PDF → Markdown", en: "PDF → Markdown" },
      chip: { ko: "PDF→MD", en: "PDF→MD" },
      desc: { ko: "PDF·ZIP을 Markdown으로 변환·비교·다운로드", en: "Convert, compare and download Markdown from PDF/ZIP" },
      fields: [
        {
          key: "files",
          type: "file",
          required: true,
          advanced: false,
          accept: ".pdf,.zip,application/pdf,application/zip",
          label: { ko: "PDF 또는 ZIP 파일", en: "PDF or ZIP file" },
          placeholder: { ko: "PDF 파일을 선택하세요", en: "Choose a PDF or ZIP file" },
          question: { ko: "Markdown으로 변환할 PDF 또는 ZIP 파일을 첨부해 주세요.", en: "Please attach the PDF or ZIP file to convert to Markdown." },
        },
        {
          key: "mode",
          type: "select",
          required: false,
          advanced: false,
          defaultValue: "fast",
          label: { ko: "변환 방식", en: "Conversion mode" },
          question: { ko: "빠른 변환과 검증 변환 중 어떤 방식으로 진행할까요?", en: "Would you like fast conversion or verified conversion?" },
          options: [
            { value: "fast", label: { ko: "빠른 변환", en: "Fast conversion" } },
            { value: "verify", label: { ko: "검증 변환", en: "Verified conversion" } },
          ],
        },
      ],
    }),
    makeTool({
      id: "quote",
      icon: "◇",
      category: "business",
      requiredTier: "free",
      serverPath: "/api/util/quote/preview",
      slashCommand: "/견적서",
      name: { ko: "견적서 초안", en: "Quote draft" },
      chip: { ko: "견적서", en: "Quote" },
      desc: { ko: "요청을 붙이면 견적서·발주서·답장 초안 — 서버에서 생성", en: "Draft a quotation, purchase order and reply from a request" },
      fields: [
        {
          key: "content",
          type: "textarea",
          rows: 6,
          maxLength: 12000,
          required: true,
          advanced: false,
          label: { ko: "요청 원문", en: "Request" },
          placeholder: { ko: "받은 요청이나 메시지를 그대로 붙여넣어 주세요. 견적서·발주서·답장 초안을 만듭니다.", en: "Paste the request or message as received. This drafts a quotation, purchase order or reply." },
          question: { ko: "견적서·발주서·답장 초안을 만들 요청 원문을 알려 주세요.", en: "Please paste the request text you want turned into a draft." },
        },
        {
          key: "channel",
          type: "select",
          required: false,
          advanced: false,
          defaultValue: "other",
          label: { ko: "채널", en: "Channel" },
          question: { ko: "요청을 받은 채널(이메일·카카오톡·문자 등)은 어디인가요?", en: "Which channel did the request arrive on?" },
          options: [
            { value: "other", label: { ko: "기타", en: "Other" } },
            { value: "kakao", label: { ko: "카카오톡", en: "KakaoTalk" } },
            { value: "sms", label: { ko: "문자", en: "SMS" } },
            { value: "email", label: { ko: "이메일", en: "Email" } },
            { value: "telegram", label: { ko: "텔레그램", en: "Telegram" } },
            { value: "discord", label: { ko: "디스코드", en: "Discord" } },
          ],
        },
        {
          key: "action",
          type: "select",
          required: false,
          advanced: false,
          defaultValue: "quote",
          label: { ko: "작업", en: "Action" },
          question: { ko: "견적서·발주서·답장·항목 정리 중 어떤 초안을 만들까요?", en: "Which draft should we build: quotation, purchase order, reply, or summary?" },
          options: [
            { value: "quote", label: { ko: "견적서 초안", en: "Quote draft" } },
            { value: "order", label: { ko: "발주서 초안", en: "Purchase order draft" } },
            { value: "reply", label: { ko: "답장 초안", en: "Reply draft" } },
            { value: "summary", label: { ko: "요청 항목 정리", en: "Summarize the request" } },
            { value: "extract_candidates", label: { ko: "후보 추출", en: "Extract candidates" } },
          ],
        },
        {
          key: "sender_hint",
          type: "text",
          maxLength: 120,
          required: false,
          advanced: false,
          label: { ko: "발신자 힌트 (선택)", en: "Sender hint (optional)" },
          placeholder: { ko: "예: A상사 담당자", en: "e.g. the contact at Company A" },
          question: { ko: "발신자 이름이나 거래처 힌트가 있다면 알려 주세요.", en: "Is there a sender or company name hint to include?" },
        },
      ],
    }),
    makeTool({
      id: "excel",
      icon: "▦",
      category: "business",
      requiredTier: "free",
      serverPath: null,
      slashCommand: "/엑셀",
      name: { ko: "Excel 열기/검토", en: "Excel open & review" },
      chip: { ko: "Excel", en: "Excel" },
      desc: { ko: "XLSX 원본을 이 화면에서 열어 검토·작업", en: "Open an XLSX file here to review and work on it" },
      fields: [
        {
          key: "file",
          type: "file",
          required: true,
          advanced: false,
          accept: ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          label: { ko: "XLSX 원본 파일", en: "XLSX file" },
          placeholder: { ko: "검토할 .xlsx 파일 선택", en: "Choose an .xlsx file to review" },
          question: { ko: "열어 검토할 Excel(.xlsx) 파일을 첨부해 주세요.", en: "Please attach the Excel (.xlsx) file you want to review." },
        },
        {
          key: "goal",
          type: "textarea",
          rows: 3,
          required: false,
          advanced: false,
          label: { ko: "검토 메모 (선택)", en: "Review note (optional)" },
          placeholder: { ko: "예: 합계 수식과 단가 누락 여부 확인", en: "e.g. Check totals and missing unit prices" },
          question: { ko: "시트에서 중점적으로 확인할 항목이 있다면 알려 주세요.", en: "What should we check or review in the workbook?" },
        },
      ],
    }),
  ]);

  const TOOL_BY_ID = new Map(TOOLS.map((tool) => [tool.id, tool]));
  const TOOL_IDS = deepFreeze(TOOLS.map((tool) => tool.id));

  function getTool(id) {
    return TOOL_BY_ID.get(String(id || "")) || null;
  }

  function listHref() {
    return ROUTE_PREFIX;
  }

  function toolHref(id) {
    const tool = getTool(id);
    return tool ? tool.route : ROUTE_PREFIX + "/" + String(id || "");
  }

  function hasFieldValue(field, rawValue) {
    if (!field) return false;
    if (field.type === "file") {
      if (!rawValue) return false;
      if (typeof rawValue.length === "number") return rawValue.length > 0;
      if (typeof rawValue === "string") return rawValue.trim().length > 0;
      return Boolean(rawValue);
    }
    return String(rawValue == null ? "" : rawValue).trim().length > 0;
  }

  function requiredFields(id) {
    const tool = getTool(id);
    return tool ? tool.fields.filter((field) => field.required) : [];
  }

  function missingFields(id, values) {
    const bag = values && typeof values === "object" ? values : {};
    return requiredFields(id).filter((field) => !hasFieldValue(field, bag[field.key]));
  }

  function nextQuestion(id, values, langCode) {
    const missing = missingFields(id, values);
    if (!missing.length) return null;
    const field = missing[0];
    const locale = langCode === "en" ? "en" : "ko";
    return {
      toolId: String(id || ""),
      fieldKey: field.key,
      field: field,
      question: (field.question && (field.question[locale] || field.question.ko)) || "",
    };
  }

  window.PadiemUtilManifest = deepFreeze({
    ROUTE_PREFIX: ROUTE_PREFIX,
    CATEGORIES: CATEGORIES,
    TOOLS: TOOLS,
    TOOL_IDS: TOOL_IDS,
    getTool: getTool,
    listHref: listHref,
    toolHref: toolHref,
    requiredFields: requiredFields,
    missingFields: missingFields,
    nextQuestion: nextQuestion,
  });
})();
