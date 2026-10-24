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
        yield connection
    finally:
        connection.close()


@pytest.fixture
def dbt_project(tmp_path: Path, starrocks_connection: MySQLConnection) -> Generator[Path, None, None]:
    """Run each test in its own StarRocks database and remove it afterward."""
    schema = f"dbt_core_{uuid4().hex[:12]}"
    project = tmp_path / schema
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
    (project / "profiles.yml").write_text(yaml.safe_dump(profile), encoding="utf-8")

    with starrocks_connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{schema}`")
    try:
        yield project
    finally:
        with starrocks_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{schema}`")
