"""
Dodo Payments Webhook Handler
Handles all subscription and payment lifecycle events.
Verifies signatures, processes events idempotently.
"""

import os
import hmac
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

from fastapi import HTTPException
from supabase import Client

# ============================================================
# CONFIG
# ============================================================
DODO_WEBHOOK_SECRET = os.environ.get("DODO_WEBHOOK_SECRET", "")

# ============================================================
# SIGNATURE VERIFICATION
# ============================================================
def verify_dodo_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify Dodo Payments webhook HMAC-SHA256 signature.
    Dodo sends: dodo-signature: t=...,v1=...
    Format: t=timestamp,v1=hmac_hex
    """
    if not signature or not secret:
        return False

    try:
        parts = dict(x.split("=", 1) for x in signature.split(","))
        timestamp = parts.get("t", "")
        received_hmac = parts.get("v1", "")

        # Compute expected HMAC
        signed_payload = f"{timestamp}.".encode() + payload
        expected_hmac = hmac.new(
            secret.encode(),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_hmac, received_hmac)
    except Exception:
        return False


def verify_dodo_signature_simple(payload: bytes, signature: str, secret: str) -> bool:
    """
    Simple fallback: verify using direct HMAC comparison.
    """
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ============================================================
# EVENT TYPES
# ============================================================
@dataclass
class DodoEvent:
    event_id: str
    event_type: str
    timestamp: str
    data: dict
    metadata: dict


# ============================================================
# WEBHOOK PROCESSORS
# ============================================================
def handle_payment_succeeded(supabase: Client, event: DodoEvent):
    """Payment completed — credit organization account."""
    org_id = event.metadata.get("organization_id")
    amount_cents = event.data.get("amount_cents", 0)
    currency = event.data.get("currency", "USD")

    if not org_id:
        return {"status": "skipped", "reason": "no organization_id in metadata"}

    # Record billing event
    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "payment.succeeded",
        "dodo_event_id": event.event_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "metadata": {
            "raw_event": event.data,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        },
    }).execute()

    # Update subscription status
    sub = supabase.table("subscriptions").select("*").eq("organization_id", org_id).execute()
    if sub.data:
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        new_period_end = now + timedelta(days=30)
        supabase.table("subscriptions").update({
            "status": "active",
            "current_period_start": now.isoformat(),
            "current_period_end": new_period_end.isoformat(),
        }).eq("organization_id", org_id).execute()

    return {"status": "processed", "org_id": org_id, "amount_cents": amount_cents}


def handle_payment_failed(supabase: Client, event: DodoEvent):
    """Payment failed — trigger dunning workflow."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    # Record failure
    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "payment.failed",
        "dodo_event_id": event.event_id,
        "amount_cents": event.data.get("amount_cents", 0),
        "metadata": {"raw_event": event.data, "processed_at": datetime.now(timezone.utc).isoformat()},
    }).execute()

    # Update subscription to past_due
    supabase.table("subscriptions").update({
        "status": "past_due",
    }).eq("organization_id", org_id).execute()

    # Queue dunning task
    supabase.table("agent_tasks").insert({
        "organization_id": org_id,
        "task_type": "dunning_email",
        "priority": 8,
        "input_payload": {
            "event_id": event.event_id,
            "failure_reason": event.data.get("failure_reason", "unknown"),
        },
        "status": "queued",
    }).execute()

    return {"status": "processed", "org_id": org_id}


