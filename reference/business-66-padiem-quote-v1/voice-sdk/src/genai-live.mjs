/* #3404 — the only upstream surface B66 needs from the pinned SDK.
   Kept to one symbol so tree-shaking stays honest: the browser build
   (`@google/genai/web`) is what global-classroom exercises, and its `live`
   namespace is the transport this lane uses instead of a hand-rolled socket. */
export { GoogleGenAI } from '@google/genai/web';
