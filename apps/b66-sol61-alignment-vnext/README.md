# Same-Sol CGI geometry v2 candidate - #3839

The existing Sol CGI form's upper black frame has a different left edge and
thickness from the lower table. This review-only tool derives an explicitly
versioned correction from that SAME source vector program. It does not install
or activate a template. The issued release, original certificate, public manifest,
QuoteCore and LOCAL1 #4001 files are not changed.

## Measured cause and correction

| Geometry (points) | Issued source | Candidate |
| --- | --- | --- |
| Title/footer white background left | 25.306 | 24.587 |
| Information black frame left | outer 25.786, inner 26.506 | 24.587 |
| Information extra vertical | 26.506, width 0.836 | removed |
| Information outline | nested black fill + stroke, width 0.75 | single stroke, width 0.72 |
| Yellow / item / lower frame left | 24.587, width 0.72 | unchanged |
| Information top / right / bottom | double contours | original contour centre lines |

The reported 0.719pt difference (25.306 minus 24.587) is real for white
backgrounds. The actual upper black ring's theoretical outside ink begins at
25.411pt, versus 24.227pt for the lower table: about 1.184pt apart. Individual
vertical lines already had zero slope. The correction handles both anchors and
the overlapping filled/stroked ring.

Chosen information-frame centre lines in page coordinates are left 24.587,
top 134.1335, right 572.587, bottom 260.7295. The old nested clips started at the
new left stroke centre and therefore cut half its width. Both frame clips now
include the complete stroke, from x=24.227 through 572.947. A strict 200% raster
test caught this additional defect; it passes after the clip correction.

Only exact, classified source anchors are changed. Nearby short dotted rules,
text operators, glyph positions, underline bytes, embedded resources, logo,
stamp and QuoteCore are preserved. Binding byte offsets and the drawing-program
hash are rebuilt in the NEW manifest. Old certification metadata is cleared.
No original certificate is copied into the candidate.

## Reproduce

Use the pinned Python dependencies and the same source fonts required by the
existing Sol engine. Node must be on PATH. No model, browser or network is used
during generation.

```powershell
python -m venv .venv-sol-alignment
.\.venv-sol-alignment\Scripts\python.exe -m pip install -r apps/b66-sol61-alignment-vnext/requirements.txt
```

Obtain the read-only LOCAL1 engine from Draft #4001 at exact commit
`f25b02541726e06bef8685d366e71815394b7614`. `verify_visuals.py` rejects a different
Python renderer or QuoteCore adapter hash. Supply that engine directory;
do not copy its files into this app or edit its branch.

```powershell
.\.venv-sol-alignment\Scripts\python.exe -B apps/b66-sol61-alignment-vnext/verify_visuals.py --source-bundle reference/b66-public-standard-templates/cgi/v1/sol61 --upstream-engine <read-only-4001-engine-directory> --out <new-empty-evidence-directory>
```

Outputs: candidate-sol/ (uncertified bundle), before/after PDFs, 72/144dpi
first/middle/last comparison PNGs, comparison.html, visual-audit.json and
completion.ini. The adapter uses the exact 24.587pt grid anchor instead of
LOCAL1's rounded 24.59pt. Candidate PDFs and instance metadata explicitly say
PENDING; use of the old single-page engine is not a certification claim.

```powershell
python -B -m pytest -q -p no:cacheprovider apps/b66-sol61-alignment-vnext/tests/test_alignment.py reference/b66-public-standard-templates/cgi/v1/tests/test_public_bundle_contract.py
```

To include the two raster mutation tests, set `B66_ALIGNMENT_RASTER_PAIRS` to a
JSON list of `{"original":"before.pdf","candidate":"after.pdf"}` for all seven
sizes. Tests require the original to FAIL collinearity and the candidate to PASS
at both DPIs with the same gray threshold (160). Without pre-rendered PDFs these
two tests explicitly skip; a source-only run is not visual acceptance.

## Verified Candidate

Windows / PyMuPDF 1.26.3 / pinned requirements; synthetic recipient and items.

| Items | Pages | All-page vector and 72/144dpi checks |
| --- | --- | --- |
| 1 / 2 / 3 | 1 each | PASS |
| 4 / 8 | 2 each | PASS |
| 25 | 4 | PASS |
| 100 | 11 | PASS |

All 22 pages have zero left-border coordinate difference and a 0.72pt left
stroke. Every page is checked at both scales; first/middle/last are also saved
as images. Text is exactly preserved, each item occurs once, QuoteCore totals
are unchanged, and repeated candidate renders are byte-identical. Instance
records are freshly written for both routes and checked against the PDF, item
count, pages, input and totals, including reused single/multipage output paths. There are
zero black diagonal segments or dark pixels in the inspected outer margins.
Pixel changes are restricted to the declared left/right outline strips and
information-frame top/bottom bands. All 18 issued hashes plus manifest match.
LOCAL1 renderer/adapter hashes match before and after generation.

Source dotted rules retain their 0.836pt style, and lower row hairlines retain
0.12pt. Source duplicate black segments (154 in the examined 8-item page) are
preserved rather than silently changing interior aesthetics. Existing LOCAL1
pagination/layout deviations, including the open right-side area below item
rows on multipage output, remain visible in the before/after report and require
LOCAL1/CENTRAL disposition. This candidate's pass is the bounded alignment
check, not full multipage certification or product acceptance.

```ini
ORIGINAL_TEMPLATE_GEOMETRY=info outer25.786 inner26.506; lower24.587
LEFT_BORDER_MISALIGNMENT_CAUSE=section offsets; double frame; overlapping rule
CORRECTED_GEOMETRY=left24.587pt width0.72pt; full-stroke clip
BEFORE_AFTER_IMAGES=comparison.html and images/*.png
ONE_PAGE_VISUAL_RESULT=IMPLEMENTATION_CHECK_PASS_1_2_3
MULTIPAGE_VISUAL_RESULT=ALIGNMENT_CHECK_PASS_4_8_25_100_ALL_PAGES
CERTIFIED_ORIGINAL_UNCHANGED=YES
NEW_TEMPLATE_VERSION_REQUIRED=YES_V2_CANDIDATE_REQUIRES_NEW_CERTIFICATE
OWNER_VISUAL_APPROVAL=PENDING
PRODUCTION_MUTATION=0
```

Handoff: Sol geometry proposal -> LOCAL1 integration into its own bounded
revision -> CENTRAL comparison/re-certification -> Owner visual approval.
No merge, deployment, issue closure or release certification is performed here.
