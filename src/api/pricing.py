"""
Shopify with AI — Pricing Tiers Configuration
2026 Best Practices: 3-tier structure, usage-based overages, annual discounts
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum


class PricingTier(Enum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"


@dataclass
class TierConfig:
    name: str
    monthly_price_usd: float
    annual_price_usd: float
    ai_calls_limit: int
    store_limit: int
    products_research_per_month: int
    ad_credits: int
    support: str
    features: List[str]

    @property
    def monthly_price_naira(self) -> int:
        """Approximate NGN (using 1500/USD — update periodically)"""
        return int(self.monthly_price_usd * 1500)

    @property
    def annual_discount_percent(self) -> float:
        if self.monthly_price_usd == 0:
            return 0
        annual_savings = (self.monthly_price_usd * 12) - self.annual_price_usd
        return round((annual_savings / (self.monthly_price_usd * 12)) * 100, 1)


TIERS: Dict[PricingTier, TierConfig] = {
    PricingTier.FREE: TierConfig(
        name="Free",
        monthly_price_usd=0,
        annual_price_usd=0,
        ai_calls_limit=30,
        store_limit=1,
        products_research_per_month=5,
        ad_credits=0,
        support="Community",
        features=[
            "Connect 1 Shopify store",
            "30 AI calls/month",
            "Product research (5 ideas/month)",
            "Basic ad copy (3生成)",
            "14-day trial access to all tiers",
        ],
    ),
    PricingTier.STARTER: TierConfig(
        name="Starter",
        monthly_price_usd=29,
        annual_price_usd=276,  # ~20% off ($23/mo equiv)
        ai_calls_limit=100,
        store_limit=3,
        products_research_per_month=50,
        ad_credits=10,
        support="Email",
        features=[
            "Connect up to 3 Shopify stores",
            "100 AI calls/month",
            "Unlimited product research",
            "AI store setup (1 click)",
            "Ad copy generator (10/month)",
            "Supplier sourcing (5 queries/month)",
            "Priority email support",
        ],
    ),
    PricingTier.GROWTH: TierConfig(
        name="Growth",
        monthly_price_usd=79,
        annual_price_usd=756,  # ~20% off ($63/mo equiv)
        ai_calls_limit=500,
        store_limit=10,
        products_research_per_month=-1,  # unlimited
        ad_credits=50,
        support="Priority",
        features=[
            "Connect up to 10 Shopify stores",
            "500 AI calls/month",
            "AI agent team (all 6 agents)",
            "Full store setup (logo + pages)",
            "Facebook/Meta ad creation (50/month)",
            "Unlimited supplier sourcing",
            "Analytics dashboard",
            "Multi-store management",
            "Priority support + monthly call",
        ],
    ),
}


@dataclass
class OverageConfig:
    ai_call_price_usd: float = 0.05  # $0.05 per AI call over limit
    extra_product_research_price_usd: float = 0.50  # $0.50 per product research
    extra_ad_credit_price_usd: float = 1.00  # $1 per ad generation


@dataclass
class BillingConfig:
    currency: str = "USD"
    payout_currency: str = "USD"
    payout_threshold_cents: int = 5000  # $50 minimum
    payout_schedule: str = "bi-monthly"  # bi-monthly | weekly | monthly
    tax_category: str = "saas_digital"  # for global VAT/GST compliance


@dataclass
class DodoProducts:
    starter_monthly_product_id: str = ""  # Set via env DODO_PRODUCT_STARTER_MONTHLY
    starter_annual_product_id: str = ""   # Set via env DODO_PRODUCT_STARTER_ANNUAL
    growth_monthly_product_id: str = ""   # Set via env DODO_PRODUCT_GROWTH_MONTHLY
    growth_annual_product_id: str = ""    # Set via env DODO_PRODUCT_GROWTH_ANNUAL
    free_trial_product_id: str = ""       # Set via env DODO_PRODUCT_FREE_TRIAL


# ============================================================
# PRICING HELPERS
# ============================================================

def get_tier(plan: str) -> TierConfig:
    """Get tier config by plan name."""
    try:
        return TIERS[PricingTier(plan)]
    except ValueError:
        return TIERS[PricingTier.FREE]


def calculate_ai_overage(used: int, plan: str) -> float:
    """Calculate charges for AI calls over the plan limit."""
    tier = get_tier(plan)
    overage = used - tier.ai_calls_limit
    if overage <= 0:
        return 0.0
    return round(overage * OverageConfig().ai_call_price_usd, 2)


def format_price_display(price_usd: float, billing_cycle: str = "monthly") -> str:
    """Format price for display."""
    if price_usd == 0:
        return "Free"
    cycle_label = "/month" if billing_cycle == "monthly" else "/year"
    return f"${price_usd:.0f}{cycle_label}"


def get_upgrade_path(current_plan: str) -> List[str]:
    """Suggest plan upgrades based on current plan."""
    order = ["free", "starter", "growth"]
    current_idx = order.index(current_plan) if current_plan in order else 0
    return [p for p in order[current_idx + 1:]]


def format_tier_for_display(tier: TierConfig, billing_cycle: str = "monthly") -> dict:
    """Format tier config for frontend display."""
    return {
        "name": tier.name,
        "price": tier.monthly_price_usd if billing_cycle == "monthly" else tier.annual_price_usd,
        "price_formatted": format_price_display(
            tier.monthly_price_usd if billing_cycle == "monthly" else tier.annual_price_usd / 12,
            billing_cycle,
        ),
        "ai_calls": tier.ai_calls_limit if tier.ai_calls_limit > 0 else "Unlimited",
        "features": tier.features,
        "annual_savings_percent": tier.annual_discount_percent,
    }


# ============================================================
# PRORATION HELPERS (2026 best practice)
# ============================================================

def calculate_proration_credit(
    current_tier: str,
    days_remaining: int,
    total_days: int = 30
) -> float:
    """
    Calculate credit when downgrading mid-cycle.
    2026 best practice: no refund, credit applied to next billing.
    """
    tier = get_tier(current_tier)
    daily_rate = tier.monthly_price_usd / total_days
    return round(daily_rate * days_remaining, 2)


def calculate_proration_charge(
    new_tier: str,
    days_used: int,
    total_days: int = 30
) -> float:
    """
    Calculate additional charge when upgrading mid-cycle.
    2026 best practice: prorate new tier, charge immediately.
    """
    tier = get_tier(new_tier)
    daily_rate = tier.monthly_price_usd / total_days
    days_remaining = total_days - days_used
    return round(daily_rate * days_remaining, 2)


# ============================================================
# USAGE ALERTS (2026 best practice: prevent bill shock)
# ============================================================

def get_usage_alerts(ai_calls_used: int, plan: str) -> List[dict]:
    """
    Return usage threshold alerts.
    2026 best practice: alert at 50%, 80%, 95%, 100%
    """
    tier = get_tier(plan)
    if tier.ai_calls_limit <= 0:
        return []

    thresholds = [50, 80, 95, 100]
    alerts = []

    for threshold in thresholds:
        usage_percent = (ai_calls_used / tier.ai_calls_limit) * 100
        if usage_percent >= threshold:
            alerts.append({
                "threshold": threshold,
                "percent_used": round(usage_percent, 1),
                "calls_used": ai_calls_used,
                "calls_limit": tier.ai_calls_limit,
                "overage_rate": OverageConfig().ai_call_price_usd,
                "suggestion": f"Upgrade to Growth for 500 AI calls/month",
            })

    return alerts


# ============================================================
# EXPORT FOR API
# ============================================================

def get_all_tiers_display(billing_cycle: str = "monthly") -> List[dict]:
    """Get all tiers formatted for frontend pricing page."""
    return [
        {
            "plan": tier.name.lower(),
            **format_tier_for_display(config, billing_cycle),
            "is_popular": config.name == "Starter",  # Middle tier is anchor
            "is_recommended": config.name == "Starter",
        }
        for tier, config in TIERS.items()
    ]


def get_plan_comparison() -> dict:
    """Get a feature comparison matrix for pricing page."""
    features = [
        "AI calls/month",
        "Shopify stores",
        "Product research",
        "AI store setup",
        "Ad copy generator",
        "Supplier sourcing",
        "Analytics dashboard",
        "Priority support",
    ]

    return {
        "features": features,
        "tiers": {
            tier.name.lower(): [
                config.ai_calls_limit if config.ai_calls_limit > 0 else "Unlimited",
                config.store_limit,
                "Unlimited" if config.products_research_per_month == -1 else config.products_research_per_month,
                "✓" if tier == PricingTier.GROWTH else "Basic" if tier == PricingTier.STARTER else "✗",
                config.ad_credits,
                "Unlimited" if tier == PricingTier.GROWTH else ("5/mo" if tier == PricingTier.STARTER else "✗"),
                "✓" if tier == PricingTier.GROWTH else "✗",
                "Priority" if tier == PricingTier.GROWTH else "Email" if tier == PricingTier.STARTER else "Community",
            ]
            for tier, config in TIERS.items()
        },
    }