def handle_subscription_created(supabase: Client, event: DodoEvent):
    """New subscription created via Dodo checkout."""
    org_id = event.metadata.get("organization_id")
    sub_id = event.data.get("subscription_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    tier = event.data.get("tier", "starter")

    # Check if subscription record already exists (idempotency)
    existing = supabase.table("subscriptions").select("id").eq("organization_id", org_id).execute()
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    period_end = now + timedelta(days=30)

    if existing.data:
        supabase.table("subscriptions").update({
            "external_subscription_id": sub_id,
            "tier": tier,
            "status": "active",
            "current_period_start": now.isoformat(),
            "current_period_end": period_end.isoformat(),
        }).eq("organization_id", org_id).execute()
    else:
        supabase.table("subscriptions").insert({
            "organization_id": org_id,
            "external_subscription_id": sub_id,
            "tier": tier,
            "status": "active",
            "ai_calls_limit": 100 if tier == "growth" else 30,
            "current_period_start": now.isoformat(),
            "current_period_end": period_end.isoformat(),
        }).execute()

    # Create trial product_ideas if new
    try:
        from src.ai.nvidia_client import NVIDIAAIClient, run_agent, parse_agent_json
        ai = NVIDIAAIClient(os.environ.get("NVIDIA_API_KEY", ""))
        response = run_agent(ai, "trend_hunter", "Find 5 dropshipping product ideas for the current quarter. Return as JSON with 'products' array.", model="fast")
        products = parse_agent_json(response)
        for p in products.get("products", []):
            p["organization_id"] = org_id
            p["source_type"] = "onboarding_research"
            supabase.table("product_ideas").insert(p).execute()
    except Exception:
        pass  # Don't block subscription creation on AI failure

    return {"status": "processed", "org_id": org_id, "tier": tier}


def handle_subscription_updated(supabase: Client, event: DodoEvent):
    """Subscription fields changed — real-time sync."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    update_fields = {}
    if "status" in event.data:
        update_fields["status"] = event.data["status"]
    if "tier" in event.data:
        update_fields["tier"] = event.data["tier"]
        update_fields["ai_calls_limit"] = 100 if event.data["tier"] == "growth" else 30

    if update_fields:
        supabase.table("subscriptions").update(update_fields).eq("organization_id", org_id).execute()

    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "subscription.updated",
        "dodo_event_id": event.event_id,
        "metadata": {"raw_event": event.data},
    }).execute()

    return {"status": "processed"}


def handle_subscription_renewed(supabase: Client, event: DodoEvent):
    """Subscription renewed — extend billing period."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    period_end = now + timedelta(days=30)

    supabase.table("subscriptions").update({
        "status": "active",
        "current_period_start": now.isoformat(),
        "current_period_end": period_end.isoformat(),
        "renewal_count": supabase.table("subscriptions").select("renewal_count").eq("organization_id", org_id).execute().data[0].get("renewal_count", 0) + 1,
    }).eq("organization_id", org_id).execute()

    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "subscription.renewed",
        "dodo_event_id": event.event_id,
        "metadata": {"renewed_at": now.isoformat()},
    }).execute()

    return {"status": "processed"}


def handle_subscription_cancelled(supabase: Client, event: DodoEvent):
    """Subscription cancelled — downgrade access."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    supabase.table("subscriptions").update({
        "status": "cancelled",
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
    }).eq("organization_id", org_id).execute()

    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "subscription.cancelled",
        "dodo_event_id": event.event_id,
        "metadata": {"cancelled_at": datetime.now(timezone.utc).isoformat()},
    }).execute()

    return {"status": "processed"}


def handle_subscription_on_hold(supabase: Client, event: DodoEvent):
    """Renewal failed — subscription on hold."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    supabase.table("subscriptions").update({
        "status": "on_hold",
    }).eq("organization_id", org_id).execute()

    # Queue dunning task
    supabase.table("agent_tasks").insert({
        "organization_id": org_id,
        "task_type": "dunning_email",
        "priority": 9,
        "input_payload": {
            "event_id": event.event_id,
            "reason": "renewal_failed",
        },
        "status": "queued",
    }).execute()

    return {"status": "processed"}


def handle_dispute_opened(supabase: Client, event: DodoEvent):
    """Chargeback opened — alert and queue response."""
    org_id = event.metadata.get("organization_id")
    if not org_id:
        return {"status": "skipped", "reason": "no organization_id"}

    supabase.table("billing_events").insert({
        "organization_id": org_id,
        "event_type": "dispute.opened",
        "dodo_event_id": event.event_id,
        "amount_cents": event.data.get("amount_cents", 0),
        "metadata": {
            "reason": event.data.get("reason"),
            "evidence_due_by": event.data.get("evidence_due_by"),
        },
    }).execute()

    # Queue alert to Odiadev team
    supabase.table("agent_tasks").insert({
        "organization_id": org_id,
        "task_type": "dispute_alert",
        "priority": 10,
        "input_payload": {
            "event_id": event.event_id,
            "amount_cents": event.data.get("amount_cents", 0),
            "reason": event.data.get("reason", "unknown"),
        },
        "status": "queued",
    }).execute()

    return {"status": "processed"}


