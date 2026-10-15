import json

import pytest
import yaml

from dbt.cli.main import dbtRunner


def mapping_project(tmp_path, initial_mapping):
    """Create a real parseable project without a server dependency."""
    (tmp_path / "models").mkdir()
    (tmp_path / "dbt_project.yml").write_text(
        "name: mapping_test\nversion: '1.0'\nconfig-version: 2\nprofile: mapping_test\n",
        encoding="utf-8",
    )
    (tmp_path / "profiles.yml").write_text(
        "mapping_test:\n  target: dev\n  outputs:\n    dev:\n"
        "      type: duckdb\n      path: ':memory:'\n      threads: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "models" / "requests.sql").write_text(
        "select 1 as id, 502 as status, cast('2026-01-01' as date) as ds",
        encoding="utf-8",
    )
    (tmp_path / "models" / "time_spine.sql").write_text(
        "select cast('2026-01-01' as date) as ds", encoding="utf-8"
    )
    for name in ("status_codes", "other_codes"):
        (tmp_path / "models" / (name + ".sql")).write_text(
            "select 502 as raw_value, 'failed' as display_value", encoding="utf-8"
        )
    status = {"name": "status", "type": "categorical"}
    if initial_mapping:
        status["value_mapping"] = {
            "semantic_model": "status_codes",
            "value_dimension": "raw_value",
            "display_dimension": "display_value",
        }
    schema = {
        "version": 2,
        "models": [
            {
                "name": "time_spine",
                "time_spine": {"standard_granularity_column": "ds"},
                "columns": [{"name": "ds", "granularity": "day"}],
            }
        ],
        "semantic_models": [
            {
                "name": "requests",
                "model": "ref('requests')",
                "defaults": {"agg_time_dimension": "ds"},
                "entities": [{"name": "request", "type": "primary", "expr": "id"}],
                "dimensions": [
                    status,
                    {"name": "ds", "type": "time", "type_params": {"time_granularity": "day"}},
                ],
                "measures": [
                    {"name": "requests_count", "agg": "sum", "expr": "1", "create_metric": True}
                ],
            },
            *[
                {
                    "name": name,
                    "model": "ref('" + name + "')",
                    "entities": [{"name": name + "_key", "type": "primary", "expr": "raw_value"}],
                    "dimensions": [
                        {"name": "raw_value", "type": "categorical"},
                        {"name": "display_value", "type": "categorical"},
                    ],
                }
                for name in ("status_codes", "other_codes")
            ],
        ],
    }
    return schema


@pytest.mark.parametrize("change", ["add", "change", "remove", "target_delete"])
def test_value_mapping_survives_full_and_partial_parse(tmp_path, change):
    """Actual msgpack reuse must not retain removed or outdated mapping references."""
    schema = mapping_project(tmp_path, initial_mapping=change != "add")
    schema_path = tmp_path / "models" / "schema.yml"
    schema_path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    args = ["parse", "--project-dir", str(tmp_path), "--profiles-dir", str(tmp_path)]
    initial = dbtRunner().invoke([*args, "--no-partial-parse"])
    assert initial.success, initial.exception
    assert (tmp_path / "target" / "partial_parse.msgpack").exists()
    old_model = initial.result.semantic_models["semantic_model.mapping_test.requests"]
    status = schema["semantic_models"][0]["dimensions"][0]
    if change == "add":
        status["value_mapping"] = {
            "semantic_model": "other_codes",
            "value_dimension": "raw_value",
            "display_dimension": "display_value",
        }
    elif change == "change":
        status["value_mapping"]["semantic_model"] = "other_codes"
    elif change == "remove":
        del status["value_mapping"]
    else:
        schema["semantic_models"] = [
            model for model in schema["semantic_models"] if model["name"] != "status_codes"
        ]
    schema_path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    updated = dbtRunner().invoke([*args, "--partial-parse"])
    if change == "target_delete":
        assert not updated.success
        return
    assert updated.success, updated.exception
    new_model = updated.result.semantic_models["semantic_model.mapping_test.requests"]
    assert not new_model.same_contents(old_model)
    manifest = json.loads((tmp_path / "target" / "manifest.json").read_text(encoding="utf-8"))
    semantic = json.loads(
        (tmp_path / "target" / "semantic_manifest.json").read_text(encoding="utf-8")
    )
    native_model = manifest["semantic_models"]["semantic_model.mapping_test.requests"]
    semantic_model = next(
        model for model in semantic["semantic_models"] if model["name"] == "requests"
    )
    native_status = next(item for item in native_model["dimensions"] if item["name"] == "status")
    semantic_status = next(
        item for item in semantic_model["dimensions"] if item["name"] == "status"
    )
    assert native_status.get("value_mapping") == semantic_status.get("value_mapping")
    if change == "remove":
        assert semantic_status.get("value_mapping") is None
    else:
        assert semantic_status["value_mapping"]["semantic_model"] == "other_codes"
