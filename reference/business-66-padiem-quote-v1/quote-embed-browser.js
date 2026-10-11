(() => {
  "use strict";

  const Bridge = window.B66QuoteEmbedBridge;
  const runtime = {
    Core: window.QuoteCore,
    SavedSkill: window.SavedQuoteSkill,
    Renderer: window.QuoteTemplateRenderer,
  };
  if (!Bridge || !Bridge.installBrowserBridge(window, document, runtime)) {
    const status = document.getElementById("embedStatus");
    if (status) {
      status.textContent = "견적서 렌더러를 준비하지 못했습니다.";
      status.dataset.state = "error";
    }
  }

  const printButton = document.getElementById("embedPrint");
  if (printButton) {
    printButton.addEventListener("click", () => window.print());
  }
})();
