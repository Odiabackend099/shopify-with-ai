"""
Shopify with AI — FastAPI Backend
Deployed on Render (Free Tier)
"""

import os
import json
import hashlib
import hmac
import base64
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client
import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE", "") or os.environ.get("SUPABASE_KEY", "")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
DODO_SECRET_KEY = os.environ.get("DODO_SECRET_KEY", "")
DODO_TEST_API_KEY = os.environ.get("DODO_PAYMENTS_TEST_API_KEY", "")
DODO_PUBLIC_KEY = os.environ.get("DODO_PUBLIC_KEY", "")
DODO_WEBHOOK_SECRET = os.environ.get("DODO_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://storewright.odia.dev")
SHOPIFY_APP_URL = os.environ.get("SHOPIFY_APP_URL", "")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
META_APP_ID = os.environ.get("META_APP_ID", "")

DODO_PRODUCTS = {
    "starter": "pdt_0Nca6q2zRqMTFNhTYPqb1",
    "growth": "pdt_0Nca6q7q8fAIJSDxYXNBm",
    "scale": "pdt_0Nca6qBBtiUmMNnGXyV8E",
}

GRAPHQL_VERSION = "2026-01"


def get_supabase_service() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(500, "SUPABASE_SERVICE_ROLE_KEY is required")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_supabase_anon() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(500, "SUPABASE_ANON_KEY is required")
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[storewright] Starting — {datetime.now(timezone.utc)}")
    yield
    print("[storewright] Shutdown")


app = FastAPI(title="Storewright API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://storewright.odia.dev",
        "https://www.storewright.odia.dev",
        "https://*.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    supabase_anon: str
    supabase_service: str
    dodo: str
    nvidia: str


class OrganizationCreate(BaseModel):
    name: str
    email: str


class AuthOrgCreate(BaseModel):
    user_id: str
    email: str
    name: str


class AgentTaskRequest(BaseModel):
    task_type: str
    input_payload: dict
    priority: int = Field(default=5, ge=1, le=10)


async def shopify_graphql(shop: str, token: str, query: str, variables: dict[str, Any]) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"https://{shop}/admin/api/{GRAPHQL_VERSION}/graphql.json",
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": token,
            },
            json={"query": query, "variables": variables},
        )
    if res.status_code >= 400:
        raise HTTPException(res.status_code, f"Shopify API error: {res.text[:500]}")
    data = res.json()
    if data.get("errors"):
        raise HTTPException(502, f"Shopify GraphQL errors: {json.dumps(data['errors'])[:500]}")
    return data.get("data", {})


async def dodo_create_checkout(org_id: str, plan: str) -> dict:
    sb = get_supabase_service()
    org = sb.table("organizations").select("name").eq("id", org_id).execute().data
    users = sb.table("users").select("email").eq("organization_id", org_id).limit(1).execute().data
    customer_email = users[0]["email"] if users else ""
    org_name = org[0]["name"] if org else "Customer"

    api_key = DODO_SECRET_KEY or DODO_TEST_API_KEY
    if not api_key:
        raise HTTPException(500, "DODO_SECRET_KEY not configured")
    is_test_mode = api_key.startswith("GFWIN") or bool(DODO_TEST_API_KEY and not DODO_SECRET_KEY)
    base_url = "https://test.dodopayments.com" if is_test_mode else "https://live.dodopayments.com"

    product_id = DODO_PRODUCTS.get(plan)
    if not product_id:
        raise HTTPException(400, f"Invalid plan: {plan}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/checkouts",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "product_cart": [{"product_id": product_id, "quantity": 1}],
                "customer": {"email": customer_email, "name": org_name},
                "return_url": f"{APP_URL}/dashboard?checkout=success&plan={plan}",
                "cancel_url": f"{APP_URL}/dashboard?checkout=cancelled",
                "metadata": {"organization_id": org_id, "plan": plan},
            },
        )
    if response.status_code not in (200, 201):
        raise HTTPException(response.status_code, f"Dodo checkout failed: {response.text[:500]}")
    return response.json()


@app.get("/health", tags=["Health"])
async def health():
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        supabase_anon="✓" if SUPABASE_ANON_KEY else "✗",
        supabase_service="✓" if SUPABASE_SERVICE_ROLE_KEY else "✗",
        dodo="✓" if DODO_SECRET_KEY or DODO_TEST_API_KEY else "✗",
        nvidia="✓" if NVIDIA_API_KEY else "✗",
    )


