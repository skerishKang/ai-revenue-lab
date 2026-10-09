#!/usr/bin/env bash
# #3930 exact-B62 Cloudflare management GET only; retry strictly HTTP 504.
set -euo pipefail
test "$#" -eq 2
url="$1"
output="$2"
test -n "${CLOUDFLARE_API_TOKEN:-}"
test -n "${CLOUDFLARE_ACCOUNT_ID:-}"
test -n "${B62_WORKER:-}"
base="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${B62_WORKER}"
case "${url}" in
  "${base}/settings"|"${base}/deployments"|"${base}/subdomain"|"${base}/versions"*)
    ;;
  *) echo 'CF_B62_READONLY_GET=UNAUTHORIZED_PATH' >&2; exit 2 ;;
esac
for attempt in 1 2; do
  code="$(curl -sS --connect-timeout 8 --max-time 70 \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H 'Content-Type: application/json' \
    -o "${output}" -w '%{http_code}' "${url}" || true)"
  if [ "${code}" = "200" ]; then
    echo 'CF_B62_READONLY_GET=HTTP_200'
    if [ "${attempt}" -eq 2 ]; then echo 'CF_B62_READONLY_504_RETRY=RECOVERED'; fi
    exit 0
  fi
  if [ "${code}" != "504" ]; then
    echo 'CF_B62_READONLY_GET=BLOCKED_NON_504' >&2
    exit 1
  fi
  if [ "${attempt}" -eq 1 ]; then
    echo 'CF_B62_READONLY_504_RETRY=ONCE'
    sleep 2
  fi
done
echo 'CF_B62_READONLY_GET=BLOCKED_REPEATED_504' >&2
exit 1
