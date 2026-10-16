# B68 — AI Color Lens Discovery + Virtual Try-On

Status: **DISCOVERY / VALIDATION**  
Business ID: **B68**  
Master issue: **#3342**  
Primary market: **Saudi Arabia**  
Secondary market / partner hub: **UAE, then GCC**  
Working product name: **Padiem Lens** (working name only)

---

## 1. Executive thesis

B68 is not a generic eye-color filter.

The product hypothesis is:

> A Saudi-first mobile experience that lets consumers discover, compare and virtually try **real colored-contact-lens SKUs on their own eyes**, with special emphasis on realistic results for naturally dark-brown irises, then continue to an authorized retailer.

The core purchase problem is not "can software make my iris blue?" That is already commodity functionality.

The harder and more valuable question is:

> "What will this exact lens product look like on my actual eye, and which real product best matches the look I want?"

The long-term opportunity is a two-sided platform:

1. **B2C discovery and comparison**
   - virtual try-on;
   - real-SKU search;
   - visual comparison;
   - save/share;
   - retailer routing.

2. **B2B commerce infrastructure**
   - hosted VTO;
   - retailer/brand SDK or API;
   - product digitization;
   - privacy-safe aggregate preference/conversion analytics.

B68 should validate demand before committing to a proprietary AR stack.

---

## 2. Why revisit this idea now?

Several years ago, accurate eye-only color replacement and stable iris tracking were meaningful implementation problems.

In 2026, the technical landscape is different:

- commercial vendors already sell contact-lens virtual try-on;
- browser/mobile face and eye landmark tracking is mature;
- reference images and product assets can be processed by existing VTO systems;
- a small team can test real consumer behavior without first building a research-grade computer-vision stack.

This changes the core risk.

### Old primary risk

```text
Can the technology be built?
```

### Current primary risks

```text
Can real-SKU appearance be reproduced credibly?
Can official/permissioned product assets be obtained?
Will users repeatedly compare products rather than use it once as a novelty?
Will try-on materially increase merchant clicks or purchases?
Can B2B customers pay enough to support the economics?
```

---

## 3. Why Saudi Arabia first?

Saudi Arabia is the strongest first validation market currently identified.

The Saudi Communications, Space & Technology Commission (CST) 2025 Internet Report reports:

- mobile phone internet usage: 99.6%;
- female online shoppers: 85.6%;
- cosmetics purchased by female online shoppers: 79.1%;
- female Snapchat usage: 88.2%;
- female TikTok usage: 77.6%.

This does not by itself prove colored-contact-lens demand, but it strongly supports the distribution environment required by B68:

```text
mobile-first
+ beauty purchase behavior
+ social discovery
+ e-commerce familiarity
```

Saudi contact-lens studies provide additional evidence that cosmetic usage is meaningful. A 1,708-user Saudi study reported:

- 86.4% of participants were women;
- 36.1% used lenses for cosmetic purposes;
- 35.1% used them for both medical and cosmetic purposes.

The study population must not be treated as a perfect representation of every Saudi consumer, but it is strong evidence that cosmetic motivation is structurally important among lens users.

---

## 4. Market-size posture: directional, not authoritative

Third-party market-research estimates materially disagree.

Examples retrieved in 2026:

- Ken Research models the total Saudi contact-lens market at USD 132M in 2025 and estimates cosmetic/colored products at roughly 40% of value.
- IMARC estimates the total Saudi contact-lens market at USD 84.5M in 2025.
- Deep Market Insights estimates the Saudi colored-contact-lens market alone at USD 61.79M in 2025.

These figures are not sufficiently consistent to treat one as canonical.

Therefore B68 adopts the following rule:

> **Do not justify the business using one TAM number.**

Use market-size reports only as directional evidence. Product decisions should be driven by:

- active retailer assortments;
- observed prices;
- consumer behavior;
- try-on engagement;
- save/compare behavior;
- merchant click-through;
- attributed purchase evidence;
- B2B willingness to pay.

---

## 5. Existing market validation

### 5.1 Regional retailer scale

eyewa announced a USD 100M Series C round led by General Atlantic in November 2024. At the time, it reported more than 150 GCC stores and plans for substantial expansion.

This is important not because B68 should copy eyewa, but because it proves the regional eyewear category has enough economic activity to attract major growth capital.

