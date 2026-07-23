// Living Travel — Staging Firebase initialization (modular ESM SDK).
//
// The SDK is loaded from the pinned gstatic version below. These import
// specifiers are static literals (ESM requires literal specifiers), so the
// version appears here directly and MUST equal FIREBASE_SDK_VERSION in
// config.js. Only the modules we actually use are imported.
import { initializeApp } from "https://www.gstatic.com/firebasejs/12.16.0/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  signOut,
} from "https://www.gstatic.com/firebasejs/12.16.0/firebase-auth.js";

import { FIREBASE_CONFIG } from "./config.js";

const app = initializeApp(FIREBASE_CONFIG);
export const auth = getAuth(app);

const provider = new GoogleAuthProvider();

export function signInWithGoogle() {
  return signInWithPopup(auth, provider);
}

export function signOutUser() {
  return signOut(auth);
}

export function onAuth(callback) {
  return onAuthStateChanged(auth, callback);
}

// Return a fresh Firebase ID token for the signed-in user. The token is never
// persisted to custom localStorage/sessionStorage by this app; the Firebase
// SDK manages its own session persistence, and we request a short-lived token
// on demand for each API call.
export async function getCurrentIdToken() {
  const user = auth.currentUser;
  if (!user) {
    return null;
  }
  return user.getIdToken();
}
