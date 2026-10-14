# Web fetch grounding: search snippet != retrieved page evidence

Audit scope: current Firecrawl and TinyFish Core web provider runtimes used
by B62/Engine research, with user-uploaded documents checked separately.

Both full-page provider fetch implementations normalized their extracted text
through the common evidence helper, which silently applied a 2000-character
search snippet ceiling to every source type. As a result, retrieved page text
beyond the first 2,000 characters was discarded even if the provider had
already returned all of it within the existing bounded response and the
Core grounding context could safely carry it. This was an arbitrary
page-to-model truncation, not a provider-native input cap or a Worker
resource-protection necessity.

The correction retains 2,000 characters for search result snippets and
allows source_type=fetch to retain page evidence up to the EXISTING
1,048,576-byte bounded provider JSON response ceiling. The provider HTTP
reader continues aborting above that existing size, so this does NOT
disable memory protection or permit unbounded fetch/recursive crawling.
Grounding's distinct 5,500,000-character downstream context safety budget,
source selection/provenance, URL/SSRF allowlist, API credential redaction,
citation numbering, trusted/untrusted data boundary, request concurrency,
timeouts and model/quote permissions are unchanged.

Synthetic tests: Firecrawl 5,000-char page complete; TinyFish 15,000+
character source tail survives fetch -> Core model-grounding context;
oversized upstream body still fails with web_response_too_large; ordinary
search result excerpts remain 2,000 chars. No paid provider calls.

For document references: B62 provider-facing build_document_context and
build_project_files_context already default to complete source, while an
explicit max_chars remains a UI excerpt. Engine's separate 4k
ContextWindowProjection is an intentionally bounded public preview
with retained canonical evidence and is not to be silently widened into
a model instruction. No document admission or preview policy changed.

After code merge, B62 and Engine production delivery must be reviewed
according to their exact artifact packaging: source-only changes to the
Core web runtime may need both Worker bundles redeployed; neither may be
claimed served until protected GitHub production proof confirms it.