### 5.2 Virtual try-on is already commercially accepted

Commercial providers already support contact-lens try-on:

- **Banuba TINT** lists contact lenses among supported try-on categories and, as of 2026, publishes plans beginning at USD 49/month for 1,000 virtual try-ons.
- **Perfect Corp** offers an eye-color/contact-lens try-on API capable of processing customer photos and lens reference/style assets.

Therefore B68 does not need to prove that virtual try-on is technically possible.

The product must prove that a **better discovery and comparison layer around real SKUs** creates value.

---

## 6. Competitive framing

The market is not empty.

### Generic eye-color editors

Strength:
- easy;
- fun;
- cheap;
- visually impressive.

Weakness:
- not necessarily tied to a real lens product;
- poor purchase authority;
- may change appearance in ways that do not correspond to a physical SKU.

### Brand-native VTO

Strength:
- official product assets;
- direct conversion path.

Weakness:
- only the brand's own catalog;
- does not solve cross-brand discovery.

### Retailer VTO

Strength:
- real products;
- direct purchase path;
- existing traffic.

Weakness:
- optimized for that retailer's own assortment;
- often weak on product-neutral search and comparison.

### General-purpose VTO providers

Strength:
- mature tracking/rendering infrastructure;
- fast integration.

Weakness:
- they are infrastructure vendors, not the consumer discovery destination.

### B68 opening

B68 should occupy:

```text
brand-neutral discovery
+ real SKU comparison
+ dark-iris realism
+ product metadata
+ authorized retailer routing
```

---

## 7. Core user jobs

B68 should be designed around concrete user questions.

### Job A — "What will this actual product look like on me?"

Input:
- user's camera/selfie;
- selected SKU.

Output:
- bounded visual simulation;
- product identity preserved;
- no unrelated facial edits.

### Job B — "Which of these products looks better for the style I want?"

Input:
- 2–4 products.

Output:
- side-by-side or quick-toggle comparison;
- product facts;
- visual descriptors.

### Job C — "I want a natural gray lens, not a fake-looking gray."

Input:
- desired look.

Output:
- ranked/searchable candidates by product characteristics;
- not an opaque beauty judgment.

### Job D — "Find a real lens similar to this look."

Later phase:

```text
reference image
-> visual feature extraction
-> query real SKU catalog
-> try candidates on user
```

The system should search for **product characteristics**, not claim that it identified the exact lens worn in an unrelated photo unless evidence actually supports that claim.

---

## 8. Product scope

### First surface

**Mobile web / PWA**, not native app.

Reasons:

- social links can open directly;
- no install friction before first try-on;
- easier Saudi-market experiments;
- faster analytics iteration;
- native app can be justified later by repeat behavior.

### Languages

- Arabic;
- English.

Arabic is not an afterthought. Layout, right-to-left behavior and local copy quality are part of the Saudi product.

### Initial catalog

Target:

- 3–5 brands;
- approximately 30–50 SKUs/shades;
- official or permissioned assets where possible;
- traceable product facts.

Do not scrape thousands of assets first.

---

## 9. Candidate user flow

```text
social / search / direct link
-> landing
-> choose desired look OR browse real products
-> camera or selfie consent
-> first real-SKU try-on
-> swipe/toggle more products
-> compare 2–4
-> save
-> share
-> view verified product facts
-> authorized retailer
```

No account should be required before the first useful try-on unless a vendor constraint forces it.

---

## 10. Real-SKU data model

A future lens asset should be more than a color name.

Candidate structure:

```text
brand
product_family
sku
shade
replacement_cycle
prescription_availability
base_curve
diameter
graphic_diameter
material
water_content

visual:
  texture_asset
  pupil_aperture
  opacity_map
  limbal_ring_strength
  pattern_family
  dominant_color_family
  warm_cool_character
  natural_dramatic_position

calibration:
  dark_iris_response
  medium_iris_response
  light_iris_response
  indoor_response
  daylight_response

commerce:
  country
  authorized_retailer
  retailer_product_url
  price_observed
  price_observed_at

provenance:
  source_url
  source_type
  retrieved_at
  asset_rights_status
  last_verified_at
```

Unknown fields must remain unknown. AI-generated guesses must never silently become product facts.

---

## 11. The most important technical problem: appearance fidelity

Iris tracking is no longer the main differentiator.

The key technical problem is:

