(() => {
  const root = document.getElementById("world-feed-root");
  const markup = (window.WorldFeedViewMarkup || []).join("");
  root.insertAdjacentHTML("beforebegin", markup);
  root.remove();
  delete window.WorldFeedViewMarkup;
})();
