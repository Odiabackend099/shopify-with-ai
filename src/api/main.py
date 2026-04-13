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

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client

# ============================================
# CONFIG — Supabase standard env var names
# SUPABASE_URL        : https://<project>.supabase.co
# SUPABASE_ANON_KEY  : eyJhbGci... (safe for browser)
# SUPABASE_SERVICE_ROLE_KEY : eyJhbGci... (server only, bypasses RLS)
# ============================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# Legacy aliases for other naming conventions
if not SUPABASE_SERVICE_ROLE_KEY:
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE", "")
if not SUPABASE_SERVICE_ROLE_KEY:
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_ANON_KEY:
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON", "")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
DODO_SECRET_KEY = os.environ.get("DODO_SECRET_KEY", "")
DODO_PUBLIC_KEY = os.environ.get("DODO_PUBLIC_KEY", "")
DODO_WEBHOOK_SECRET = os.environ.get("DODO_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://shopifywithai.odia.dev")

# ============================================
# SUPABASE CLIENTS
# ============================================
def get_supabase_service() -> Client:
    """Service-role client — bypasses RLS. Server-side only."""
    key = SUPABASE_SERVICE_ROLE_KEY
    if not key:
        raise HTTPException(500, "SUPABASE_SERVICE_ROLE_KEY is required")
    return create_client(SUPABASE_URL, key)

