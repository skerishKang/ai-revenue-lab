# B59 Local Import/Index Slice

This package is the bounded `#2464` source-only slice for Business 59.

```text
MODEL_EXECUTION=OFF
LOCAL_ONLY=YES
NETWORK_CALLS=0
SYNTHETIC_FIXTURES_ONLY=YES
```

It accepts caller-provided bytes for UTF-8 TXT, Markdown, and a small
extractable-text PDF contract. It keeps original bytes in memory, records a
content checksum and versioned metadata, creates deterministic page/section
anchors, and supports exact title/text search with source-grounded references.

It intentionally does not provide OCR, embeddings, semantic search, model
execution, persistence, authentication, cloud sync, or private-file ingestion.

Run the focused tests from this directory:

```text
python -m unittest discover -s tests -v
```
