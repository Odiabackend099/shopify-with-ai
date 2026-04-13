"""
Shopify with AI — FastAPI Backend
Main entry point for the Render-deployed API
"""

import os
import sys
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from supabase import create_client, Client
from dotenv import load_dotenv

# Load .env for local dev
load_dotenv()

# ============================================
# CONFIG
# ============================================
class Settings(BaseSettings):
    nvidia_api_key: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_url: str = "https://ykxemuauhxsktrkhsfo.supabase.co"
    dodo_public_key: str = ""
    dodo_secret_key: str = ""
    app_secret: str = "dev-secret-change-me"
    app_url: str = "https://shopifywithai.odia.dev"
    render_deploy: bool = False

    class Config:
        env_file = "infrastructure/.env"
        extra = "allow"

settings = Settings()

# ============================================
# SUPABASE CLIENT
# ============================================
def get_supabase_service() -> Client:
    """Service-role client (bypasses RLS) — server-side only."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )

def get_supabase_anon() -> Client:
    """Anon client (respects RLS) — for user-facing endpoints."""
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
    )

# ============================================
# LIFESPAN
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Shopify with AI] Starting up — {datetime.now(timezone.utc)}")
    print(f"[Config] Supabase: {settings.supabase_url}")
    print(f"[Config] Dodo: {'✓ configured' if settings.dodo_secret_key else '✗ missing'}")
    yield
    print(f"[Shopify with AI] Shutting down")

# ============================================
# APP
# ============================================
app = FastAPI(
    title="Shopify with AI API",
    description="AI-powered dropshipping automation platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shopifywithai.odia.dev",
        "https://www.shopifywithai.odia.dev",
        "https://vercel.app",
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
    model: str = "fast"  # fast | research | backup

class AgentTaskResponse(BaseModel):
    task_id: str
    status: str
    output: Optional[dict] = None
    error: Optional[str] = None

# ============================================
# HEALTH
# ============================================
@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint for Render."""
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
    """Create a new organization (and first user)."""
    supabase = get_supabase_service()

    # Create organization
    org_data = {
        "name": body.name,
        "plan": "free",
    }
    org_result = supabase.table("organizations").insert(org_data).execute()

    if not org_result.data:
        raise HTTPException(status_code=500, detail="Failed to create organization")

    org = org_result.data[0]

    # Create user
    user_data = {
        "email": str(body.email),
        "full_name": body.name,
        "organization_id": org["id"],
        "role": "owner",
    }
    user_result = supabase.table("users").insert(user_data).execute()

    # Create free subscription
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    sub_data = {
        "organization_id": org["id"],
        "tier": "free",
        "status": "trialing",
        "ai_calls_limit": 30,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=14)).isoformat(),
    }
    supabase.table("subscriptions").insert(sub_data).execute()

    return {"organization": org, "user": user_result.data[0] if user_result.data else None}


