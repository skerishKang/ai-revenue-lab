// #7216 R5: strict test deps helper (shared by the R5 contract tests).
//
// A test fake that omits a deps property used by the moved code does not fail:
// most call sites sit inside broad catches (TypeError swallowed), so the test
// passes without exercising the stub it thinks it is driving (argon review of
// PR #7249, finding (d)). Wrap every test deps object in this Proxy: reading a
// property the fake does not define throws immediately, at the read site.
function r5StrictDeps(target, label) {
  return new Proxy(target, {
    get(obj, prop, receiver) {
      if (typeof prop === "symbol" || prop in obj) return Reflect.get(obj, prop, receiver);
      throw new Error((label || "deps") + "." + String(prop) + " is not defined in the test deps");
    },
    set(obj, prop, value, receiver) {
      if (typeof prop === "symbol" || prop in obj) return Reflect.set(obj, prop, value, receiver);
      throw new Error((label || "deps") + "." + String(prop) + " is not defined in the test deps (set)");
    },
  });
}
