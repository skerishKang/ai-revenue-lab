# #3936 Hark 8-scene UX / real-document E2E acceptance

**Status: BLOCKED_REAL_E2E.** This report documents testable evidence and remaining
real-world acceptance gates, not a Hark pixel-by-pixel copy nor a Production release
certificate. #3928 stays OPEN while #3523, #3580, #3929, #3932, #3933, #3934,
#3935 and the real Production model/Office/Drive path remain separately gated.

## Eight benchmark scenes and Claw behavioral assertions

| Scene | Benchmark observation | Exact Claw product behavior to prove |
|---|---|---|
| 01 | Empty conversation | Authenticated Owner/anonymous context, one composer, consistent state |
| 02 | Natural-language request | User-selected exact model; entered XLSX source and explicit edit terms |
| 03 | Task acknowledgement | Real accepted P01 run ID with authority, not a pretend progress step |
| 04 | Phase transition | Canonical server/Engine event IDs, monotonic sequence, no generated labels |
| 05 | Intermediate progress | Partial/no response, 429/502/timeout, approval pause and safe no-replay |
| 06 | PDF result card | Real owner-authorized output.pdf receipt and verified content SHA/MIME |
| 07 | PDF preview | Canonical tenant GET of exact PDF bytes; denied for foreign/deleted/unsupported |
| 08 | Download and follow-up | Correct XLSX/PDF files, owner authorization, durable source ref in next turn |

The private benchmark on the authorized Windows machine is
`E:\PADIEM_CLAW_HARK_UX_DEMO_20261009\`: 8 screenshots, a private HTML narrative,
and a **40.79-second time-sampled reference**. The MP4 is **not** a continuous 24/30fps
capture. None of those private visuals or Hark branding should be committed.

## Repeatable source evidence (real code under test, but NOT Production)

Existing B62 CI includes:
- #3930 server event projection/real run identity tests;
- #3932 actual owner-scoped Starlette PDF preview endpoint tests;
- #3933 selected-model/source-hash/copy-on-write *proposal* tests;
- #3934 canonical source/working/output read-only version projection;
- #3935 actual Node VM SSE terminal/paused/error/recovery functions;
- #3580 KAgent simulated Office/Drive artifact chain, **mock provider/renderer**.

New `test_3936_hark_acceptance.py` verifies exactly eight benchmark slots,
prevents false E2E PASS, and checks the non-mutating synthetic XLSX fidelity gate.
The source-only gate deliberately **always reports BLOCKED_REAL_E2E** when given
offline/CI/mocked observations, including self-asserted "production observed".
This is intentional; no offline model can certify real authenticated execution.

## Synthetic (no PII) financial fixture

One workbook source should have supply amount 88,000,000, 10% VAT, merged title,
formatting and formulas. After **copy-on-write editing only B4**, the resulting
workbook must show B4 = **99,200,000**, B6 = **9,920,000**, and B7 =
**109,120,000**, with formulas `=B4*B5` and `=SUM(B4,B6)`, same cell formats,
same original merged range A1:D1, no unexpected cell changes, and unchanged
original SHA256. This is inspected using read-only XLSX OOXML; no local Office,
provider, secrets, KAgent dispatcher or workbook mutation is implied.

To evaluate a private synthetic workbook pair (using existing approved
owner-authorized test material), from repo root:

```powershell
$sha = (Get-FileHash 'E:\private\quote-source.xlsx' -Algorithm SHA256).Hash.ToLowerInvariant()
python apps/padiem-chat/scripts/hark_3936_acceptance.py `
  --reference-dir 'E:\PADIEM_CLAW_HARK_UX_DEMO_20261009\01_스크린샷_모음' `
  --original-xlsx 'E:\private\quote-source.xlsx' `
  --updated-xlsx 'E:\private\quote-updated.xlsx' `
  --original-sha256 $sha `
  --output 'E:\private\hark-3936-local-evidence.json'
```

The verifier never prints private paths or copies screenshots. The output
contains only status, scene identifiers, expected dummy financial figures and
SHA hashes. Do not put evidence reports, screenshots, secrets, user names,
authorization headers or customer workbooks in GitHub.

## Real E2E acceptance still required

Run 2 browser widths (desktop 1600x900 and mobile 390x844) on the **actual**
authenticated Owner against the deployed exact-main version after the
independent Production 503 / Secrets Store owner approves activation.
Collect an independent timestamped eight-scene private screenshot sequence,
correlating the same actual P01 run ID, selected provider/model, authorized
Office output XLSX/PDF receipt, browser preview bytes, download and next turn.
Separate exact values and XLSX/PDF hash/geometry/print area/image positions,
as well as auth denial (other account), approval pause, cancelled run, and
429/502/timeout fail-closed behavior. Capture before/after local Claw
visual snapshots for non-Hark-own-identity regression thresholds; don't
measure pixel similarity against another product's branding.

**Close #3936 only when:** authenticated live text-first Golden Path #3523,
actual Office editable XLSX/PDF output #3580/#3933, #3929 next-turn reference,
#3932 file cards/preview/download, source fidelity #3934, failures #3935,
and desktop/mobile screenshot behavioral evidence are independently verified.
A source PASS, synthetic dummy amounts, existing 4/4 CI, or 8 Hark baseline
screenshots alone are not completion proof.
