import { useState, type FormEvent } from "react";
import { loginWithPassword } from "../api/chatApi";

interface LoginDialogProps {
  open: boolean;
  onClose: () => void;
  onSignedIn: () => void;
}

/**
 * #5298 — the sign-in surface.
 *
 * The clone has no authentication of its own. This dialog posts to the
 * operational password route and the operational session cookie decides the
 * rest. The element ids and classes are the operational ones, so the approved
 * styling applies unchanged.
 */
export function LoginDialog({ open, onClose, onSignedIn }: LoginDialogProps) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await loginWithPassword(identifier.trim(), password);
      setPassword("");
      onSignedIn();
      onClose();
    } catch (failure) {
      setError(
        failure instanceof Error && failure.message
          ? failure.message
          : "로그인 정보를 확인해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog className="auth-dialog" id="authDialog" open aria-labelledby="authDialogTitle">
      <div className="auth-panel">
        <div className="auth-header">
          <div>
            <p>Padiem Account</p>
            <h2 id="authDialogTitle">로그인 / 회원가입</h2>
          </div>
          <button
            className="auth-close"
            id="authDialogClose"
            type="button"
            aria-label="로그인 창 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <form className="auth-form" id="passwordLoginForm" onSubmit={submit}>
          <h3>아이디로 로그인</h3>
          <label htmlFor="passwordLoginIdentifier">아이디 또는 이메일</label>
          <input
            id="passwordLoginIdentifier"
            name="identifier"
            type="text"
            autoComplete="username"
            maxLength={320}
            required
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
          />
          <label htmlFor="passwordLoginPassword">비밀번호</label>
          <input
            id="passwordLoginPassword"
            name="password"
            type="password"
            autoComplete="current-password"
            maxLength={128}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {error ? (
            <p className="auth-error" id="passwordLoginError" role="alert">
              {error}
            </p>
          ) : null}
          <button className="auth-primary" id="passwordLoginSubmit" type="submit" disabled={busy}>
            로그인
          </button>
        </form>
      </div>
    </dialog>
  );
}
