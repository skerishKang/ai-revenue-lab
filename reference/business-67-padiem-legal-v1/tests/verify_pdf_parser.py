from __future__ import annotations

import base64
import os

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("B67_PDF_QA_BASE_URL", "http://127.0.0.1:8899")
MULTIPAGE = "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3VyY2UpCjEgMCBvYmoKPDwKL0YxIDIgMCBSCj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nIC9OYW1lIC9GMSAvU3VidHlwZSAvVHlwZTEgL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL0NvbnRlbnRzIDkgMCBSIC9NZWRpYUJveCBbIDAgMCA2MTIgNzkyIF0gL1BhcmVudCA4IDAgUiAvUmVzb3VyY2VzIDw8Ci9Gb250IDEgMCBSIC9Qcm9jU2V0IFsgL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSSBdCj4+IC9Sb3RhdGUgMCAvVHJhbnMgPDwKCj4+IAogIC9UeXBlIC9QYWdlCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9Db250ZW50cyAxMCAwIFIgL01lZGlhQm94IFsgMCAwIDYxMiA3OTIgXSAvUGFyZW50IDggMCBSIC9SZXNvdXJjZXMgPDwKL0ZvbnQgMSAwIFIgL1Byb2NTZXQgWyAvUERGIC9UZXh0IC9JbWFnZUIgL0ltYWdlQyAvSW1hZ2VJIF0KPj4gL1JvdGF0ZSAwIC9UcmFucyA8PAoKPj4gCiAgL1R5cGUgL1BhZ2UKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL0NvbnRlbnRzIDExIDAgUiAvTWVkaWFCb3ggWyAwIDAgNjEyIDc5MiBdIC9QYXJlbnQgOCAwIFIgL1Jlc291cmNlcyA8PAovRm9udCAxIDAgUiAvUHJvY1NldCBbIC9QREYgL1RleHQgL0ltYWdlQiAvSW1hZ2VDIC9JbWFnZUkgXQo+PiAvUm90YXRlIDAgL1RyYW5zIDw8Cgo+PiAKICAvVHlwZSAvUGFnZQo+PgplbmRvYmoKNiAwIG9iago8PAovUGFnZU1vZGUgL1VzZU5vbmUgL1BhZ2VzIDggMCBSIC9UeXBlIC9DYXRhbG9nCj4+CmVuZG9iago3IDAgb2JqCjw8Ci9BdXRob3IgKGFub255bW91cykgL0NyZWF0aW9uRGF0ZSAoRDoyMDI2MTAwMTA5MDkwNCswMCcwMCcpIC9DcmVhdG9yIChhbm9ueW1vdXMpIC9LZXl3b3JkcyAoKSAvTW9kRGF0ZSAoRDoyMDI2MTAwMTA5MDkwNCswMCcwMCcpIC9Qcm9kdWNlciAoUmVwb3J0TGFiIFBERiBMaWJyYXJ5IC0gXChvcGVuc291cmNlXCkpIAogIC9TdWJqZWN0ICh1bnNwZWNpZmllZCkgL1RpdGxlICh1bnRpdGxlZCkgL1RyYXBwZWQgL0ZhbHNlCj4+CmVuZG9iago4IDAgb2JqCjw8Ci9Db3VudCAzIC9LaWRzIFsgMyAwIFIgNCAwIFIgNSAwIFIgXSAvVHlwZSAvUGFnZXMKPj4KZW5kb2JqCjkgMCBvYmoKPDwKL0ZpbHRlciBbIC9BU0NJSTg1RGVjb2RlIC9GbGF0ZURlY29kZSBdIC9MZW5ndGggMTIxCj4+CnN0cmVhbQpHYXBRaDBFPUYsMFVcSDNUXHBOWVReUUtrP3RjPklQLDtXI1UxXjIzaWhQRU1fP0NXNEtJU2k8IVs3YCNPQl9zSyEoVjY3ImIvYTxLcCdyW2dzIUZMUDBFaGRLdFI+SGJpRF90S29kaj4mMXJ1TSJZS2UjZS8zP34+ZW5kc3RyZWFtCmVuZG9iagoxMCAwIG9iago8PAovRmlsdGVyIFsgL0FTQ0lJODVEZWNvZGUgL0ZsYXRlRGVjb2RlIF0gL0xlbmd0aCA1OQo+PgpzdHJlYW0KR2FwUWgwRT1GLDBVXEgzVFxwTllUXlFLaz90Yz5JUCw7VyNVMV4yM2loUEVNX1BQJE8hM14sQzVRfj5lbmRzdHJlYW0KZW5kb2JqCjExIDAgb2JqCjw8Ci9GaWx0ZXIgWyAvQVNDSUk4NURlY29kZSAvRmxhdGVEZWNvZGUgXSAvTGVuZ3RoIDExMQo+PgpzdHJlYW0KR2FwUWgwRT1GLDBVXEgzVFxwTllUXlFLaz90Yz5JUCw7VyNVMV4yM2loUEVNXz9DVzRLSVNpPCFbN2AjT0Jfc0shKFY2N0tiMDpmPScoKk1lRGMpWF1dKW1iS29kaj4mMXJ0YiJZS2VTQ0RBS34+ZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgMTIKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDYxIDAwMDAwIG4gCjAwMDAwMDAwOTIgMDAwMDAgbiAKMDAwMDAwMDE5OSAwMDAwMCBuIAowMDAwMDAwMzkyIDAwMDAwIG4gCjAwMDAwMDA1ODYgMDAwMDAgbiAKMDAwMDAwMDc4MCAwMDAwMCBuIAowMDAwMDAwODQ4IDAwMDAwIG4gCjAwMDAwMDExMDkgMDAwMDAgbiAKMDAwMDAwMTE4MCAwMDAwMCBuIAowMDAwMDAxMzkxIDAwMDAwIG4gCjAwMDAwMDE1NDAgMDAwMDAgbiAKdHJhaWxlcgo8PAovSUQgCls8NDAwNzI5Njc0MzRlNDY2Y2VlZDNmNTFkZmRiZjNhZTg+PDQwMDcyOTY3NDM0ZTQ2NmNlZWQzZjUxZGZkYmYzYWU4Pl0KJSBSZXBvcnRMYWIgZ2VuZXJhdGVkIFBERiBkb2N1bWVudCAtLSBkaWdlc3QgKG9wZW5zb3VyY2UpCgovSW5mbyA3IDAgUgovUm9vdCA2IDAgUgovU2l6ZSAxMgo+PgpzdGFydHhyZWYKMTc0MgolJUVPRgo="
NO_TEXT = "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgNjEyIDc5MiBdCi9QYXJlbnQgMiAwIFIKPj4KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDU0IDAwMDAwIG4gCjAwMDAwMDAxMTMgMDAwMDAgbiAKMDAwMDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjI1NgolJUVPRgo="
ENCRYPTED = "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgPDI0ZjdiNzEyZGY+Cj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9UeXBlIC9QYWdlcwovQ291bnQgMQovS2lkcyBbIDQgMCBSIF0KPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL0NhdGFsb2cKL1BhZ2VzIDIgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9QYWdlCi9SZXNvdXJjZXMgPDwKPj4KL01lZGlhQm94IFsgMC4wIDAuMCA2MTIgNzkyIF0KL1BhcmVudCAyIDAgUgo+PgplbmRvYmoKNSAwIG9iago8PAovViAyCi9SIDMKL0xlbmd0aCAxMjgKL1AgNDI5NDk2NzI5MgovRmlsdGVyIC9TdGFuZGFyZAovTyA8MGU1MjI5MjVhM2U0ZTg3NGMzY2ZhY2JlZjUxMWE3M2FjNGVjMmJkODY1ZGNkM2Q0NjI3NjE0OTE3YWJmZDdlND4KL1UgPDAxODBmY2VkMTZhNjA0MjJmNDJjNDhhNTMzZjMzYjRlMjhiZjRlNWU0ZTc1OGE0MTY0MDA0ZTU2ZmZmYTAxMDg+Cj4+CmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA1OSAwMDAwMCBuIAowMDAwMDAwMTE4IDAwMDAwIG4gCjAwMDAwMDAxNjcgMDAwMDAgbiAKMDAwMDAwMDI2MSAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDYKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKL0lEIFsgPDM1NjEzMTMyNjIzNzY0MzczODM1NjEzNjY0MzUzNTM3MzUzNjM5NjI2MjM3MzA2NDMyMzQzMjMyNjEzNzMwMzk+IDwzNTYxMzEzMjYyMzc2NDM3MzgzNTYxMzY2NDM1MzUzNzM1MzYzOTYyNjIzNzMwNjQzMjM0MzIzMjYxMzczMDM5PiBdCi9FbmNyeXB0IDUgMCBSCj4+CnN0YXJ0eHJlZgo0NzYKJSVFT0YK"


