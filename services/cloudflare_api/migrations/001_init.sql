-- TradingConfiguration
CREATE TABLE IF NOT EXISTS trading_configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    budget_pct REAL NOT NULL,
    enable_w_shape INTEGER NOT NULL DEFAULT 1,
    enable_leading_signal INTEGER NOT NULL DEFAULT 1,
    risk_json TEXT NOT NULL,
    rule_params_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- OrderHistory
CREATE TABLE IF NOT EXISTS order_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    order_type TEXT NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL,
    pnl REAL,
    reason TEXT,
    rule_snapshot_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

-- PositionState
CREATE TABLE IF NOT EXISTS position_state (
    pair TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    entry_price REAL,
    entry_time TEXT,
    w_low REAL,
    last_rule_pass_json TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- PatternClassification
CREATE TABLE IF NOT EXISTS pattern_classification (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    classification TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
