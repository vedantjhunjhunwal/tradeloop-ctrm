# Data flow

```mermaid
flowchart LR
    T[Trader ticket<br/>REST POST /trades] --> V{Validation<br/>VR-01..VR-07}
    V -- reject --> X[Rejected with rule ID]
    V -- pass --> DB[(SQLite<br/>trades · versions · audit_log)]
    CF[Counterparty confirmation<br/>free text, 3 layouts] --> P[Parse 8 fields] --> MT{Match vs trade}
    MT -- full match --> DB
    MT -- mismatch / unreadable --> EQ[Exception queue]
    MD[(Forward curves<br/>+ daily history)] --> R[Positions · MtM · P&L explain<br/>VaR · credit vs limits]
    DB --> R
    DB --> S[Invoices<br/>physical + swap] --> N[Netting by<br/>counterparty-month]
    MD --> S
    ST[Counterparty statement] --> RC{Reconcile}
    S --> RC --> BR[Breaks by type]
    DB --> REP[Transaction report N/M/C<br/>+ field checks]
```

| Step | Module | Input | Output |
|---|---|---|---|
| Capture | `trades.py` | Ticket, reference data, forward curve | Stored trade + audit entry, or rejection with rule ID |
| Confirm | `confirmations.py` | Confirmation text | MATCHED / MISMATCH (fields) / UNREADABLE |
| Value and risk | `risk.py` | Live trades, curves | Positions, MtM, P&L explain, VaR, credit report |
| Settle | `settlement.py` | Delivered months, fixings | Invoice lines, net amounts, receivables |
| Reconcile | `settlement.py` | Our lines, counterparty statement | Matched count, breaks by type |
| Report | `reporting.py` | Audit log + versions | Transaction report CSV, check errors |
