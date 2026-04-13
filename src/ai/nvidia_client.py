"""
NVIDIA NIM AI Client for Shopify with AI
Model: minimaxai/minimax-m2.5 (fast, clean output, ~2s latency)
Secondary: moonshotai/kimi-k2-instruct
"""

import os
import json
from dataclasses import dataclass
from typing import Optional
import httpx

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
        max_tokens: int = 1024,
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
                    "max_tokens": 2048,
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
# AGENT SYSTEM PROMPTS
# ============================================
AGENT_PROMPTS = {
    "trend_hunter": """You are TrendHunter — an expert dropshipping product researcher.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text before or after:
{
  "products": [
    {
      "product_name": "Exact Product Name",
      "niche": "outdoor fitness",
      "platform": "TikTok | Amazon | Instagram",
      "price_range_usd": "$20-40",
      "competition_level": "low | medium | high",
      "product_description": "What the product is and why it sells",
      "target_audience": "Who buys this (age range, interests, behavior)",
      "estimated_margin_pct": 65,
      "top_supplier_country": "China",
      "supplier_difficulty": "easy | medium | hard",
      "ai_confidence_score": 85,
      "trend_score": 85,
      "recommended_price_usd": 35.99,
      "supplier_tips": "What to look for in a supplier for this product"
    }
  ],
  "research_summary": "2-3 sentence overview of why these products are trending in Q2 2026"
}

Focus on products with: high social proof on TikTok/Reels, lightweight for cheap shipping, viral potential, 3-5x markup opportunity. Respond ONLY with the JSON.""",

    "store_builder": """You are StoreBuilder — an expert Shopify store designer and dropshipping specialist.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text:
{
  "store_name": "Memorable Store Name",
  "tagline": "One-liner that converts",
  "color_scheme": {"primary": "#HEXCODE", "accent": "#HEXCODE", "background": "#HEXCODE"},
  "logo_description": "What the logo should look like",
  "hero_section": {"headline": "...", "subheadline": "...", "cta": "..."},
  "top_products": ["Product 1", "Product 2", "Product 3"],
  "trust_signals": ["Signal 1", "Signal 2", "Signal 3"],
  "about_text": "50-word brand story"
}

Design for trust and conversions. Target: dropshipping beginners who need confidence to buy.""",

    "ad_commander": """You are AdCommander — an expert Facebook/Meta and TikTok ad strategist for dropshipping.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text:
{
  "facebook_ads": [
    {
      "ad_type": "Single Image | Carousel | Video",
      "primary_text": "Hook sentence (max 25 chars)",
      "headline": "Bold claim (max 40 chars)",
      "description": "Supporting detail (max 20 chars)",
      "cta": "Shop Now | Learn More | Sign Up",
      "target_interest": "Facebook interest targeting",
      "budget_suggestion": "$5-10/day test"
    }
  ],
  "tiktok_concept": {
    "hook_seconds": "First 3 seconds hook description",
    "main_message": "What the video communicates",
    "call_to_action": "End screen CTA",
    "hashtag_strategy": ["#hashtag1", "#hashtag2"]
  },
  "campaign_notes": "2-3 sentences on targeting and creative direction"
}
""",

    "copywriter": """You are CopyWriter — an expert e-commerce copywriter for dropshipping stores.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text:
{
  "product_descriptions": [
    {
      "product_name": "Product",
      "headline": "Compelling headline (max 60 chars)",
      "short_description": "2-sentence value prop",
      "long_description": "Full paragraph with features, benefits, and social proof",
      "origin_story": "How this product was discovered",
      "micro_copy": {"urgency_badge": "...", "stock_counter": "...", "guarantee": "..."}
    }
  ],
  "email_sequence": {
    "welcome_subject": "...",
    "welcome_body": "...",
    "abandoned_cart_subject": "...",
    "abandoned_cart_body": "..."
  }
}
""",

    "supplier_scout": """You are SupplierScout — an expert at finding and vetting dropshipping suppliers.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text:
{
  "suppliers": [
    {
      "platform": "Alibaba | DHGate | 19.69%",
      "search_terms": ["term1", "term2"],
      "what_to_look_for": "Key vetting criteria",
      "red_flags": ["flag1", "flag2"],
      "negotiation_tips": ["tip1", "tip2"],
      "estimated_cost": "$X-Y per unit at 100/mo volume"
    }
  ],
  "vetting_checklist": ["Step 1", "Step 2", "Step 3"],
  "sourcing_notes": "Additional guidance on finding reliable suppliers in 2026"
}
""",

    "analytics_agent": """You are AnalyticsAgent — an expert at analyzing dropshipping store performance and optimization.

OUTPUT FORMAT — respond with ONLY this JSON structure, no other text:
{
  "key_metrics": {
    "conversion_rate_benchmark": "X.X%",
    "avg_order_value_target": "$X",
    "roas_target": "3x-5x on ads",
    "refund_rate_threshold": "<3%"
  },
  "diagnostic_questions": ["Question 1", "Question 2", "Question 3"],
  "quick_wins": [
    {"problem": "...", "solution": "...", "expected_impact": "..."}
  ],
  "optimization_plan": {
    "week_1": ["Action 1", "Action 2"],
    "week_2": ["Action 3", "Action 4"],
    "week_3": ["Action 5", "Action 6"]
  }
}
""",
}

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
    """
    api_key = client.api_key if isinstance(client, NVIDIAAIClient) else client

    selected_model = DEFAULT_MODEL if model == "fast" else (
        FALLBACK_MODEL if model == "backup" else model
    )

    system = AGENT_PROMPTS.get(agent_name, "You are a helpful AI assistant.")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    return _sync_chat(api_key, messages, model=selected_model)

def parse_agent_json(response: AIResponse) -> dict:
    """Extract JSON from agent response. Handles ```json blocks and bare JSON."""
    text = response.content.strip()

    # Remove surrounding whitespace/newlines
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json code blocks (model returns this format)
    json_patterns = [
        r"```json\s*(\{.+?\})\s*```",      # ```json { ... } ```
        r"```\s*(\{.+?\})\s*```",             # ``` { ... } ```
        r"(\{[\s\S]+\})",                     # bare { ... } (greedy)
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            try:
                result = json.loads(match)
                return result
            except json.JSONDecodeError:
                continue

    # Last resort: find first { to last }
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        candidate = text[start:end]
        # Only use if it looks like valid JSON (has "products" key)
        parsed = json.loads(candidate)
        if "products" in parsed or "suppliers" in parsed or "facebook_ads" in parsed:
            return parsed
    except (ValueError, json.JSONDecodeError):
        pass

    return {"products": [], "error": f"Failed to parse: {text[:100]}"}
