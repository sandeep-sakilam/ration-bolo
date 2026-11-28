# Accessibility and low-bandwidth audit

Scope: the three web pages (call simulator, dealer dashboard, impact metrics).
The phone line and WhatsApp are voice-first by design and need no screen at all,
which is the main accessibility feature of Ration Bolo: callers who cannot read, type
or see a screen use speech, with keypad and numbered menus as fallbacks.

## Automated checks (in CI, `tests/e2e/test_accessibility.py`)

- **axe-core**, WCAG 2.0/2.1/2.2 A and AA rules, on every page, including the
  simulator during a call with the keypad open and the dealer dashboard after login:
  **0 violations**.
- **Keyboard only**: start a call and talk to the app with Tab, Enter and typing.
- **Low bandwidth**: each page loads under 80 KB of HTML/CSS/JS before compression
  (no fonts, images, frameworks or third-party requests); responses are gzip-compressed
  and static files are cached for an hour.

## Fixes made in this audit

| WCAG 2.2 criterion | Problem | Fix |
| --- | --- | --- |
| 1.4.3 Contrast (minimum) | "Demo data" badge, white on orange, 3.0:1 | Darker orange, now above 4.5:1 |
| 4.1.2 Name, role, value | Example-phrase container had a label but no role | `role="group"` |
| 2.1.1 Keyboard | Scrollable queue, bookings and outbox tables could not be reached by keyboard | Scroll regions are focusable, labelled regions |
| 3.1.2 Language of parts | Telugu/Hindi replies were marked as English | Each reply bubble carries its language (`te-IN`, `hi-IN`); the English gloss is marked `en` |

## Manual review (WCAG 2.2 AA)

- **Perceivable**: every reply is shown as text and spoken; an English gloss sits under
  each Telugu/Hindi reply; status (stock, machine, paused) is written in words, not only colour.
  A dark theme follows the device setting; both themes use the same colour tokens and keep
  AA contrast (axe checks the light theme in CI).
- **Operable**: all controls are native buttons, inputs and selects; visible focus ring
  (3 px); buttons and keypad keys are at least 24×24 px (2.5.8 Target size); nothing is
  time-limited (silence is an explicit "Stay silent" button, not a timer); the pulsing mic
  animation and the reply fade-in stop with `prefers-reduced-motion`.
- **Understandable**: one language per page (`lang="en"`) with per-reply language marks;
  errors are announced (`role="alert"` on login, `role="status"` on dashboard messages);
  the dealer PIN field says what to enter.
- **Robust**: plain HTML, no custom widgets; the transcript is an `aria-live="polite"` log.

## Known gaps

- The dealer's "Resolve complaint" uses the browser's `prompt()` dialog: accessible but plain.
- Browser speech recognition for Telugu depends on the browser (best in Chrome/Edge);
  the text box and example phrases are the fallback.
- No screen-reader testing with real users yet (NVDA/TalkBack) — planned for the pilot.
