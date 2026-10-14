# Cost Register — Project Sentinel

Last updated: 2026-10-15 (full cost audit as of 2026-10-14, end of day UTC, plus the owner's OpenAI changes of the 2026-10-14 evening: top-up, auto-reload, spend limit and data sharing)

This is the living list of what Sentinel pays for. It answers three questions: which services cost money, how each one bills, and which balance or deadline can silently stop alerts. The numbers come from the latest audit. Re-check them there before you act on them.

- Latest report (Polish, for the owner): [finance/reports/2026-10-14-full-audit/report.html](../../finance/reports/2026-10-14-full-audit/report.html)
- All totals as data: [finance/reports/2026-10-14-full-audit/summary.json](../../finance/reports/2026-10-14-full-audit/summary.json)
- Living records: [finance/ledger.csv](../../finance/ledger.csv), [finance/history-monthly.csv](../../finance/history-monthly.csv), [finance/current-monthly.csv](../../finance/current-monthly.csv)
- Build script: [finance/build_full_audit_20261014.py](../../finance/build_full_audit_20261014.py) (run it with `--check` to prove the files match the inputs)

Contents: [Totals](#totals) · [What Sentinel pays for](#what-sentinel-pays-for) · [Not a Sentinel cost](#not-a-sentinel-cost) · [Accounting conventions](#accounting-conventions) · [When a new cost appears](#when-a-new-cost-appears)

---

## Totals

All figures are as of 2026-10-14, end of day UTC. PLN uses NBP table A mid rates.

| Measure | Value | Native currencies |
|---|---|---|
| Economic cost since 2026-03-21 | PLN 2,199.43 | USD 442.58 + EUR 30.46 + PLN 429.00 |
| Cash paid, Sentinel's share | PLN 2,220.73 | USD 453.73 + EUR 28.04 + PLN 429.00 |
| Current monthly cost | PLN 147.87 (range 116.26–157.00) | USD 23.69 + EUR 4.49 + PLN 35.75 |

The economic cost and the cash differ for four reasons. Prepaid credit counts only when it is used. The Twilio account owes rental that is not paid yet. The October Hetzner invoice is not issued yet. Free credits are kept out of both totals.

## What Sentinel pays for

"Current monthly" uses the October 1–14 daily average × 30.44 for usage services, the monthly price for fixed fees and the annual fee / 12 for Apple.

| Service | Provider | What it does for Sentinel | Billing model | Current monthly (native) | Renewal / expiry | Status | Where invoices live | Balance or limit to watch |
|---|---|---|---|---|---|---|---|---|
| GPT-5.6 Luna API | OpenAI | Live classifier for every article, plus the enrichment quality check and the Polish summary translation. | Prepaid credit, usage-billed. Auto-reload is on again since the evening of 2026-10-14: when the balance falls to USD 5 it reloads to USD 20, with no monthly cap on reloads. The previous automatic charge failed on 2026-10-08, so the card is not yet proven on an automatic charge. Data sharing with OpenAI is on for all projects since the same evening, in exchange for complimentary daily tokens. | USD 18.54 (range 15.59–20.88). If the complimentary tokens cover gpt-5.6-luna, about USD 1.81 (scenario outside the total, range 0–18.54); check the usage dashboard by service tier after 2026-10-15 00:00 UTC. | Current credit grant expires 2027-10-01. | Active | OpenAI platform billing portal (invoices, cost exports) | Prepaid balance: USD 20.70 at about 21:00 UTC on 2026-10-14, after the owner's USD 20.00 top-up (USD 0.77 at 18:03 UTC before it). If an automatic reload fails, OpenAI turns auto-reload off and the remaining USD 5 lasts only about 6–8 days. Project Sentinel hard spend limit: USD 30 a month since 2026-10-14 (raised from USD 10; USD 8.48 used at about 22:00 UTC), above the run-rate. A USD 10 spend alert stays as an early warning. The limit equals the app's own USD 30 budget, so a heavy incident month can still reach it. |
| Polish phone number | Twilio | Sender number for alert calls and confirmation-code SMS. | Prepaid balance; rental charged monthly. | USD 4.00 | Renews on the 28th of each month. | Account suspended since 2026-08-23 (balance ran out) and left unfunded on purpose; rental accrues as debt. | Twilio console (Billing: statements and receipts) | Balance: USD −9.49 on 2026-10-14. A recharge first pays the debt. |
| US phone number | Twilio | Original trial number; recent traffic used only the Polish number. | Prepaid balance; rental charged monthly. | USD 1.15 | Renews on the 21st of each month. | Suspended with the account; rental accrues as debt. Releasing it saves USD 1.15 a month. | Twilio console | Same balance as above. |
| Calls, SMS and text-to-speech | Twilio | Urgency 9–10 phone calls and confirmation-code SMS. | Prepaid, usage-billed. | USD 0 while suspended. After a recharge, about USD 18.03 a month (range 16.83–32.27) under today's routing (scenario, priced per urgency 9–10 alert event, not per rejected attempt). | — | Suspended: every call and SMS is rejected (HTTP 401). | Twilio console | Auto-recharge is not configured; the account suspends whenever the balance reaches zero. |
| CX23 cloud server + IPv4 | Hetzner | The whole production system runs on this one server. | Postpaid monthly invoice, card auto-debit. Months under EUR 10 are batched. | EUR 4.49 (legacy CX23 price) | Monthly. The October invoice is expected around 2026-11-04. | Active | Hetzner billing portal | Card on file. A failed debit ends in a server lock, which stops every alert. |
| Developer Program (Individual) | Apple | Lets the iPhone companion app be built, signed and receive push. | Annual fee, PLN 429.00, paid 2026-05-27. | PLN 35.75 (annual fee / 12) | Membership ends 2027-06-01; auto-renew is off. A new licence agreement must be accepted by 2026-11-13. | Active | Apple developer account (Membership) and Apple Store order status | No balance. Watch the two dates. |
| Expo / EAS | Expo | Push delivery to the iPhone app and app builds. | Free plan. | USD 0 | — | Active | expo.dev Billing | Free-plan limits (far from reached). Push is currently the only working alert channel. |
| Claude Haiku 4.5 API (rollback only) | Anthropic | Former classifier, kept as the rollback path. | Prepaid credit on an organisation shared with other projects. | USD 0 (not used since 2026-09-20) | Remaining credit expires about 2027-09-20. | Standby; the Sentinel API key is still active. | Anthropic Console (Billing) | Shared balance USD 18.77 (not Sentinel's). Auto-reload tops up to USD 20 below USD 10. Org monthly spend limit USD 150. |
| Model-evaluation key | OpenRouter | Offline model comparisons (September 2026 only). | Prepaid credit on a shared account; 23% VAT and a purchase fee are paid. | USD 0 | The evaluation key has expired. | Inactive | OpenRouter billing (receipts and invoices) | Shared balance USD 60.78 (not Sentinel's). |
| Jev model (experiment) | TypeSafe | Jev+Luna hybrid classifier experiment (September 2026, eval branch only). | Prepaid credit on a shared account. | USD 0 | — | Inactive | TypeSafe console (not read in the audit) | Not Sentinel's. |
| Code hosting | GitHub | Public repository, no CI. | Free plan. | USD 0 | — | Active | GitHub billing settings | — |
| News sources | RSS, Google News, Telegram user API | Article collection. | Free. | USD 0 | — | Active | — | — |
| Database backups | Server disk | Daily SQLite copies on the server's own disk. | Included in the Hetzner server price. | EUR 0 | — | Active | — | Hetzner Backups and snapshots are off; backups share the server's disk. |

**OpenAI complimentary tokens (unverified).** OpenAI's help article "Sharing feedback, evaluation and fine-tuning data, and API inputs and outputs with OpenAI" (help.openai.com/en/articles/10306912) lists gpt-5.6-luna in its small-model group. A Build-tier org that shares its traffic gets up to 2.5M free tokens a day across that group. The counter resets at 00:00 UTC. The request that would cross the daily limit, and every later one that day, is billed at normal rates. Tool use, evals and fine-tuning are excluded, and the balance must stay positive. Sentinel used about 2.77M tokens a day in October, so only about a tenth of its traffic would be billed: about USD 1.81 a month instead of USD 18.54. The pop-up on the settings page does not name gpt-5.6-luna, so the saving counts only after the usage dashboard shows "data sharing incentive tier" tokens for it. Until then the run-rate stays at USD 18.54.

## Not a Sentinel cost

These items appear in the same mailboxes or accounts but are deliberately left out of every Sentinel total. The full catalogue, with amounts and reasons, is in [excluded.csv](../../finance/reports/2026-10-14-full-audit/excluded.csv).

| Category | Examples | Why it is excluded |
|---|---|---|
| AI assistant subscriptions | Claude Max plans and Claude extra usage, ChatGPT Pro and Business, Google AI Ultra and Plus | They serve all of the owner's work, not Sentinel. Agreed rule. |
| Coding tools | Claude Code sessions, Codex, OpenCode via OpenRouter, Firecrawl, Exa and Context7, Cursor, Wispr Flow | Cross-project tools for writing code. Agreed rule. |
| msigalert / InfoCentral | Netcup server, InfoCentral domains, the .xyz sending domain, OpenPanel, the msigalert Anthropic verifier keys, Better Stack, Resend, Cloudflare zones | The second product has its own accounts and its own ledger. |
| Other projects | MemSearchBacklog key on Anthropic, Google Cloud gtasks-cli, Cloud Vision, Voyage AI, TypeSafe mail cleanup and jev tooling, law-firm domain, Workspace and SES, legal databases | Not Sentinel. Shared accounts are split by API key, project or model. |
| Personal and pre-project | Password manager, personal apps, mobile plan, purchases before 2026-03-21 | Private spending or older than the project. |
| The owner's time | — | Not counted by agreement. |

## Accounting conventions

- The primary table is economic cost by month of use. Usage services go to the usage month, invoices to their service month, and one-off or annual fees to the month of purchase.
- Prepaid credit counts when it is consumed, not when it is bought. On shared prepaid accounts (Anthropic, OpenRouter, TypeSafe), Sentinel's share is set first-in, first-out by credit grant.
- Reverse-charged VAT (0% on the invoice) is excluded. Twilio, Anthropic, OpenAI and Hetzner all invoice this way on the owner's Polish VAT number. VAT and fees that were actually paid, such as OpenRouter's 23% VAT and purchase fee or Apple's gross price, are included pro rata.
- Whether the excluded reverse-charge VAT is deductible is an open tax question for the owner. If it is not, Sentinel's cost is higher by 23% on those four providers: about PLN 403.45 to date and about PLN 25.79 a month. These amounts stay outside every total; `summary.json` (`reverse_charge_vat`) has the split by provider.
- Free or promotional credit is shown as a zero-cash note line and stays outside every total.
- Charges that accrue but are not paid yet (Twilio rental while suspended) are cost of the month they accrue. They are owed, not paid.
- No amount is invented. An unknown amount is recorded as unknown. An estimate is labelled, states its method and has low and high bounds.
- The secondary table is cash by payment date, Sentinel's share only. A purchase and its consumption are never added together.
- PLN uses the NBP table A mid rate: the last business day of the usage month for costs, the last business day before the payment for cash, and the latest available day for the current monthly cost.

## When a new cost appears

An agent that notices a new paid service, plan, model, top-up, price change or renewal must **ask the owner** whether to add it as a Sentinel cost. It must not add it on its own. This applies even when the cost looks small or obviously Sentinel's.

If the owner says yes:

1. Add a line in the same schema as `finance/reports/2026-10-14-full-audit/input/lines.json`: provider, item, basis, month, amount in native currency, evidence class, public evidence label and `in_total`. Do not edit a dated report folder after it is published. Copy its `input/` folder to a new dated folder under `finance/reports/`, copy the build script with the new as-of date and folder, and add the line there. Keep invoice numbers, account IDs, emails and card digits out of public files; the raw documents go to `finance/private/` (git-ignored).
2. Run the build script, then run it again with `--check`. The build rewrites the dated outputs and the living records (`finance/ledger.csv`, `finance/history-monthly.csv`, `finance/current-monthly.csv`).
3. Update the table in [What Sentinel pays for](#what-sentinel-pays-for), the [Totals](#totals) and the "Last updated" date at the top of this page.
4. Update the latest-report link in this page and in `finance/index.html`.

This page replaces the October 11 proposal in `finance/maintenance-policy.html`, which was never adopted. `CLAUDE.md` does not link to this page yet. A one-line pointer for its Docs section has been proposed to the owner and waits for his approval.
