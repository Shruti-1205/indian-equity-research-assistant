# Deployment guide

Three steps. Each takes 5 to 10 minutes.

## 1. Push to GitHub

```bat
cd "c:\Users\shrut\OneDrive\Desktop\Project2"
git init
git add .
git commit -m "Indian Equity Research Assistant: initial commit"
```

Go to https://github.com/new, create a public repo (name it something like `indian-equity-research-assistant`), then back in your terminal:

```bat
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

The initial push will be roughly 100 MB because the DuckDB database and ChromaDB vectors are included. GitHub accepts this without issue.

## 2. Configure GitHub Actions secrets

The daily data refresh workflow needs your API keys. In your GitHub repo:

1. Click **Settings** tab at the top.
2. In the left sidebar, click **Secrets and variables**, then **Actions**.
3. Click **New repository secret** and add each of these one at a time:
   - `GROQ_API_KEY` (paste the value from your `.env`)
   - `FRED_API_KEY`
   - `CEREBRAS_API_KEY`
   - `ANTHROPIC_API_KEY`

The workflow reads these from the secrets vault. They never appear in logs.

**Confirm the workflow is active:**

- Click the **Actions** tab in your repo.
- You should see a workflow called "Daily data refresh".
- Click it, then click **Run workflow** to trigger it manually once right now. It will take about 12 minutes.
- After it finishes, your repo gets a new commit named `chore(data): automated daily refresh YYYY-MM-DD`.
- From then on, the workflow runs automatically every weekday at 19:30 IST (14:00 UTC).

## 3. Deploy the Streamlit dashboard

1. Go to https://share.streamlit.io and sign in with your GitHub account.
2. Click **New app**.
3. Select your repo, set the main file path to `src/dashboard/app.py`, leave the branch as `main`.
4. Click **Advanced settings** and paste the same API keys from step 2 into the Secrets field, in TOML format:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   CEREBRAS_API_KEY = "csk-..."
   GROQ_API_KEY = "gsk-..."
   FRED_API_KEY = "..."
   DAILY_USD_BUDGET = "0.50"
   ```

   Note the lower `DAILY_USD_BUDGET` of 50 cents for the public deployment.
   This protects you from random visitors burning your balance.

5. Click **Deploy**. You will get a URL like `your-app.streamlit.app`.

The Streamlit Cloud deployment watches the `main` branch. Every time the daily GitHub Action commits new data, Streamlit redeploys automatically (takes 1 to 2 minutes). The live app always shows the most recent trading session.

## What happens on a non-trading day

On Saturday, Sunday, or Indian market holidays, the cron still fires but fewer things change: no new prices from yfinance (market closed), possibly no new BSE filings. The commit will likely only include FRED macro updates or nothing. The app keeps showing the last trading session.

## Cost expectations

| What | Cost |
|---|---|
| GitHub Actions | Free (2,000 minutes per month, we use ~300) |
| Streamlit Community Cloud | Free |
| Cerebras, Groq, FRED | Free tier |
| Anthropic Claude Haiku | Roughly $0.01 per query. With `DAILY_USD_BUDGET=0.50`, max $15 per month even with heavy use. |

## Troubleshooting

**The daily workflow fails with a rate limit.** Groq or Cerebras may be throttled. Retry manually from the Actions tab.

**Streamlit deployment fails with "out of memory".** Reduce the number of stocks in `config.py`'s `WATCHLIST` from Nifty 100 to Nifty 50, push, redeploy.

**The app says "No data yet, run scripts/bootstrap".** The initial commit did not include the `data/` and `chroma_db/` folders. Check that `.gitignore` is not excluding them, then re-commit.

**The app shows an old date.** Check the Actions tab. The workflow may have failed. Look at the logs to diagnose.
