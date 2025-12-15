-- Migration: Add Trailing Stop and Entry Trend fields
-- Created: 2025-12-14

-- Add fields to position_states table
ALTER TABLE position_states ADD COLUMN activation_price REAL;
ALTER TABLE position_states ADD COLUMN entry_trend_bullish BOOLEAN;
ALTER TABLE position_states ADD COLUMN trailing_stop_activated BOOLEAN DEFAULT 0;
ALTER TABLE position_states ADD COLUMN trailing_stop_price REAL;
ALTER TABLE position_states ADD COLUMN prev_high REAL;

-- Add activation_price to order_history table
ALTER TABLE order_history ADD COLUMN activation_price REAL;
