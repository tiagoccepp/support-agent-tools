# Database schema

SQLite by default (`DB_PATH`, offline-friendly). Tables are created on first
use by `src/tools/db_tool.py`:

```sql
CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    agent TEXT NOT NULL DEFAULT 'support',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'starter',
    created_at TEXT NOT NULL
);
CREATE TABLE onboarding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_email TEXT NOT NULL,
    step TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (customer_email, step)
);
```

Tests run against isolated temp databases (`tests/conftest.py`).
