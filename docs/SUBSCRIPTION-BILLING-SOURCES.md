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
