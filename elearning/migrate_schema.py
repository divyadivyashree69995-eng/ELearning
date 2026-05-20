"""Add missing columns to an older elearning_db. Run: python migrate_schema.py"""
import mysql.connector

DB = {"user": "root", "password": "", "host": "127.0.0.1", "database": "elearning_db"}

MIGRATIONS = [
    ("users", "class_name", "ALTER TABLE users ADD COLUMN class_name VARCHAR(100) NULL AFTER role"),
    ("users", "is_approved", "ALTER TABLE users ADD COLUMN is_approved TINYINT(1) NOT NULL DEFAULT 1 AFTER class_name"),
    ("users", "last_active", "ALTER TABLE users ADD COLUMN last_active TIMESTAMP NULL AFTER is_approved"),
    ("users", "created_at", "ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("content", "uploaded_by", "ALTER TABLE content ADD COLUMN uploaded_by VARCHAR(100) NULL AFTER filename"),
    ("content", "view_count", "ALTER TABLE content ADD COLUMN view_count INT NOT NULL DEFAULT 0"),
    ("tests", "created_by", "ALTER TABLE tests ADD COLUMN created_by VARCHAR(100) NULL AFTER title"),
    ("tests", "due_date", "ALTER TABLE tests ADD COLUMN due_date DATETIME NULL AFTER created_by"),
    ("student_scores", "answers_json", "ALTER TABLE student_scores ADD COLUMN answers_json JSON NULL AFTER score"),
]


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (DB["database"], table, column),
    )
    return cur.fetchone() is not None


def main() -> None:
    conn = mysql.connector.connect(**DB)
    cur = conn.cursor()
    for table, column, sql in MIGRATIONS:
        if column_exists(cur, table, column):
            print(f"  skip {table}.{column} (exists)")
            continue
        try:
            cur.execute(sql)
            conn.commit()
            print(f"  added {table}.{column}")
        except mysql.connector.Error as e:
            print(f"  warn {table}.{column}: {e}")
    cur.close()
    conn.close()
    print("Done. Restart the app and try login again.")


if __name__ == "__main__":
    main()