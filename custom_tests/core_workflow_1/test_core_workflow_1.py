"""Exercise dbt Core's main commands with a small local project."""

from __future__ import annotations

from pathlib import Path

from dbt.cli.main import dbtRunner, dbtRunnerResult
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.results import RunExecutionResult
from mysql.connector import MySQLConnection


def _invoke(project: Path, command: str, *options: str) -> dbtRunnerResult:
    return dbtRunner().invoke([command, *options, "--project-dir", str(project), "--profiles-dir", str(project)])


def test_01_parse_project(dbt_project: Path) -> None:
    """Parsing discovers the seed, models, and their dependencies."""
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


def test_02_select_model_and_ancestors(dbt_project: Path) -> None:
    """Selecting a model with + includes its upstream seed and model."""
    result = _invoke(dbt_project, "list", "--select", "+mart_people", "--resource-type", "model", "seed")

    assert result.success, result.exception
    assert set(result.result) == {"custom_test_dbt.people", "custom_test_dbt.stg_people", "custom_test_dbt.mart_people"}


def test_03_build_and_query_models(dbt_project: Path, starrocks_connection: MySQLConnection) -> None:
    """Build table/view models, run column tests, and verify relation types and rows."""
    result = _invoke(dbt_project, "build")

    assert result.success, result.exception
    assert isinstance(result.result, RunExecutionResult)
    assert len(result.result.results) == 7  # One seed, two models, four column tests.
    assert {node.status for node in result.result.results} == {"success", "pass"}

    with starrocks_connection.cursor() as cursor:
        cursor.execute(
            "select TABLE_NAME, TABLE_TYPE from information_schema.tables "
            "where TABLE_SCHEMA = %s and TABLE_NAME in ('stg_people', 'mart_people') order by TABLE_NAME",
            (dbt_project.name,),
        )
        assert cursor.fetchall() == [("mart_people", "BASE TABLE"), ("stg_people", "VIEW")]

        cursor.execute(f"select id, name from `{dbt_project.name}`.mart_people order by id")
        assert cursor.fetchall() == [
            (1, "ADA"),
            (2, "GRACE"),
            (3, "ALAN"),
        ]


def test_04_run_data_tests(dbt_project: Path) -> None:
    """The test command checks the built models independently of build."""
    built = _invoke(dbt_project, "build")
    assert built.success, built.exception

    result = _invoke(dbt_project, "test")

    assert result.success, result.exception
    assert isinstance(result.result, RunExecutionResult)
    assert len(result.result.results) == 4
    assert {node.status for node in result.result.results} == {"pass"}
