# Product Contract

## Promise

Turn heterogeneous personal source files into readable volumes and collections. Let the user discover and remember them spatially in a 3D library, then inspect, search and annotate them precisely in a 2D reader.

## Primary result

```text
A SEARCHABLE, READABLE, USER-CONTROLLED PERSONAL RECORD LIBRARY
```

## Authoritative layers

1. **Original source** — immutable or explicitly versioned bytes and provenance.
2. **Derived index** — extracted text, thumbnails, 3D previews, OCR, outline, embeddings and summaries; regenerable.
3. **User record** — shelf composition, titles, notes, highlights, bookmarks, corrections and links; durable and exportable.

The product must not silently merge these layers.

## Mode contract

- 3D mode owns spatial recognition, volume identity and bounded preview.
- 2D mode owns faithful reading, search, selection, zoom, navigation and anchored records.
- Direct 2D access is always available.
- 3D previews never replace the source.
- Position changes in either mode synchronize through a source-relative page or section anchor.

## Initial source types

- PDF with extractable text;
- UTF-8 TXT;
- Markdown.

DOCX, OCR and image collections are later bounded additions.

## Model modes

```text
OFF
LOCAL_ONLY
LOCAL_PLUS_WEB
```

Local-only operation must remain useful. A web call requires explicit source/range selection and must produce resolvable source references.
