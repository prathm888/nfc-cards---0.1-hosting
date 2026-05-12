"""
Migration script: Add SRS-required columns to existing nfc.db
Run once: python migrate_db.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'nfc.db')

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # --- users table ---
    users_cols = [
        ("emp_id",        "TEXT"),
        ("name",          "TEXT"),
        ("address",       "TEXT"),
        ("total_points",  "INTEGER DEFAULT 0"),
        ("designation",   "TEXT DEFAULT 'Publicity Officer'"),
        ("photo_url",     "TEXT"),  # legacy alias; logo_filename is the canonical column
    ]
    for col, coltype in users_cols:
        if not column_exists(cur, 'users', col):
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {coltype}")
            print(f"  + users.{col}")
        else:
            print(f"  [ok] users.{col} already exists")

    # --- nfc_cards table: add status and target_url ---
    if not column_exists(cur, 'nfc_cards', 'status'):
        cur.execute("ALTER TABLE nfc_cards ADD COLUMN status TEXT DEFAULT 'active'")
        cur.execute("UPDATE nfc_cards SET status = CASE WHEN is_active = 0 THEN 'suspended' ELSE 'active' END")
        print("  + nfc_cards.status (migrated from is_active)")
    else:
        # Rename legacy 'paused' values to 'suspended'
        cur.execute("UPDATE nfc_cards SET status = 'suspended' WHERE status = 'paused'")
        print("  [ok] nfc_cards.status: migrated 'paused' -> 'suspended'")

    if not column_exists(cur, 'nfc_cards', 'target_url'):
        cur.execute("ALTER TABLE nfc_cards ADD COLUMN target_url TEXT")
        print("  + nfc_cards.target_url")
    else:
        print("  [ok] nfc_cards.target_url already exists")

    # --- tap_analytics table: add is_unique ---
    if not column_exists(cur, 'tap_analytics', 'is_unique'):
        cur.execute("ALTER TABLE tap_analytics ADD COLUMN is_unique INTEGER DEFAULT 1")
        print("  + tap_analytics.is_unique")
    else:
        print("  [ok] tap_analytics.is_unique already exists")

    # --- Create daily_goals table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE NOT NULL,
            target_scans INTEGER NOT NULL DEFAULT 10,
            reward_desc VARCHAR(300),
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  [ok] daily_goals table ready")

    # --- Create notifications table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_emp_id VARCHAR(20),
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER REFERENCES users(id)
        )
    """)
    print("  [ok] notifications table ready")

    conn.commit()
    conn.close()
    print("\nMigration complete.")

if __name__ == '__main__':
    print("Running NFC Platform DB migration...")
    migrate()
