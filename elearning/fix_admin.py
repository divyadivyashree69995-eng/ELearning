"""Reset admin password to admin123 (hashed). Run: python fix_admin.py"""
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash

DB_CONFIG = {"user": "root", "password": "", "host": "127.0.0.1", "database": "elearning_db"}


def main() -> None:
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT username, password, role FROM users WHERE username = %s", ("admin",))
    row = cur.fetchone()

    if not row:
        hashed = generate_password_hash("admin123")
        cur.execute(
            "INSERT INTO users (username, password, role, is_approved) VALUES (%s, %s, 'admin', 1)",
            ("admin", hashed),
        )
        conn.commit()
        print("Created admin user: username=admin  password=admin123")
    else:
        pw = row["password"]
        ok = pw and check_password_hash(pw, "admin123")
        print(f"Admin exists. Password works: {ok}")
        if not ok:
            hashed = generate_password_hash("admin123")
            cur.execute("UPDATE users SET password = %s WHERE username = 'admin'", (hashed,))
            conn.commit()
            print("Reset admin password to: admin123")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()