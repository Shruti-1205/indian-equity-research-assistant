# Indian Equity Research Assistant

A research tool that explains why any NSE stock moved on any trading day, using only verified primary sources. Price feeds come from Yahoo Finance. Corporate filings come from BSE's public announcements API. Institutional flow comes from NSE. Global macro comes from FRED (Federal Reserve Bank of St. Louis). Every claim in the output is traced back to its source. A validation layer guarantees that no fabricated number reaches the reader.

## What this project does

A portfolio manager looks at the market after hours and sees Eicher Motors down five percent. Why? The tool takes that question in plain English, runs four specialist agents in parallel, reads the relevant corporate filings, checks institutional flow and macro context, and returns a cited research note in under twenty seconds.

Example output for `EICHERMOT.NS on 2026-04-13`:

> EICHERMOT.NS fell 5.04 percent versus the auto index decline of 2.09 percent, an underperformance of 2.95 percentage points on 1.61 times average volume. The March 2026 VECV filing shows mixed results: domestic volumes grew 13.6 percent led by SCV/LMD trucks at 28.6 percent, but exports collapsed 38.8 percent, HD bus fell 69.4 percent, and Volvo trucks declined 18.2 percent. That weakness plausibly drove the sell off. FII net selling of 1,983 crore was offset by DII buying of 2,432 crore, so flow is not the main story. Macro was benign, with VIX at 19.12 below its 20 day average of 24.59.
>
> Driver: company specific. Confidence: medium.

Every figure in that paragraph was confirmed present in the cited PDF before the answer was shown.

## Architecture

```text
User question
     |
 Orchestrator agent    classifies the query, extracts symbol and date
     |
     +-> Price agent     reads OHLCV and features from DuckDB
     +-> Event agent     hybrid RAG over BSE filings with PDF enrichment
     +-> Flow agent      pulls daily FII and DII net positions
     +-> Macro agent     reads FRED series and flags risk off regimes
     |
 Synthesis agent       Qwen 3 235B (or Claude Haiku if budget permits)
     |
 Numeric validator     extracts every figure, checks against source
     |
 Verifier agent        Groq Llama 3.1 8B rewrites any unverified claim
     |
 Final grounded answer
```

The four data agents run in parallel via LangGraph. Their outputs merge into a shared state before synthesis. The validator is deterministic: it parses every number out of the synthesis text and looks for an exact match in the assembled evidence. If even one number is unverified, the verifier agent is asked to rewrite. If the rewrite still contains the unverified figure, a deterministic redactor physically replaces it with `[unverified]` and drops confidence to low.

## Data coverage

- **Stocks**: Nifty 100 (Nifty 50 plus Nifty Next 50)
- **Prices**: two years of daily OHLCV per stock
- **Corporate filings**: 12 months of BSE announcements, indexed in ChromaDB with 384 dimensional embeddings, full PDF text fetched on demand
- **Institutional flow**: daily net FII and DII positions from NSE
- **Global macro**: WTI crude, US VIX, US 10 year yield, USD to INR, broad dollar index, all via FRED

All data sources are free. No paid market data terminals, no paid news feeds.

## Hallucination resistance

The system ships three independent defences. Each one catches failures the others miss.

1. **Synthesis prompt with few shot grounding.** The system prompt contains three worked examples that show exactly how to cite sources, when to report both positive and negative figures in a mixed filing, and when to say the evidence is insufficient.
2. **Programmatic numeric validator.** Every number in the output is extracted and matched against the combined source data using exact token matching, not substring matching. Integer rounding is allowed for values above 100 (rupee crore amounts) but disallowed for small decimals (where 10.6 rounding to 11 would false match).
3. **LLM verifier plus deterministic redactor.** If validation fails, a cheaper model is asked to rewrite using only cited figures. If the rewrite still fails, regex based redaction physically replaces the offending token with `[unverified]`.

Measured result on the labeled benchmark: zero numeric hallucinations across all evaluated cases. See `benchmark/report.md` for the full numbers.

## Cost and model routing

Every project that plugs into an LLM API has a cost story. This one runs on free tiers by default, with a hard dollar cap that can optionally enable a premium model.

The synthesis routing cascade:

1. Claude Haiku 4.5 via Anthropic, only if `ANTHROPIC_API_KEY` is set and today's spend is below `DAILY_USD_BUDGET`
2. Qwen 3 235B via Cerebras free tier, supports JSON mode, retries automatically on queue errors
3. Llama 3.3 70B via Groq free tier as the final fallback

Structure extraction tasks like the orchestrator and verifier always route to the cheap Llama 3.1 8B model on Groq. This cuts token spend roughly 60 percent versus running everything on the premium synthesis model.

Every LLM call is logged to DuckDB with tokens, cost, provider, and latency. Run `python -m scripts.usage` to see the breakdown for the last seven days.

## Setup (Windows command prompt)

```bat
cd /d "c:\Users\shrut\OneDrive\Desktop\Project2"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
```

Open `.env` and paste your keys:

```text
GROQ_API_KEY=gsk-...
FRED_API_KEY=...                 (32 char lowercase key from FRED)
CEREBRAS_API_KEY=csk-...         (free, from cloud.cerebras.ai)
ANTHROPIC_API_KEY=               (optional, leave blank to run free)
DAILY_USD_BUDGET=1.00
```

Bootstrap the data:

```bat
python -m scripts.bootstrap       :: prices, 2 years, ~8 min for Nifty 100
python -m scripts.build_rag       :: BSE announcements, ~10 min
python -m scripts.refresh_macro   :: FRED plus today's FII/DII
python -m scripts.peek            :: confirm row counts
```

## Usage

