(function(){
  try {
    var theme = "padiem-home";
    document.documentElement.setAttribute("data-theme", theme);
    var colorScheme = document.querySelector('meta[name="color-scheme"]');
    var themeColor = document.querySelector('meta[name="theme-color"]');
    if (colorScheme) colorScheme.setAttribute("content", "light");
    if (themeColor) themeColor.setAttribute("content", "#e6e9ee");
  } catch (error) {}
})();
