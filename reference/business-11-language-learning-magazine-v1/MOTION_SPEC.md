# Margin Echo Motion Specification

## Purpose

`Margin Echo / 여백 메아리` visualizes close reading. Selecting one underlined phrase reveals meaning, usage, a translation fragment, and one related expression in the margin while the article line and reading position remain stable.

This is a Phase 1 visual review motion, not an accepted vocabulary workflow.

## Trigger

- Activate the underlined phrase `linger after closing` or the `여백 메아리 재생` button.
- Keyboard activation uses the native button contract.
- The phrase remains in its original line throughout the sequence.

## Sequence

Target total duration: **680ms**.

1. **0–220ms — underline extension**
   - the accent underline expands from left to right;
   - implemented with `transform: scaleX()` and a fixed transform origin.
2. **100–460ms — margin rail opens**
   - the annotation layer reveals horizontally using `clip-path: inset()` and slight `translateX()`;
   - opacity rises without changing the article column width.
3. **260–620ms — meaning and usage appear**
   - meaning, Korean translation fragment, and usage line enter with a restrained stagger;
   - each item uses `opacity` and `translateY(6px)`.
4. **420–680ms — related expression aligns**
   - `stay a little longer` locks onto the baseline below the usage note;
   - no bounce, rotation, scaling spectacle, or article reflow.

## Stable elements

- article text and scroll position;
- image, caption, page number, and source line;
- annotation rail width;
- review navigation.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- underline, rail, and annotation items switch immediately;
- there is no translation, stagger, clip travel, or animated duration;
- the complete expanded state remains visible and semantically equivalent;
- the document root exposes `data-reduced-motion="true"` for evidence.

## Implementation constraints

- CSS `transform`, `opacity`, and `clip-path` only;
- minimal JavaScript toggles `is-echoing` and `is-expanded` classes;
- no animation library, canvas, WebGL, particles, or layout-driven motion;
- no persistent storage or network request.
