"""
Run this once to create / upgrade all database tables.
Usage:  python init_db.py
"""
import mysql.connector
from werkzeug.security import generate_password_hash

DB_CONFIG = {
    "user": "root",
    "password": "",
    "host": "127.0.0.1",
    "database": "elearning_db",
}


def main() -> None:
    conn = mysql.connector.connect(
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
    )
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS elearning_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute("USE elearning_db")

    statements = [
        # ── users ──────────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            username    VARCHAR(100) NOT NULL UNIQUE,
            password    VARCHAR(255) NOT NULL,
            role        ENUM('admin','teacher','student') NOT NULL,
            class_name  VARCHAR(100) NULL,
            is_approved TINYINT(1)   NOT NULL DEFAULT 1,
            last_active TIMESTAMP    NULL,
            created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── content ────────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS content (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            title       VARCHAR(255) NOT NULL,
            file_type   ENUM('video','photo','pdf') NOT NULL,
            filename    VARCHAR(255) NOT NULL,
            uploaded_by VARCHAR(100) NULL,
            view_count  INT          NOT NULL DEFAULT 0,
            upload_date TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_content_uploader
                FOREIGN KEY (uploaded_by) REFERENCES users(username)
                ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── content_permissions ────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS content_permissions (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            content_id       INT          NOT NULL,
            student_username VARCHAR(100) NOT NULL,
            UNIQUE KEY uq_content_student (content_id, student_username),
            CONSTRAINT fk_cp_content
                FOREIGN KEY (content_id) REFERENCES content(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_cp_student
                FOREIGN KEY (student_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── tests ──────────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS tests (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            title      VARCHAR(255) NOT NULL,
            created_by VARCHAR(100) NULL,
            due_date   DATETIME     NULL,
            created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_tests_teacher
                FOREIGN KEY (created_by) REFERENCES users(username)
                ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── questions ──────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS questions (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            test_id        INT  NOT NULL,
            question_text  TEXT NOT NULL,
            options        JSON NOT NULL,
            correct_answer TEXT NOT NULL,
            CONSTRAINT fk_questions_test
                FOREIGN KEY (test_id) REFERENCES tests(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── quiz_permissions ───────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS quiz_permissions (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            test_id          INT          NOT NULL,
            student_username VARCHAR(100) NOT NULL,
            UNIQUE KEY uq_test_student (test_id, student_username),
            CONSTRAINT fk_qp_test
                FOREIGN KEY (test_id) REFERENCES tests(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_qp_student
                FOREIGN KEY (student_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── student_scores ─────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS student_scores (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            student_username VARCHAR(100) NOT NULL,
            test_id          INT          NOT NULL,
            score            FLOAT        NOT NULL,
            answers_json     JSON         NULL,
            submission_date  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_score_once (student_username, test_id),
            CONSTRAINT fk_ss_student
                FOREIGN KEY (student_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_ss_test
                FOREIGN KEY (test_id) REFERENCES tests(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── comments ───────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS comments (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            content_id   INT          NOT NULL,
            user_username VARCHAR(100) NOT NULL,
            comment_text TEXT         NOT NULL,
            sentiment    VARCHAR(20)  DEFAULT 'neutral',
            created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_comments_content
                FOREIGN KEY (content_id) REFERENCES content(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_comments_user
                FOREIGN KEY (user_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── bookmarks ──────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS bookmarks (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            student_username VARCHAR(100) NOT NULL,
            content_id       INT          NOT NULL,
            created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_bookmark (student_username, content_id),
            CONSTRAINT fk_bm_student
                FOREIGN KEY (student_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_bm_content
                FOREIGN KEY (content_id) REFERENCES content(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── content_views ──────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS content_views (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            content_id       INT          NOT NULL,
            student_username VARCHAR(100) NOT NULL,
            viewed_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_cv_content
                FOREIGN KEY (content_id) REFERENCES content(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_cv_student
                FOREIGN KEY (student_username) REFERENCES users(username)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── announcements ──────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            teacher_username VARCHAR(100) NOT NULL,
            message          TEXT         NOT NULL,
            target_class     VARCHAR(100) NULL,
            created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── chat_messages ──────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            room_key         VARCHAR(120) NOT NULL,
            sender_username  VARCHAR(100) NOT NULL,
            sender_role      VARCHAR(20)  NOT NULL,
            message_text     TEXT         NOT NULL,
            created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_room_created (room_key, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        # ── audit_log ──────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            actor_username VARCHAR(100) NOT NULL,
            action         VARCHAR(100) NOT NULL,
            details        TEXT         NULL,
            created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]

    for stmt in statements:
        cur.execute(stmt)

    # ── Migrations: add columns missing on older MySQL / older DBs ────────
    migrations = [
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
    for table, column, sql in migrations:
        cur.execute(
            """
            SELECT 1 FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (DB_CONFIG["database"], table, column),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """
            SELECT 1 FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """,
            (DB_CONFIG["database"], table),
        )
        if not cur.fetchone():
            continue
        try:
            cur.execute(sql)
            print(f"  added {table}.{column}")
        except Exception as e:
            print(f"  migration skipped {table}.{column}: {e}")

    # Seed admin with hashed password (skip if already exists)
    hashed = generate_password_hash("admin123")
    cur.execute(
        """
        INSERT INTO users (username, password, role, class_name, is_approved)
        SELECT %s, %s, 'admin', NULL, 1
        FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin')
        """,
        ("admin", hashed),
    )

    conn.commit()
    cur.execute("SHOW TABLES")
    tables = ", ".join(r[0] for r in cur.fetchall())
    print(f"OK  Tables ready: {tables}")
    print("Default admin -> username: admin  |  password: admin123")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()