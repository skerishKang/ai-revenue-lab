# Verified-Package-to-Marketplace-Listing

## Meaning

The signature motion shows a synthetic package becoming a human-reviewed marketplace listing without implying installation, execution, permission grant, payment, account connection or production approval.

## Sequence

1. publisher and package
2. objective and prerequisites
3. authorized inputs and ordered steps
4. compatibility and permission requirements
5. publisher claims and independent evidence
6. version, licence and limitations
7. listing review
8. `HUMAN-APPROVED WORKFLOW MARKETPLACE LISTING`

## Timing contract

- steps 1–7: 90ms each, staggered at 0/90/180/270/360/450/540ms;
- last preceding nominal end: 630ms;
- final element delay: 650ms;
- final element duration: 90ms;
- nominal completion: 740ms;
- normal completion authority: actual `animationend` from `#motion-final` with animation name `final-listing`;
- fixed completion timeout: absent;
- final element is the actual last animation.

## Replay contract

Replay removes the running class, resets completion state, performs one layout flush and restarts the same class-driven sequence. It does not move focus, scroll the document or alter geometry. Replay 1 and Replay 2 must have equal final computed styles, element geometry and screenshots.

## Completion boundaries

The following elements remain outside the moving sequence and visible after completion:

- `DEPRECATED VERSION — DO NOT INSTALL`
- `PERMISSION REQUIRED — NOT GRANTED`
- `SAFE TRIAL ONLY`
- `UNRESOLVED CONDITION`
- `NO TRANSACTION PERFORMED`
- `NOT INSTALLED`

## Reduced motion

With `prefers-reduced-motion: reduce`, all steps and the final listing are immediately information-complete. JavaScript marks the motion complete synchronously and does not wait for a timeout.
