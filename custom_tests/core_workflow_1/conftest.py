"""Fixtures for the standalone dbt Core workflow tests."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Generator
from uuid import uuid4

import mysql.connector
import pytest
import yaml
from mysql.connector import MySQLConnection

HOST = os.getenv("STARROCKS_TEST_HOST", "127.0.0.1")
PORT = int(os.getenv("STARROCKS_TEST_PORT", "9030"))
USER = os.getenv("STARROCKS_TEST_USER", "root")
PASSWORD = os.getenv("STARROCKS_TEST_PASSWORD", "")


@pytest.fixture
def starrocks_connection() -> Generator[MySQLConnection, None, None]:
    """Connect to the StarRocks container's MySQL-compatible port."""
    connection = mysql.connector.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, connection_timeout=5, autocommit=True
    )
    try:
        # pytest 将 yield 的连接注入依赖此 fixture 的函数，结束后继续执行 finally。
        yield connection
    finally:
        connection.close()


@pytest.fixture
def dbt_project(starrocks_connection: MySQLConnection) -> Generator[Path, None, None]:
    """Run each test in its own StarRocks database and remove it afterward."""
    # 连接由同名 fixture 注入；工作副本使用固定目录，便于调试时查看文件。
    schema = f"dbt_core_{uuid4().hex[:12]}"
    test_root = Path(__file__).resolve().parent
    project = test_root / ".work"
    # 删除前确认路径没有被符号链接或目录联接重定向，避免清理其他目录。
    if project.resolve() != project:
        raise ValueError(f"Test work directory must not be redirected: {project}")
    if project.exists():
        shutil.rmtree(project)
    # 每次重新复制，清除上次生成的 target、日志及其他存量文件；结束后保留供查看。
    shutil.copytree(test_root / "project", project)
    profile = {
        "custom_test_dbt": {
            "target": "test",
            "outputs": {
                "test": {
                    "type": "starrocks",
                    "host": HOST,
                    "port": PORT,
                    "schema": schema,
                    "username": USER,
                    "password": "{{ env_var('STARROCKS_TEST_PASSWORD', '') }}",
                    "threads": 1,
                }
            },
        }
    }
    # profile 名称与 dbt_project.yml 的 profile 字段对应，type 决定使用的适配器。
    (project / "profiles.yml").write_text(yaml.safe_dump(profile), encoding="utf-8")

    with starrocks_connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{schema}`")
    try:
        # 此路径成为测试函数的 dbt_project 入参；测试结束后恢复执行并删除测试数据库。
        yield project
    finally:
        # dbt 的 file_log 会跨命令保留 handler；释放本项目日志，避免 Windows 下次清理失败。
        file_logger = logging.getLogger("file_log")
        for handler in file_logger.handlers[:]:
            if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).is_relative_to(
                project
            ):
                handler.close()
                file_logger.removeHandler(handler)
        with starrocks_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{schema}`")
