-- Fix product_ideas table for shopify-with-ai
-- Run in: https://supabase.com/project/ykyemuahvxshtsrkhsfo/sql

-- Drop and recreate product_ideas with all correct columns
DROP TABLE IF EXISTS product_ideas CASCADE;

CREATE TABLE product_ideas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL,
  product_name TEXT NOT NULL,
  niche TEXT DEFAULT 'general',
  platform TEXT DEFAULT 'general',
  source_type TEXT DEFAULT 'ai_research',  -- ai_research | manual | supplier
  trend_score INTEGER DEFAULT 0,
  price_range_usd TEXT DEFAULT '$0-$50',
  competition_level TEXT DEFAULT 'medium',  -- low | medium | high
  supplier_difficulty TEXT DEFAULT 'easy',   -- easy | medium | hard
  product_description TEXT,
  estimated_margin_pct INTEGER DEFAULT 30,
  top_supplier_country TEXT,
  recommended_price_usd NUMERIC(10,2),
  product_url TEXT,
  target_audience TEXT,
  ai_confidence_score INTEGER DEFAULT 70,
  agent_task_id UUID,
  status TEXT DEFAULT 'idea',  -- idea | validated | launched | dropped
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security
ALTER TABLE product_ideas ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read own org product ideas" ON product_ideas FOR SELECT USING (organization_id IN (SELECT organization_id FROM users WHERE auth.uid() = '00000000-0000-0000-0000-000000000000'));
-- For service role (bypass RLS)
CREATE POLICY "Service role can do all" ON product_ideas FOR ALL USING (true);

-- Indexes
CREATE INDEX idx_product_ideas_org ON product_ideas(organization_id);
CREATE INDEX idx_product_ideas_niche ON product_ideas(niche);
CREATE INDEX idx_product_ideas_platform ON product_ideas(platform);
CREATE INDEX idx_product_ideas_status ON product_ideas(status);

-- Fix agent_tasks table too (add model_used column)
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS model_used TEXT DEFAULT 'minimaxai/minimax-m2.5';
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS input_tokens INTEGER;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS output_tokens INTEGER;

-- Add missing columns to shopify_stores
ALTER TABLE shopify_stores ADD COLUMN IF NOT EXISTS store_currency TEXT DEFAULT 'USD';
ALTER TABLE shopify_stores ADD COLUMN IF NOT EXISTS store_country TEXT DEFAULT 'US';
ALTER TABLE shopify_stores ADD COLUMN IF NOT EXISTS primary_locale TEXT DEFAULT 'en';