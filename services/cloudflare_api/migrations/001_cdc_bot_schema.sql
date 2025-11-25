-- CDC Zone Bot Database Schema
-- Cloudflare D1 SQLite Database

-- Position States per pair
CREATE TABLE IF NOT EXISTS position_states (
    pair TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'FLAT', -- FLAT, LONG

    entry_price REAL,
    entry_time TEXT,
    entry_bar_index INTEGER,

    w_low REAL,
    sl_price REAL,
    qty REAL,

    last_update_time TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Order History - บันทึกทุก order ที่ส่งและได้รับการยืนยัน
CREATE TABLE IF NOT EXISTS order_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Order Info
    pair TEXT NOT NULL,
    order_type TEXT NOT NULL, -- ENTRY, EXIT
    side TEXT NOT NULL, -- BUY, SELL

    -- Execution
    requested_qty REAL NOT NULL,
    filled_qty REAL,
    avg_price REAL,

    order_id TEXT, -- Binance order ID
    status TEXT NOT NULL, -- PENDING, FILLED, PARTIAL, FAILED

    -- Entry/Exit Context
    entry_reason TEXT, -- กฎที่ผ่านทั้ง 4 ข้อ
    exit_reason TEXT, -- CDC_RED_EXIT, STRUCTURAL_SL, etc.

    -- Rule Evaluation Snapshot
    rule_1_cdc_green BOOLEAN,
    rule_2_leading_red BOOLEAN,
    rule_3_leading_signal BOOLEAN,
    rule_4_pattern BOOLEAN,

    -- P&L (for exit orders)
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,

    -- Metadata
    w_low REAL,
    sl_price REAL,

    -- Timestamps
    requested_at TEXT NOT NULL,
    filled_at TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_order_history_pair ON order_history(pair);
CREATE INDEX idx_order_history_created ON order_history(created_at);

-- Trading Sessions - สรุปการเทรดแต่ละรอบ
CREATE TABLE IF NOT EXISTS trading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    pair TEXT NOT NULL,

    -- Entry
    entry_order_id INTEGER,
    entry_time TEXT,
    entry_price REAL,
    entry_qty REAL,

    -- Exit
    exit_order_id INTEGER,
    exit_time TEXT,
    exit_price REAL,
    exit_qty REAL,
    exit_reason TEXT,

    -- P&L
    pnl REAL,
    pnl_pct REAL,

    -- Rule Context
    entry_rules_passed TEXT, -- JSON: {"rule_1": true, ...}

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (entry_order_id) REFERENCES order_history(id),
    FOREIGN KEY (exit_order_id) REFERENCES order_history(id)
);

CREATE INDEX idx_sessions_pair ON trading_sessions(pair);
CREATE INDEX idx_sessions_created ON trading_sessions(created_at);

-- Circuit Breaker State
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Singleton

    is_active BOOLEAN NOT NULL DEFAULT 0,
    reason TEXT,

    daily_loss REAL DEFAULT 0,
    daily_loss_pct REAL DEFAULT 0,
    total_drawdown_pct REAL DEFAULT 0,

    last_reset_date TEXT,
    activated_at TEXT,

    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO circuit_breaker_state (id) VALUES (1);