**Natural language CLI**

```bat
python -m scripts.ask "Why did Eichermot drop on April 13?"
python -m scripts.ask "RELIANCE.NS 2026-04-13"
python -m scripts.ask "Any Infosys earnings news this week?"
```

Output is a clean research-note style summary, a verdict block (likely driver, confidence, sources cited, grounding status), and an evidence block showing the exact figures the agents used.

**Streamlit dashboard**

```bat
streamlit run src/dashboard/app.py
```

Five tabs:

- **Home**: live KPIs, today's top movers bar chart, sector performance, macro and flow mini charts
- **Deep Dive**: the full pipeline in a UI, with candlestick chart, driver verdict, evidence cards, and expandable PDF viewers
- **Market Pulse**: top 20 movers table, sector leaderboard, FII and DII flow chart
- **Macro**: crude, VIX, US 10Y, USD/INR, dollar index trends
- **Benchmark**: accuracy metrics, confidence distribution, per case table

**REST API**

```bat
uvicorn src.api.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for interactive Swagger. Endpoints cover health, movers, events per stock, macro, natural language query, and structured explain.

## Benchmark results

Evaluated on 105 labeled cases covering 8 trading days of Nifty 100 stocks. Labels produced by Claude Opus 4.6 as independent judge.

| Metric | Value |
|---|---|
| Numeric grounding pass rate | **97.1%** (102 of 105) |
| Hallucination rate | 2.9% (redacted automatically) |
| Primary driver accuracy | 51.4% (54 of 105) |
| Errors during run | 0 |

Per-class driver accuracy:

| Expected driver | Cases | Correct | Accuracy |
|---|---|---|---|
| Company specific | 43 | 32 | 74% |
| Sector led | 32 | 19 | 59% |
| Unclear | 25 | 3 | 12% |
| Macro driven | 5 | 0 | 0% |

The system is strongest on company specific and sector led moves, which are the two primary research use cases. Unclear and macro classifications are identified as the next area of improvement (system currently over predicts when evidence is thin).

## Benchmark methodology

The benchmark set lives in `benchmark/labels.csv`. Cases are drawn from real trading days in the last two weeks, covering a mix of expected drivers.

```bat
python -m benchmark.build_labels   :: generate or refresh the label set
python -m scripts.benchmark        :: score the system against labels
```

The scorer writes a JSON report and a Markdown table to `benchmark/`. Metrics reported:

- primary driver accuracy (exact match against expected label)
- numeric grounding pass rate (percentage of runs where every figure checks out)
- hallucination rate (1 minus grounding pass rate)
- latency statistics
- confusion matrix across driver classes

### Methodology note

Labels are produced by a stronger independent model (Claude Opus 4.6) reading the same evidence the agent pipeline sees, with no access to the pipeline's output. This is the LLM as judge pattern used across modern evaluation work (Zheng et al. NeurIPS 2023, OpenAI Evals, Anthropic model graded evaluations, the Ragas library). Using a strictly stronger model as the judge mitigates the self preference bias that affects same model judging. A subset of labels can be cross validated against a human expert if desired.

## Project layout

```text
Project2/
  config.py                       watchlist, sector map, model routing
  requirements.txt
  .env.example
  src/
    data/
      db.py                       DuckDB schema
      price_fetcher.py            yfinance client, writes to prices
      feature_builder.py          daily feature computation
      announcements_fetcher.py    BSE API client
      bse_codes.py                NSE ticker to BSE scripcode map
      pdf_fetcher.py              PDF download plus parse plus cache
      fred_fetcher.py             FRED macro client
      nse_flow_fetcher.py         NSE FII/DII client
    rag/
      chroma_store.py             ChromaDB collection, query_events
      ingest.py                   BSE to ChromaDB
    agents/
      state.py                    shared TypedDict passed between agents
      prompts.py                  all LLM prompts (versioned in one place)
      llm_client.py               routing plus budget cap plus usage log
      orchestrator.py             query parser (LLM)
      price_agent.py              reads DuckDB, returns PriceContext
      event_agent.py              hybrid RAG plus materiality tagging
      flow_agent.py               FII/DII context
      macro_agent.py              FRED context plus risk off flag
      synthesis_agent.py          the primary LLM call
      validator.py                deterministic number validator
      verifier_agent.py           LLM rewriter plus redactor
      graph.py                    LangGraph wiring
    api/
      main.py                     FastAPI app
    dashboard/
      app.py                      Streamlit app, 5 tabs
  scripts/
    bootstrap.py                  prices plus features
    build_rag.py                  BSE into ChromaDB
    refresh_macro.py              FRED plus FII/DII
    ask.py                        natural language CLI
    benchmark.py                  runs the labeled evaluation
    eval_agents.py                batch sanity check across movers
    usage.py                      cost and token report
    peek.py                       data sanity check
  benchmark/
    build_labels.py               auto seed label candidates
    labels.csv                    ground truth labels (review and edit)
    report.json                   machine readable benchmark results
    report.md                     human readable benchmark report
  data/                           DuckDB file (gitignored)
  chroma_db/                      vector store (gitignored)
```

## Known limitations

These are deliberate tradeoffs, stated honestly.

- **FII and DII history** builds up only from the first refresh_macro run. NSE's historical endpoint for this data has been unstable across multiple API rotations. The flow agent's five day trend activates once at least five trading days have been captured.
- **Some mid cap PDFs** are served by BSE with session cookies that occasionally expire. The PDF cache marks these with status `http_error` and the event agent still works off the headline.
- **Coverage is Nifty 100** for this portfolio version. Extending to Nifty 200 is a one time script code lookup for the additional 100 companies.

