(() => {
  "use strict";
  const order = ["front", "news", "photos", "calendar", "sources", "mobile", "fold"];
  const publication = document.querySelector("#publication");
  publication.innerHTML = order.map((state) => window.familyNewspaperStates[state]).join("\n");
})();
