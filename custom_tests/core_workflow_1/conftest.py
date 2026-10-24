"""Fixtures for the standalone dbt Core workflow tests."""

from __future__ import annotations

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
def dbt_project(tmp_path: Path, starrocks_connection: MySQLConnection) -> Generator[Path, None, None]:
    """Run each test in its own StarRocks database and remove it afterward."""
    # 参数按 fixture 名称注入：tmp_path 由 pytest 内置提供，连接由上面的 fixture 提供。
    schema = f"dbt_core_{uuid4().hex[:12]}"
    project = tmp_path / schema
    # 运行的是临时副本，因此调试时的 project_root 与仓库中的项目目录不同。
    shutil.copytree(Path(__file__).parent / "project", project)
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
        with starrocks_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{schema}`")
