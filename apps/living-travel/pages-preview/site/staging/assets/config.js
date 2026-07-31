// Living Travel — Staging frontend configuration.
//
// PUBLIC CONFIG ONLY. This module must never contain secrets: no service
// account, no private key, no Neon/PostgreSQL URL, no Modal secret, no
// operator secret. Firebase *web* config fields (apiKey, authDomain, ...) are
// public by design and safe to ship to the browser.
//
// The staging contract test (tests/test_staging_contract.py) pins the SDK
// version and verifies that API_BASE's origin appears in the /staging/* CSP
// connect-src. Keep FIREBASE_SDK_VERSION, the gstatic import URLs in
// firebase.js, and the _headers connect-src in sync.

// Pinned Firebase Web SDK version (modular ESM). Never use "latest" or an
// unversioned URL. Must match the import URLs in firebase.js.
export const FIREBASE_SDK_VERSION = "12.16.0";

// Public Firebase web config for the shared identity project. authDomain and
// projectId are the real shared-identity project; apiKey/appId/sender are
// staging placeholders that must be replaced with the real PUBLIC web config
// from the Firebase console before live verification.
export const FIREBASE_CONFIG = {
  apiKey: "AIzaSyCiHMN8g11Fahz8bU8DGPW2Rva_rULeOlU",
  authDomain: "ai-revenue-lab-identity.firebaseapp.com",
  projectId: "ai-revenue-lab-identity",
  storageBucket: "ai-revenue-lab-identity.firebasestorage.app",
  messagingSenderId: "864728700692",
  appId: "1:864728700692:web:01dc5a0fffb78bf4801401",
};

// Exact origin of the isolated Modal staging API (app ai-revenue-living-travel
// -staging, function "web"). Must be an exact origin (no wildcard) and must
// match the /staging/* CSP connect-src in _headers.
export const API_BASE = "https://padiemipu--ai-revenue-living-travel-staging-web.modal.run";

// API path prefix served by the FastAPI factory.
export const API_PREFIX = "/api/v1";

// Visible staging label rendered on every staging screen.
export const STAGING_LABEL = "Staging · Synthetic data · Connected API";
