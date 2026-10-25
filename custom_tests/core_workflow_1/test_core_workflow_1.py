"""Exercise dbt Core's main commands with a small local project."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from dbt.cli.main import dbtRunner, dbtRunnerResult
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.results import RunExecutionResult
from mysql.connector import MySQLConnection


def _invoke(project: Path, command: str, *options: str) -> dbtRunnerResult:
    # 通过 Python 调用 dbt 命令；项目配置和连接配置都从 fixture 创建的固定工作目录读取。
    return dbtRunner().invoke([command, *options, "--project-dir", str(project), "--profiles-dir", str(project)])


def test_01_parse_project(dbt_project: Path) -> None:
    """Parsing discovers the seed, models, and their dependencies."""
    # pytest 按参数名找到同名 fixture，将其 yield 的 Path 注入；Path 注解不负责匹配。
    result = _invoke(dbt_project, "parse")

    assert result.success, result.exception
    assert isinstance(result.result, Manifest)
    nodes = result.result.nodes
    assert {"seed.custom_test_dbt.people", "model.custom_test_dbt.stg_people", "model.custom_test_dbt.mart_people"} <= set(
        nodes
    )
    assert "model.custom_test_dbt.stg_people" in nodes["model.custom_test_dbt.mart_people"].depends_on.nodes
    assert nodes["model.custom_test_dbt.stg_people"].config.materialized == "view"
    assert nodes["model.custom_test_dbt.mart_people"].config.materialized == "table"

    # 语义模型与指标独立存储，不属于 manifest.nodes 中的 SQL 模型。
    semantic_model = result.result.semantic_models["semantic_model.custom_test_dbt.mart_people"]
    assert semantic_model.depends_on.nodes == ["model.custom_test_dbt.mart_people"]
    assert [(entity.name, entity.type.value, entity.expr) for entity in semantic_model.entities] == [
        ("person", "primary", "id")
    ]
    dimensions = {dimension.name: dimension for dimension in semantic_model.dimensions}
    assert dimensions["person_name"].type.value == "categorical"
    assert dimensions["person_name"].expr == "name"
    assert dimensions["registered_on"].type.value == "time"
    assert semantic_model.defaults.agg_time_dimension == "registered_on"
    metric = result.result.metrics["metric.custom_test_dbt.people_count"]
    assert metric.type.value == "simple"
    assert "semantic_model.custom_test_dbt.mart_people" in metric.depends_on.nodes
    assert metric.type_params.metric_aggregation_params.agg.value == "count"
    assert metric.type_params.expr == "id"
    assert nodes["model.custom_test_dbt.time_spine"].time_spine.standard_granularity_column == "date_day"


def test_02_select_model_and_ancestors(dbt_project: Path) -> None:
    """Selecting a model with + includes its upstream seed and model."""
    result = _invoke(dbt_project, "list", "--select", "+mart_people", "--resource-type", "model", "seed")

    assert result.success, result.exception
    assert set(result.result) == {"custom_test_dbt.people", "custom_test_dbt.stg_people", "custom_test_dbt.mart_people"}


def test_03_build_and_query_models(dbt_project: Path, starrocks_connection: MySQLConnection) -> None:
    """Build table/view models, run column tests, and verify relation types and rows."""
    # 工作目录固定，数据库名仍每次独立生成，应从实际连接配置中读取。
    profile = yaml.safe_load((dbt_project / "profiles.yml").read_text(encoding="utf-8"))
    schema = profile["custom_test_dbt"]["outputs"]["test"]["schema"]
    result = _invoke(dbt_project, "build")

    assert result.success, result.exception
    assert isinstance(result.result, RunExecutionResult)
    assert len(result.result.results) == 8  # One seed, three models, four column tests.
    assert {node.status for node in result.result.results} == {"success", "pass"}

    with starrocks_connection.cursor() as cursor:
        cursor.execute(
            "select TABLE_NAME, TABLE_TYPE from information_schema.tables "
            "where TABLE_SCHEMA = %s and TABLE_NAME in ('stg_people', 'mart_people') order by TABLE_NAME",
            (schema,),
        )
        assert cursor.fetchall() == [("mart_people", "BASE TABLE"), ("stg_people", "VIEW")]

        cursor.execute(f"select id, name, registered_on from `{schema}`.mart_people order by id")
        assert cursor.fetchall() == [
            (1, "ADA", date(2026, 1, 1)),
            (2, "GRACE", date(2026, 1, 1)),
            (3, "ALAN", date(2026, 1, 2)),
        ]
        cursor.execute(f"select date_day from `{schema}`.time_spine order by date_day")
        assert cursor.fetchall() == [(date(2026, 1, 1),), (date(2026, 1, 2),)]


def test_04_run_data_tests(dbt_project: Path) -> None:
    """The test command checks the built models independently of build."""
    built = _invoke(dbt_project, "build")
    assert built.success, built.exception

    result = _invoke(dbt_project, "test")

    assert result.success, result.exception
    assert isinstance(result.result, RunExecutionResult)
    assert len(result.result.results) == 4
    assert {node.status for node in result.result.results} == {"pass"}
