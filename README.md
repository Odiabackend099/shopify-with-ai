# Shopify with AI — Project Setup and Run Guide

## Project Structure

```
shopify-with-ai/
├── infrastructure/
│   ├── Dockerfile           # Render deployment
│   ├── requirements.txt    # Python dependencies
│   ├── render.yaml         # Render deployment config
│   └── .env.example        # Environment template
├── supabase/
│   └── schema.sql          # Database schema (APPLIED)
├── src/
│   ├── api/
│   │   ├── main.py         # FastAPI backend
│   │   ├── pricing.py      # 2026 pricing tiers (3-tier Good/Better/Best)
│   │   └── webhooks/
│   │       └── dodo_webhook.py  # Dodo Payments webhook handlers
│   ├── workers/
│   │   └── task_processor.py  # Background task worker
│   └── ai/
│       └── nvidia_client.py    # AI client + 6 agent prompts
└── docs/
```

---

## Confirmed Infrastructure

| Component | Technology | Status |
|---|---|---|
| AI Models | NVIDIA KIMI K2.5 / MiniMax M2.5 | ✅ Tested |
| Database | Supabase (`ykyemuahvxshtsrkhsfo`) | ✅ Schema applied |
| Backend | Render (free tier) | 🚀 Ready to deploy |
| Frontend | Vercel | 🚀 Ready to deploy |
| Payments | Dodo Payments | ✅ Tested (USD → Nigeria confirmed) |
| Parent | Odiadev (Nigeria) | — |
| UK Sponsor | Call Waiting AI | — |

---

## AI Model Selection (Tested)

| Model | Latency | Output | Verdict |
|---|---|---|---|
| **MiniMax M2.5** | **2.2 sec** | Clean, no thinking | ✅ **USE FOR PRODUCTION** |
| KIMI K2-instruct | 36 sec | Clean | ⚠️ Slow |
| KIMI K2.5 | ~1 sec | Output in `reasoning` field | ❌ Don't use |
| MiniMax M2.7 | 64+ sec | Thinking embedded | ❌ Too slow |

---

## STEP 1: Save Secrets

Go to https://barpel.zo.computer/?t=settings&s=advanced and add:

| Secret Name | Value |
|---|---|
| `NVIDIA_API_KEY` | `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` |
| `SUPABASE_ANON_KEY` | From Supabase → Settings → API → `anon` key |
| `SUPABASE_SERVICE_ROLE_KEY` | From Supabase → Settings → API → `service_role` key |
| `SUPABASE_PAT` | Personal Access Token for migrations |
| `DODO_PAYMENTS_API_KEY` | From Dodo Payments dashboard |
| `DODO_WEBHOOK_SECRET` | From Dodo Payments dashboard → Webhooks |

---

## STEP 2: Supabase Database (✅ ALREADY APPLIED)

Project ID: `ykyemuahvxshtsrkhsfo` (shopifywithai)
Tables created via Management API — no manual action needed.

**Tables:** organizations, users, subscriptions, billing_events, agent_tasks, product_ideas, shopify_stores, agent_artifacts, payouts

---

## STEP 3: Deploy Backend to Render

1. Create GitHub repo with this project
2. Connect to Render.com (free tier)
3. Create Web Service:
   - **Root directory:** `/`
   - **Build command:** `pip install -r infrastructure/requirements.txt`
   - **Start command:** `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 src.api.main:app`
4. Add environment variables from STEP 1
5. Deploy

---

## STEP 4: Dodo Payments Integration

### 4A: Create Products in Dodo Dashboard

Create these subscription products in Dodo Payments dashboard:

| Product | Monthly ID Env Var | Annual ID Env Var |
|---|---|---|
| Starter | `DODO_PRODUCT_STARTER_MONTHLY` | `DODO_PRODUCT_STARTER_ANNUAL` |
| Growth | `DODO_PRODUCT_GROWTH_MONTHLY` | `DODO_PRODUCT_GROWTH_ANNUAL` |
| Free Trial | `DODO_PRODUCT_FREE_TRIAL` | — |

### 4B: Connect Webhook

In Dodo Payments Dashboard → Developer → Webhooks:
- **URL:** `https://your-render-url.onrender.com/webhooks/dodo`
- **Events to subscribe:**
  - `payment.succeeded`
  - `payment.failed`
  - `subscription.created`
  - `subscription.updated`
  - `subscription.renewed`
  - `subscription.cancelled`
  - `subscription.on_hold`
  - `dispute.opened`