> **Does the simulated SKU resemble the real lens when worn?**

Important variables include:

- natural iris darkness;
- texture/pattern;
- transparency;
- limbal ring;
- pupil aperture;
- graphic diameter;
- lighting;
- corneal highlights;
- eyelid occlusion;
- camera white balance.

A beautiful but inaccurate preview harms the product.

### Dedicated quality metric

```text
VIRTUAL_VS_REAL_ACCURACY
```

This should become a formal evaluation program, especially for dark-brown irises.

---

## 12. Dark-iris strategy

B68 should intentionally optimize for dark irises rather than treat them as one test case among many.

Potential calibration buckets:

```text
very_dark_brown
dark_brown
medium_brown
light_brown
other
```

These labels are appearance/calibration categories only.

The system must not infer race or ethnicity from facial appearance.

Testing should use consented/synthetic/controlled image sets and real product wear comparisons where possible.

---

## 13. Build vs buy

### Phase 0: buy/integrate

Use an existing provider to answer:

- Do users start try-on?
- Do they try several SKUs?
- Do they compare?
- Do they save/share?
- Do they click to merchants?
- Is VTO accuracy acceptable enough for an initial pilot?

This reduces time spent rebuilding commodity tracking.

### Phase 1: evaluate proprietary core

Only after demand evidence:

- MediaPipe/other local landmark tracking;
- WebGL/WebGPU/canvas renderer;
- product-specific opacity/texture blending;
- local/on-device processing;
- calibration DB.

### Why proprietary rendering may later matter

Potential benefits:

- dark-iris specialization;
- lower marginal cost;
- lower latency;
- better privacy;
- vendor independence;
- deeper product calibration;
- B2B control.

But proprietary rendering is **not** the first proof required.

---

## 14. Generative-AI boundary

Generative image editing can make visually impressive eyes, but should not be the canonical product renderer.

Risks:

- eye shape changes;
- iris geometry changes;
- makeup changes;
- skin/lighting changes;
- product texture hallucination;
- mismatch with physical lens.

Preferred role of AI:

- desired-look interpretation;
- catalog search;
- product attribute extraction with provenance/review;
- recommendation candidate generation;
- reference-look feature extraction;
- copy/localization assistance.

Preferred source of truth for product appearance:

```text
real SKU asset
+ deterministic geometry
+ controlled blending
+ calibration evidence
```

---

## 15. Regulatory boundary

Saudi FDA classification guidance explicitly states that non-corrective lenses, colored or not, are medical devices, and that cosmetic contact lenses without medical claims must comply with Medical Device Law.

Therefore B68 V1 must remain an appearance/discovery product.

### B68 must not claim

- diagnosis;
- prescription;
- fit;
- safe-for-you determination;
- base-curve compatibility;
- medical suitability;
- treatment.

### B68 may provide

- virtual appearance simulation;
- traceable factual product specifications;
- safety education sourced from authoritative material;
- routing to an authorized retailer.

Direct inventory ownership and cross-border lens sales should not be the initial model.

---

## 16. Privacy posture

Selfies and live camera frames are personal data and require a strict privacy model.

Preferred V1 posture:

```text
IDENTITY_RECOGNITION=NO
FACE_TEMPLATE_FOR_IDENTITY=NO
RACE_ETHNICITY_INFERENCE=NO
RAW_SELFIE_RETENTION_DEFAULT=NO
CAMERA_CONSENT=YES
PURPOSE_LIMITATION=YES
VENDOR_DATA_FLOW_DOCUMENTED=YES
```

Technical preference:

1. process locally/on-device where feasible;
2. if third-party/cloud VTO is used, explicitly document:
   - transmitted data;
   - region;
   - retention;
   - subprocessors;
   - deletion;
   - training use;
   - contractual controls.

No Production launch before these facts are reviewed.

---

## 17. Business model ladder

### Consumer subscription

Not the primary assumption.

A generic paid beauty-filter subscription is crowded and weakly differentiated.

### Affiliate / referral

Useful as an early monetization and attribution channel.

Weakness:
- lens basket sizes are not high enough to assume affiliate alone supports the business.

### B2B hosted VTO / SDK

More credible recurring-revenue lane.

Target customers:
- independent lens retailers;
- optical chains;
- lens brands;
- regional e-commerce sellers.