@app.get("/v1/organizations/{org_id}", tags=["Organizations"])
async def get_organization(org_id: str, x_organization_id: str = Header(...)):
    if org_id != x_organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    supabase = get_supabase_service()
    result = supabase.table("organizations").select("*").eq("id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result.data[0]

# ============================================
# AI AGENT TASKS
# ============================================
@app.post("/v1/tasks", response_model=AgentTaskResponse, tags=["AI Agents"])
async def create_agent_task(body: AgentTaskRequest):
    """Queue an AI agent task for processing."""
    supabase = get_supabase_service()

    # Validate org_id is provided in input_payload
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

    # If on render (not local), trigger background worker via internal hook
    # The worker polls for queued tasks, so just return the task_id
    return AgentTaskResponse(
        task_id=task["id"],
        status="queued",
        output=None,
        error=None,
    )


@app.get("/v1/tasks/{task_id}", tags=["AI Agents"])
async def get_task(task_id: str):
    """Get task status and output."""
    supabase = get_supabase_service()
    result = supabase.table("agent_tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
    task = result.data[0]
    return AgentTaskResponse(
        task_id=task["id"],
        status=task["status"],
        output=task.get("output_payload"),
        error=task.get("error_message"),
    )


@app.get("/v1/organizations/{org_id}/tasks", tags=["AI Agents"])
async def list_organization_tasks(org_id: str, status: Optional[str] = None, limit: int = 20):
    """List tasks for an organization."""
    supabase = get_supabase_service()
    query = supabase.table("agent_tasks").select("*").eq("organization_id", org_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return {"tasks": result.data, "count": len(result.data)}

# ============================================
# PRODUCT RESEARCH
# ============================================
@app.post("/v1/research/trending", tags=["Product Research"])
async def research_trending_products(body: dict):
    """
    Run product trend research.
    Body: { "organization_id": "...", "niche": "optional niche", "count": 5 }
    """
    from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json

    org_id = body.get("organization_id")
    niche = body.get("niche", "")
    count = body.get("count", 5)

    if not org_id:
        raise HTTPException(status_code=400, detail="organization_id required")

    if not settings.nvidia_api_key:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY not configured")

    ai = NVIDIAAIClient(settings.nvidia_api_key)

    user_prompt = f"Find the top {count} dropshipping product opportunities"
    if niche:
        user_prompt += f" in the niche: {niche}"
    user_prompt += ". Focus on products that can launch in Q2 2026. Return 5 products."

    response = run_agent(ai, "trend_hunter", user_prompt, model="fast")
    products = parse_agent_json(response)

    # Save to product_ideas table
    supabase = get_supabase_service()
    for p in products.get("products", []):
        p["organization_id"] = org_id
        p["source_type"] = "ai_research"
        p["agent_task_id"] = None
        supabase.table("product_ideas").insert(p).execute()

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
    """
    Receive Dodo Payments webhooks.
    Validate signature and process events.
    """
    body = await request.body()
    signature = request.headers.get("dodo-signature", "")

    # TODO: Validate Dodo webhook signature
    # if not validate_dodo_signature(body, signature, settings.dodo_webhook_secret):
    #     raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    supabase = get_supabase_service()

    if event_type == "payment_succeeded":
        # Credit user account
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            supabase.table("billing_events").insert({
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
            supabase.table("subscriptions").update({
                "external_subscription_id": event.get("subscription_id"),
                "status": "active",
            }).eq("organization_id", org_id).execute()

    elif event_type == "subscription_cancelled":
        org_id = event.get("metadata", {}).get("organization_id")
        if org_id:
            supabase.table("subscriptions").update({
                "status": "cancelled",
            }).eq("organization_id", org_id).execute()

    return {"received": True}


# ============================================
# SHOPIFY OAUTH
# ============================================
@app.get("/v1/shopify/auth", tags=["Shopify"])
async def shopify_auth(shop: str):
    """
    Initiate Shopify OAuth flow.
    Redirects to Shopify to request store access.
    """
    if not settings.app_url:
        raise HTTPException(status_code=500, detail="APP_URL not configured")

    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "")
    redirect_uri = f"{settings.app_url}/v1/shopify/callback"

    auth_url = (
        f"https://partner.account.shopify.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope=read_orders,write_orders,read_products,write_products,read_fulfillments"
        f"&redirect_uri={redirect_uri}"
        f"&state={shop}"
    )
    return {"auth_url": auth_url}


@app.post("/v1/shopify/disconnect", tags=["Shopify"])
async def shopify_disconnect(x_organization_id: str = Header(...)):
    """Disconnect Shopify store from organization."""
    supabase = get_supabase_service()
    supabase.table("organizations").update({
        "shopify_store_url": None,
        "shopify_access_token_encrypted": None,
    }).eq("id", x_organization_id).execute()
    return {"success": True}


# ============================================
# ERROR HANDLERS
# ============================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

# ============================================
# RUN LOCALLY
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)