(function () {
  "use strict";

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function revealAll(steps) {
    steps.forEach(function (el) { el.classList.add("is-visible"); });
  }

  function animateSteps(container) {
    var steps = Array.prototype.slice.call(
      container.querySelectorAll(".step")
    );
    if (reduceMotion || steps.length === 0) {
      revealAll(steps);
      return;
    }
    container.setAttribute("data-animating", "true");
    steps.forEach(function (el, index) {
      window.setTimeout(function () {
        el.classList.add("is-visible");
        if (index === steps.length - 1) {
          container.removeAttribute("data-animating");
        }
      }, 220 * index);
    });
  }

  function handleRunAnimation() {
    var params = new URLSearchParams(window.location.search);
    var justRan = params.get("ran") === "1";
    var container = document.querySelector("[data-run-steps]");
    if (!container) { return; }
    if (justRan) {
      animateSteps(container);
      params.delete("ran");
      var clean = window.location.pathname +
        (params.toString() ? "?" + params.toString() : "");
      window.history.replaceState(null, "", clean);
    } else {
      revealAll(Array.prototype.slice.call(container.querySelectorAll(".step")));
    }
  }

  function handleProjectPrefill() {
    var select = document.getElementById("project_id");
    if (!select) { return; }
    var allowed = document.getElementById("allowed_paths");
    var denied = document.getElementById("denied_paths");
    select.addEventListener("change", function () {
      var option = select.options[select.selectedIndex];
      if (!option) { return; }
      var defAllowed = (option.getAttribute("data-allowed") || "").replace(/,/g, ", ");
      var defDenied = (option.getAttribute("data-denied") || "").replace(/,/g, ", ");
      if (allowed && allowed.value.trim() === "") { allowed.value = defAllowed; }
      if (denied && denied.value.trim() === "") { denied.value = defDenied; }
    });
  }

  handleRunAnimation();
  handleProjectPrefill();
})();
