#!/usr/bin/env python3
"""
Tiny SQLite migration runner.

Usage:
  python scripts/migrate.py --db data/photochrono.db
  python scripts/migrate.py --db data/photochrono.db --dir db_migrations
  python scripts/migrate.py --db data/photochrono.db --status
"""
from __future__ import annotations
import argparse
import hashlib
import sys
import time
from pathlib import Path
import sqlite3


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          filename   TEXT PRIMARY KEY,
          checksum   TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
    """)
    conn.commit()


def file_checksum(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def apply_sql(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn:  # single transaction
        conn.executescript(sql)


def list_applied(conn: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in conn.execute(
        "SELECT filename, checksum FROM schema_migrations"
    )}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to SQLite DB file")
    ap.add_argument("--dir", default="db_migrations", help="Migrations directory")
    ap.add_argument("--status", action="store_true",
                    help="Show applied/pending and exit (no changes)")
    args = ap.parse_args()

    db_path = Path(args.db)
    mig_dir = Path(args.dir)

    if not db_path.exists():
        print(f"✖ DB not found: {db_path}", file=sys.stderr)
        return 1
    if not mig_dir.exists():
        print(f"✖ Migrations dir not found: {mig_dir}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    ensure_migrations_table(conn)

    applied = list_applied(conn)
    files = sorted(mig_dir.glob("*.sql"), key=lambda p: p.name)

    if args.status:
        print(f"DB: {db_path}")
        print(f"Dir: {mig_dir}")
        print("\nApplied migrations:")
        if applied:
            for fname in sorted(applied):
                print(f"  ✓ {fname}")
        else:
            print("  (none)")
        print("\nPending migrations:")
        pending = [f for f in files if f.name not in applied]
        if pending:
            for f in pending:
                print(f"  → {f.name}")
        else:
            print("  (none)")
        return 0

    for f in files:
        checksum = file_checksum(f)
        if f.name in applied:
            if applied[f.name] != checksum:
                print(
                    f"✖ {f.name} was already applied but the file has changed.\n"
                    f"  Create a new migration instead of editing an applied one.",
                    file=sys.stderr,
                )
                return 2
            print(f"✓ {f.name} already applied")
            continue

        print(f"→ Applying {f.name} ...")
        apply_sql(conn, f)
        conn.execute(
            "INSERT INTO schema_migrations(filename, checksum, applied_at) VALUES (?,?,?)",
            (f.name, checksum, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        conn.commit()
        print(f"✔ Applied {f.name}")

    print("All migrations up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
