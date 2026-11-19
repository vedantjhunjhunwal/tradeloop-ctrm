# UAT results

As-of date 2026-11-20. **24/24 passed**, covering 14 requirements (FR-01, FR-02, FR-03, FR-04, FR-05, FR-06, FR-07, FR-08, FR-09, FR-10, FR-11, FR-12, FR-13, FR-14).

| ID | Requirement | Scenario | Expected result | Result |
|---|---|---|---|---|
| UAT-01 | FR-01 | Capture a valid power forward | Trade stored as VALIDATED, version 1 | PASS  |
| UAT-02 | FR-01 | Ticket with no trader | Rejected by VR-01 | PASS  |
| UAT-03 | FR-01 | Ticket against an inactive counterparty | Rejected by VR-03 | PASS  |
| UAT-04 | FR-02 | Delivery end before start | Rejected by VR-05 | PASS  |
| UAT-05 | FR-02 | Trade date in the future | Rejected by VR-06 | PASS  |
| UAT-06 | FR-03 | Price keyed 60% above the strip curve | Rejected by VR-07 (fat finger) | PASS  |
| UAT-07 | FR-03 | Price 20% above the strip curve | Accepted with a VR-07 warning | PASS  |
| UAT-08 | FR-04 | Amend quantity on a confirmed trade | Version 2, back to VALIDATED, v1 kept | PASS  |
| UAT-09 | FR-05 | Cancel a trade, then try to confirm it | Cancel succeeds; confirm is blocked | PASS  |
| UAT-10 | FR-05 | Cancelled trade leaves positions | No open position remains | PASS  |
| UAT-11 | FR-06 | Audit trail after capture, confirm, amend | 3 events with user and before/after values | PASS  |
| UAT-12 | FR-07 | Matching confirmation in each of the 3 layouts | Auto-confirmed | PASS  |
| UAT-13 | FR-07 | Counterparty confirms a different price | MISMATCH on price; trade stays VALIDATED | PASS  |
| UAT-14 | FR-07 | Confirmation with the price smudged | UNREADABLE, routed to manual review | PASS  |
| UAT-15 | FR-08 | Long 5,000 and short 2,000 in the same month | Net position +3,000 | PASS  |
| UAT-16 | FR-09 | Daily P&L explain | Curve move + new trades = total, nothing unexplained | PASS  |
| UAT-17 | FR-10 | VaR on an offsetting buy and sell | VaR is zero | PASS  |
| UAT-18 | FR-11 | Large in-the-money exposure | Counterparty flagged BREACH | PASS  |
| UAT-19 | FR-12 | Invoice a delivered physical month | Amount = quantity x fixed price, payable | PASS  |
| UAT-20 | FR-12 | Cash-settle a swap month | Amount = quantity x (monthly average index - fixed) | PASS  |
| UAT-21 | FR-13 | Statement with one wrong amount | One AMOUNT break, everything else matched | PASS  |
| UAT-22 | FR-13 | Statement missing a line and with an unknown line | MISSING_AT_CPTY and MISSING_IN_OURS | PASS  |
| UAT-23 | FR-14 | Report a trade that was amended then cancelled | Records N, M, C under one UTI; no errors | PASS  |
| UAT-24 | FR-14 | Lifecycle event reported before the NEW | Rejected by RP-04 | PASS  |
