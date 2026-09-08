import os

import psycopg2.pool

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5433"),
            dbname=os.environ.get("DB_NAME", "nba_predictor"),
            user=os.environ.get("DB_USER", "nba"),
            password=os.environ.get("DB_PASSWORD", "nba"),
        )
    return _pool


def get_db():
    conn = get_pool().getconn()
    try:
        yield conn
    finally:
        conn.rollback()
        get_pool().putconn(conn)
