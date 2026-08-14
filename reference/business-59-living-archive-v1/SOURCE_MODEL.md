# Source Model

## SourceAsset

```text
id
version
checksum
filename
mime_type
byte_size
page_or_character_count
imported_at
modified_at
provenance_note
extraction_status
```

## Volume

```text
id
title
collection_id
cover_style
source_refs[]
chapter_order[]
last_anchor
updated_at
```

One volume may reference one source, selected ranges from one source, several sources arranged as chapters, or user-authored entries appended over time.

## DerivedArtifact

```text
source_id
source_version
artifact_type
implementation_version
status
location_or_key
created_at
```

Examples: extracted text, outline, page thumbnail, 3D texture, OCR result, semantic chunk, embedding and summary.

## ReadingRecord

```text
volume_id
source_id
anchor
mode
zoom
bookmark
note
updated_at
```

## Integrity rules

- derived artifacts can be regenerated without changing the source or user record;
- re-indexing must preserve source-relative anchors;
- unsupported extraction leaves the source readable;
- model suggestions remain suggestions until explicitly accepted;
- no web model receives source content without a separate explicit authorization event.
