export default {
  fetch() {
    return new Response("trial-b", {headers: {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"}});
  }
};
