# Browser Validation Record

## Environment limitation

The available Chromium binary blocks navigation to both `http://127.0.0.1` and `file://` URLs with `ERR_BLOCKED_BY_ADMINISTRATOR`.

To avoid overstating validation, the browser check used an offline Playwright harness that:

1. read the authored `index.html`, CSS, JavaScript, and repository-local SVG bytes from the workspace;
2. inlined those exact bytes into `page.set_content` without changing the source files;
3. rendered and interacted with the result in Chromium at 1440px and 390×844;
4. separately verified that every source path exists and that the ordinary source contains no external runtime URL.

This proves the rendered DOM, responsive layout, state switching, keyboard controls, focus treatment, Margin Echo classes and timing, reduced-motion state, and source-path consistency. It does not prove navigation through an HTTP server in this restricted environment.

## Results

See `validation.json` for the machine-readable record.

- Seven required states: present and switchable
- Desktop horizontal overflow: 0
- Actual 390×844 horizontal overflow: 0
- Console errors: 0
- Page errors: 0
- Failed requests in offline harness: 0
- Runtime requests in offline harness: 0
- Missing local source references: 0
- External runtime URLs in source HTML: 0
- Keyboard arrow navigation: passed
- Visible focus: passed
- Margin Echo: passed; reading scroll position stable in the dedicated timing check
- Reduced motion: immediate expanded state, no transition duration
- Source files over 500 lines: 0
- Missing or stale CSS/JS version query: 0

## Binary evidence

The PNG and GIF evidence is not committed to GitHub. It is packaged separately because the implementation contract requires truthful handling of binary artifacts.
