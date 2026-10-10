"use strict";

// Synthetic DOM event harness for B66 Drive offline tests. Each call creates
// an independent document, element registry and event listener collection.
function createStubDocument(containerId) {
  if (typeof containerId !== "string" || !containerId) {
    throw new TypeError("B66_TEST_CONTAINER_ID_REQUIRED");
  }
  const registry = new Map();
  const docHandlers = {};
  function makeNode(tag) {
    return {
      tagName: tag, id: "", children: [], listeners: {}, className: "", type: "",
      hidden: false, disabled: false, textContent: "", value: "", dataset: {},
      appendChild(child) { this.children.push(child); return child; },
      replaceChildren() { this.children = Array.prototype.slice.call(arguments); },
      addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); },
      click() { (this.listeners.click || []).slice().forEach((handler) => handler()); }
    };
  }
  const container = makeNode("div");
  container.id = containerId;
  registry.set(containerId, container);
  return {
    container,
    createElement: makeNode,
    getElementById: (id) => registry.get(id) || null,
    addEventListener(type, handler) { (docHandlers[type] = docHandlers[type] || []).push(handler); },
    dispatch(type, detail) { (docHandlers[type] || []).slice().forEach((handler) => handler({ detail })); }
  };
}

module.exports = Object.freeze({ createStubDocument });
