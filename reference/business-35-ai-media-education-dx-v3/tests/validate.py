from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    'index.html', 'styles/main.css', 'scripts/data.js', 'scripts/app.js',
    'PRODUCT_CONTRACT.md', 'EXPERIENCE_ARCHITECTURE.md', 'VISUAL_SYSTEM.md',
    'MARKET_REFERENCE_MAP.md', 'IMAGE_SOURCES.md', 'README.md'
]
for item in required:
    assert (ROOT / item).is_file(), f'missing: {item}'
html = (ROOT / 'index.html').read_text(encoding='utf-8')
for phrase in [
    'AI 교육을 듣는 데서 끝내지 않고',
    '전환안 생성',
    '6주 업무전환 파일럿',
    'data-copy-brief',
    'SYNTHETIC CASE'
]:
    assert phrase in html, f'missing phrase: {phrase}'
assert html.count('<section') >= 7
print('BUSINESS_35_V3_STATIC_CONTRACT_PASS')
