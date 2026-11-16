// #7818 PR 2: a synthetic visitor answers the external-login age gate so the
// existing Google-login tests can keep asserting the post-login behavior.
// Returns the original response when no gate was shown.
export async function passGoogleAgeGate(fetcher, response, cookie, origin = 'https://auth.padiem.net') {
  const html = await response.clone().text();
  if (response.status !== 200 || !html.includes('name="age_confirm"')) return response;
  const handle = html.match(/name="handle" value="([^"]+)"/)?.[1];
  if (!handle) throw new Error('age gate handle missing');
  return fetcher(new Request(`${origin}/age-confirm/google`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded', cookie },
    body: new URLSearchParams({ handle, age_confirm: 'yes' }),
  }));
}
