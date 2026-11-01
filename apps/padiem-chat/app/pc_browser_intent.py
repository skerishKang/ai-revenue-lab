"""Select the browser-only Claw plan from actual user speech.

This selects tools, never authorizes an action. The common Engine harness
checks the role-preserved evidence and the signed Mesh lane checks the PC.
"""
import re

_ADDRESS = re.compile(r"https?://\S*|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?=[/\s]|$)", re.I)
# A bare file name reads as "something.ext" too. Those are files on the PC,
# never a page: the TXT lane and the file tools own them.
_FILE_NAME = re.compile(
    r"\.(?:txt|md|markdown|csv|tsv|log|ini|cfg|conf|yaml|yml|toml|json|jsonl|xml|"
    r"pdf|docx?|pptx?|xlsx?|hwpx?|odt|ods|rtf|"
    r"png|jpe?g|gif|webp|bmp|svg|heic|"
    r"zip|7z|rar|tar|gz|exe|msi|dll|"
    r"py|js|mjs|cjs|ts|tsx|jsx|css|html?|sh|bat|ps1|sql|db|sqlite3?|ipynb)$",
    re.I,
)
_BROWSER = re.compile(r"브라우저|웹\s*페이지|웹사이트|사이트|\bbrowser\b", re.I)
_ACTION = re.compile(r"열|읽|제목|캡처|캡쳐|클릭|눌러|입력|접속|방문|\b(?:open|read|title|capture|screenshot|click|type|visit)\b", re.I)
_YES = re.compile(r"^\s*(?:네|예|응|그래|맞아|진행해|해줘|확인|yes|ok|okay|go ahead)[.!。]?\s*$", re.I)


def _names_a_page(text):
    for match in _ADDRESS.finditer(text):
        host = match.group(0).split("/", 1)[0]
        if host.lower().startswith(("http://", "https://")) or not _FILE_NAME.search(host):
            return True
    return False


def requested_pc_browser(user_text, *, records=()):
    if not isinstance(user_text, str):
        return False
    if (_names_a_page(user_text) or _BROWSER.search(user_text)) and _ACTION.search(user_text):
        return True
    if not _YES.fullmatch(user_text):
        return False
    # records are only the owner-scoped saved conversation, never HTTP history.
    prior = next((row.get("content", "") for row in reversed(records)
                  if row.get("role") == "assistant"), "")
    return bool(isinstance(prior, str) and _ADDRESS.search(prior) and (
        "페이지에서" in prior and "동작을 실행할까요?" in prior
        or "페이지를 열까요?" in prior
    ))
