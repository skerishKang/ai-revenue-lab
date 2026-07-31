(function () {
  const stored = localStorage.getItem("arl-portfolio-theme");
  const theme = stored === "dark" || stored === "light" ? stored : "dark";
  document.documentElement.setAttribute("data-theme", theme);
})();
