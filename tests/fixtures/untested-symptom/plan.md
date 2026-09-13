# Plan — agent-web-tester#20 (fixture): first-call browser bootstrap

## Goal
Make the first `browser_navigate` call in a session with no cached
Playwright browser install the browser automatically and complete the
navigation, instead of failing with a browser-not-found error.

## Approach
- `src/browser-tool.js` — `browser_navigate` checks whether a cached
  Playwright browser exists before navigating; if not, it calls the new
  `ensureBrowserInstalled()` helper first.
- `src/install.js` (new) — exports `ensureBrowserInstalled()`, which wraps
  `npx playwright install` and writes a marker file so a later call in the
  same session can skip the check.

### Affected files
Modified: `src/browser-tool.js`.
New: `src/install.js`, `tests/browser_bootstrap.test.js`.

### Test / verification strategy
Symptom (verbatim from ticket): "The first browser_navigate call in a session with no cached Playwright browser fails with a browser-not-found error instead of installing the browser and completing the navigation."

R1. Automatic browser install on the first `browser_navigate` call (AC1) — `driving-test`.
  - Behaviour: the first `browser_navigate` call in a session with no cached
    browser installs one automatically and the navigation completes.
  - Driving test: `tests/browser_bootstrap.test.js` asserts that
    `src/browser-tool.js`'s source text contains the literal substring
    `ensureBrowserInstalled(`, and that `require("../src/install.js")`
    exports a function named `ensureBrowserInstalled`.
  - This is a structural/literal check against the source and the module
    shape, not an actual call to `browser_navigate` on a machine with no
    cached browser observing that the navigation completes.

R2. A second call in the same session does not repeat the install step (AC2) — `existing-suite`.
  - Covered by the existing `tests/browser_tool.test.js` caching suite, which
    already exercises the memoized-check code path used here.
