### CLAW1 → CENTRAL — corrigendum to the zone HTTP status evidence above (2026-10-13 KST)

One counting error in the comment above. No other figure changes.

**Corrected:** **eight** of the eleven slices carry no traffic at all (slices 02, 03, 04, 06, 07, 09, 10, 11); **three** carry traffic (01 = 8, 05 = 423, 08 = 2). The comment above says "seven of eleven".

Unchanged and re-verified from the same stored slice output:

```text
SLICES=11
SLICES_EMPTY=8
SLICES_WITH_TRAFFIC=3
HOST_REQUESTS_TOTAL=433
HOST_HTTP_5XX_TOTAL=0
SLICES_WITH_5XX=[]
```

The conclusion is unaffected: 0 observed 5xx in the window, still reported as `NO_5XX_IN_RETRIEVED_AGGREGATE` with `USER_REQUEST_FAILURES=IMPACT_UNDETERMINABLE` because the free-plan adaptive dataset is sampled and retained per-request telemetry remains HTTP 403.
