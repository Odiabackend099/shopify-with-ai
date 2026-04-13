"""
Shopify with AI — FastAPI Backend
Deployed on Render (Free Tier)
"""

import os
import hmac
import hashlib
import json
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ============================================
# CONFIG — reads from environment variables
# ============================================
class Settings(BaseSettings):
    nvidia_api_key: str = ""
    supabase_url: str = "https://ykyemuahvxshtsrkhsfo.supabase.co"  # CORRECTED
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    dodo_public_key: str = ""
    dodo_secret_key: str = ""
    dodo_webhook_secret: str = ""
    app_secret: str = "dev-secret-change-in-production"
    app_url: str = "https://shopifywithai.odia.dev"

    class Config:
        extra = "allow"

settings = Settings()

# ============================================
# SUPABASE CLIENTS
# ============================================
def get_supabase_service() -> Client:
    """Service-role client — bypasses RLS. Server-side only, never expose."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

def get_supabase_anon() -> Client:
    """Anon client — respects RLS. For user-facing endpoints."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)

# ============================================
# LIFESPAN
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[shopify-with-ai] Starting — {datetime.now(timezone.utc)}")
    print(f"  Supabase : {settings.supabase_url}")
    print(f"  Dodo     : {'✓' if settings.dodo_secret_key else '✗ missing'}")
    print(f"  NVIDIA   : {'✓' if settings.nvidia_api_key else '✗ missing'}")
    yield
    print(f"[shopify-with-ai] Shutdown")

# ============================================
# APP
# ============================================
app = FastAPI(
    title="Shopify with AI API",
    description="AI-powered dropshipping automation platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shopifywithai.odia.dev",
        "https://www.shopifywithai.odia.dev",
        "https://vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# MODELS
# ============================================
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    supabase: str
    dodo: str
    nvidia: str

class OrganizationCreate(BaseModel):
    name: str
    email: EmailStr

class AgentTaskRequest(BaseModel):
    task_type: str  # product_research | store_setup | ad_creation | copywriting | supplier_sourcing | analytics_review
    input_payload: dict
    priority: int = Field(default=5, ge=1, le=10)

# ============================================
# HEALTH
# ============================================
@app.get("/health", tags=["Health"])
async def health():
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        supabase="✓" if settings.supabase_service_role_key else "✗",
        dodo="✓" if settings.dodo_secret_key else "✗",
        nvidia="✓" if settings.nvidia_api_key else "✗",
    )

# ============================================
# ORGANIZATIONS
# ============================================
@app.post("/v1/organizations", tags=["Organizations"])
async def create_organization(body: OrganizationCreate):
    supabase = get_supabase_service()

    org_result = supabase.table("organizations").insert({"name": body.name, "plan": "free"}).execute()
    if not org_result.data:
        raise HTTPException(status_code=500, detail="Failed to create organization")
    org = org_result.data[0]

    user_result = supabase.table("users").insert({
        "email": str(body.email),
        "full_name": body.name,
        "organization_id": org["id"],
        "role": "owner",
    }).execute()

    now = datetime.now(timezone.utc)
    supabase.table("subscriptions").insert({
        "organization_id": org["id"],
        "tier": "free",
        "status": "trialing",
        "ai_calls_limit": 30,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=14)).isoformat(),
    }).execute()

    return {"organization": org, "user": user_result.data[0] if user_result.data else None}

@app.get("/v1/organizations/{org_id}", tags=["Organizations"])
async def get_organization(org_id: str, x_organization_id: str = Header(...)):
    if org_id != x_organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    result = get_supabase_service().table("organizations").select("*").eq("id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Not found")
    return result.data[0]

