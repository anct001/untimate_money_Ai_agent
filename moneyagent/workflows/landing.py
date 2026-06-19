"""Minimal, honest landing page for the SaaS API.

Server-rendered HTML (no build step). Shows the jobs, the pricing tiers, and a
self-serve button that calls /v1/signup to mint a free API key. Copy is plain
and avoids hype/false income promises.
"""
from __future__ import annotations

import html


def _plan_cards(plans: dict) -> str:
    order = ["free", "starter", "pro"]
    cards = []
    for name in order:
        if name not in plans:
            continue
        p = plans[name]
        price = "Free" if p["price_usd"] == 0 else f"${p['price_usd']}/mo"
        cards.append(
            f"""<div class="card">
              <h3>{name.title()}</h3>
              <p class="price">{price}</p>
              <ul>
                <li>{p['monthly_requests']:,} requests / month</li>
                <li>{p['rate_per_minute']} requests / minute</li>
              </ul>
            </div>"""
        )
    return "\n".join(cards)


def render_landing(plans: dict, jobs: list[str]) -> str:
    jobs_html = ", ".join(f"<code>{html.escape(j)}</code>" for j in jobs)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>moneyagent — automation API</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto;
          padding: 0 1rem; line-height: 1.5; color: #1a1a1a; }}
  h1 {{ margin-bottom: .2rem; }}
  .muted {{ color: #666; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.5rem 0; }}
  .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 1rem 1.25rem; flex: 1; min-width: 180px; }}
  .price {{ font-size: 1.4rem; font-weight: 600; }}
  code {{ background: #f3f3f3; padding: .1rem .3rem; border-radius: 4px; }}
  button {{ background: #111; color: #fff; border: 0; padding: .6rem 1rem;
           border-radius: 8px; cursor: pointer; font-size: 1rem; }}
  pre {{ background: #f7f7f7; padding: 1rem; border-radius: 8px; overflow:auto; }}
  #out {{ margin-top: 1rem; }}
</style>
</head>
<body>
  <h1>moneyagent</h1>
  <p class="muted">An automation API that turns repetitive text jobs into one call.</p>

  <p>Available jobs: {jobs_html}.</p>

  <h2>Pricing</h2>
  <div class="cards">{_plan_cards(plans)}</div>

  <h2>Get started — free</h2>
  <p>Click to create a free API key (no card required).</p>
  <button onclick="signup()">Get free API key</button>
  <div id="out"></div>

  <h2>Use it</h2>
  <pre>curl -X POST /v1/run \\
  -H "X-API-Key: YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"job":"summarize","input_text":"your text..."}}'</pre>

  <p class="muted">To upgrade, POST to <code>/v1/checkout</code> with your key (requires
  Stripe configured by the operator). This is a tool that does real work — results
  should be reviewed before you rely on them.</p>

<script>
async function signup() {{
  const out = document.getElementById('out');
  out.textContent = 'Creating key...';
  try {{
    const r = await fetch('/v1/signup', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: '{{}}'
    }});
    const j = await r.json();
    out.innerHTML = 'Your free API key: <code>' + j.api_key + '</code><br>' +
      'Keep it secret. ' + j.limits.monthly_requests + ' requests/month.';
  }} catch (e) {{ out.textContent = 'Error: ' + e; }}
}}
</script>
</body>
</html>"""
