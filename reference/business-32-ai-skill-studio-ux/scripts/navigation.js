/* Business 32 · AI Skill Studio — Phase 2 deterministic keyboard focus navigation.
 * Pure function only. Binds nothing. app.js wires it to the DOM.
 * Works in node (module.exports) and browser (window.B32Nav).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.B32Nav = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const KEYS = {
    next: ['ArrowRight', 'ArrowDown'],
    previous: ['ArrowLeft', 'ArrowUp'],
    home: ['Home'],
    end: ['End'],
    activate: ['Enter', ' ']
  };

  function classify(key) {
    if (KEYS.next.indexOf(key) !== -1) return 'next';
    if (KEYS.previous.indexOf(key) !== -1) return 'previous';
    if (KEYS.home.indexOf(key) !== -1) return 'home';
    if (KEYS.end.indexOf(key) !== -1) return 'end';
    if (KEYS.activate.indexOf(key) !== -1) return 'activate';
    return null;
  }

  function clamp(index, length) {
    if (length <= 0) return -1;
    if (index < 0) return length - 1;
    if (index >= length) return 0;
    return index;
  }

  function nextIndex(descriptorCount, currentIndex, key) {
    const kind = classify(key);
    if (kind === null || descriptorCount <= 0) return currentIndex;
    if (kind === 'home') return 0;
    if (kind === 'end') return descriptorCount - 1;
    if (kind === 'next') return clamp(currentIndex + 1, descriptorCount);
    if (kind === 'previous') return clamp(currentIndex - 1, descriptorCount);
    return currentIndex;
  }

  function shouldActivate(key) {
    return classify(key) === 'activate';
  }

  return {
    KEYS: KEYS,
    classify: classify,
    nextIndex: nextIndex,
    shouldActivate: shouldActivate
  };
});
