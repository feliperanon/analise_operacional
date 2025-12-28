-- Migration: Add logs column to dailyoperation table
ALTER TABLE dailyoperation ADD COLUMN IF NOT EXISTS logs JSON;
