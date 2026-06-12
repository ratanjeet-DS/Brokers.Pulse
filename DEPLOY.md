# 🚀 Deploy BrokerPulse — pick your 2-minute path

## Option A — Netlify Drop (fastest, no Git needed)
1. Go to  https://app.netlify.com/drop
2. Drag the `index.html` file (or this whole folder) onto the page
3. ✅ Instant live URL like:  https://brokerpulse-nse.netlify.app
   (rename the site in Site settings → free custom subdomain)
To update monthly: regenerate index.html locally, drag again.

## Option B — GitHub Pages (fully automatic pipeline) ⭐ recommended
You already use GitHub for the Streamlit app — this adds a static site:
1. Create a new repo (e.g. `brokerpulse`) and push this folder's contents
2. Repo → Settings → Pages → Source: **GitHub Actions**
3. ✅ Live URL:  https://<your-username>.github.io/brokerpulse/

The included workflow (.github/workflows/deploy.yml) then makes it
hands-free: every time you push a new report file into `data/reports/`,
GitHub regenerates the dashboard and republishes automatically.
Monthly update = drop file → git push → done.

## Option C — Vercel
1. https://vercel.com/new → import the repo (or drag the folder via CLI)
2. Framework preset: **Other** · no build command · output dir: `.`
3. ✅ URL:  https://brokerpulse.vercel.app

## Option D — Cloudflare Pages
1. https://pages.cloudflare.com → create project → connect repo
2. Build command: `pip install pandas numpy xlrd openpyxl lxml html5lib && python generate_dashboard.py`
   Output directory: `.`
3. ✅ URL:  https://brokerpulse.pages.dev

## Option E — keep it inside Streamlit (zero new accounts)
Your existing app at znseresearch.streamlit.app can serve the HTML:
add `st.components.v1.html(open("index.html").read(), height=4000, scrolling=True)`
— but a static host (A–D) is faster and cleaner for this page.
