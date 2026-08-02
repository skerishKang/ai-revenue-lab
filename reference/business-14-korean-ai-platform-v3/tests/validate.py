from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    ROOT / "index.html",
    ROOT / "styles/main.css",
    ROOT / "scripts/app.js",
    ROOT / "scripts/catalog-v31-install.js",
    ROOT / "scripts/catalog-rows-a.js",
    ROOT / "scripts/catalog-rows-b.js",
    ROOT / "scripts/catalog-shell-v31.js",
    ROOT / "scripts/catalog-v31.js",
    ROOT / "README.md",
    ROOT / "PRODUCT_CONTRACT.md",
    ROOT / "REFERENCE_NOTES.md",
]
for path in required:
    assert path.exists(), f"missing: {path}"

html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
scripts = "\n".join(
    path.read_text(encoding="utf-8")
    for path in required
    if path.suffix == ".js"
)

for token in [
    "간편", "개발자", "모델·가격", "요금제", "Pay as you go",
    "Personal Plus", "가격 미공개", "플랫폼 수수료", "비용 계산기",
    "예시 환율", "실제 Provider 호출 없음", "무제한이 아닙니다",
]:
    assert token in html, token

for token in [
    "GPT-5.6 Sol",
    "GPT-5.6 Terra",
    "Claude Fable 5",
    "Claude Sonnet 5",
    "Gemini 3.6 Flash",
    "DeepSeek V4 Flash",
    "Qwen 3.6 Plus",
    "Mistral Small 4",
    "HyperCLOVA X THINK",
    'data-filter=\\"popular\\"',
    'data-filter=\\"free\\"',
    "gpt-5.6-sol",
    "claude-sonnet-5",
    "gemini-3.6-flash",
]:
    assert token in scripts, token

assert "prefers-reduced-motion" in css
assert "@media (max-width: 620px)" in css
assert "https://" not in css
assert "fetch(" not in scripts
assert "localStorage" not in scripts
assert "sessionStorage" not in scripts
assert "navigator.clipboard" in scripts
assert "ctrlKey" in scripts
assert "B14CatalogReady" in scripts
assert "latest alias" in scripts.lower()
assert "exact ID" in scripts
assert "가격 미공개" in scripts
assert "전기·장비 제외" in scripts

print("validation passed")
