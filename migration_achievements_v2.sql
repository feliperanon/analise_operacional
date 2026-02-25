-- Migration: Add category, trigger_type, trigger_value to gameachievement table

-- Add new columns if they don't exist
ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'general';
ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS trigger_type VARCHAR(50) DEFAULT 'manual';
ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS trigger_value TEXT DEFAULT NULL;

-- Make slug nullable (was required before)
ALTER TABLE gameachievement ALTER COLUMN slug DROP NOT NULL;