Possible pricing:
- monthly base;
- try-on volume;
- catalog digitization;
- enterprise integration.

### Aggregate analytics

Later only, with privacy-safe aggregation.

Examples:
- which product characteristics receive higher save rates;
- which styles convert after try-on;
- dark-iris versus medium-iris visual preferences.

Never sell raw face/selfie data.

---

## 18. Initial KPI framework

### Acquisition

- landing sessions;
- source channel;
- Arabic/English split.

### Activation

- camera/selfie start rate;
- first successful try-on rate;
- time to first try-on.

### Engagement

- SKUs tried per activated user;
- TRY_3_PLUS rate;
- compare rate;
- save rate;
- share rate.

### Commerce

- merchant-click rate;
- product-detail open rate;
- attributed purchase rate where available;
- VTO vs non-VTO conversion comparison when a partner can support an experiment.

### Quality

- virtual-vs-real user rating;
- product identity correctness;
- dark-iris fidelity;
- rendering failure rate;
- latency.

### B2B

- retailer demo-to-pilot conversion;
- willingness-to-pay;
- pilot retention;
- try-on volume;
- conversion lift.

---

## 19. Pre-registered pilot thinking

Before purchasing meaningful traffic, set thresholds.

Example structure only — exact thresholds require a dedicated issue:

```text
H1: users will try multiple real SKUs after first try-on
H2: comparison/save behavior persists beyond novelty
H3: users will click a merchant after VTO at a meaningful rate
H4: dark-iris users rate the simulation as sufficiently faithful
H5: at least one retailer/brand sees enough value to discuss a paid pilot
```

Thresholds must be defined **before** reading the pilot outcome to avoid moving the goalposts.

---

## 20. Kill / pivot criteria

Do not scale because the demo looks impressive.

B68 should stop, narrow or pivot if:

- try-on is mostly one-time novelty;
- multi-SKU comparison is weak;
- merchant intent is weak;
- dark-iris fidelity remains poor;
- product assets cannot be obtained legally/economically;
- retailer relationships cannot be established;
- privacy/data-processing terms are unacceptable;
- B2B willingness-to-pay is insufficient;
- customer acquisition economics are clearly unsustainable.

---

## 21. Proposed phase map

### G0 — research authority

Deliverables:

- master issue;
- research dossier;
- source register;
- competitor baseline;
- regulatory boundary;
- product thesis.

### G1 — feasibility prototype

Deliverables:

- 30+ real SKUs;
- working photo/camera VTO;
- comparison;
- dark-iris test protocol;
- privacy architecture;
- Saudi Arabic/English surface.

### G2 — consumer pilot

Deliverables:

- pre-registered KPI thresholds;
- small controlled traffic experiment;
- measured funnel;
- accuracy feedback.

### G3 — commercial proof

Deliverables:

- retailer/brand partner;
- referral attribution and/or paid B2B pilot;
- economics evidence.

### G4 — proprietary core decision

Only then decide whether to build:

- custom renderer;
- calibration lab/data workflow;
- Lens Asset Database at scale;
- B2B SDK/API.

---

## 22. Current decisions

```text
BUSINESS_ID=B68
PRIMARY_MARKET=SAUDI_ARABIA
SECONDARY_MARKET=UAE_GCC
POSITIONING=REAL_SKU_LENS_DISCOVERY
GENERIC_EYE_COLOR_FILTER=NO
NATIVE_APP_FIRST=NO
MOBILE_WEB_FIRST=YES
FULL_CUSTOM_AR_FIRST=NO
BUY_TO_VALIDATE_FIRST=YES
DIRECT_INVENTORY_FIRST=NO
AUTHORIZED_RETAILER_ROUTING=YES
DARK_IRIS_ACCURACY=CORE
REAL_SKU_ACCURACY=CORE
GENERATIVE_RENDERER_AS_PRODUCT_TRUTH=NO
B2B_OPTION=PRESERVED
```

---

## 23. Next issues after G0

Recommended child issue sequence:

1. competitor teardown;
2. Saudi/UAE brand and authorized-retailer map;
3. candidate 30–50 SKU dataset;
4. VTO provider technical trial;
5. dark-iris accuracy protocol;
6. privacy/data-flow review;
7. Arabic/English mobile UX prototype;
8. pilot analytics and threshold preregistration.

No Production launch, medical claim or direct lens retail is authorized by this document.
