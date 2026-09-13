# agent-web-tester#20 — first browser_navigate call fails with no cached Playwright browser

**Type:** Bug
**Reported by:** a user running the tool on a fresh machine / a fresh CI runner

## Description

On a machine with no Playwright browser binaries cached yet, the very first
call to `browser_navigate` in a new session fails outright instead of
bootstrapping itself.

The first browser_navigate call in a session with no cached Playwright browser fails with a browser-not-found error instead of installing the browser and completing the navigation.

Today the user has to notice the failure, go read the README, and manually
run `npx playwright install` before the tool works at all — which defeats
the entire point of a tool that is supposed to work out of the box on a
fresh checkout.

## Steps to reproduce

1. Delete the local Playwright browser cache (`~/.cache/ms-playwright` on
   Linux, the platform equivalent elsewhere), or use a fresh CI runner that
   has never run this tool before.
2. Start a new session and call `browser_navigate("https://example.com")` as
   the very first tool call of the session.
3. Observe: the call raises a browser-not-found error immediately. It should
   instead detect that no browser is cached, install one, and then complete
   the navigation to `https://example.com`.

## Acceptance criteria

- AC1: the first `browser_navigate` call in a session with no cached
  Playwright browser completes successfully — it navigates to the requested
  page — after transparently installing the browser first.
- AC2: a second `browser_navigate` call in the same session does not repeat
  the install step (it uses the browser installed for AC1).

## Comments

(none — this is the ticket's only content, verbatim as filed)
