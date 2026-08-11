# B01 V5 — Raster Asset Source Provenance

Status: `SOURCE_PROVENANCE_RECORDED`

These source photographs are used only to create **local processed WebP assets** for B01 V5. Production must not request Pexels at runtime.

All meaningful B01 text, annotations, issue labels, source excerpts, review decisions, and controls remain HTML. Source photography is cropped/defocused/processed so readable third-party print text is not used as product content.

## 1. Hero / private publication material

- Source page: `https://www.pexels.com/photo/detail-of-open-magazine-6348/`
- Author shown by source: Karolina Grabowska / kaboompics.com
- Source page status inspected 2026-08-11: Free to use (CC0)
- Source image: open magazine / printed publication still life
- B01 translation: private publication material / Edition atmosphere
- Processing: editorial crop, warm paper/ink grade, slight print-content defocus, WebP conversion

## 2. Human Review / editorial intervention

- Source page: `https://www.pexels.com/photo/a-person-taking-notes-5582874/`
- Author shown by source: Thirdman
- Source page status inspected 2026-08-11: Free to use
- Source image: hands making notes on printed editorial material
- B01 translation: explicit human review / proofing
- Processing: tight crop to hands + page, blur source handwritten/printed text, warm/ink/coral grade, WebP conversion

## 3. Private Library / collectible sequence

- Source page: `https://www.pexels.com/photo/a-stack-of-open-magazines-4271624/`
- Author shown by source: alleksana
- Source page status inspected 2026-08-11: Free to use
- Source image: stacked open magazines
- B01 translation: accumulated Edition sequence / collectible publication depth
- Processing: crop emphasizing edges/spines/page depth, suppress source content detail, warm/ink/coral grade, WebP conversion

## 4. Edition Read / opening material

- Source page: `https://www.pexels.com/photo/person-holding-white-paper-8148578/`
- Author shown by source: Vie Studio
- Source page status inspected 2026-08-11: Free to use
- Source image: blank open notebook held by hands
- B01 translation: physical opening / readable Edition surface
- Processing: crop to blank spread + hands, reduce identifiable person presence, warm paper grade, WebP conversion

## Runtime rule

```text
PEXELS_RUNTIME_REQUESTS=FORBIDDEN
LOCAL_WEBP_REQUIRED=true
READABLE_TEXT_BAKED_IN_RASTER=FORBIDDEN
```

The temporary source-ingest workflow used during development must be deleted before merge.