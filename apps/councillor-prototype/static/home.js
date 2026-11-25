// Home-page hooks for #5972. The activity cards, media column and link tiles are
// prerendered by scripts/prerender.py; this file only wires the existing DOM so a
// visitor can enlarge a photo and external links keep their shared marker.
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const media = document.getElementById("homeMedia");
    if (media && typeof enhanceMediaCards === "function") enhanceMediaCards(media);
    if (typeof markExternalLinks === "function") markExternalLinks();
  });
})();