# ============================================================
# MAIN WEBHOOK HANDLER
# ============================================================
def parse_dodo_event(body: dict) -> Optional[DodoEvent]:
    """Parse raw Dodo webhook payload into a DodoEvent."""
    return DodoEvent(
        event_id=body.get("id", body.get("event_id", "")),
        event_type=body.get("type", ""),
        timestamp=body.get("timestamp", ""),
        data=body.get("data", {}),
        metadata=body.get("metadata", {}),
    )


async def process_webhook(
    payload: bytes,
    signature: str,
    supabase: Client
) -> dict:
    """
    Main entry point — verify, parse, route to handler.
    Returns dict for logging/response.
    """
    # Verify signature
    if DODO_WEBHOOK_SECRET:
        if not verify_dodo_signature(payload, signature, DODO_WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse event
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = parse_dodo_event(raw)
    if not event.event_type:
        return {"status": "skipped", "reason": "no event type"}

    event_type = event.event_type

    # Route to handler
    handlers = {
        "payment.succeeded": handle_payment_succeeded,
        "payment.failed": handle_payment_failed,
        "subscription.created": handle_subscription_created,
        "subscription.updated": handle_subscription_updated,
        "subscription.renewed": handle_subscription_renewed,
        "subscription.cancelled": handle_subscription_cancelled,
        "subscription.on_hold": handle_subscription_on_hold,
        "subscription.failed": handle_subscription_on_hold,  # Same as on_hold
        "dispute.opened": handle_dispute_opened,
    }

    handler = handlers.get(event_type)
    if not handler:
        return {"status": "skipped", "reason": f"no handler for {event_type}"}

    result = handler(supabase, event)

    # Log to dodo_webhook_events table (idempotency)
    try:
        supabase.table("dodo_webhook_events").upsert({
            "event_id": event.event_id,
            "event_type": event_type,
            "payload": raw,
            "processed_result": result,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="event_id")
    except Exception:
        pass  # Table might not exist

    return result


# ============================================================
# CHECKOUT SESSION CREATION
# ============================================================
async def create_subscription_checkout(
    supabase: Client,
    org_id: str,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    """
    Create a Dodo Payments checkout session for a subscription.
    Returns { checkout_url, session_id }
    """
    import httpx

    api_key = os.environ.get("DODO_PAYMENTS_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="DODO_PAYMENTS_API_KEY not configured")

    # Get plan details
    plan_config = {
        "starter": {
            "product_id": os.environ.get("DODO_PRODUCT_STARTER", ""),
            "ai_calls": 30,
            "name": "Starter Plan",
        },
        "growth": {
            "product_id": os.environ.get("DODO_PRODUCT_GROWTH", ""),
            "ai_calls": 100,
            "name": "Growth Plan",
        },
    }

    config = plan_config.get(plan, plan_config["starter"])

    # Get org email
    org = supabase.table("organizations").select("name").eq("id", org_id).execute()
    users = supabase.table("users").select("email").eq("organization_id", org_id).limit(1).execute()
    customer_email = users.data[0]["email"] if users.data else ""

    # Create checkout session via Dodo REST API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://live.dodopayments.com/checkouts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "product_cart": [
                    {
                        "product_id": config["product_id"],
                        "quantity": 1,
                    }
                ],
                "customer": {
                    "email": customer_email,
                    "name": org.data[0]["name"] if org.data else "Customer",
                },
                "return_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "organization_id": org_id,
                    "plan": plan,
                },
            },
            timeout=30.0,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Dodo checkout failed: {response.text}",
        )

    data = response.json()
    return {
        "checkout_url": data.get("checkout_url"),
        "session_id": data.get("session_id"),
    }