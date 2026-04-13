# Shopify with AI
### AI-Powered Dropshipping Automation Platform

> Built by [Odiadev](https://odiadev.com) (Nigeria) + [Call Waiting AI](https://callwaiting.ai) (UK)

---

## What It Does

An AI agent team that automates your entire dropshipping operation:
- 🔍 **TrendHunter** → Finds viral products via Google Trends, TikTok, Amazon
- 🏪 **StoreBuilder** → Creates your Shopify store with logo, pages, policies
- ✍️ **CopyWriter** → Writes product descriptions, ad copy, email sequences
- 📢 **AdCommander** → Creates + launches Meta/Instagram ads
- 🔎 **SupplierScout** → Sources from Alibaba/DHGate with price negotiation
- 📊 **AnalyticsAgent** → Monitors ROAS and optimizes campaigns

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Render (free tier) |
| Database | Supabase (PostgreSQL) |
| AI | NVIDIA NIM — MiniMax M2.5 (2.2s latency) |
| Payments | Dodo Payments |
| Shopify | Custom App OAuth |

---

## Quick Start

### 1. Clone & Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Odiabackend099/shopify-with-ai)

Or manually:
```bash
# Connect GitHub repo in Render Dashboard
# Create Web Service:
#   Root directory: /
#   Build command: pip install -r infrastructure/requirements.txt
#   Start command: gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 src.api.main:app
```

### 2. Set Environment Variables in Render

| Variable | Value |
|---|---|
| `NVIDIA_API_KEY` | Your NVIDIA NIM API key |
| `SUPABASE_ANON_KEY` | From Supabase → Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | From Supabase → Settings → API |
| `SUPABASE_URL` | `https://your-project.supabase.co` |
| `DODO_PAYMENTS_TEST_API_KEY` | `sk_test_...` from Dodo dashboard |
| `DODO_PAYMENTS_WEBHOOK_SECRET` | From Dodo → Developer → Webhooks |
| `APP_SECRET` | Random 64-char string |

### 3. Set Up Supabase Database

Run in Supabase SQL Editor (`https://supabase.com/project/YOUR_PROJECT/sql`):
```sql
-- See supabase/schema.sql for the full schema
```

Tables created: `organizations`, `users`, `subscriptions`, `billing_events`, `agent_tasks`, `product_ideas`, `shopify_stores`, `agent_artifacts`, `payouts`

### 4. Create Dodo Products

After getting a **write-enabled** Dodo API key, run:
```bash
bash scripts/create-dodo-products.sh
```

Or create manually in [Dodo Dashboard](https://app.dodopayments.com):
| Product | Price |
|---|---|
| Shopify with AI - Free Trial | $0 (14-day trial) |
| Shopify with AI - Starter Monthly | $29/mo |
| Shopify with AI - Growth Monthly | $79/mo |
| Shopify with AI - Starter Annual | $276/yr (save $72) |
| Shopify with AI - Growth Annual | $756/yr (save $192) |

### 5. Configure Dodo Webhook

In Dodo Dashboard → Developer → Webhooks:
- URL: `https://your-render-url.onrender.com/webhooks/dodo`
- Events: `payment.succeeded`, `subscription.active`, `subscription.cancelled`, `subscription.renewed`

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/v1/organizations` | Create organization + user |
| GET | `/v1/organizations/{id}` | Get organization |
| POST | `/v1/tasks` | Queue AI agent task |
| GET | `/v1/tasks/{id}` | Get task status |
| GET | `/v1/tasks/{org_id}` | List org tasks |
| POST | `/v1/research/trending` | Run trend research |
| POST | `/webhooks/dodo` | Dodo webhook handler |
| GET | `/v1/shopify/auth` | Shopify OAuth |
| POST | `/v1/shopify/disconnect` | Disconnect store |

---

## Pricing Tiers

| Tier | AI Calls/mo | Price |
|---|---|---|
| Free | 30 | $0 (14d trial) |
| Starter | 100 | $29/mo |
| Growth | 500 | $79/mo |

Annual plans: 2 months free.

---

## Project Structure

```
shopify-with-ai/
├── infrastructure/
│   ├── Dockerfile           # Render deployment
│   ├── requirements.txt    # Python dependencies
│   └── .env.example        # Environment template
├── src/
│   ├── api/
│   │   ├── main.py         # FastAPI app
│   │   ├── pricing.py      # Pricing tiers
│   │   └── webhooks/
│   │       └── dodo_webhook.py
│   ├── ai/
│   │   └── nvidia_client.py  # AI agents (6 prompts)
│   └── workers/
│       └── task_processor.py  # Background queue
├── supabase/
│   └── schema.sql          # Database schema
├── scripts/
│   └── create-dodo-products.sh
└── README.md
```

---

## Powered By

- **Odiadev** — Nigerian tech company powering the project
- **Call Waiting AI** — UK-based sponsor
- **NVIDIA NIM** — Free AI inference (MiniMax M2.5)
- **Dodo Payments** — USD billing + Nigeria payouts

---

## License

MIT