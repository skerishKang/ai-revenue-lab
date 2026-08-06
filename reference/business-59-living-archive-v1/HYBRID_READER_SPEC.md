# Hybrid Reader Specification

## State

```js
{
  volumeId,
  sourceId,
  pageIndex,
  readingMode,
  zoom,
  searchQuery,
  bookmarks,
  notes,
  reducedMotion
}
```

## Transitions

### Shelf → 3D book

Preserve selected `volumeId` and its last `pageIndex`. Open a derived preview. Do not parse or rewrite the source during this transition.

### Shelf → 2D reader

Allow a direct precision-reader route. The 3D animation is not a gate.

### 3D book → 2D reader

Carry `volumeId`, `sourceId` and the left-page anchor into the 2D reader.

### 2D reader → 3D book

Return to the same volume and map the active source page or section to the nearest derived preview spread.

## Mapping authority

Source-relative anchors are authoritative. 3D page textures and coordinates are derived. Re-rendering a cover or preview must not invalidate notes or bookmarks.

## Accessibility

- every book is a button with an accessible name and selected state;
- the reader is reachable without 3D motion;
- reading text is DOM text in this MVP;
- focus is visible;
- reduced-motion mode removes spatial transitions without removing functionality;
- mobile prioritizes the 2D reader over preserving a desktop 3D composition.

## MVP limitations

The current `PDF-like` fixture is accessible DOM text, not a production PDF rendering. A future runtime should use a maintained PDF renderer and text layer while preserving this state contract.