# ============================================
# AI AGENT TASKS
# ============================================
@app.post("/v1/tasks", tags=["AI Agents"])
async def create_agent_task(body: AgentTaskRequest):
    supabase = get_supabase_service()
    org_id = body.input_payload.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="organization_id required in input_payload")

    task_data = {
        "organization_id": org_id,
        "task_type": body.task_type,
        "priority": body.priority,
        "input_payload": body.input_payload,
        "status": "queued",
        "model_used": "minimaxai/minimax-m2.5",
    }
    result = supabase.table("agent_tasks").insert(task_data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to queue task")

    task = result.data[0]
    return {"task_id": task["id"], "status": "queued"}

@app.get("/v1/tasks/{task_id}", tags=["AI Agents"])
async def get_task(task_id: str):
    result = get_supabase_service().table("agent_tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
    task = result.data[0]
    return {
        "task_id": task["id"],
        "status": task["status"],
        "output": task.get("output_payload"),
        "error": task.get("error_message"),
    }

@app.get("/v1/organizations/{org_id}/tasks", tags=["AI Agents"])
async def list_organization_tasks(org_id: str, status: Optional[str] = None, limit: int = 20):
    query = get_supabase_service().table("agent_tasks").select("*").eq("organization_id", org_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return {"tasks": result.data, "count": len(result.data)}

# ============================================
# PRODUCT RESEARCH
# ============================================
@app.post("/v1/research/trending", tags=["Product Research"])
async def research_trending_products(body: dict):
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json

    org_id = body.get("organization_id")
    niche = body.get("niche", "")
    count = body.get("count", 5)

    if not org_id:
        raise HTTPException(status_code=400, detail="organization_id required")
    if not settings.nvidia_api_key:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY not configured")

    ai = NVIDIAAIClient(settings.nvidia_api_key)
    user_prompt = f"Find top {count} dropshipping product opportunities"
    if niche:
        user_prompt += f" in niche: {niche}"
    user_prompt += ". Focus on Q2 2026 trends. Return exactly 5 products."

    response = run_agent(ai, "trend_hunter", user_prompt, model="fast")
    products = parse_agent_json(response)

    supabase = get_supabase_service()
    for p in products.get("products", []):
        p["organization_id"] = org_id
        p["source_type"] = "ai_research"
        supabase.table("product_ideas").insert(p).execute()

    return {
        "products": products.get("products", []),
        "research_summary": products.get("research_summary", ""),
        "usage": response.usage,
    }

# ============================================
# DODO PAYMENTS WEBHOOK
# ============================================
def verify_dodo_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify Dodo Payments webhook HMAC-SHA256 signature."""
    if not signature or not secret:
        return False
    try:
        timestamp, _, sig = signature.partition(",")
        if sig.startswith("v1="):
            expected = hmac.new(
                secret.encode(),
                body + timestamp.encode(),
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, sig[3:])
    except Exception:
        return False
    return False

@app.post("/webhooks/dodo", tags=["Webhooks"])
async def dodo_webhook(request: Request):
    """
    Dodo Payments webhook receiver.
    Validates signature and processes payment events idempotently.
    """
    body = await request.body()
    signature = request.headers.get("dodo-signature", "")

    # Verify signature in production
    if settings.dodo_webhook_secret and not verify_dodo_signature(body, signature, settings.dodo_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    metadata = event.get("metadata", {})
    org_id = metadata.get("organization_id")
    supabase = get_supabase_service()

    # Idempotency: skip if already processed
    if event.get("id"):
        existing = supabase.table("billing_events").select("id").eq("dodo_event_id", event["id"]).execute()
        if existing.data:
            return {"received": True, "skipped": "already_processed"}

    if event_type == "payment_succeeded":
        if org_id:
            supabase.table("billing_events").insert({
                "organization_id": org_id,
                "event_type": "payment_succeeded",
                "dodo_event_id": event.get("id"),
                "amount_cents": event.get("amount", {}).get("cents"),
                "currency": event.get("amount", {}).get("currency", "USD"),
                "metadata": event,
            }).execute()

            # Credit the organization's AI calls
            amount = event.get("amount", {}).get("cents", 0)
            extra_calls = (amount // 100) * 10  # $1 = 10 calls
            if extra_calls > 0:
                org = supabase.table("organizations").select("ai_calls_used,ai_calls_limit").eq("id", org_id).execute()
                if org.data:
                    current = org.data[0]
                    supabase.table("organizations").update({
                        "ai_calls_limit": current.get("ai_calls_limit", 0) + extra_calls,
                    }).eq("id", org_id).execute()

    elif event_type == "subscription_created":
        if org_id:
            supabase.table("subscriptions").update({
                "external_subscription_id": event.get("subscription_id"),
                "status": "active",
            }).eq("organization_id", org_id).execute()

    elif event_type == "subscription_cancelled":
        if org_id:
            supabase.table("subscriptions").update({"status": "cancelled"}).eq("organization_id", org_id).execute()

    elif event_type == "payment_failed":
        if org_id:
            supabase.table("billing_events").insert({
                "organization_id": org_id,
                "event_type": "payment_failed",
                "dodo_event_id": event.get("id"),
                "metadata": event,
            }).execute()

    return {"received": True}

# ============================================
# SHOPIFY OAUTH
# ============================================
@app.get("/v1/shopify/auth", tags=["Shopify"])
async def shopify_auth(shop: str):
    """Initiate Shopify OAuth flow."""
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "")
    redirect_uri = f"{settings.app_url}/v1/shopify/callback"
    auth_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope=read_orders,write_orders,read_products,write_products"
        f"&redirect_uri={redirect_uri}"
    )
    return {"auth_url": auth_url}

# ============================================
# ERROR HANDLER
# ============================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
