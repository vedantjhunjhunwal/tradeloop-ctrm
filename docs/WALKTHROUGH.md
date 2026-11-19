# Stakeholder walkthrough (20 minutes)

A script for demoing TradeLoop to a mixed audience: a trader, a risk manager and an operations
lead. Each section starts with the question that person cares about.

**Setup:** `python -m tradeloop.scenario` then `uvicorn tradeloop.api:app` and open `/docs`.

## 1. Trader — "Will it stop me making a costly mistake?" (4 min)
- Book a valid TTF forward with `POST /trades`. Show the VALIDATED status.
- Re-send it with the price keyed 60% too high. Show the VR-07 rejection and the curve price
  quoted in the message.
- Point to `results/run_summary.json → capture`: 12 bad tickets, each rejected by the rule it was
  designed to hit.

## 2. Operations — "How much of my confirmation work is automatic?" (5 min)
- `POST /confirmations` with a confirmation in each of the three layouts. All three auto-confirm.
- Change the price in one and send it again. Show the MISMATCH naming the `price` field.
- Scenario result: 198 of 232 confirmations auto-matched; the 34 exceptions are exactly the 34
  documents with planted errors, with no false matches.
- Open `results/recon_breaks.csv`: 15 statement breaks, each tagged with its type, and none raised
  on clean lines.

## 3. Risk — "What is my exposure right now?" (6 min)
- `GET /positions` and `GET /risk/mtm` by book.
- `GET /risk/var`: 1-day 95% and 99% VaR, split by commodity. Brent dominates, so that is where a
  hedge would cut risk most.
- P&L explain: today's change splits into curve move and new trades, with zero unexplained.
- `GET /risk/credit`: one counterparty in BREACH, one in WARN. Talk through the action
  (stop new trades, ask for collateral).

## 4. Compliance — "Can we prove what happened?" (3 min)
- `GET /trades/{id}/audit` on an amended trade: who changed what, from and to which value.
- `GET /reports/transactions`: N, M and C records under one UTI, 0 check errors.

## 5. Questions to ask the audience (2 min)
- Which tolerance should apply to reconciliation in your process?
- Should a 15–30% price move warn, or need a second approval?
- Which breaks should reach a person first?