def get_supabase_anon() -> Client:
    """Anon client — respects RLS. For user-facing endpoints."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ============================================
# LIFESPAN
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[shopify-with-ai] Starting — {datetime.now(timezone.utc)}")
    print(f"  Supabase : {SUPABASE_URL}")
    print(f"  Dodo     : {'✓' if DODO_SECRET_KEY else '✗ missing'}")
    print(f"  NVIDIA   : {'✓' if NVIDIA_API_KEY else '✗ missing'}")
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
        "https://*.vercel.app",
        "http://localhost:3000",
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
    supabase_anon: str
    supabase_service: str
    dodo: str
    nvidia: str

class OrganizationCreate(BaseModel):
    name: str
    email: str  # plain str — EmailStr requires email-validator

# ============================================
# HEALTH
# ============================================
@app.get("/health", tags=["Health"])
async def health():
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        supabase_anon="✓" if SUPABASE_ANON_KEY else "✗",
        supabase_service="✓" if SUPABASE_SERVICE_ROLE_KEY else "✗",
        dodo="✓" if DODO_SECRET_KEY else "✗",
        nvidia="✓" if NVIDIA_API_KEY else "✗",
    )

@app.get("/health/db", tags=["Health"])
async def health_db():
    """Direct DB health check — verifies credentials work."""
    try:
        sb = get_supabase_service()
        result = sb.table("organizations").select("id").limit(1).execute()
        return {"status": "ok", "tables_accessible": True, "count": len(result.data)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}

# ============================================
# DEBUG (dev only — remove in production)
# ============================================
@app.get("/debug/env", tags=["Debug"])
async def debug_env():
    """Show which env vars are set (values redacted)."""
    return {
        "supabase_url": SUPABASE_URL or "✗",
        "supabase_anon_key": "✓" if SUPABASE_ANON_KEY else "✗",
        "supabase_service_role_key": "✓" if SUPABASE_SERVICE_ROLE_KEY else "✗",
        "nvidia_api_key": "✓" if NVIDIA_API_KEY else "✗",
        "dodo_secret_key": "✓" if DODO_SECRET_KEY else "✗",
        "dodo_public_key": "✓" if DODO_PUBLIC_KEY else "✗",
        "dodo_webhook_secret": "✓" if DODO_WEBHOOK_SECRET else "✗",
    }

# ============================================
# ORGANIZATIONS
# ============================================
@app.post("/v1/organizations", tags=["Organizations"])
async def create_organization(body: OrganizationCreate):
    sb = get_supabase_service()

    org_result = sb.table("organizations").insert({"name": body.name, "plan": "free"}).execute()
    if not org_result.data:
        raise HTTPException(500, "Failed to create organization")

    org = org_result.data[0]
    now = datetime.now(timezone.utc)

    # Create user
    sb.table("users").insert({
        "email": body.email,
        "full_name": body.name,
        "organization_id": org["id"],
        "role": "owner",
    }).execute()

    # Create free trial subscription
    sb.table("subscriptions").insert({
        "organization_id": org["id"],
        "tier": "free",
        "status": "trialing",
        "ai_calls_limit": 30,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=14)).isoformat(),
    }).execute()

    return {"organization": org}

@app.get("/v1/organizations/{org_id}", tags=["Organizations"])
async def get_organization(org_id: str, x_organization_id: str = Header(...)):
    if org_id != x_organization_id:
        raise HTTPException(403, "Access denied")
    result = get_supabase_service().table("organizations").select("*").eq("id", org_id).execute()
    if not result.data:
        raise HTTPException(404, "Organization not found")
    return result.data[0]

# ============================================
# AI AGENT TASKS
# ============================================
class AgentTaskRequest(BaseModel):
    task_type: str
    input_payload: dict
    priority: int = Field(default=5, ge=1, le=10)

@app.post("/v1/tasks", tags=["AI Agents"])
async def create_agent_task(body: AgentTaskRequest):
    sb = get_supabase_service()
    org_id = body.input_payload.get("organization_id")
    if not org_id:
        raise HTTPException(400, "organization_id required in input_payload")

    task_data = {
        "organization_id": org_id,
        "task_type": body.task_type,
        "priority": body.priority,
        "input_payload": body.input_payload,
        "status": "queued",
        "model_used": "minimaxai/minimax-m2.5",
    }
    result = sb.table("agent_tasks").insert(task_data).execute()
    if not result.data:
        raise HTTPException(500, "Failed to queue task")
    task = result.data[0]
    return {"task_id": task["id"], "status": "queued"}

@app.get("/v1/tasks/{task_id}", tags=["AI Agents"])
async def get_task(task_id: str):
    result = get_supabase_service().table("agent_tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(404, "Task not found")
    task = result.data[0]
    return {
        "task_id": task["id"],
        "status": task["status"],
        "output": task.get("output_payload"),
        "error": task.get("error_message"),
    }

@app.get("/v1/organizations/{org_id}/tasks", tags=["AI Agents"])
async def list_organization_tasks(org_id: str, status: Optional[str] = None, limit: int = 20):
    sb = get_supabase_service()
    query = sb.table("agent_tasks").select("*").eq("organization_id", org_id)
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

    # Save to product_ideas table
    sb = get_supabase_service()
    for p in products.get("products", []):
        p["organization_id"] = org_id
        p["source_type"] = "ai_research"
        sb.table("product_ideas").insert(p).execute()

    return {
        "products": products.get("products", []),
        "research_summary": products.get("research_summary", ""),
        "usage": response.usage,
    }

# ============================================
# DOODO PAYMENTS WEBHOOK
# ============================================
@app.post("/webhooks/dodo", tags=["Webhooks"])
async def dodo_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("dodo-signature", "")

    if DODO_WEBHOOK_SECRET:
        import hmac
        expected = hmac.new(
            DODO_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
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
            sb.table("billing_events").insert({
                "organization_id": org_id,
                "event_type": "payment_succeeded",
                "dodo_event_id": event.get("id"),
                "amount_cents": event.get("amount", {}).get("cents"),
                "currency": event.get("amount", {}).get("currency", "USD"),
                "metadata": event,
            }).execute()

    elif event_type == "subscription_created":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            sb.table("subscriptions").update({
                "external_subscription_id": event.get("subscription_id"),
                "status": "active",
            }).eq("organization_id", org_id).execute()

    elif event_type == "subscription_cancelled":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            sb.table("subscriptions").update({"status": "cancelled"}).eq("organization_id", org_id).execute()

    return {"received": True}

# ============================================
# ERROR HANDLER
# ============================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)[:200]})

# ============================================
# RUN LOCALLY
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
