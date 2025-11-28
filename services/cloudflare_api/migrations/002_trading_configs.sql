-- Trading Configurations
-- เก็บ config สำหรับแต่ละ pair (max 5 pairs)

CREATE TABLE IF NOT EXISTS trading_configs (
    pair TEXT PRIMARY KEY,

    -- Timeframe
    timeframe TEXT NOT NULL DEFAULT '1d',

    -- Rule Parameters
    cdc_threshold REAL NOT NULL DEFAULT 0.0,
    leading_signal_threshold REAL NOT NULL DEFAULT 0.0,

    -- Feature Flags
    enable_w_shape_filter BOOLEAN NOT NULL DEFAULT 1,
    enable_leading_signal BOOLEAN NOT NULL DEFAULT 1,

    -- Risk Management
    per_trade_cap_pct REAL NOT NULL DEFAULT 0.1, -- 10% of equity per trade
    max_drawdown_pct REAL NOT NULL DEFAULT 20.0,
    daily_loss_limit_pct REAL NOT NULL DEFAULT 5.0,

    -- Active Status
    is_active BOOLEAN NOT NULL DEFAULT 1,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_configs_active ON trading_configs(is_active);
CREATE INDEX idx_configs_updated ON trading_configs(updated_at);