@app.get("/health/db", tags=["Health"])
async def health_db():
    sb = get_supabase_service()
    result = sb.table("organizations").select("id").limit(1).execute()
    return {"status": "ok", "tables_accessible": True, "count": len(result.data)}


@app.get("/debug/env", tags=["Debug"])
async def debug_env():
    return {
        "supabase_url": SUPABASE_URL or "✗",
        "supabase_anon_key": "✓" if SUPABASE_ANON_KEY else "✗",
        "supabase_service_role_key": "✓" if SUPABASE_SERVICE_ROLE_KEY else "✗",
        "nvidia_api_key": "✓" if NVIDIA_API_KEY else "✗",
        "dodo_secret_key": "✓" if DODO_SECRET_KEY else "✗",
        "dodo_test_api_key": "✓" if DODO_TEST_API_KEY else "✗",
        "dodo_webhook_secret": "✓" if DODO_WEBHOOK_SECRET else "✗",
        "shopify_app_url": "✓" if SHOPIFY_APP_URL else "✗",
        "shopify_client_id": "✓" if SHOPIFY_CLIENT_ID else "✗",
        "meta_app_id": "✓" if META_APP_ID else "✗",
    }


@app.post("/v1/organizations", tags=["Organizations"])
async def create_organization(body: OrganizationCreate):
    sb = get_supabase_service()
    existing = sb.table("users").select("id,organization_id").eq("email", body.email.lower().strip()).execute().data
    if existing:
        user = existing[0]
        org = sb.table("organizations").select("*").eq("id", user["organization_id"]).execute().data[0]
        return {"organization": org, "user": user, "existing": True}

    org_result = sb.table("organizations").insert({"name": body.name, "plan": "free"}).execute()
    if not org_result.data:
        raise HTTPException(500, "Failed to create organization")
    org = org_result.data[0]
    now = datetime.now(timezone.utc)

    try:
        user_result = sb.table("users").insert({
            "email": body.email.lower().strip(),
            "full_name": body.name,
            "organization_id": org["id"],
            "role": "owner",
        }).execute()
    except Exception as e:
        sb.table("organizations").delete().eq("id", org["id"]).execute()
        if "23505" in str(e):
            raise HTTPException(409, "An account with this email already exists")
        raise HTTPException(500, f"Failed to create user: {str(e)}")

    sb.table("subscriptions").insert({
        "organization_id": org["id"],
        "tier": "free",
        "status": "trialing",
        "ai_calls_limit": 30,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=14)).isoformat(),
    }).execute()

    return {"organization": org, "user": user_result.data[0] if user_result.data else None}


@app.post("/v1/organizations/from-auth", tags=["Organizations"])
async def create_org_from_auth(body: AuthOrgCreate):
    sb = get_supabase_service()
    existing = sb.table("users").select("organization_id").eq("id", body.user_id).execute().data
    if existing and existing[0].get("organization_id"):
        return {"organization_id": existing[0]["organization_id"]}

    org_result = sb.table("organizations").insert({"name": body.name, "plan": "free"}).execute()
    if not org_result.data:
        raise HTTPException(500, "Failed to create organization")
    org = org_result.data[0]
    now = datetime.now(timezone.utc)
    sb.table("users").upsert({
        "id": body.user_id,
        "email": body.email.lower().strip(),
        "full_name": body.name,
        "organization_id": org["id"],
        "role": "owner",
    }).execute()
    sb.table("subscriptions").insert({
        "organization_id": org["id"],
        "tier": "free",
        "status": "trialing",
        "ai_calls_limit": 15,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=14)).isoformat(),
    }).execute()
    return {"organization_id": org["id"]}


@app.get("/v1/organizations/me", tags=["Organizations"])
async def get_my_organization(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing authorization header")
    token = auth_header.replace("Bearer ", "")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(401, "Invalid token")
    user_data = resp.json()
    user_id = user_data["id"]
    sb = get_supabase_service()
    user_result = sb.table("users").select("*, organizations(*)").eq("id", user_id).execute()
    if not user_result.data:
        raise HTTPException(404, "User not found")
    user = user_result.data[0]
    return {"user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name")}, "organization": user.get("organizations")}


