# Temporary Image, Font and Icon Sources

## Status

These assets exist only to review the Business 5 v2 reference design. They are not approved production assets.

Before production:

1. download and freeze every approved asset;
2. preserve required license material;
3. remove remote hotlinks;
4. review logos, faces, locations and private information;
5. replace the apartment hero with a user-supplied or permission-cleared photograph of 방림명지로드힐.

## Apartment hero

Current temporary reference:

- URL: `https://images.unsplash.com/photo-1545324418-cc1a3fa10c00`
- Use: generic modern apartment-building context
- Important: **not a photograph of 방림명지로드힐**
- UI disclosure: `참고 이미지 · 실제 단지 사진 교체 전`

Do not scrape or copy apartment photography from Apartment i, KB Real Estate, Naver Real Estate, Hogangnono, Richgo or a property listing into production. A publicly visible image is not automatically cleared for reuse.

## Shop photographs

All shop identities and offerings are synthetic. The photographs are temporary category illustrations.

| Prototype use | Unsplash image URL |
|---|---|
| 반찬·식사 | `https://images.unsplash.com/photo-1547592180-85f173990554` |
| 식탁·메뉴 | `https://images.unsplash.com/photo-1504674900247-0877df9cc836` |
| 채소·도시락 준비 | `https://images.unsplash.com/photo-1547592166-23ac45744acd` |
| 카페 | `https://images.unsplash.com/photo-1495474472287-4d71bcdd2085` |
| 청소·홈케어 | `https://images.unsplash.com/photo-1581578731548-c64695cc6952` |
| 교육·교실 | `https://images.unsplash.com/photo-1509062522246-3755977927d7` |
| 헤어·뷰티 | `https://images.unsplash.com/photo-1522337660859-02fbefca4702` |
| 반려견 | `https://images.unsplash.com/photo-1552053831-71594a27632d` |
| 세무·문서 | `https://images.unsplash.com/photo-1450101499163-c8848c66ca85` |
| 꽃·플라워 | `https://images.unsplash.com/photo-1490750967868-88aa4486c946` |
| 사진 촬영 | `https://images.unsplash.com/photo-1516035069371-29a1b244cc32` |
| 스트레칭·움직임 | `https://images.unsplash.com/photo-1518611012118-696072aa579a` |

Reference transformation parameters append `auto=format`, `fit=crop`, width and quality values. They do not change the source identity.

Official Unsplash license reference:

- `https://unsplash.com/license`

Even where copyright use is permitted, production must review model/property releases, visible brands, sensitive context and the suitability of presenting the image as a specific business.

## Font

Reference font:

- Pretendard
- CDN: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css`
- Project: `https://github.com/orioncactus/pretendard`
- License: SIL Open Font License 1.1
- License text: `https://github.com/orioncactus/pretendard/blob/main/LICENSE`

Production should pin and self-host an approved version rather than depending indefinitely on an unversioned remote stylesheet.

## Icons

The prototype uses hand-selected inline outline SVG paths following the simple interaction language of open-source line-icon sets.

Reference license family:

- Heroicons: MIT
- `https://heroicons.com/`

No Baemin, Yogiyo, Karrot, Apartment i or other commercial-service icons, mascots, wordmarks or UI artwork are copied.

## Public apartment facts

The prototype uses only these public location/context facts:

- 방림명지로드힐
- 광주광역시 남구 대남대로85번길 3
- 192세대
- 2개 동
- 2015-10-30 사용승인

Reference sources used during design research:

- K-apt-derived apartment information: `https://apt.koreacharts.com/apt/A10027831/contents.html`
- KB Real Estate complex page: `https://kbland.kr/se/c/30889`

The management-office phone number visible on third-party pages is deliberately not included in the marketplace prototype.
