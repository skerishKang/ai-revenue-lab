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
    Object.keys(value).forEach((key) => { deepFreeze(value[key]); });
    return Object.freeze(value);
  }

  function fld(key, type, required, advanced, labelKo, labelEn, phKo, phEn, qKo, qEn, extra) {
    const ext = extra || {};
    return deepFreeze({
      key: key,
      type: type || "text",
      required: Boolean(required),
      advanced: Boolean(advanced),
      label: { ko: labelKo, en: labelEn },
      placeholder: { ko: phKo || "", en: phEn || "" },
      question: { ko: qKo, en: qEn },
      rows: ext.rows || 0,
      maxLength: ext.maxLength || 0,
      accept: ext.accept || "",
      defaultValue: ext.defaultValue !== undefined ? ext.defaultValue : "",
      options: Array.isArray(ext.options)
        ? ext.options.map((o) => ({ value: o[0], label: { ko: o[1], en: o[2] } }))
        : [],
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
      fields: spec.fields,
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
        fld("event", "text", true, false, "행사명", "Event name",
          "예: 제78주년 광복절 기념식", "e.g. 78th Liberation Day Ceremony",
          "어떤 행사의 축사·인사말인가요? 행사명을 알려 주세요.", "Which event is this address for? Please share the event name."),
        fld("audience", "text", false, false, "참석 대상", "Audience",
          "예: 지역 주민 200명", "e.g. 200 local residents",
          "주로 누가 참석하나요?", "Who will attend the event?"),
        fld("author", "text", false, false, "직책과 이름", "Title & speaker name",
          "예: 지역구 국회의원 김의민", "e.g. Council member Kim",
          "인사말을 전하는 분의 직책과 이름은 무엇인가요?", "What are the speaker's title and name?"),
        fld("length", "select", false, false, "분량", "Length", "", "",
          "분량은 1분·3분·5분 중 어느 정도가 좋을까요?", "How long should it be (1, 3, or 5 minutes)?",
          { defaultValue: "medium", options: [["short", "1분", "1 min"], ["medium", "3분", "3 min"], ["long", "5분", "5 min"]] }),
        fld("date", "date", false, true, "행사 날짜", "Event date", "", "",
          "행사 날짜가 언제인가요?", "When is the event?"),
        fld("place", "text", false, true, "장소", "Venue",
          "예: 시청 대강당", "e.g. City Hall Auditorium",
          "행사가 열리는 장소는 어디인가요?", "Where is the event held?"),
        fld("nature", "text", false, true, "행사 성격", "Event type",
          "예: 지역 행사", "e.g. Community gathering",
          "행사의 성격이나 분위기를 간단히 알려 주세요.", "What kind of event or atmosphere is it?"),
        fld("message", "textarea", false, true, "주요 메시지", "Key message",
          "예: 함께 성장하는 지역사회", "e.g. Growing together as one community",
          "꼭 담고 싶은 핵심 메시지가 있나요?", "Is there a core message you want to include?", { rows: 3 }),
        fld("emphasis", "textarea", false, true, "강조 내용", "Points to emphasize",
          "예: 상생과 배려", "e.g. Mutual care and cooperation",
          "특별히 강조하고 싶은 내용이 있나요?", "Any points you want emphasized?", { rows: 3 }),
        fld("tone", "select", false, true, "말투", "Tone", "", "",
          "말투는 공식·따뜻한·간결 중 어떤 느낌으로 작성할까요?", "Which tone fits best: formal, warm, or concise?",
          { defaultValue: "formal", options: [["formal", "공식", "Formal"], ["warm", "따뜻한", "Warm"], ["concise", "간결", "Concise"]] }),
        fld("style", "textarea", false, true, "기존 축사 샘플 (말투 반영)", "Sample address (style reference)",
          "기존 축사/인사말 원문 붙여넣기", "Paste a previous address to match its style",
          "말투에 참고할 기존 축사·인사말 원문이 있다면 붙여넣어 주세요.", "Do you have a sample address whose style we should match?", { rows: 4 }),
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
        fld("event", "text", true, false, "행사명", "Topic / event",
          "예: 주민 정원 사업 설명회", "e.g. Community garden briefing",
          "홍보할 행사나 소식 이름을 알려 주세요.", "What event or topic would you like to promote?"),
        fld("whenwhere", "text", false, false, "날짜·장소", "Date & place",
          "예: 10월 30일 오후 2시, 구청 소회의실", "e.g. Oct 30 2 PM, District Hall Room 2",
          "일시와 장소 정보가 있다면 알려 주세요.", "When and where does it take place?"),
        fld("content", "textarea", true, false, "주요 내용", "Key details",
          "예: 정원 사업 신청 방법과 지원 금액 안내", "e.g. How to apply and subsidy details",
          "게시글에 꼭 들어갈 주요 내용을 알려 주세요.", "What key details must be included in the post?", { rows: 4 }),
        fld("audience", "text", false, false, "대상 독자", "Target readers",
          "예: 구내 상인", "e.g. Local shop owners",
          "주로 누구에게 보여줄 홍보글인가요?", "Who is the target audience?"),
        fld("memo", "textarea", false, false, "메모", "Extra notes",
          "예: 참석자에게 강조할 한 가지", "e.g. One highlight to emphasize",
          "추가로 덧붙일 메모나 안내가 있나요?", "Any extra note or highlight to add?", { rows: 4 }),
        fld("tone", "select", false, false, "문체", "Tone", "", "",
          "문체는 캐주얼·전문적·감성적 중 무엇이 좋을까요?", "Which tone works best: casual, professional, or emotional?",
          { defaultValue: "professional", options: [["casual", "캐주얼", "Casual"], ["professional", "전문적", "Professional"], ["emotional", "감성적", "Emotional"]] }),
        fld("platform", "choice", false, false, "게시할 곳", "Where it goes", "", "",
          "블로그·페이스북·인스타그램 중 어디에 올릴 게시글인가요?", "Which platform is this post for: blog, Facebook, or Instagram?",
          { defaultValue: "blog", options: [["blog", "블로그", "Blog"], ["facebook", "페이스북", "Facebook"], ["instagram", "인스타그램", "Instagram"]] }),
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
        fld("title", "text", true, false, "회의명", "Meeting title",
          "예: 10월 주민 민원 회의", "e.g. October community review",
          "정리할 회의 이름을 알려 주세요.", "What is the title of the meeting?"),
        fld("when", "datetime-local", false, false, "회의 일시", "Date & time", "", "",
          "회의 일시는 언제였나요?", "When did the meeting take place?"),
        fld("attendees", "text", false, false, "참석자", "Attendees",
          "예: 비서실장, 지역 담당", "e.g. Chief of staff, regional lead",
          "참석자는 누구였나요?", "Who attended the meeting?"),
        fld("content", "textarea", true, false, "회의 내용", "Meeting notes / transcript",
          "회의에서 오간 내용을 그대로 적어 주세요", "Paste or write what was discussed in the meeting",
          "정리할 회의 내용을 붙여넣거나 말씀해 주세요.", "Please share the meeting notes or transcript to summarize.", { rows: 8 }),
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
        fld("files", "file", true, false, "PDF 또는 ZIP 파일", "PDF or ZIP file",
          "PDF 파일을 선택하세요", "Choose a PDF or ZIP file",
          "Markdown으로 변환할 PDF 또는 ZIP 파일을 첨부해 주세요.", "Please attach the PDF or ZIP file to convert to Markdown.",
          { accept: ".pdf,.zip,application/pdf,application/zip" }),
        fld("mode", "select", false, false, "변환 방식", "Conversion mode", "", "",
          "빠른 변환과 검증 변환 중 어떤 방식으로 진행할까요?", "Would you like fast conversion or verified conversion?",
          { defaultValue: "fast", options: [["fast", "빠른 변환", "Fast conversion"], ["verify", "검증 변환", "Verified conversion"]] }),
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
        fld("content", "textarea", true, false, "요청 원문", "Request",
          "받은 요청이나 메시지를 그대로 붙여넣어 주세요. 견적서·발주서·답장 초안을 만듭니다.",
          "Paste the request or message as received. This drafts a quotation, purchase order or reply.",
          "견적서·발주서·답장 초안을 만들 요청 원문을 알려 주세요.", "Please paste the request text you want turned into a draft.",
          { rows: 6, maxLength: 12000 }),
        fld("channel", "select", false, false, "채널", "Channel", "", "",
          "요청을 받은 채널(이메일·카카오톡·문자 등)은 어디인가요?", "Which channel did the request arrive on?",
          { defaultValue: "other", options: [["other", "기타", "Other"], ["kakao", "카카오톡", "KakaoTalk"], ["sms", "문자", "SMS"], ["email", "이메일", "Email"], ["telegram", "텔레그램", "Telegram"], ["discord", "디스코드", "Discord"]] }),
        fld("action", "select", false, false, "작업", "Action", "", "",
          "견적서·발주서·답장·항목 정리 중 어떤 초안을 만들까요?", "Which draft should we build: quotation, purchase order, reply, or summary?",
          { defaultValue: "quote", options: [["quote", "견적서 초안", "Quote draft"], ["order", "발주서 초안", "Purchase order draft"], ["reply", "답장 초안", "Reply draft"], ["summary", "요청 항목 정리", "Summarize the request"], ["extract_candidates", "후보 추출", "Extract candidates"]] }),
        fld("sender_hint", "text", false, false, "발신자 힌트 (선택)", "Sender hint (optional)",
          "예: A상사 담당자", "e.g. the contact at Company A",
          "발신자 이름이나 거래처 힌트가 있다면 알려 주세요.", "Is there a sender or company name hint to include?",
          { maxLength: 120 }),
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
        fld("file", "file", true, false, "XLSX 원본 파일", "XLSX file",
          "검토할 .xlsx 파일 선택", "Choose an .xlsx file to review",
          "열어 검토할 Excel(.xlsx) 파일을 첨부해 주세요.", "Please attach the Excel (.xlsx) file you want to review.",
          { accept: ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
        fld("goal", "textarea", false, false, "검토 메모 (선택)", "Review note (optional)",
          "예: 합계 수식과 단가 누락 여부 확인", "e.g. Check totals and missing unit prices",
          "시트에서 중점적으로 확인할 항목이 있다면 알려 주세요.", "What should we check or review in the workbook?", { rows: 3 }),
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

  // #7502: which input a "내 PC에서 가져오기" fill lands in. The rule is read
  // from the declaration, never from a tool name: the required long-text field
  // first, then the roomiest one. A tool with no textarea gets no import button.
  function pcImportField(id) {
    const tool = getTool(id);
    if (!tool) return null;
    const areas = tool.fields.filter((field) => field.type === "textarea");
    if (!areas.length) return null;
    const required = areas.filter((field) => field.required);
    const pool = required.length ? required : areas;
    return pool.slice().sort((a, b) => (b.rows || 0) - (a.rows || 0))[0] || null;
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
    pcImportField: pcImportField,
    nextQuestion: nextQuestion,
  });
})();
