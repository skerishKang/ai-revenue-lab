from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    ROOT / "index.html",
    ROOT / "styles/main.css",
    ROOT / "scripts/app.js",
    ROOT / "README.md",
    ROOT / "PRODUCT_CONTRACT.md",
    ROOT / "REFERENCE_NOTES.md",
]
for path in required:
    assert path.exists(), f"missing: {path}"

html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
js = (ROOT / "scripts/app.js").read_text(encoding="utf-8")

for token in [
    "간편", "개발자", "모델·가격", "요금제", "Pay as you go",
    "Personal Plus", "가격 미공개", "플랫폼 수수료", "비용 계산기",
    "예시 환율", "실제 Provider 호출 없음", "무제한이 아닙니다",
]:
    assert token in html, token

assert "prefers-reduced-motion" in css
assert "@media (max-width: 620px)" in css
assert "https://" not in css
assert "fetch(" not in js
assert "localStorage" not in js
assert "sessionStorage" not in js
assert "navigator.clipboard" in js
assert "Ctrl" not in js or "ctrlKey" in js

print("validation passed")
