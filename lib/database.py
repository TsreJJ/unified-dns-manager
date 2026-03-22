#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : lib/database.py
Function: SQLite 连接管理、schema 创建、初始化种子数据
Author  : jim
Created : 2026-03-22
Version : 2.0.0
说明: 使用 Flask g 对象缓存连接，自动建表
"""

import os
import sqlite3
import logging

from flask import g

logger = logging.getLogger(__name__)

# ---------- 连接管理 ----------


def get_db():
    """
    获取当前请求的 SQLite 连接（Flask g 缓存）
    返回值: sqlite3.Connection
    """
    if "db" not in g:
        db_path = g.get("db_path", os.environ.get(
            "DB_PATH",
            os.path.expanduser("~/.credentials/unified-dns-manager.db"),
        ))
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    """
    关闭当前请求的数据库连接
    参数: e - 异常（Flask teardown 回调传入）
    """
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------- Schema ----------

_SCHEMA_SQL = """
-- 用户表：email 为唯一标识（来自 CF Access JWT）
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT    NOT NULL UNIQUE,
    role         TEXT    NOT NULL DEFAULT 'viewer'
                        CHECK(role IN ('admin','operator','viewer')),
    display_name TEXT    DEFAULT '',
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 域名权限表（admin 隐含全部域名，此表仅约束 operator/viewer）
CREATE TABLE IF NOT EXISTS domain_permissions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain   TEXT    NOT NULL,
    UNIQUE(user_id, domain)
);

-- 审计日志表（仅写操作）
CREATE TABLE IF NOT EXISTS audit_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    user_email     TEXT    NOT NULL,
    action         TEXT    NOT NULL CHECK(action IN ('add','update','delete')),
    domain         TEXT    NOT NULL,
    rr             TEXT    DEFAULT '',
    record_type    TEXT    DEFAULT '',
    value          TEXT    DEFAULT '',
    request_body   TEXT    DEFAULT '',
    result_success INTEGER DEFAULT 0,
    result_message TEXT    DEFAULT '',
    ip_address     TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_email);
CREATE INDEX IF NOT EXISTS idx_audit_domain ON audit_logs(domain);
"""


def _create_schema(db: sqlite3.Connection):
    """
    执行建表 SQL
    参数: db - SQLite 连接
    """
    db.executescript(_SCHEMA_SQL)
    logger.info("数据库 schema 已就绪")


# ---------- 初始化 ----------


def seed_admin(db: sqlite3.Connection, email: str):
    """
    种入初始 admin 用户（幂等）
    参数: db - SQLite 连接
          email - 管理员邮箱
    """
    if not email:
        return
    row = db.execute("SELECT id, role FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        if row["role"] != "admin":
            db.execute(
                "UPDATE users SET role = 'admin', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                (row["id"],),
            )
            db.commit()
            logger.info("已将 %s 提升为 admin", email)
    else:
        db.execute(
            "INSERT INTO users (email, role, display_name) VALUES (?, 'admin', 'Initial Admin')",
            (email,),
        )
        db.commit()
        logger.info("已创建初始 admin: %s", email)


def init_db(app):
    """
    Flask 应用初始化：建表 + 种子 admin + 注册 teardown
    参数: app - Flask 应用实例
    """
    db_path = os.environ.get(
        "DB_PATH",
        os.path.expanduser("~/.credentials/unified-dns-manager.db"),
    )
    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, mode=0o700, exist_ok=True)

    app.config["DB_PATH"] = db_path

    # 建表（启动时用独立连接）
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _create_schema(conn)
        admin_email = os.environ.get("INITIAL_ADMIN_EMAIL", "")
        seed_admin(conn, admin_email)
    finally:
        conn.close()

    # 设置数据库文件权限 600
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass

    # 注册 teardown
    app.teardown_appcontext(close_db)

    # 在请求上下文中注入 db_path
    @app.before_request
    def _set_db_path():
        g.db_path = app.config["DB_PATH"]

    logger.info("数据库初始化完成: %s", db_path)
