# Neighbor Market Phase 0 Demo QA

## Required screens

| Mode | Screen | Route/state |
|---|---|---|
| Resident | Home | `home` |
| Resident | Discovery | `explore` |
| Resident | Listing detail | `detail` |
| Resident | Benefits | `benefits` |
| Resident | Saved and requests | `saved` |
| Resident | Unavailable/suspended listing | `detail` (단비 세탁소, id 10) |
| Owner | Registration | `owner-register` |
| Owner | Public preview | `owner-preview` |
| Owner | Dashboard/status | `owner-dashboard` |
| Operator | Review queue | `operator-queue` |
| Operator | Review detail | `operator-review` |

## Required interactions

- [ ] Role switch changes resident, owner, and operator screens.
- [ ] Search applies on Enter and search button click.
- [ ] Relationship filters preserve current → neighbor → local order.
- [ ] Empty search state is reachable.
- [ ] Unavailable/suspended listing shows a clear text state, a disabled primary action, and an explicit demo notice.
- [ ] Every listing card opens detail.
- [ ] Favorite toggles and appears in Saved.
- [ ] Request modal creates an in-memory request record.
- [ ] Registration progresses through three steps.
- [ ] Registration values update the owner preview.
- [ ] Review submission changes owner state to `under_review`.
- [ ] Operator approve, request changes, and reject update local state.
- [ ] Reset and refresh clear local demo state.
- [ ] No primary button silently does nothing.

## Truthfulness checks

- [ ] Header states that the demo does not send or store data.
- [ ] Request confirmation states that nothing was sent or saved.
- [ ] Owner submission states that no real review was created.
- [ ] Operator mode states that it is not authentication or authority.
- [ ] No claim of management-office endorsement or service-quality guarantee.
- [ ] No real resident identity, unit number, roster, phone number, evidence, or private management information.

## Responsive evidence

Capture at minimum:

### 390×844

- resident home;
- resident detail;
- suspended listing state;
- saved/request state;
- owner registration;
- owner dashboard;
- operator queue;
- operator review.

### 768×1024

- resident home;
- owner registration;
- operator review.

### 1440×1100

- resident home;
- resident discovery;
- listing detail;
- owner dashboard;
- operator queue.

For each viewport verify:

```javascript
({
  clientWidth: document.documentElement.clientWidth,
  scrollWidth: document.documentElement.scrollWidth,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth
})
```

Required:

- `overflowX === false`;
- console errors: 0;
- JavaScript exceptions: 0;
- broken visible images: 0;
- failed local asset requests: 0.

## Asset fallback

Remote reference images must have a visible neutral fallback when unavailable. Image failure must not collapse card geometry or present the demo as real business evidence.
