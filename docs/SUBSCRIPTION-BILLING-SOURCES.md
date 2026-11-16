# Domestic subscription credit and check-in sources

Implementation: `src/ios/Providers/Subscription/SubscriptionCredit.swift`.
These protocols are adapted to the App's own OAuth/Keychain, HTTPS transport,
account generation, and existing native detail page; no desktop credential
extraction, external plugin runtime, automatic reward claim, account switching,
or new provider policy is imported.

## Frozen references

- [dingminhua/dsh-connect-trae](https://github.com/dingminhua/dsh-connect-trae/tree/b04d865fa2da7f78f5a1d98d376306a65580fa11), commit `b04d865fa2da7f78f5a1d98d376306a65580fa11`.
  `src/usage.ts`: CN pay origin `https://api.trae.cn`, Cloud-IDE-JWT auth,
  POST `/trae/api/v2/pay/web_user_ent_usage` (`require_usage: true`),
  `/trae/api/v2/ug/checkin_credits/status`, and `/trae/api/v2/ug/checkin_credits/claim`.
  `tests/usage.spec.ts` and `src/web-status.ts`: total minus consumed, per-pack
  general/Work endpoint buckets, device id on claims, business failures under
  HTTP 200, and same-day idempotence. The App sends only the device id its own
  successful Trae login recorded. No random replacement id.
- [dingminhua/dsh-connect-workbuddy](https://github.com/dingminhua/dsh-connect-workbuddy/tree/531efd3578eca867acfe1bc0e882bbfedbcef175), commit `531efd3578eca867acfe1bc0e882bbfedbcef175`.
  `src/upstream.ts`: fixed CN billing origin `https://www.codebuddy.cn`,
  POST `/v2/billing/meter/checkin-activity-status` and `/v2/billing/meter/daily-checkin`;
  status `active` AND NOT `today_checked_in` controls claiming. Receipt `credit`
  is the granted amount, not the status's quoted daily reward.
- Existing KWWKAI dependency pinned at `a7fe8390d8ef82686c67dadd4f250c82a44a0ee9`:
  `Sources/KWWKAuth/Providers/WorkBuddyOAuth.swift`, WorkBuddyUsageReader's
  POST `https://copilot.tencent.com/billing/meter/get-user-resource-summary`.
  That existing route is preserved for WorkBuddy credit summaries.

## Adaptation and verification limits

Missing/malformed figures are reported as unknown, never manufactured zeroes.
A structurally valid empty WorkBuddy package list is a real zero. Duplicate
claim actions are serialized per instance, recheck status before sending, and
are never automatically replayed after an uncertain network failure. The UI
updates only for the same stored credential and account generation. Credit
and check-in reads fail independently. A claim without a numeric grant cannot
invent its reward; a fresh checked-in status may confirm completion.

Qualification is three-state: explicitly eligible, explicitly ineligible, or
unknown. Missing/malformed flags never default to eligible; optional malformed
reward metadata cannot erase an explicit denial. Qualification now precedes
`beginAttempt` and `clearClaimOutcome`. Attempts/dispatches themselves are
memory-only: durable journals contain confirmed completion/receipt dedup or a
specifically verified retryable failure, never mere qualification or exclusion.

Explicitly ineligible accounts make no claim, enter no success/failure/unsigned
report, save no check-in key, and show neither a check-in button nor check-in
note. Balances, login and account identity are unchanged. Unknown qualification
and transport/cancellation errors create no fresh journal or failure marker;
unknown buttons are disabled. An identity-scoped, 128-entry maximum memory map
expires at the Asia/Shanghai day boundary. Unknown reads retry after two hours;
explicit exclusion or an unclassified claim refusal stops automatic attempts
for that process/day. Restart may re-read qualification without recreating an
error journal. Explicit user refresh/claim can requalify, not bypass flags.

Only documented Trae 9095 establishes device participation today. The frozen
source documents 9004 as missing/invalid own-device or request/order parameters,
NOT proof that the account is ineligible. Generic nonzero claim refusals remain
unknown, quiet, and memory-throttled; they are not labelled permanently
unsupported. Manual explicit claims may still surface the actual error. No
parser guesses a retryable-code mapping. The separate
`verifiedRetryableFailure` opt-in flag defaults to false for older JSON; only
that evidence plus today's qualification and dispatched claim may remind.

Legacy blocked/unclassified failed/provisional journals are retired on read for
only the affected identity. An old unverified refusal is not automatically
replayed today. Cleanup never deletes confirmed completion/receipt/dedup; a
late refusal, failed read or cancelled waiter cannot downgrade real success.
Confirmed history remains even if today's account cannot participate.

Installed build 297 logged status and claim HTTP 200 at 08:58:49, but did not
capture the fourth account's business code. Its exact denial is still unknown;
this change does not invent a code or classify that specific account.

Local regression commands:

```sh
python3 scripts/test_subscription_checkin_20261113.py
python3 scripts/test_subscription_checkin_no_participation_20261116.py
python3 scripts/test_subscription_billing_20261113.py
```

The runtime fixture extracts the actual production Swift ledger/API/automatic
loop, mocking only transport and app dependencies, not a Python policy clone.
It checks three saved/deduplicated successes, absent fourth UserDefaults key,
false/unknown/9095/generic/9004/old-failure variants, zero unqualified claims,
no repeated same-day refused claim, verified failure opt-in, cancellation,
late/concurrent success protection, bounded memory and next-day expiry.
iSH has no Swift compiler: native compilation/execution is explicitly SKIPPED,
not passed. Future macOS CI must run both check-in scripts above with
`V64R_REQUIRE_SWIFT=1`; missing Swift then fails rather than skips. This local
change does not alter CI, project/version files or install/run a device build.

These are upstream source/test contracts, not proof that the user's current
account/phone accepts the adapted requests. The GitHub Swift tests compile and
execute the production parser region; device acceptance and actual credited
rewards require separate verification. No account request or reward claim is
performed by the assistant while developing or building.

## License for adapted dsh-connect code

MIT License

Copyright (c) 2026 LaoDing

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
