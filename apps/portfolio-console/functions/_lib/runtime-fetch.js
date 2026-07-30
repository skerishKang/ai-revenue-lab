export function bindFetchImpl(fetchImpl = globalThis.fetch) {
  if (typeof fetchImpl !== "function") {
    throw new TypeError("Fetch implementation is unavailable.");
  }
  return (...args) => Reflect.apply(fetchImpl, globalThis, args);
}
