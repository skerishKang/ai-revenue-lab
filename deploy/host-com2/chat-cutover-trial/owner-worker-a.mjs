export default {
  fetch() {
    return new Response("trial-a", {headers: {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"}});
  }
};