### 4C: Webhook Signature Verification

Dodo uses HMAC-SHA256 with format: `t=timestamp,v1=hmac_hex`

```python
# In dodo_webhook.py:
def verify_dodo_signature(payload: bytes, signature: str, secret: str) -> bool:
    parts = dict(x.split("=", 1) for x in signature.split(","))
    timestamp = parts.get("t", "")
    received_hmac = parts.get("v1", "")
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_hmac)
```

---

## STEP 5: Pricing Tiers (2026 Best Practice)

### 3-Tier Structure (Good/Better/Best)

| Tier | Monthly | Annual | AI Calls | Stores | Key Features |
|---|---|---|---|---|---|
| **Free** | $0 | $0 | 30/mo | 1 | Product research (5/mo) |
| **Starter** | $29 | $276 (~$23/mo) | 100/mo | 3 | Unlimited research, ad copy (10/mo) |
| **Growth** | $79 | $756 (~$63/mo) | 500/mo | 10 | Full agent team, ads (50/mo), analytics |

**2026 Pricing Insights Applied:**
- Middle tier (Starter) is anchor — drives most conversions
- Annual discount ~20% — reduces churn by 40%
- AI call overage: $0.05/call (prevents runaway costs)
- Usage alerts at 50%, 80%, 95%, 100% (prevents bill shock)
- Proration on upgrade/downgrade (credit next cycle, not refund)

### Payout Configuration

- **Currency:** USD (Dodo collects globally, pays out in USD)
- **Payout threshold:** $50 minimum
- **Payout schedule:** Bi-monthly (default)
- **Nigeria bank:** Receives via Dodo's USD → NGN flow

---

## STEP 6: Test the API

```bash
# Health check
curl https://your-render-url.onrender.com/health

# Create organization (first user + free trial)
curl -X POST https://your-render-url.onrender.com/v1/organizations \
  -H "Content-Type: application/json" \
  -d '{"name": "My Store", "email": "user@example.com"}'

# Run product research
curl -X POST https://your-render-url.onrender.com/v1/research/trending \
  -H "Content-Type: application/json" \
  -d '{"organization_id": "YOUR-ORG-ID", "niche": "outdoor fitness", "count": 5}'

# Check task status
curl https://your-render-url.onrender.com/v1/tasks/TASK-ID
```

---

## Agent Team (Already Scheduled)

4 agents scheduled to run in sequence (1 AM Nigeria time):

| Agent | Time | Output |
|---|---|---|
| Technical Architecture Agent | 01:00 | `docs/technical-architecture.md` |
| User Experience Agent | 01:15 | `docs/user-experience.md` |
| Devil's Advocate Agent | 01:30 | `docs/devil-advocate.md` |
| Documentation & Best Practices Agent | 01:45 | `docs/best-practices.md` |

---

## Key Files Reference

| File | Purpose |
|---|---|
| `src/api/main.py` | FastAPI app — all endpoints |
| `src/api/webhooks/dodo_webhook.py` | Dodo webhook signature + event handlers |
| `src/api/pricing.py` | 2026 pricing tier config (3-tier, overage, proration) |
| `src/ai/nvidia_client.py` | MiniMax M2.5 client + 6 agent prompts |
| `src/workers/task_processor.py` | Background worker (polls `agent_tasks` table) |
| `supabase/schema.sql` | Applied database schema |
| `infrastructure/render.yaml` | Render deployment config |

---

## Next Steps After Deployment

1. **Set Dodo product IDs** in Render environment variables
2. **Connect Shopify** via Custom App (Dev Dashboard) — not OAuth (simpler for single-store)
3. **Test checkout flow** — create checkout session → redirect → verify webhook fires
4. **Configure Dodo webhook** in dashboard — subscribe to all events
5. **Frontend:** Deploy Vercel app connected to Render API

---

## Dodo Payments — Key 2026 Notes

- **Merchant of Record (MoR):** Dodo handles global VAT/GST — you don't
- **Webhooks are source of truth:** Never rely on client callbacks
- **Idempotent handling:** Dodo retries failed deliveries — must handle duplicates
- **Signature rotation:** Old secret valid for 24h after rotation
- **On-hold = dunning trigger:** `subscription.on_hold` queues automated retry emails
- **Dispute alerts:** `dispute.opened` queues immediate alert to Odiadev team