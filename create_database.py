"""
建立 calculus_ai_tutor 專題所需的 SQLite 資料庫與五張資料表。
use:python create_database.py
"""

import sqlite3
import os

DB_NAME = "calculus_tutor.db"


def create_connection():
    """建立（或開啟）資料庫檔案，回傳連線物件。"""
    conn = sqlite3.connect(DB_NAME)
    # 開啟外鍵約束（SQLite 預設是關閉的，要手動開啟）
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_tables(conn):
    """建立五張資料表（如果已存在則不重複建立）。"""
    cursor = conn.cursor()

    # 1. 使用者資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL,
            email       TEXT UNIQUE,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. 對話紀錄表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            title           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
    """)

    # 3. 教材／文件資訊表
    #    先建立這張，因為 qa_records 會用外鍵參照它
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            material_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT NOT NULL,
            topic        TEXT,
            file_path    TEXT,
            uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. 題目與回答紀錄表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS qa_records (
            record_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            material_id     INTEGER,
            question        TEXT NOT NULL,
            answer           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id),
            FOREIGN KEY (material_id) REFERENCES materials(material_id)
        );
    """)

    # 5. 學習紀錄表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_records (
            record_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id            INTEGER NOT NULL,
            topic              TEXT NOT NULL,
            correct_count      INTEGER DEFAULT 0,
            wrong_count        INTEGER DEFAULT 0,
            last_practiced_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
    """)

    conn.commit()
    print("五張資料表建立完成！")


def insert_sample_data(conn):
    """塞一些範例資料，方便你確認資料庫有正常運作。"""
    cursor = conn.cursor()

    # 避免每次執行都重複塞資料：先檢查 users 表是不是空的
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] > 0:
        print("已經有資料了，跳過範例資料塞入。")
        return

    cursor.execute(
        "INSERT INTO users (username, email) VALUES (?, ?)",
        ("小明", "xiaoming@example.com")
    )
    user_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
        (user_id, "第一次的微積分問答")
    )
    conversation_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO materials (filename, topic, file_path) VALUES (?, ?, ?)",
        ("limit_chapter.pdf", "極限", "/materials/limit_chapter.pdf")
    )
    material_id = cursor.lastrowid

    cursor.execute(
        """INSERT INTO qa_records (conversation_id, material_id, question, answer)
           VALUES (?, ?, ?, ?)""",
        (conversation_id, material_id,
         "請解釋一下極限的概念", "極限描述的是當變數趨近某個值時，函數值的趨勢……")
    )

    cursor.execute(
        """INSERT INTO learning_records (user_id, topic, correct_count, wrong_count)
           VALUES (?, ?, ?, ?)""",
        (user_id, "極限", 1, 0)
    )

    conn.commit()
    print("範例資料塞入完成！")


def show_all_tables(conn):
    """列出資料庫中所有的資料表，確認建立成功。"""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("\n目前資料庫中的資料表：")
    for t in tables:
        print(f"  - {t[0]}")


if __name__ == "__main__":
    print(f"正在建立資料庫檔案：{os.path.abspath(DB_NAME)}")
    conn = create_connection()
    create_tables(conn)
    insert_sample_data(conn)
    show_all_tables(conn)
    conn.close()
    print("\n完成！可以用資料庫檢視工具（例如 DB Browser for SQLite）打開 calculus_tutor.db 來看看內容。")
