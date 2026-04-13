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
from pydantic_settings import BaseSettings
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    nvidia_api_key: str = Field(default="", validation_alias="NVIDIA_API_KEY")
    supabase_url: str = Field(default="https://ykyemuahvxshtsrkhsfo.supabase.co", validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", validation_alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(default="", validation_alias="SUPABASE_SERVICE_ROLE")
    dodo_public_key: str = Field(default="", validation_alias="DODO_PAYMENTS_TEST_API_KEY")
    dodo_secret_key: str = Field(default="", validation_alias="DODO_PAYMENTS_TEST_API_KEY")
    dodo_webhook_secret: str = Field(default="", validation_alias="DODO_WEBHOOK_SECRET")
    app_secret: str = Field(default="dev-secret", validation_alias="APP_SECRET")
    app_url: str = Field(default="https://shopifywithai.odia.dev", validation_alias="APP_URL")

    class Config:
        extra = "allow"


settings = Settings()


def get_supabase_service() -> Client:
    """Service-role client — bypasses RLS. Server-side only."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_supabase_anon() -> Client:
    """Anon client — respects RLS."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[shopify-with-ai] Starting — {datetime.now(timezone.utc)}")
    print(f"  Supabase : {settings.supabase_url}")
    print(f"  NVIDIA   : {'✓' if settings.nvidia_api_key else '✗ missing'}")
    print(f"  Dodo     : {'✓' if settings.dodo_secret_key else '✗ missing'}")
    yield
    print(f"[shopify-with-ai] Shutdown")


app = FastAPI(
    title="Shopify with AI API",
    description="AI-powered dropshipping automation platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Models ----
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    supabase: str
    dodo: str
    nvidia: str


class OrganizationCreate(BaseModel):
    name: str
    email: str


class AgentTaskRequest(BaseModel):
    task_type: str
    input_payload: dict
    priority: int = Field(default=5, ge=1, le=10)


# ---- Health ----
@app.get("/health", tags=["Health"])
async def health():
    """Health check — no DB calls, instant response."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        supabase="✓" if settings.supabase_service_role_key else "✗ missing",
        dodo="✓" if settings.dodo_secret_key else "✗ missing",
        nvidia="✓" if settings.nvidia_api_key else "✗ missing",
    )


@app.get("/health/db", tags=["Health"])
async def health_db():
    """Health check that also verifies Supabase connection."""
    supabase_ok = "✗"
    if settings.supabase_service_role_key:
        try:
            supabase = get_supabase_service()
            result = supabase.table("organizations").select("id").limit(1).execute()
            supabase_ok = f"✓ ({len(result.data)} rows)"
        except Exception as e:
            supabase_ok = f"✗ {type(e).__name__}: {str(e)[:100]}"

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "supabase": supabase_ok,
        "dodo": "✓" if settings.dodo_secret_key else "✗ missing",
        "nvidia": "✓" if settings.nvidia_api_key else "✗ missing",
    }


@app.get("/debug/env", tags=["Debug"])
async def debug_env():
    """Show which env vars are set (values redacted)."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": "✓" if settings.supabase_anon_key else "✗",
        "supabase_service_role_key": "✓" if settings.supabase_service_role_key else "✗",
        "nvidia_api_key": "✓" if settings.nvidia_api_key else "✗",
        "dodo_secret_key": "✓" if settings.dodo_secret_key else "✗",
        "dodo_public_key": "✓" if settings.dodo_public_key else "✗",
        "dodo_webhook_secret": "✓" if settings.dodo_webhook_secret else "✗",
    }


# ---- Organizations ----
@app.post("/v1/organizations", tags=["Organizations"])
async def create_organization(body: OrganizationCreate):
    supabase = get_supabase_service()
    org_result = supabase.table("organizations").insert({"name": body.name, "plan": "free"}).execute()
    if not org_result.data:
        raise HTTPException(status_code=500, detail="Failed to create organization")

    org = org_result.data[0]
    now = datetime.now(timezone.utc)
    supabase.table("subscriptions").insert({
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
        raise HTTPException(status_code=403, detail="Access denied")
    result = get_supabase_service().table("organizations").select("*").eq("id", org_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result.data[0]


# ---- AI Agent Tasks ----
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
    return {"task_id": result.data[0]["id"], "status": "queued"}


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


# ---- Webhooks ----
@app.post("/webhooks/dodo", tags=["Webhooks"])
async def dodo_webhook(request: Request):
    """Receive Dodo Payments webhooks."""
    body = await request.body()
    sig = request.headers.get("dodo-signature", "")

    if settings.dodo_webhook_secret and sig:
        expected = hmac.new(
            settings.dodo_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(f"sha256={expected}", sig):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    supabase = get_supabase_service()
    event_type = event.get("type", "")
    org_id = event.get("metadata", {}).get("organization_id")

    if event.get("id"):
        existing = supabase.table("billing_events").select("id").eq("dodo_event_id", event["id"]).execute()
        if existing.data:
            return {"received": True, "skipped": "already_processed"}

    if event_type == "payment_succeeded" and org_id:
        supabase.table("billing_events").insert({
            "organization_id": org_id,
            "event_type": "payment_succeeded",
            "dodo_event_id": event.get("id"),
            "amount_cents": event.get("amount", {}).get("cents"),
            "currency": event.get("amount", {}).get("currency", "USD"),
            "metadata": event,
        }).execute()

    elif event_type == "subscription_created" and org_id:
        supabase.table("subscriptions").update({
            "external_subscription_id": event.get("subscription_id"),
            "status": "active",
        }).eq("organization_id", org_id).execute()

    elif event_type == "subscription_cancelled" and org_id:
        supabase.table("subscriptions").update({"status": "cancelled"}).eq("organization_id", org_id).execute()

    return {"received": True}


# ---- Error Handler ----
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    print(f"[ERROR] {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": str(exc)[:200]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
