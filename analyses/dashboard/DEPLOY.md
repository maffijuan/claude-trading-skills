# Deploy the live dashboard to a URL (team uses it, nobody installs anything)

The app is a normal Flask app; any Python host runs it. Below is the free path
on **Render** (no credit card). Railway / Fly.io / PythonAnywhere are analogous.

## Render (free tier)

1. Push this repo to GitHub (if it isn't already).
2. On [render.com](https://render.com) → **New +** → **Web Service** → connect the repo.
3. Fill in:
   - **Root Directory:** `analyses/dashboard`
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2`
   - **Instance Type:** Free
   *(Or use the included `render.yaml` via **New + → Blueprint** to prefill all of this.)*
4. **(Recommended) Protect it:** Environment → add `DASH_PASSWORD` = a password.
   The site then asks for it (any username). Leave it unset for open access.
5. Create → wait for the build. You get a URL like
   `https://fundamental-analyzer.onrender.com`. Share that link.

Your team just opens the URL — analyze any ticker live, batch, universes, Excel/
CSV export. No Python, no install.

## Things to know about the free tier

- **Cold start:** the free instance sleeps after ~15 min idle; the first hit
  then takes ~30–60 s to wake. Subsequent requests are fast.
- **Batch speed:** a big universe pulls many yfinance calls; the 120 s gunicorn
  timeout covers ~a few dozen tickers. For a full S&P 500 sweep, prefer the
  static report generator (`build_static.py`) instead of the live batch.
- **Data source:** still Yahoo Finance server-side — same numbers as local.

## Railway (alternative)

New Project → Deploy from repo → set **Root Directory** `analyses/dashboard`,
Start Command `gunicorn app:app --bind 0.0.0.0:$PORT`. Add `DASH_PASSWORD` var
if you want the gate.

## Local production check (optional)

```bash
cd analyses/dashboard
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:5000        # (Linux/Mac; on Windows use: python app.py)
```
