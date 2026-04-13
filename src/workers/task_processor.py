"""
Background Worker — Processes queued AI agent tasks
Runs as a cron job on Render (every 1 minute via Render Cron)

Usage:
  python -m workers.task_processor
"""

import os
import sys
import json
import time
import signal
from datetime import datetime, timezone
from supabase import create_client

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.nvidia_client import (
    NVIDIAAIClient,
    run_agent,
    parse_agent_json,
    SYSTEM_PROMPTS,
)

# Config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ykxemuauhxsktrkhsfo.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")

# Map task_type → agent name
AGENT_MAP = {
    "product_research": "trend_hunter",
    "store_setup": "store_builder",
    "ad_creation": "ad_commander",
    "copywriting": "copywriter",
    "supplier_sourcing": "supplier_scout",
    "analytics_review": "analytics_agent",
}

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
ai_client = NVIDIAAIClient(NVIDIA_API_KEY) if NVIDIA_API_KEY else None


def process_task(task: dict) -> dict:
    """Process a single agent task. Returns output_payload or error."""
    if not ai_client:
        return {"error": "NVIDIA_API_KEY not configured"}

    task_type = task.get("task_type")
    input_payload = task.get("input_payload", {})
    model = input_payload.get("model", "fast")

    agent_name = AGENT_MAP.get(task_type, "trend_hunter")

    # Build user message from input payload
    user_message = input_payload.get("message", json.dumps(input_payload, indent=2))

    print(f"[Worker] Processing {task_type} with {agent_name} (model={model})")

    try:
        response = run_agent(
            ai_client,
            agent_name=agent_name,
            user_input=user_message,
            model=model,
            thinking_tokens=512 if model == "research" else 0,
        )

        output = parse_agent_json(response)

        return {
            "output_payload": output,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "actual_cost_cents": estimate_cost(response.usage),
            "model_used": response.model,
        }

    except Exception as e:
        print(f"[Worker] Error processing task {task['id']}: {e}")
        return {
            "error_message": str(e),
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }


def estimate_cost(usage: dict) -> int:
    """Estimate cost in cents for MiniMax M2.5."""
    # MiniMax M2.5: $0.50 input / $2.80 output per 1M tokens
    input_cost = (usage.get("prompt_tokens", 0) / 1_000_000) * 0.50
    output_cost = (usage.get("completion_tokens", 0) / 1_000_000) * 2.80
    return int((input_cost + output_cost) * 100)  # cents


def claim_and_process_task() -> bool:
    """
    Claim a queued task (mark as 'running'), process it, update result.
    Uses optimistic locking to prevent double-processing.
    Returns True if a task was processed.
    """
    # Find a queued task
    result = supabase.table("agent_tasks").select("*").eq("status", "queued").order("priority").order("created_at").limit(1).execute()

    if not result.data:
        return False

    task = result.data[0]
    task_id = task["id"]

    # Mark as running
    update_result = supabase.table("agent_tasks").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", task_id).eq("status", "queued").execute()

    # If another worker already claimed it, skip
    if not update_result.data:
        print(f"[Worker] Task {task_id} already claimed by another worker, skipping")
        return False

    # Process
    result_data = process_task(task)

    # Update with result
    supabase.table("agent_tasks").update({
        "status": result_data.get("status", "completed"),
        "output_payload": result_data.get("output_payload"),
        "error_message": result_data.get("error_message"),
        "completed_at": result_data.get("completed_at"),
        "actual_cost_cents": result_data.get("actual_cost_cents"),
        "model_used": result_data.get("model_used"),
    }).eq("id", task_id).execute()

    print(f"[Worker] Task {task_id} → {result_data.get('status')}")
    return True


def run_worker():
    """Main worker loop. Processes up to 10 tasks per run."""
    print(f"[Worker] Starting task processor at {datetime.now(timezone.utc)}")
    print(f"[Worker] NVIDIA: {'✓' if ai_client else '✗'} | Supabase: ✓")

    processed = 0
    max_tasks = 10  # Process up to 10 per cron run (1 minute)

    for i in range(max_tasks):
        had_task = claim_and_process_task()
        if not had_task:
            break
        processed += 1
        time.sleep(0.5)  # Small delay to avoid rate limiting

    print(f"[Worker] Processed {processed} tasks. Sleeping.")


if __name__ == "__main__":
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print(f"[Worker] Received signal {sig}, finishing current task...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    run_worker()