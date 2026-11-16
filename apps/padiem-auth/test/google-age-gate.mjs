// Synthetic visitor answers the 14-or-older gate so existing login tests keep
// asserting post-login behavior. Returns the original response when no gate
// was shown; the gate is detected by its opaque handle field (signup screens
// carry age_confirm but never a handle).
export async function passAgeGate(fetcher, response, cookie, origin, action) {
  const html = await response.clone().text();
  if (response.status !== 200 || !html.includes('name="handle"') || !html.includes('name="age_confirm"')) return response;
  const handle = html.match(/name="handle" value="([^"]+)"/)?.[1];
  if (!handle) throw new Error('age gate handle missing');
  return fetcher(new Request(`${origin}${action}`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', cookie },
    body: new URLSearchParams({ handle, age_confirm: 'yes' }),
  }));
}
export const passGoogleAgeGate = (fetcher, response, cookie, origin = 'https://auth.padiem.net') =>
  passAgeGate(fetcher, response, cookie, origin, '/age-confirm/google');
export const passPasswordAgeGate = (fetcher, response, cookie, origin = 'https://auth.padiem.net') =>
  passAgeGate(fetcher, response, cookie, origin, '/age-confirm/password');
