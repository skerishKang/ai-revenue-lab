# Image Sources — Living Travel Interactive Demo

All images are synthetically generated. No real photographs, no identifiable
people, property, or personal data. CC0-equivalent.

## Image inventory

| File | Method | Date | Dimensions | Size | Notes |
|---|---|---|---|---|---|
| `busan-hero.webp` | Algorithmic gradient + radial accents via Pillow | 2026-07-24 | 1200×600 | 5,250 B | Synthetic hero. Not a real photograph of Busan. Warm coastal palette. |
| `busan-alley.webp` | Algorithmic gradient + radial accents via Pillow | 2026-07-24 | 800×500 | 2,168 B | Alley/neighborhood atmosphere. Synthetic. Warm earth tones. |
| `busan-food.webp` | Algorithmic gradient + radial accents via Pillow | 2026-07-24 | 800×500 | 3,544 B | Local food atmosphere. Synthetic. Warm terracotta-to-cream. |
| `busan-sea.webp` | Algorithmic gradient + radial accents via Pillow | 2026-07-24 | 800×500 | 2,618 B | Coastal/sea atmosphere. Synthetic. Deep forest to sea-foam. |
| `edition-cover.webp` | Algorithmic gradient + radial accents via Pillow | 2026-07-24 | 800×500 | 4,656 B | Edition cover image. Synthetic. Forest/terracotta/gold editorial palette. |
| `placeholder.webp` | Algorithmic gradient via Pillow | 2026-07-24 | 800×500 | 870 B | Generic fallback. Neutral gray gradient. |

## Generation method

All images generated via a Python script using Pillow (`gen_images2.py`):

1. Linear vertical gradient base over two or three RGB stops.
2. Subtle radial line burst accents (procedural, no external input).
3. Saved as WebP (quality 80, method 6 for hero/cover; quality 70 for placeholder).
4. No EXIF metadata (Pillow does not embed EXIF by default).
5. No external assets, no hotlinks, no AI model inference.

## Visual nature

These are **synthetic atmosphere images** — they communicate mood, not factual
travel conditions. The demo intentionally uses algorithmic gradients to avoid:

- Misrepresentation as real-time travel photography.
- Licensing ambiguity from scraped or hotlinked photographs.
- Depiction of identifiable locations, people, or businesses.

## Replacement policy

When properly CC0-licensed Busan travel photographs are obtained for a
production deployment:

1. Convert to WebP (quality 80).
2. Keep under 400 KB (hero) / 250 KB (section).
3. Strip EXIF.
4. Add meaningful Korean `alt` text.
5. Replace gradient files with real images.
6. Update this file with source URL, photographer attribution, and date.

## Prohibited

- Hotlinking from search results, travel blogs, or unlicensed sources.
- Images containing identifiable people, property, or personal data.
- Images that could be mistaken for real-time travel conditions.
