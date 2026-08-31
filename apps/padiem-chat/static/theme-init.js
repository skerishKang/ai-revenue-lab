(function(){
  try {
    var valid = ["padiem-home", "light", "dark", "cinematic"];
    var saved = localStorage.getItem("padiem_theme");
    var theme = valid.indexOf(saved) !== -1 ? saved : "padiem-home";
    document.documentElement.setAttribute("data-theme", theme);
    var scheme = theme === "light" || theme === "padiem-home" ? "light" : "dark";
    var colorScheme = document.querySelector('meta[name="color-scheme"]');
    var themeColor = document.querySelector('meta[name="theme-color"]');
    if (colorScheme) colorScheme.setAttribute("content", scheme);
    if (themeColor) themeColor.setAttribute("content", ({light:"#f8f8fb", dark:"#0b0c0e", cinematic:"#06080d", "padiem-home":"#e6e9ee"})[theme] || "#e6e9ee");
  } catch (error) {}
})();
