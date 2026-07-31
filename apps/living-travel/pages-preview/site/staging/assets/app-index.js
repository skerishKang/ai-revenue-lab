// Living Travel — Staging sign-in gate logic.
import { onAuth, signInWithGoogle, signInWithEmail, signOutUser } from "./firebase.js";
import { api, describeError } from "./api.js";
import { setHidden, setText } from "./dom.js";

const statusEl = document.getElementById("auth-status");
const signinBtn = document.getElementById("signin-btn");
const signoutBtn = document.getElementById("signout-btn");
const signinEmailBtn = document.getElementById("signin-email-btn");
const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const emailAuthForm = document.getElementById("email-auth-form");
const rolePanel = document.getElementById("role-panel");
const roleText = document.getElementById("role-text");
const gotoTraveler = document.getElementById("goto-traveler");
const gotoOperator = document.getElementById("goto-operator");
const claimPanel = document.getElementById("claim-panel");
const claimCode = document.getElementById("claim-code");
const claimBtn = document.getElementById("claim-btn");
const claimResult = document.getElementById("claim-result");
const errorRegion = document.getElementById("error-region");

function showError(message) {
  setText(errorRegion, message);
  setHidden(errorRegion, !message);
}

function resetPanels() {
  setHidden(rolePanel, true);
  setHidden(claimPanel, true);
  setHidden(gotoTraveler, true);
  setHidden(gotoOperator, true);
}

async function refreshRole() {
  try {
    const me = await api.get("/me");
    if (me.role === "traveler") {
      setText(roleText, "traveler 계정으로 연결되었습니다.");
      setHidden(rolePanel, false);
      setHidden(gotoTraveler, false);
    } else if (me.role === "operator") {
      setText(roleText, "operator 계정으로 연결되었습니다.");
      setHidden(rolePanel, false);
      setHidden(gotoOperator, false);
    } else {
      setText(roleText, "연결된 역할이 없습니다. 초대 코드를 등록하세요.");
      setHidden(rolePanel, false);
      setHidden(claimPanel, false);
    }
    if (me.revoked) {
      setText(roleText, "이 계정의 접근 권한이 회수되었습니다.");
      setHidden(claimPanel, true);
    }
  } catch (err) {
    showError(describeError(err));
  }
}

onAuth((user) => {
  showError("");
  setText(claimResult, "");
  resetPanels();
  if (user) {
    setText(statusEl, "로그인되었습니다.");
    setHidden(signinBtn, true);
    setHidden(signinEmailBtn, true);
    setHidden(emailAuthForm, true);
    setHidden(signoutBtn, false);
    refreshRole();
  } else {
    setText(statusEl, "로그인되어 있지 않습니다.");
    setHidden(signinBtn, false);
    setHidden(signinEmailBtn, false);
    setHidden(emailAuthForm, false);
    setHidden(signoutBtn, true);
  }
});

signinBtn.addEventListener("click", async () => {
  showError("");
  try {
    await signInWithGoogle();
  } catch {
    showError("로그인에 실패했습니다.");
  }
});

signinEmailBtn.addEventListener("click", async () => {
  showError("");
  const email = loginEmail.value.trim();
  const password = loginPassword.value;
  if (!email || !password) {
    showError("이메일과 비밀번호를 입력하세요.");
    return;
  }
  try {
    await signInWithEmail(email, password);
    loginEmail.value = "";
    loginPassword.value = "";
  } catch {
    showError("로그인에 실패했습니다. 이메일과 비밀번호를 확인하세요.");
  }
});

signoutBtn.addEventListener("click", async () => {
  showError("");
  try {
    await signOutUser();
  } catch {
    showError("로그아웃에 실패했습니다.");
  }
});

claimBtn.addEventListener("click", async () => {
  showError("");
  setText(claimResult, "처리 중…");
  try {
    const result = await api.post("/invitations/claim", {
      invitation_code: claimCode.value.trim(),
    });
    setText(claimResult, `연결 완료 (traveler ${result.traveler_id}).`);
    claimCode.value = "";
    await refreshRole();
  } catch (err) {
    setText(claimResult, "");
    showError(describeError(err));
  }
});
