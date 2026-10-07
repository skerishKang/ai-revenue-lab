# B67 browser PDF parser dependency review

Issue: #3329

The browser-native PDF extraction POC uses **Mozilla PDF.js / pdfjs-dist
6.3.289**. The version is exact-pinned in both the browser coordinator and the
dedicated Worker.

- Package: pdfjs-dist
- Version: 6.3.289
- Upstream: mozilla/pdf.js
- License: Apache-2.0
- Runtime source bytes: user-provided/Drive-mediated ArrayBuffer only
- Runtime URL fetch by parser: disabled
- useWorkerFetch: false
- useWasm: false
- Raw PDF browser persistence: none

The repository does not commit the third-party distribution bundle in this
review slice. Local/CI verification installs the exact package version and
copies only build/pdf.mjs and build/pdf.worker.mjs into pdf/vendor/ before the
static server starts. The Worker imports those same-origin local assets before
the PDF bytes are sent.

This POC is not Production deployment authority and does not change Drive,
OAuth, Core, Engine, Control Plane, model/provider, or schema state.
