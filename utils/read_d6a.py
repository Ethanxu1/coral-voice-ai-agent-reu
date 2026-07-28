#!/usr/bin/env python3
"""Read a Hiwonder/AiNex .d6a action-group file and print its contents.

A .d6a file is a SQLite database. It holds a single table (typically named
``ActionGroup``) where each row is one motion frame: a ``Time`` column giving
the move duration in milliseconds, followed by one ``Servo<N>`` column per
servo holding the target position for that frame.

Usage:
    python3 read_d6a.py path/to/action.d6a
"""

import sqlite3
import sys


def read_d6a(path):
    """Return (table_name, column_names, rows) read from the .d6a file."""
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()

        # Find the action-group table (usually "ActionGroup").
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [name for (name,) in cur.fetchall()]
        if not tables:
            raise ValueError("no tables found in %s" % path)
        table = "ActionGroup" if "ActionGroup" in tables else tables[0]

        # Column names, in order.
        cur.execute("PRAGMA table_info(%s)" % table)
        columns = [info[1] for info in cur.fetchall()]

        cur.execute("SELECT * FROM %s" % table)
        rows = cur.fetchall()
        return table, columns, rows
    finally:
        conn.close()


def main():
    if len(sys.argv) != 2:
        print("usage: python3 read_d6a.py path/to/action.d6a", file=sys.stderr)
        return 1

    path = sys.argv[1]
    table, columns, rows = read_d6a(path)

    print("file:   %s" % path)
    print("table:  %s" % table)
    print("frames: %d" % len(rows))
    print()
    print("\t".join(columns))
    for row in rows:
        print("\t".join("" if v is None else str(v) for v in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
