# Shopify with AI — Supabase Database Schema
-- Run this in Supabase SQL Editor: https://supabase.com/project/ykxemuauhxsktrkhsfo/sql

-- ============================================
-- ENABLE REQUIRED EXTENSIONS
-- ============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_net";  -- for webhooks/http calls from DB

-- ============================================
-- CUSTOM TYPES
-- ============================================
CREATE TYPE subscription_tier AS ENUM ('free', 'starter', 'growth', 'pro');
CREATE TYPE task_status AS ENUM ('queued', 'running', 'completed', 'failed', 'cancelled');
CREATE TYPE task_type AS ENUM ('product_research', 'store_setup', 'ad_creation', 'copywriting', 'supplier_sourcing', 'analytics_review');
CREATE TYPE payout_status AS ENUM ('pending', 'completed', 'failed');

-- ============================================
-- USERS & ORGANIZATIONS
-- ============================================
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  plan subscription_tier DEFAULT 'free',
  shopify_store_url TEXT,
  shopify_access_token_encrypted TEXT,  -- encrypted, never plaintext
  shopify_refresh_token_encrypted TEXT,
  meta_ad_account_id TEXT,
  meta_access_token_encrypted TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  full_name TEXT,
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member',  -- owner, admin, member
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_active_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- SUBSCRIPTIONS & BILLING
-- ============================================
CREATE TABLE subscriptions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  external_subscription_id TEXT,  -- Dodo subscription ID
  tier subscription_tier NOT NULL DEFAULT 'free',
  status TEXT DEFAULT 'active',  -- active, cancelled, past_due, trialing
  current_period_start TIMESTAMPTZ,
  current_period_end TIMESTAMPTZ,
  cancel_at_period_end BOOLEAN DEFAULT FALSE,
  ai_calls_used_this_period INTEGER DEFAULT 0,
  ai_calls_limit INTEGER DEFAULT 30,  -- free tier = 30 calls
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE billing_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,  -- payment_succeeded, payment_failed, subscription_created, subscription_cancelled
  dodo_event_id TEXT,
  amount_cents INTEGER,
  currency TEXT DEFAULT 'USD',
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- AI AGENTS & TASKS
-- ============================================
CREATE TABLE agent_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id),
  task_type task_type NOT NULL,
  status task_status DEFAULT 'queued',
  priority INTEGER DEFAULT 5,  -- 1 = highest, 10 = lowest
  input_payload JSONB NOT NULL,  -- task-specific input data
  output_payload JSONB,  -- task result
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  estimated_cost_cents INTEGER,
  actual_cost_cents INTEGER,
  model_used TEXT DEFAULT 'minimaxai/minimax-m2.5',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for task queue processing
CREATE INDEX idx_agent_tasks_queue ON agent_tasks(status, priority, created_at)
  WHERE status IN ('queued', 'running');

-- ============================================
-- PRODUCT RESEARCH
-- ============================================
CREATE TABLE product_ideas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  category TEXT,
  trend_score INTEGER DEFAULT 0,  -- 0-100
  competition_level TEXT DEFAULT 'medium',  -- low, medium, high
  sourcing_cost_estimate NUMERIC(10,2),
  selling_price_estimate NUMERIC(10,2),
  supplier_count_estimate INTEGER,
  source_url TEXT,
  source_type TEXT,  -- tiktok, google_trends, amazon, shopify_app
  agent_task_id UUID REFERENCES agent_tasks(id),
  image_url TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- STORES (SHOPIFY)
-- ============================================
CREATE TABLE shopify_stores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  store_url TEXT NOT NULL,
  access_token_encrypted TEXT,
  scope TEXT[],  -- requested permissions
  is_active BOOLEAN DEFAULT TRUE,
  last_sync_at TIMESTAMPTZ,
  shopify_shop_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- AGENT OUTPUTS & ARTIFACTS
-- ============================================
CREATE TABLE agent_artifacts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  agent_task_id UUID REFERENCES agent_tasks(id),
  artifact_type TEXT NOT NULL,  -- store_theme, ad_copy, product_description, logo, email_sequence
  artifact_data JSONB NOT NULL,  -- structured output
  file_url TEXT,  -- for generated images, PDFs, etc.
  version INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- PAYOUTS (Dodo)
-- ============================================
CREATE TABLE payouts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  dodo_payout_id TEXT,
  amount_cents INTEGER NOT NULL,
  currency TEXT DEFAULT 'USD',
  status payout_status DEFAULT 'pending',
  initiated_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  bank_reference TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE shopify_stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE payouts ENABLE ROW LEVEL SECURITY;

-- Organizations: users can only see their own org
CREATE POLICY "Users see own organization" ON organizations
  FOR ALL USING (true);  -- TODO: filter by user membership

-- Users: users can only see users in their org
CREATE POLICY "Users see org members" ON users
  FOR ALL USING (true);  -- TODO: filter by org

-- Subscriptions: org-scoped
CREATE POLICY "Org-scoped subscriptions" ON subscriptions
  FOR ALL USING (true);  -- TODO: filter by org

-- Agent tasks: org-scoped
CREATE POLICY "Org-scoped tasks" ON agent_tasks
  FOR ALL USING (true);  -- TODO: filter by org

-- Product ideas: org-scoped
CREATE POLICY "Org-scoped product ideas" ON product_ideas
  FOR ALL USING (true);  -- TODO: filter by org

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_organizations_updated_at
  BEFORE UPDATE ON organizations
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- AI Usage tracking trigger
CREATE OR REPLACE FUNCTION track_ai_usage()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status = 'completed' AND NEW.actual_cost_cents IS NOT NULL THEN
    UPDATE subscriptions
    SET ai_calls_used_this_period = ai_calls_used_this_period + 1
    WHERE organization_id = NEW.organization_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_track_ai_usage
  AFTER UPDATE OF status ON agent_tasks
  FOR EACH ROW EXECUTE FUNCTION track_ai_usage();

-- ============================================
-- INITIAL SEED DATA
-- ============================================
INSERT INTO organizations (id, name, plan) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Odiadev (Demo)', 'starter');