@app.post("/v1/billing/checkout", tags=["Billing"])
async def create_checkout(body: dict):
    org_id = body.get("organization_id")
    plan = body.get("plan", "starter")
    if not org_id:
        raise HTTPException(400, "organization_id required")
    data = await dodo_create_checkout(org_id, plan)
    return {"checkout_url": data.get("checkout_url"), "session_id": data.get("session_id"), "plan": plan}


@app.get("/v1/billing/plans", tags=["Billing"])
async def list_plans():
    return {"plans": [
        {"id": "free", "name": "Free Trial", "price_usd": 0, "ai_calls": 30, "description": "14-day free trial. No credit card required."},
        {"id": "starter", "name": "Starter", "price_usd": 29, "ai_calls": 30, "description": "30 AI calls/month.", "dodo_product_id": DODO_PRODUCTS["starter"]},
        {"id": "growth", "name": "Growth", "price_usd": 79, "ai_calls": 100, "description": "100 AI calls/month.", "dodo_product_id": DODO_PRODUCTS["growth"]},
        {"id": "scale", "name": "Scale", "price_usd": 199, "ai_calls": 500, "description": "500 AI calls/month.", "dodo_product_id": DODO_PRODUCTS["scale"]},
    ]}


@app.get("/v1/billing/portal", tags=["Billing"])
async def billing_portal(x_organization_id: str = Header(...)):
    sb = get_supabase_service()
    users = sb.table("users").select("email").eq("organization_id", x_organization_id).limit(1).execute().data
    customer_email = users[0]["email"] if users else ""
    return {"portal_url": f"https://app.dodopayments.com/customers/{customer_email}/subscriptions", "dashboard_url": "https://app.dodopayments.com/dashboard", "message": "Manage your subscription, update payment method, or cancel."}


@app.post("/v1/billing/activate-free", tags=["Billing"])
async def activate_free_credits(body: dict):
    org_id = body.get("organization_id")
    plan = body.get("plan", "growth")
    if not org_id:
        raise HTTPException(400, "organization_id required")
    now = datetime.now(timezone.utc)
    credits_map = {"starter": 5, "growth": 15, "scale": 30}
    ai_calls_limit = credits_map.get(plan, 15)
    sb = get_supabase_service()
    existing = sb.table("subscriptions").select("id").eq("organization_id", org_id).execute()
    payload = {
        "tier": plan,
        "status": "active",
        "ai_calls_limit": ai_calls_limit,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=365)).isoformat(),
    }
    if existing.data:
        sb.table("subscriptions").update(payload).eq("organization_id", org_id).execute()
    else:
        sb.table("subscriptions").insert({"organization_id": org_id, **payload}).execute()
    sb.table("billing_events").insert({"organization_id": org_id, "event_type": "free_credits_activated", "amount_cents": 0, "metadata": {"plan": plan, "credits": ai_calls_limit}}).execute()
    return {"success": True, "credits": ai_calls_limit, "plan": plan, "message": f"{ai_calls_limit} free AI credits activated!"}


@app.post("/v1/shopify/connect", tags=["Shopify"])
async def connect_shopify(request: Request, x_organization_id: str = Header(...)):
    body = await request.json()
    store_url = body.get("store_url", "").strip().replace("https://", "").replace("http://", "").rstrip("/")
    access_token = body.get("access_token", "").strip()
    if not store_url or not access_token:
        raise HTTPException(400, "store_url and access_token required")
    encrypted = base64.b64encode(access_token.encode()).decode()
    sb = get_supabase_service()
    sb.table("organizations").update({"shopify_store_url": store_url, "shopify_access_token_encrypted": encrypted}).eq("id", x_organization_id).execute()
    return {"success": True, "store_url": store_url}


@app.post("/v1/meta/connect", tags=["Meta"])
async def connect_meta(request: Request, x_organization_id: str = Header(...)):
    body = await request.json()
    access_token = body.get("access_token", "").strip()
    ad_account_id = body.get("ad_account_id", "").strip()
    if not access_token:
        raise HTTPException(400, "access_token required")
    encrypted = base64.b64encode(access_token.encode()).decode()
    update = {"meta_access_token_encrypted": encrypted}
    if ad_account_id:
        update["meta_ad_account_id"] = ad_account_id
    sb = get_supabase_service()
    sb.table("organizations").update(update).eq("id", x_organization_id).execute()
    return {"success": True, "ad_account_id": ad_account_id}


