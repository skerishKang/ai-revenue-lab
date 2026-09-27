/* B66 · Padiem Quote — app.js
   입력 → 결정론적 계산(수량×단가·공급가액·VAT 10%·총액) → 미리보기 렌더링.
   금액 계산의 최종 authority는 이 코드이며 AI가 아님. 로직은 원본 <script> 블록에서 그대로 추출. */

(() => {
  const $ = (id) => document.getElementById(id);
  const won = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });
  const fields = [
    "senderCompany","senderRep","senderBizNo","senderPhone","senderEmail",
    "recipientCompany","recipientPerson","recipientEmail","quoteDate","validity","quoteNo","memo"
  ];

  const demoSender = {
    company: "주식회사 파디엠",
    rep: "대표자명",
    bizNo: "000-00-00000",
    phone: "000-0000-0000",
    email: "hello@example.com"
  };

  function todayISO() {
    const d = new Date();
    return [d.getFullYear(), String(d.getMonth()+1).padStart(2,"0"), String(d.getDate()).padStart(2,"0")].join("-");
  }

  function defaultQuoteNo() {
    return "PQ-" + todayISO().replaceAll("-","") + "-001";
  }

  function safeNumber(value) {
    const n = Number(String(value ?? "").replaceAll(",", ""));
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
      .replaceAll('"',"&quot;").replaceAll("'","&#039;");
  }

  function toast(message) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => $("toast").classList.remove("show"), 1800);
  }

  /* ── 품목 행 ── */
  function createItemRow(name = "", qty = 1, unitPrice = 0) {
    const row = document.createElement("div");
    row.className = "item-row";
    row.innerHTML = `
      <input class="item-name" aria-label="품목명" value="${escapeHtml(name)}" placeholder="품목명">
      <input class="item-qty" aria-label="수량" type="number" min="0" step="1" value="${safeNumber(qty)}">
      <input class="item-price" aria-label="단가" type="number" min="0" step="1000" value="${safeNumber(unitPrice)}">
      <div class="amount">0원</div>
      <button class="icon-btn remove-item" aria-label="품목 삭제" title="품목 삭제">×</button>
    `;
    row.querySelectorAll("input").forEach((el) => el.addEventListener("input", render));
    row.querySelector(".remove-item").addEventListener("click", () => {
      if ($("items").children.length === 1) {
        row.querySelector(".item-name").value = "";
        row.querySelector(".item-qty").value = "1";
        row.querySelector(".item-price").value = "0";
      } else {
        row.remove();
      }
      render();
    });
    $("items").appendChild(row);
    render();
  }

  function readItems() {
    return [...document.querySelectorAll(".item-row")].map((row) => {
      const name = row.querySelector(".item-name").value.trim();
      const qty = safeNumber(row.querySelector(".item-qty").value);
      const price = safeNumber(row.querySelector(".item-price").value);
      const amount = Math.round(qty * price);
      row.querySelector(".amount").textContent = won.format(amount);
      return { name, qty, price, amount };
    });
  }

  function textOrDash(value) {
    const v = String(value ?? "").trim();
    return v || "-";
  }

  /* ── 렌더링(입력↔미리보기 실시간 동기화) ── */
  function render() {
    const items = readItems();
    const subtotal = items.reduce((sum, item) => sum + item.amount, 0);
    const vat = $("vatEnabled").checked ? Math.round(subtotal * 0.10) : 0;
    const grand = subtotal + vat;

    $("subtotalText").textContent = won.format(subtotal);
    $("vatText").textContent = won.format(vat);
    $("grandText").textContent = won.format(grand);

    $("pvQuoteNo").textContent = "견적번호  " + textOrDash($("quoteNo").value);
    $("pvDate").textContent = "견적일  " + textOrDash($("quoteDate").value);
    $("pvValidity").textContent = "유효기간  " + $("validity").value + "일";

    $("pvSenderCompany").textContent = textOrDash($("senderCompany").value);
    $("pvSenderRep").textContent = "대표자  " + textOrDash($("senderRep").value);
    $("pvSenderBizNo").textContent = "사업자번호  " + textOrDash($("senderBizNo").value);
    $("pvSenderContact").textContent = [ $("senderPhone").value.trim(), $("senderEmail").value.trim() ].filter(Boolean).join(" · ") || "-";

    $("pvRecipientCompany").textContent = textOrDash($("recipientCompany").value);
    $("pvRecipientPerson").textContent = "담당자  " + textOrDash($("recipientPerson").value);
    $("pvRecipientEmail").textContent = $("recipientEmail").value.trim() || "-";

    $("pvItems").innerHTML = items.map((item) => `
      <tr>
        <td class="${item.name ? "" : "empty"}">${escapeHtml(item.name || "품목을 입력하세요")}</td>
        <td>${item.qty}</td>
        <td>${won.format(item.price)}</td>
        <td>${won.format(item.amount)}</td>
      </tr>`
    ).join("");

    $("pvSubtotal").textContent = won.format(subtotal);
    $("pvVat").textContent = won.format(vat);
    $("pvGrand").textContent = won.format(grand);
    $("pvMemo").textContent = $("memo").value.trim() || "비고 없음";
  }

  /* ── 발신자 프리셋 ── */
  function applySender(sender) {
    $("senderCompany").value = sender.company || "";
    $("senderRep").value = sender.rep || "";
    $("senderBizNo").value = sender.bizNo || "";
    $("senderPhone").value = sender.phone || "";
    $("senderEmail").value = sender.email || "";
    render();
  }

  function loadCustomSender() {
    try {
      const saved = JSON.parse(localStorage.getItem("padiemQuote.sender") || "null");
      return saved && typeof saved === "object" ? saved : null;
    } catch {
      return null;
    }
  }

  $("senderPreset").addEventListener("change", () => {
    if ($("senderPreset").value === "padiem") {
      applySender(demoSender);
      return;
    }
    applySender(loadCustomSender() || { company:"", rep:"", bizNo:"", phone:"", email:"" });
  });

  $("saveSender").addEventListener("click", () => {
    const sender = {
      company: $("senderCompany").value.trim(),
      rep: $("senderRep").value.trim(),
      bizNo: $("senderBizNo").value.trim(),
      phone: $("senderPhone").value.trim(),
      email: $("senderEmail").value.trim()
    };
    localStorage.setItem("padiemQuote.sender", JSON.stringify(sender));
    $("senderPreset").value = "custom";
    toast("이 브라우저에 발신자를 저장했습니다.");
  });

  $("addItem").addEventListener("click", () => createItemRow("", 1, 0));
  $("vatEnabled").addEventListener("change", render);
  fields.forEach((id) => $(id).addEventListener("input", render));
  $("validity").addEventListener("change", render);

  $("printPdf").addEventListener("click", () => {
    render();
    window.print();
  });

  $("emailFuture").addEventListener("click", () => {
    toast("이메일 전송은 다음 단계에서 Gmail/메일 연동으로 붙입니다.");
  });

  document.querySelectorAll(".mode").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".mode").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      if (button.dataset.mode === "manual") {
        $("futureNote").className = "future-note";
        $("futureNote").textContent = "";
        return;
      }
      $("futureNote").className = "future-note show";
      $("futureNote").textContent = button.dataset.mode === "upload"
        ? "파일 업로드 → 견적서 필드 자동 추출은 다음 단계에서 AI/OCR Skill로 연결합니다. 이 데모에서는 파일을 외부로 전송하지 않습니다."
        : "자연어 채팅 → QuoteDraft 자동 입력은 다음 단계에서 연결합니다. 금액 계산은 AI가 아니라 현재와 같은 결정적 계산 코드가 담당합니다.";
    });
  });

  /* ── 초기화 ── */
  $("quoteDate").value = todayISO();
  $("quoteNo").value = defaultQuoteNo();
  createItemRow("서비스 구축", 1, 1000000);
  createItemRow("운영 지원", 1, 300000);
  render();
})();