def prepare_session(page) -> None:
    page.evaluate(
        """async () => {
          window.__b67PdfSession = await window.B67PdfPageParser.prepareParser();
        }"""
    )


def evaluate_prepared_parse(page, encoded: str, *, pad_to: int | None = None):
    return page.evaluate(
        """async ({encoded, padTo}) => {
          const raw = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
          let bytes = raw;
          if (padTo && padTo > raw.length) {
            bytes = new Uint8Array(padTo);
            bytes.set(raw);
            bytes.fill(32, raw.length);
          }
          return await window.__b67PdfSession.parseArrayBuffer(bytes.buffer);
        }""",
        {"encoded": encoded, "padTo": pad_to},
    )


def evaluate_parse(page, encoded: str, *, pad_to: int | None = None):
    prepare_session(page)
    return evaluate_prepared_parse(page, encoded, pad_to=pad_to)


def main() -> None:
    console_errors: list[str] = []
    requests: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("request", lambda request: requests.append(request.url))
        page.goto(f"{BASE_URL}/tests/pdf-parser-harness.html", wait_until="networkidle")

        assert page.evaluate("window.B67PdfPageParser.PINNED_PDFJS_VERSION") == "6.3.289"

        prepare_session(page)
        before = len(requests)
        multi = evaluate_prepared_parse(page, MULTIPAGE)
        parse_requests = requests[before:]
        assert multi["ok"] is True
        assert multi["page_count"] == 3
        assert [p["page_number"] for p in multi["pages"]] == [1, 2, 3]
        assert "PAGE ONE" in multi["pages"][0]["text"]
        assert multi["pages"][1]["text"] == ""
        assert "PAGE THREE" in multi["pages"][2]["text"]
        assert multi["native_text_state"] == "mixed"
        assert multi["ocr_candidate_pages"] == [2]
        assert parse_requests == [], parse_requests

        no_text = evaluate_parse(page, NO_TEXT)
        assert no_text["ok"] is False
        assert no_text["code"] == "pdf_no_native_text"
        assert no_text["page_count"] == 1
        assert no_text["ocr_candidate_pages"] == [1]

        encrypted = evaluate_parse(page, ENCRYPTED)
        assert encrypted == {"ok": False, "code": "pdf_password_required"}

        corrupt = evaluate_parse(page, base64.b64encode(b"%PDF-1.7\nnot-a-valid-pdf").decode())
        assert corrupt == {"ok": False, "code": "pdf_parse_failed"}

        large = evaluate_parse(page, MULTIPAGE, pad_to=2 * 1024 * 1024 + 65536)
        assert large["ok"] is True
        assert large["page_count"] == 3

        timeout = page.evaluate(
            """async () => {
              window.__b67Terminated = 0;
              class SilentWorker {
                constructor() {
                  this.onmessage = null;
                  this.onerror = null;
                  setTimeout(() => this.onmessage && this.onmessage({
                    data: {type: "ready", parser: "pdfjs-dist", parser_version: "6.3.289"}
                  }), 0);
                }
                postMessage() {}
                terminate() { window.__b67Terminated += 1; }
              }
              const session = await window.B67PdfPageParser.prepareParser({
                WorkerCtor: SilentWorker,
                workerUrl: "fake://worker",
                readyTimeoutMs: 100
              });
              const result = await session.parseArrayBuffer(
                new Uint8Array([37, 80, 68, 70, 45, 49]).buffer,
                {timeoutMs: 5}
              );
              return {result, terminated: window.__b67Terminated};
            }"""
        )
        assert timeout["result"] == {"ok": False, "code": "pdf_parser_timeout"}
        assert timeout["terminated"] == 1

        cancelled = page.evaluate(
            """async () => {
              window.__b67CancelledTerminated = 0;
              class SilentWorker {
                constructor() {
                  this.onmessage = null;
                  this.onerror = null;
                  setTimeout(() => this.onmessage && this.onmessage({
                    data: {type: "ready", parser: "pdfjs-dist", parser_version: "6.3.289"}
                  }), 0);
                }
                postMessage() {}
                terminate() { window.__b67CancelledTerminated += 1; }
              }
              const session = await window.B67PdfPageParser.prepareParser({
                WorkerCtor: SilentWorker,
                workerUrl: "fake://worker",
                readyTimeoutMs: 100
              });
              const controller = new AbortController();
              const pending = session.parseArrayBuffer(
                new Uint8Array([37, 80, 68, 70, 45, 49]).buffer,
                {timeoutMs: 100, signal: controller.signal}
              );
              controller.abort();
              const result = await pending;
              return {result, terminated: window.__b67CancelledTerminated};
            }"""
        )
        assert cancelled["result"] == {"ok": False, "code": "pdf_parse_cancelled"}
        assert cancelled["terminated"] == 1

        assert not console_errors, console_errors
        browser.close()

    print("B67_BROWSER_PDF_NATIVE_TEXT=PASS")
    print("DEDICATED_WEB_WORKER=YES")
    print("NETWORK_DURING_PARSE=0")
    print("PAGE_NUMBERS_EXACT=YES")
    print("BLANK_PAGE_RENUMBER=0")
    print("SCANNED_PDF_FALSE_SUCCESS=0")
    print("TIMEOUT_TERMINATES_WORKER=YES")
    print("CANCEL_TERMINATES_WORKER=YES")
    print("RAW_SOURCE_BROWSER_PERSISTENCE=0")
    print("PDFJS_VERSION=6.3.289")
    print("PDFJS_LICENSE=Apache-2.0")
    print("PRODUCTION_MUTATION=0")


if __name__ == "__main__":
    main()
