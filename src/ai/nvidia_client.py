"""
NVIDIA NIM AI Client for Shopify with AI
Model: minimaxai/minimax-m2.5 (fast, clean output, ~2s latency)
Secondary: moonshotai/kimi-k2-instruct
"""

import os
import re
import json
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import httpx

# Import agent prompts (time-aware, proactive)
from .agent_prompts import AGENT_PROMPTS

# ============================================
# CONFIG
# ============================================
BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "minimaxai/minimax-m2.5"
FALLBACK_MODEL = "moonshotai/kimi-k2-instruct"

# ============================================
# DATA CLASSES
# ============================================
@dataclass
class AIResponse:
    content: str
    model: str
    usage: dict
    latency_ms: int

# ============================================
# CLIENT
# ============================================
class NVIDIAAIClient:
    """Async client for NVIDIA NIM API (OpenAI-compatible)."""

    def __init__(self, api_key: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = BASE_URL
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Send a chat completion request."""
        import time
        start = time.time()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

        latency_ms = int((time.time() - start) * 1000)

        return AIResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            usage=data.get("usage", {}),
            latency_ms=latency_ms,
        )

# ============================================
# SYNC WRAPPER
# ============================================
def _sync_chat(api_key: str, messages: list, model: str = DEFAULT_MODEL) -> AIResponse:
    """Synchronous wrapper for background workers."""
    import time
    start = time.time()

    resp = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 2048},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    return AIResponse(
        content=data["choices"][0]["message"]["content"],
        model=data.get("model", model),
        usage=data.get("usage", {}),
        latency_ms=int((time.time() - start) * 1000),
    )

# ============================================
# PROMPT LOADER
# ============================================
PROMPTS_DIR = Path(__file__).parent / "prompts"

def load_agent_prompt(agent_name: str) -> str:
    """Load prompt from file if exists, otherwise use embedded."""
    prompt_file = PROMPTS_DIR / f"{agent_name}.txt"
    if prompt_file.exists():
        return prompt_file.read_text()
    return AGENT_PROMPTS.get(agent_name, "You are a helpful AI assistant.")

# ============================================
# HELPER FUNCTIONS
# ============================================
def run_agent(
    client: NVIDIAAIClient,
    agent_name: str,
    user_prompt: str,
    model: str = "fast",
) -> AIResponse:
    """
    Run a named agent with a user prompt.
    Uses minimaxai/minimax-m2.5 (fast, ~2s).
    Loads prompt from file if available.
    """
    api_key = client.api_key if isinstance(client, NVIDIAAIClient) else client

    selected_model = DEFAULT_MODEL if model == "fast" else (
        FALLBACK_MODEL if model == "backup" else model
    )

    # Load prompt from file or use embedded
    system = load_agent_prompt(agent_name)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    return _sync_chat(api_key, messages, model=selected_model)

def parse_agent_json(response: AIResponse) -> dict:
    """Extract JSON from agent response. Returns {} if invalid."""
    try:
        text = response.content.strip()
        # Try direct parse first
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    try:
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
    except (ValueError, json.JSONDecodeError):
        pass

    # Try extracting first JSON object
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"products": [], "error": "Failed to parse agent response"}
