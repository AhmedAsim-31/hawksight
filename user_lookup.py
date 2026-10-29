import sqlite3


def get_user(conn: sqlite3.Connection, user_id: str):
    return conn.execute(f"SELECT * FROM users WHERE id = '{user_id}'").fetchone()
