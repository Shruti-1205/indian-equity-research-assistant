# Benchmark report

Run on **2026-04-16** against `benchmark/labels.csv`.

| Metric | Value |
|---|---|
| Cases | 105 |
| Primary-driver accuracy | **56.2%** |
| Numeric-grounding pass rate | **97.1%** |
| Hallucination rate | **2.9%** |
| Errors | 0 |
| Latency (mean) | 6.6s |
| Latency (p50) | 5.5s |

## Per-case results

| Symbol | Date | Expected | Predicted | Match | Conf | Val OK | Latency |
|---|---|---|---|:---:|---|:---:|---|
| SIEMENS.NS | 2026-04-15 | company | company | ✅ | medium | ✅ | 10.9s |
| BPCL.NS | 2026-04-15 | company | company | ✅ | high | ✅ | 6.0s |
| DIXON.NS | 2026-04-15 | company | unclear | ❌ | low | ✅ | 5.2s |
| LICI.NS | 2026-04-15 | company | company | ✅ | low | ✅ | 6.6s |
| HDFCAMC.NS | 2026-04-15 | unclear | unclear | ✅ | low | ✅ | 6.1s |
| ICICIGI.NS | 2026-04-15 | unclear | sector | ❌ | medium | ✅ | 3.9s |
| INDUSTOWER.NS | 2026-04-15 | company | unclear | ❌ | low | ✅ | 4.1s |
| POWERGRID.NS | 2026-04-15 | sector | sector | ✅ | medium | ✅ | 5.7s |
| JSWENERGY.NS | 2026-04-15 | sector | company | ❌ | medium | ✅ | 5.5s |
| HDFCLIFE.NS | 2026-04-15 | sector | sector | ✅ | medium | ✅ | 6.4s |
| HINDALCO.NS | 2026-04-15 | sector | sector | ✅ | medium | ✅ | 4.8s |
| TECHM.NS | 2026-04-15 | sector | sector | ✅ | medium | ✅ | 4.6s |
| EICHERMOT.NS | 2026-04-13 | company | company | ✅ | low | ✅ | 7.8s |
| CHOLAFIN.NS | 2026-04-13 | company | unclear | ❌ | low | ✅ | 5.0s |
| MARUTI.NS | 2026-04-13 | company | sector | ❌ | low | ✅ | 14.4s |
| JSWENERGY.NS | 2026-04-13 | company | company | ✅ | high | ✅ | 7.2s |
| HEROMOTOCO.NS | 2026-04-13 | company | sector | ❌ | medium | ✅ | 5.7s |
| ADANIPOWER.NS | 2026-04-13 | company | company | ✅ | high | ✅ | 5.4s |
| UNITDSPR.NS | 2026-04-13 | unclear | sector | ❌ | low | ✅ | 4.5s |
| BAJFINANCE.NS | 2026-04-13 | company | unclear | ❌ | low | ✅ | 6.9s |
| TVSMOTOR.NS | 2026-04-13 | sector | sector | ✅ | medium | ✅ | 6.6s |
| RELIANCE.NS | 2026-04-13 | company | company | ✅ | medium | ✅ | 5.5s |
| DABUR.NS | 2026-04-13 | unclear | sector | ❌ | low | ✅ | 5.8s |
| PIDILITIND.NS | 2026-04-13 | sector | sector | ✅ | low | ✅ | 5.3s |
| HDFCLIFE.NS | 2026-04-13 | unclear | company | ❌ | low | ✅ | 5.9s |
| SIEMENS.NS | 2026-04-10 | company | unclear | ❌ | low | ✅ | 4.9s |
| LODHA.NS | 2026-04-10 | unclear | company | ❌ | high | ✅ | 6.6s |
| COALINDIA.NS | 2026-04-10 | company | company | ✅ | high | ✅ | 6.4s |
| BERGEPAINT.NS | 2026-04-10 | company | unclear | ❌ | low | ✅ | 6.4s |
| ASIANPAINT.NS | 2026-04-10 | company | company | ✅ | high | ✅ | 5.1s |
| ADANIGREEN.NS | 2026-04-10 | company | company | ✅ | high | ✅ | 5.4s |
| EICHERMOT.NS | 2026-04-10 | sector | sector | ✅ | low | ✅ | 5.2s |
| SUNPHARMA.NS | 2026-04-10 | company | company | ✅ | high | ✅ | 5.8s |
| HEROMOTOCO.NS | 2026-04-10 | sector | sector | ✅ | medium | ✅ | 5.2s |
| ICICIBANK.NS | 2026-04-10 | sector | sector | ✅ | medium | ✅ | 4.9s |
| BAJAJ-AUTO.NS | 2026-04-10 | sector | sector | ✅ | medium | ✅ | 4.6s |
| TVSMOTOR.NS | 2026-04-10 | sector | sector | ✅ | medium | ✅ | 5.9s |
| HINDALCO.NS | 2026-04-09 | company | sector | ❌ | medium | ✅ | 4.3s |
| HAL.NS | 2026-04-09 | company | company | ✅ | high | ✅ | 6.4s |
| NAUKRI.NS | 2026-04-09 | unclear | company | ❌ | low | ✅ | 7.6s |
| AMBUJACEM.NS | 2026-04-09 | unclear | sector | ❌ | medium | ✅ | 5.2s |
| LT.NS | 2026-04-09 | unclear | sector | ❌ | medium | ✅ | 6.0s |
| JSWENERGY.NS | 2026-04-09 | company | company | ✅ | medium | ✅ | 5.8s |
| INDUSINDBK.NS | 2026-04-09 | sector | sector | ✅ | medium | ✅ | 5.9s |
| PFC.NS | 2026-04-09 | company | sector | ❌ | medium | ✅ | 6.3s |
| BOSCHLTD.NS | 2026-04-09 | company | unclear | ❌ | low | ✅ | 7.7s |
| HDFCBANK.NS | 2026-04-09 | sector | sector | ✅ | medium | ✅ | 6.1s |
| KOTAKBANK.NS | 2026-04-09 | sector | sector | ✅ | medium | ✅ | 6.0s |
| VEDL.NS | 2026-04-09 | sector | sector | ✅ | medium | ✅ | 4.7s |
| BRITANNIA.NS | 2026-04-09 | unclear | sector | ❌ | medium | ✅ | 5.3s |
| ICICIBANK.NS | 2026-04-09 | sector | sector | ✅ | low | ✅ | 4.5s |
| SBIN.NS | 2026-04-09 | sector | sector | ✅ | medium | ✅ | 5.3s |
| ADANIGREEN.NS | 2026-04-08 | company | company | ✅ | medium | ✅ | 7.6s |
| CHOLAFIN.NS | 2026-04-08 | company | sector | ❌ | medium | ✅ | 5.3s |
| ADANIENT.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 5.4s |
| LODHA.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 6.5s |
| HDFCAMC.NS | 2026-04-08 | sector | company | ❌ | medium | ✅ | 5.2s |
| EICHERMOT.NS | 2026-04-08 | sector | sector | ✅ | low | ✅ | 7.7s |
| LT.NS | 2026-04-08 | sector | company | ❌ | high | ✅ | 5.6s |
| CANBK.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 5.3s |
| BOSCHLTD.NS | 2026-04-08 | company | sector | ❌ | low | ✅ | 10.1s |
| BPCL.NS | 2026-04-08 | company | sector | ❌ | medium | ✅ | 6.0s |
| DLF.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 4.9s |
| BAJFINANCE.NS | 2026-04-08 | sector | company | ❌ | high | ✅ | 6.2s |
| BANKBARODA.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 5.4s |
| LICI.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 5.4s |
| M&M.NS | 2026-04-08 | sector | sector | ✅ | medium | ✅ | 4.9s |
| WIPRO.NS | 2026-04-07 | sector | sector | ✅ | medium | ✅ | 5.6s |
| VEDL.NS | 2026-04-07 | unclear | company | ❌ | low | ❌ | 7.6s |
| LTIM.NS | 2026-04-07 | sector | sector | ✅ | low | ✅ | 4.4s |
| HINDALCO.NS | 2026-04-07 | sector | sector | ✅ | medium | ✅ | 3.7s |
| HCLTECH.NS | 2026-04-07 | sector | sector | ✅ | medium | ✅ | 4.1s |
| GODREJCP.NS | 2026-04-07 | company | company | ✅ | medium | ✅ | 6.1s |
| TCS.NS | 2026-04-07 | sector | sector | ✅ | medium | ✅ | 3.2s |
| INFY.NS | 2026-04-07 | sector | sector | ✅ | medium | ✅ | 4.6s |
| AMBUJACEM.NS | 2026-04-07 | company | company | ✅ | high | ✅ | 5.0s |
| DMART.NS | 2026-04-07 | company | company | ✅ | low | ✅ | 6.7s |
| PNB.NS | 2026-04-07 | unclear | unclear | ✅ | low | ✅ | 7.3s |
| TRENT.NS | 2026-04-06 | company | company | ✅ | high | ✅ | 6.1s |
| ADANIGREEN.NS | 2026-04-06 | company | company | ✅ | medium | ✅ | 6.3s |
| DMART.NS | 2026-04-06 | company | company | ✅ | low | ✅ | 35.7s |
| NMDC.NS | 2026-04-06 | company | company | ✅ | high | ✅ | 5.7s |
| BOSCHLTD.NS | 2026-04-06 | company | unclear | ❌ | low | ✅ | 3.9s |
| BANKBARODA.NS | 2026-04-06 | unclear | sector | ❌ | low | ✅ | 4.9s |
| AXISBANK.NS | 2026-04-06 | unclear | sector | ❌ | medium | ✅ | 5.1s |
| ADANIENT.NS | 2026-04-06 | unclear | company | ❌ | high | ✅ | 4.6s |
| TITAN.NS | 2026-04-06 | unclear | company | ❌ | high | ✅ | 8.7s |
| RELIANCE.NS | 2026-04-06 | company | unclear | ❌ | low | ✅ | 6.4s |
| LT.NS | 2026-04-06 | unclear | sector | ❌ | low | ✅ | 4.7s |
| ULTRACEMCO.NS | 2026-04-06 | unclear | unclear | ✅ | low | ❌ | 7.0s |
| TVSMOTOR.NS | 2026-04-06 | unclear | sector | ❌ | low | ✅ | 5.5s |
| SRF.NS | 2026-04-02 | company | company | ✅ | low | ❌ | 29.0s |
| BOSCHLTD.NS | 2026-04-02 | company | sector | ❌ | medium | ✅ | 4.1s |
| LTIM.NS | 2026-04-02 | unclear | sector | ❌ | medium | ✅ | 5.1s |
| HCLTECH.NS | 2026-04-02 | sector | sector | ✅ | medium | ✅ | 4.9s |
| DIXON.NS | 2026-04-02 | company | unclear | ❌ | low | ✅ | 5.2s |
| TORNTPHARM.NS | 2026-04-02 | unclear | company | ❌ | medium | ✅ | 6.1s |
| TECHM.NS | 2026-04-02 | sector | sector | ✅ | medium | ✅ | 4.7s |
| EICHERMOT.NS | 2026-04-02 | unclear | sector | ❌ | low | ✅ | 6.7s |
| PIDILITIND.NS | 2026-04-02 | company | sector | ❌ | low | ✅ | 29.7s |
| ASIANPAINT.NS | 2026-04-02 | company | company | ✅ | medium | ✅ | 5.1s |
| DLF.NS | 2026-04-02 | unclear | sector | ❌ | low | ✅ | 4.5s |
| UNITDSPR.NS | 2026-04-02 | company | sector | ❌ | low | ✅ | 5.5s |
| HEROMOTOCO.NS | 2026-04-02 | unclear | sector | ❌ | low | ✅ | 12.7s |
| DMART.NS | 2026-04-02 | unclear | sector | ❌ | medium | ✅ | 5.3s |

## Confusion matrix

```
expected \ predicted     company    sector   unclear
----------------------------------------------------
company                       23        10        10
sector                         4        33         0
unclear                        7        15         3
```

## Methodology note

Labels in `benchmark/labels.csv` are generated deterministically from the underlying evidence (see `benchmark/build_labels.py`) using a rule set that mirrors the analyst taxonomy in the synthesis prompt. For rigorous independent evaluation, these labels should be hand-reviewed by a domain expert — the `note` column is provided for that purpose.

The **hallucination rate** metric is independent of label quality: it measures whether every numeric claim in the synthesis output appears verbatim in the source data, regardless of whether the classification is correct.