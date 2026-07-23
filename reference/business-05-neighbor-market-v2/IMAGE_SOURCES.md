# Image and Font Sources — Business 5 Resident-First Reference

## Status

These assets are temporary reference inputs for visual review only. They are not approved production assets.

The current HTML uses remote image URLs and remote Pretendard CSS so the resident-first information hierarchy can be reviewed before a separate asset-hardening task.

No image proves that a displayed business, resident relationship, price, benefit or service actually exists.

## Font

- Pretendard web CSS
- Reference URL: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css`
- Project: `https://github.com/orioncactus/pretendard`
- License: SIL Open Font License 1.1
- Production action: pin and self-host an approved version or use the approved Korean system stack

## Temporary image host

- Unsplash image CDN: `https://images.unsplash.com/`
- Purpose: evaluate crop, density, category recognition and card balance
- License reference: `https://unsplash.com/license`
- Production action: download only approved assets, optimize them and document the final source ledger

## Current category imagery

All current identities and relationships are synthetic.

| Reference use | Unsplash source ID |
|---|---|
| 반찬·식사 | `photo-1547592180-85f173990554` |
| 청소·홈케어 | `photo-1581578731548-c64695cc6952` |
| 교육·교실 | `photo-1509062522246-3755977927d7` |
| 세무·전문업무 | `photo-1454165804606-c3d57bc86b40` |
| 베이커리·디저트 | `photo-1578985545062-69928b1d9587` |
| 헤어·뷰티 | `photo-1560066984-138dadb4c035` |
| 반려견·돌봄 | `photo-1552053831-71594a27632d` |
| 꽃·클래스 | `photo-1490750967868-88aa4486c946` |
| 사진 촬영 | `photo-1542038784456-1ea8e935640e` |
| 반찬·도시락 (Tier 3 신규) | `photo-1517841905240-472988babdf9` |

The exact transformation parameters are embedded in `index-v3.html`. Keep them unchanged during the first screenshot comparison.

## Apartment image policy

The current resident-first prototype does not use an apartment photograph as the main product message. The lead section focuses on residents helping residents.

When an apartment photograph is added later:

- it must not be described as 방림명지로드힐 unless user-supplied or permission-cleared;
- do not scrape Apartment i, Naver, KB, Hogangnono, Richgo or real-estate-listing images;
- avoid identifiable resident faces, vehicle plates and unit-identifying details;
- store the final source and permission record.

## Relationship honesty

Photographs do not establish:

- 방림명지로드힐 resident operation;
- nearby-apartment resident operation;
- actual participation;
- actual resident benefit;
- service quality;
- management-office endorsement.

Every current relationship tier is synthetic preview data.

## Icons

The prototype uses simple inline outline SVG paths.

Reference design family:

- Heroicons, MIT license
- `https://heroicons.com/`

No Baemin, Yogiyo, Karrot, Apartment i or other commercial-service logo, mascot, wordmark or proprietary UI artwork is copied.

## Public apartment facts

The prototype uses only:

- 방림명지로드힐
- 광주광역시 남구 대남대로85번길 3
- 192세대
- 2개 동
- 2015-10-30 사용승인

Research references:

- `https://apt.koreacharts.com/apt/A10027831/contents.html`
- `https://kbland.kr/se/c/30889`

The management-office phone number and resident names are deliberately excluded.

## Future asset-hardening checklist

A separate task may:

1. download the approved image set;
2. remove unneeded metadata;
3. create fixed WebP/JPEG sizes for card, detail and benefit uses;
4. add deterministic dimensions and fallback assets;
5. self-host the font;
6. include required license and attribution records;
7. replace synthetic stock images with participant-supplied business photos after consent;
8. verify that no private resident information appears.

Do not perform asset hardening as part of reference review unless separately instructed.
