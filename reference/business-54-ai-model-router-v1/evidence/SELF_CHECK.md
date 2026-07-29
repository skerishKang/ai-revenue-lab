# Implementation self-check

This is implementation-worker evidence only. It is not independent `LOCAL_VALIDATION_PASS`, `UI_REVIEW_PASS` or `UI_APPROVED`.

## Matrix contract

- states: 7
- viewports: 1440×1100, 768×1024, 390×844
- combinations: 21

## Assertions

- exactly one selected tab and visible tabpanel;
- reciprocal tab/panel ARIA relationship 7/7;
- roving `tabIndex`, ArrowLeft/ArrowRight/Home/End and native Enter/Space;
- visible focus;
- horizontal overflow, detected clipping and label overlap 0;
- all repository-local SVGs decode and render;
- required routing boundaries visible;
- hard constraints precede weighted preferences;
- unavailable candidate not selected;
- no external runtime requests;
- actual final `routingPolicyComplete` animationend at nominal 760ms;
- no fixed completion timeout;
- Replay 1/2 equality and focus/scroll/geometry stability;
- reduced-motion immediate information-complete;
- 390px dedicated mobile containment.