@app.get("/v1/meta/ad-insights", tags=["Meta"])
async def get_meta_insights(x_organization_id: str = Header(...)):
    sb = get_supabase_service()
    org = sb.table("organizations").select("*").eq("id", x_organization_id).execute().data
    if not org:
        raise HTTPException(404, "Organization not found")
    org_data = org[0]
    ad_account_id = org_data.get("meta_ad_account_id")
    token_enc = org_data.get("meta_access_token_encrypted")
    if not ad_account_id or not token_enc:
        raise HTTPException(400, "Meta not connected. Use /v1/meta/connect first.")
    access_token = base64.b64decode(token_enc).decode()
    fields = "impressions,clicks,spend,ctr,cpc,actions"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"https://graph.facebook.com/v19.0/{ad_account_id}/insights?fields={fields}&access_token={access_token}")
    if response.status_code != 200:
        raise HTTPException(502, f"Meta API error: {response.text}")
    data = response.json()
    return {"insights": data.get("data", []), "account_id": ad_account_id}


def parse_jsonish(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise


# NOTE: this assumes src/ai/nvidia_client.py provides NVIDIAAIClient, run_agent, parse_agent_json
# and that AGENT_PROMPTS already covers trend_hunter/store_builder/copywriter/ad_commander/supplier_scout/analytics_agent.

@app.post("/v1/research/trending", tags=["Product Research"])
async def research_trending_products(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    niche = body.get("niche", "")
    count = body.get("count", 5)
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = f"Find the top {count} dropshipping product opportunities"
    if niche:
        user_prompt += f" in the niche: {niche}"
    user_prompt += ". Focus on products that can launch in Q2 2026. Return 5 products."
    response = run_agent(ai, "trend_hunter", user_prompt, model="fast")
    products = parse_agent_json(response)
    inserted = []
    errors = []
    sb = get_supabase_service()
    for p in products.get("products", []):
        try:
            row = {
                "organization_id": org_id,
                "name": p.get("product_name") or p.get("name", "Unknown"),
                "category": p.get("niche", niche or "general"),
                "trend_score": int(p.get("trend_score", 0)),
                "competition_level": p.get("competition_level", "medium"),
                "sourcing_cost_estimate": float(p.get("sourcing_cost_estimate") or 0),
                "selling_price_estimate": float(p.get("recommended_price_usd") or 0),
                "supplier_count_estimate": int(p.get("supplier_count_estimate") or 0),
                "source_type": p.get("platform", "ai_research"),
                "notes": p.get("reason", ""),
            }
            result = sb.table("product_ideas").insert(row).execute()
            if result.data:
                inserted.append(row["name"])
        except Exception as e:
            errors.append(f"{p.get('product_name','unknown')}: {str(e)}")
    return {"products": products.get("products", []), "research_summary": products.get("research_summary", ""), "usage": response.usage, "inserted": inserted, "errors": errors}


@app.post("/v1/agents/store-builder", tags=["AI Agents"])
async def run_store_builder(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    niche = body.get("niche", "")
    products = body.get("products", [])
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = f"Design a dropshipping store"
    if niche:
        user_prompt += f" for niche: {niche}"
    if products:
        user_prompt += f". Top products: {', '.join(products[:3])}"
    response = run_agent(ai, "store_builder", user_prompt, model="fast")
    result = parse_agent_json(response)
    sb = get_supabase_service()
    sb.table("agent_tasks").insert({"organization_id": org_id, "task_type": "store_setup", "status": "completed", "input_payload": {"niche": niche, "products": products}, "output_payload": result, "model_used": "minimaxai/minimax-m2.5"}).execute()
    return {"store_blueprint": result, "usage": response.usage}


@app.post("/v1/agents/copywriter", tags=["AI Agents"])
async def run_copywriter(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    product_name = body.get("product_name", "")
    product_niche = body.get("product_niche", "")
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = f"Write copy for a dropshipping product: {product_name}"
    if product_niche:
        user_prompt += f" in the {product_niche} niche"
    user_prompt += ". Include product description, welcome email, and abandoned cart email."
    response = run_agent(ai, "copywriter", user_prompt, model="fast")
    result = parse_agent_json(response)
    sb = get_supabase_service()
    sb.table("agent_tasks").insert({"organization_id": org_id, "task_type": "copywriting", "status": "completed", "input_payload": {"product_name": product_name, "product_niche": product_niche}, "output_payload": result, "model_used": "minimaxai/minimax-m2.5"}).execute()
    return {"copy": result, "usage": response.usage}


@app.post("/v1/agents/ad-commander", tags=["AI Agents"])
async def run_ad_commander(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    product_name = body.get("product_name", "")
    target_audience = body.get("target_audience", "")
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = f"Create ad concepts for: {product_name}"
    if target_audience:
        user_prompt += f". Target audience: {target_audience}"
    user_prompt += ". Include Facebook ad copy and TikTok video concept."
    response = run_agent(ai, "ad_commander", user_prompt, model="fast")
    result = parse_agent_json(response)
    sb = get_supabase_service()
    sb.table("agent_tasks").insert({"organization_id": org_id, "task_type": "ad_creation", "status": "completed", "input_payload": {"product_name": product_name, "target_audience": target_audience}, "output_payload": result, "model_used": "minimaxai/minimax-m2.5"}).execute()
    return {"ads": result, "usage": response.usage}


@app.post("/v1/agents/supplier-scout", tags=["AI Agents"])
async def run_supplier_scout(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    product_name = body.get("product_name", "")
    target_price = body.get("target_price", "")
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = f"Find suppliers for: {product_name}"
    if target_price:
        user_prompt += f". Target cost under ${target_price}"
    user_prompt += ". Include vetting checklist and negotiation tips."
    response = run_agent(ai, "supplier_scout", user_prompt, model="fast")
    result = parse_agent_json(response)
    sb = get_supabase_service()
    sb.table("agent_tasks").insert({"organization_id": org_id, "task_type": "supplier_sourcing", "status": "completed", "input_payload": {"product_name": product_name, "target_price": target_price}, "output_payload": result, "model_used": "minimaxai/minimax-m2.5"}).execute()
    return {"suppliers": result, "usage": response.usage}


@app.post("/v1/agents/analytics", tags=["AI Agents"])
async def run_analytics_agent(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
    org_id = body.get("organization_id")
    store_url = body.get("store_url", "")
    metrics = body.get("metrics", {})
    if not org_id:
        raise HTTPException(400, "organization_id required")
    if not NVIDIA_API_KEY:
        raise HTTPException(500, "NVIDIA_API_KEY not configured")
    ai = NVIDIAAIClient(NVIDIA_API_KEY)
    user_prompt = "Analyze dropshipping store performance and suggest optimizations."
    if store_url:
        user_prompt += f" Store: {store_url}"
    if metrics:
        user_prompt += f" Current metrics: {json.dumps(metrics)}"
    response = run_agent(ai, "analytics_agent", user_prompt, model="fast")
    result = parse_agent_json(response)
    sb = get_supabase_service()
    sb.table("agent_tasks").insert({"organization_id": org_id, "task_type": "analytics_review", "status": "completed", "input_payload": {"store_url": store_url, "metrics": metrics}, "output_payload": result, "model_used": "minimaxai/minimax-m2.5"}).execute()
    return {"analytics": result, "usage": response.usage}


@app.post("/v1/shopify/build-store", tags=["Shopify"])
async def build_shopify_store(body: dict):
    """
    Real Shopify build step:
    - create product(s)
    - create pages
    - create collection
    - upload image assets (logo/hero)
    - publish collection/product when possible
    """
    org_id = body.get("organization_id")
    if not org_id:
        raise HTTPException(400, "organization_id required")

    sb = get_supabase_service()
    orgs = sb.table("organizations").select("*").eq("id", org_id).execute().data
    if not orgs:
        raise HTTPException(404, "Organization not found")
    org = orgs[0]
    store_url = org.get("shopify_store_url")
    token_enc = org.get("shopify_access_token_encrypted")
    if not store_url or not token_enc:
        raise HTTPException(400, "Shopify not connected. Connect your store first.")
    token = base64.b64decode(token_enc).decode()

    blueprint = body.get("blueprint") or {}
    products = body.get("products") or []
    if not products:
        raise HTTPException(400, "products required")

    created = {"products": [], "pages": [], "collections": [], "files": []}

    # Create logo file if provided as a URL (optional)
    logo_url = blueprint.get("logo_url")
    if logo_url:
        q = """
        mutation FileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files { id fileStatus }
            userErrors { field message }
          }
        }
        """
        data = await shopify_graphql(store_url, token, q, {"files": [{"originalSource": logo_url, "contentType": "IMAGE", "alt": blueprint.get("store_name", "Storewright logo")} ]})
        created["files"] = data.get("fileCreate", {}).get("files", [])

    # Create pages
    pages = blueprint.get("pages") or [
        {"title": "About Us", "handle": "about-us", "body": "<p>About us content.</p>"},
        {"title": "Contact", "handle": "contact", "body": "<p>Contact us content.</p>"},
        {"title": "Shipping Policy", "handle": "shipping-policy", "body": "<p>Shipping policy content.</p>"},
        {"title": "Refund Policy", "handle": "refund-policy", "body": "<p>Refund policy content.</p>"},
    ]
    page_mutation = """
    mutation PageCreate($page: PageCreateInput!) {
      pageCreate(page: $page) {
        page { id title handle }
        userErrors { field message }
      }
    }
    """
    for page in pages:
        data = await shopify_graphql(store_url, token, page_mutation, {"page": {"title": page["title"], "handle": page["handle"], "body": page["body"], "isPublished": True}})
        page_res = data.get("pageCreate", {})
        created["pages"].append(page_res)

    # Create collection
    collection_title = blueprint.get("collection_title") or f"{blueprint.get('store_name', 'Store')} Collection"
    collection_mutation = """
    mutation CollectionCreate($input: CollectionInput!) {
      collectionCreate(input: $input) {
        collection { id title handle }
        userErrors { field message }
      }
    }
    """
    cdata = await shopify_graphql(store_url, token, collection_mutation, {"input": {"title": collection_title, "descriptionHtml": blueprint.get("store_description", ""), "handle": blueprint.get("store_handle", "main-collection")}})
    created["collections"].append(cdata.get("collectionCreate", {}))

    # Create products
    product_mutation = """
    mutation ProductCreate($product: ProductCreateInput!) {
      productCreate(product: $product) {
        product { id title handle status }
        userErrors { field message }
      }
    }
    """
    for p in products:
        title = p.get("product_name") or p.get("name")
        desc = p.get("product_description") or p.get("reason") or ""
        price = str(p.get("recommended_price_usd") or 29.99)
        pdata = {
            "title": title,
            "descriptionHtml": f"<p>{desc}</p>",
            "vendor": blueprint.get("store_name", "Storewright"),
            "status": "DRAFT",
            "productOptions": [{"name": "Default Title", "values": [{"name": "Default Title"}]}],
            "variants": [{"price": price, "optionValues": [{"name": "Default Title", "optionName": "Title"}]}],
        }
        data = await shopify_graphql(store_url, token, product_mutation, {"product": pdata})
        created["products"].append(data.get("productCreate", {}))

    # Publish collection and products to online store if possible
    publish_mutation = """
    mutation PublishablePublish($id: ID!, $input: [PublicationInput!]!) {
      publishablePublish(id: $id, input: $input) {
        publishable { __typename }
        userErrors { field message }
      }
    }
    """

    # Try to find an online store publication
    pubs_query = """
    query Publications {
      publications(first: 10) { nodes { id name } }
    }
    """
    pubs = await shopify_graphql(store_url, token, pubs_query, {})
    publication_id = None
    for node in pubs.get("publications", {}).get("nodes", []):
        if "online" in node.get("name", "").lower() or "store" in node.get("name", "").lower():
            publication_id = node["id"]
            break

    if publication_id and created["collections"]:
        collection_obj = created["collections"][0].get("collection")
        if collection_obj:
            await shopify_graphql(store_url, token, publish_mutation, {"id": collection_obj["id"], "input": [{"publicationId": publication_id}]})
    
    return {"success": True, "created": created}


@app.post("/webhooks/dodo", tags=["Webhooks"])
async def dodo_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("dodo-signature", "")
    if DODO_WEBHOOK_SECRET:
        expected = hmac.new(DODO_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "Invalid webhook signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    event_type = event.get("type", "")
    sb = get_supabase_service()
    if event_type == "payment_succeeded":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            sb.table("billing_events").insert({"organization_id": org_id, "event_type": "payment_succeeded", "dodo_event_id": event.get("id"), "amount_cents": event.get("amount", {}).get("cents"), "currency": event.get("amount", {}).get("currency", "USD"), "metadata": event}).execute()
    elif event_type == "subscription_created":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            sb.table("subscriptions").update({"external_subscription_id": event.get("subscription_id"), "status": "active"}).eq("organization_id", org_id).execute()
    elif event_type == "subscription_cancelled":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            sb.table("subscriptions").update({"status": "cancelled"}).eq("organization_id", org_id).execute()
    return {"received": True}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)[:200]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
