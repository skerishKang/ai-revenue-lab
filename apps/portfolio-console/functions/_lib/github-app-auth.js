const API_VERSION = "2026-03-10";
const ACCEPT = "application/vnd.github+json";
const USER_AGENT = "ai-revenue-portfolio-console";

export class GitHubAuthError extends Error {
  constructor(code, message) { super(message); this.name = "GitHubAuthError"; this.code = code; }
}
function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function encodeJson(value) { return base64Url(new TextEncoder().encode(JSON.stringify(value))); }
function decodePkcs8(privateKeyPkcs8) {
  const normalized = String(privateKeyPkcs8 || "")
    .replace(/-----BEGIN PRIVATE KEY-----/g, "")
    .replace(/-----END PRIVATE KEY-----/g, "")
    .replace(/\s+/g, "");
  if (!normalized) throw new GitHubAuthError("PRIVATE_KEY_INVALID", "GitHub App authentication failed.");
  try {
    const binary = atob(normalized);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    throw new GitHubAuthError("PRIVATE_KEY_INVALID", "GitHub App authentication failed.");
  }
}
export async function createGitHubAppJwt({ appId, privateKeyPkcs8, nowSeconds, cryptoImpl = globalThis.crypto }) {
  if (!cryptoImpl?.subtle) throw new GitHubAuthError("CRYPTO_UNAVAILABLE", "GitHub App authentication failed.");
  const now = Number.isFinite(nowSeconds) ? Math.floor(nowSeconds) : Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = { iat: now - 60, exp: now + 540, iss: String(appId) };
  const unsigned = `${encodeJson(header)}.${encodeJson(payload)}`;
  try {
    const key = await cryptoImpl.subtle.importKey("pkcs8", decodePkcs8(privateKeyPkcs8),
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
    const signature = await cryptoImpl.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
    return `${unsigned}.${base64Url(new Uint8Array(signature))}`;
  } catch (error) {
    if (error instanceof GitHubAuthError) throw error;
    throw new GitHubAuthError("JWT_SIGNING_FAILED", "GitHub App authentication failed.");
  }
}
export class InstallationTokenProvider {
  constructor({ appId, installationId, privateKeyPkcs8, fetchImpl = fetch, now = () => Date.now(), cryptoImpl = globalThis.crypto }) {
    this.appId = appId; this.installationId = installationId; this.privateKeyPkcs8 = privateKeyPkcs8;
    this.fetchImpl = fetchImpl; this.now = now; this.cryptoImpl = cryptoImpl; this.cached = null; this.inFlight = null;
  }
  invalidate() { this.cached = null; }
  async exchange() {
    const nowMs = this.now();
    const jwt = await createGitHubAppJwt({ appId: this.appId, privateKeyPkcs8: this.privateKeyPkcs8,
      nowSeconds: Math.floor(nowMs / 1000), cryptoImpl: this.cryptoImpl });
    const response = await this.fetchImpl(
      `https://api.github.com/app/installations/${encodeURIComponent(String(this.installationId))}/access_tokens`,
      { method: "POST", headers: { Accept: ACCEPT, Authorization: `Bearer ${jwt}`,
        "X-GitHub-Api-Version": API_VERSION, "User-Agent": USER_AGENT } }
    );
    if (!response.ok) throw new GitHubAuthError("INSTALLATION_TOKEN_EXCHANGE_FAILED", "GitHub App authentication failed.");
    let data;
    try { data = await response.json(); } catch { throw new GitHubAuthError("INSTALLATION_TOKEN_RESPONSE_INVALID", "GitHub App authentication failed."); }
    const expiresAtMs = Date.parse(data?.expires_at || "");
    if (typeof data?.token !== "string" || !data.token || !Number.isFinite(expiresAtMs)) {
      throw new GitHubAuthError("INSTALLATION_TOKEN_RESPONSE_INVALID", "GitHub App authentication failed.");
    }
    this.cached = { token: data.token, expiresAtMs };
    return data.token;
  }
  getToken({ forceRefresh = false } = {}) {
    const nowMs = this.now();
    if (!forceRefresh && this.cached && this.cached.expiresAtMs - 60_000 > nowMs) return Promise.resolve(this.cached.token);
    if (forceRefresh) this.cached = null;
    if (this.inFlight) return this.inFlight;
    let wrapped;
    wrapped = this.exchange().finally(() => { if (this.inFlight === wrapped) this.inFlight = null; });
    this.inFlight = wrapped;
    return wrapped;
  }
}
