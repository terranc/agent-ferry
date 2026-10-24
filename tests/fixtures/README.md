The notification integration test uses the unmodified upstream script at
`skills/wake-on-done/scripts/notify-run`. Its revision and license status are
recorded in `skills/UPSTREAM.md`; there is no duplicate test copy.

The integration test runs it against a local HTTP server and an isolated HOME.
No production webhook configuration or credentials are used.

Claude JSON is currently simulated by `fake_claude.py`. Replace/add a captured
real result fixture when validating external assumptions S1-S10.
