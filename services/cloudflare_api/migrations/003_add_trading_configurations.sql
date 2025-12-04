-- Ensure trading_configurations table exists (idempotent)
CREATE TABLE IF NOT EXISTS trading_configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL UNIQUE,
    timeframe TEXT NOT NULL,
    budget_pct REAL NOT NULL,
    enable_w_shape INTEGER NOT NULL DEFAULT 1,
    enable_leading_signal INTEGER NOT NULL DEFAULT 1,
    risk_json TEXT NOT NULL,
    rule_params_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
