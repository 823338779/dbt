import pytest

from dbt.tests.util import check_relations_equal, run_dbt

models__ref_override_sql = """
select
    *
from {{ ref('seed_1') }}
"""

macros__ref_override_macro_sql = """
-- Explicitly callable as test.ref; unqualified ref keeps the built-in behavior
{% macro ref(modelname) %}
{% do return(builtins.ref(modelname).replace_path(identifier='seed_2')) %}
{% endmacro %}
"""

seeds__seed_2_csv = """a,b
6,2
12,4
18,6"""

seeds__seed_1_csv = """a,b
1,2
2,4
3,6"""


class TestRefOverride:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "ref_override.sql": models__ref_override_sql,
            "builtin_ref.sql": "select * from {{ builtins.ref('seed_1') }}",
            "explicit_ref_override.sql": "select * from {{ test.ref('seed_1') }}",
        }

    @pytest.fixture(scope="class")
    def macros(self):
        return {"ref_override_macro.sql": macros__ref_override_macro_sql}

    @pytest.fixture(scope="class")
    def seeds(self):
        return {"seed_2.csv": seeds__seed_2_csv, "seed_1.csv": seeds__seed_1_csv}

    def test_ref_override(
        self,
        project,
    ):
        run_dbt(["seed"])
        run_dbt(["run"])

        # Top-level ref and builtins.ref keep the original target. A package
        # qualifier explicitly opts into the project's custom ref macro.
        check_relations_equal(project.adapter, ["ref_override", "builtin_ref", "seed_1"])
        check_relations_equal(project.adapter, ["explicit_ref_override", "seed_2"])


models__version_ref_override_sql = """
select
    *
from {{ ref('versioned_model', version=1) }}
"""

models__package_ref_override_sql = """
select
    *
from {{ ref('test', 'versioned_model') }}
"""

models__package_version_ref_override_sql = """
select
    *
from {{ ref('test', 'versioned_model', version=1) }}
"""

models__v1_sql = """
select 1
"""

models__v2_sql = """
select 2
"""

schema__versions_yml = """
models:
  - name: versioned_model
    versions:
      - v: 1
      - v: 2
"""

macros__package_version_ref_override_macro_sql = """
-- Explicitly callable as test.ref; unqualified ref keeps the built-in behavior
{% macro ref() %}
-- extract user-provided positional and keyword arguments
{% set version = kwargs.get('version') %}
{% set packagename = none %}
{%- if (varargs | length) == 1 -%}
    {% set modelname = varargs[0] %}
{%- else -%}
    {% set packagename = varargs[0] %}
    {% set modelname = varargs[1] %}
{% endif %}

{%- set version_override = 2 -%}
{%- set packagename_override = 'test' -%}
-- call builtins.ref based on provided positional arguments
{% if packagename is not none %}
    {% do return(builtins.ref(packagename_override, modelname, version=version_override)) %}
{% else %}
    {% do return(builtins.ref(modelname, version=version_override)) %}
{% endif %}

{% endmacro %}
"""


class TestAdvancedRefOverride:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "version_ref_override.sql": models__version_ref_override_sql,
            "package_ref_override.sql": models__package_ref_override_sql,
            "package_version_ref_override.sql": models__package_version_ref_override_sql,
            "builtin_version_ref.sql": "select * from {{ builtins.ref('versioned_model', v=1) }}",
            "explicit_version_ref_override.sql": "select * from {{ test.ref('versioned_model', version=1) }}",
            "explicit_package_ref_override.sql": "select * from {{ test.ref('package', 'versioned_model') }}",
            "explicit_package_version_ref_override.sql": "select * from {{ test.ref('package', 'versioned_model', version=1) }}",
            "versioned_model_v1.sql": models__v1_sql,
            "versioned_model_v2.sql": models__v2_sql,
            "model.sql": models__v1_sql,
            "schema.yml": schema__versions_yml,
        }

    @pytest.fixture(scope="class")
    def macros(self):
        return {"ref_override_macro.sql": macros__package_version_ref_override_macro_sql}

    def test_ref_override(
        self,
        project,
    ):
        run_dbt(["run"])

        # The built-in respects version=1 and the real package name instead of
        # allowing a same-name macro to rewrite them to another target.
        check_relations_equal(
            project.adapter,
            [
                "version_ref_override",
                "package_version_ref_override",
                "builtin_version_ref",
                "versioned_model_v1",
            ],
        )
        check_relations_equal(project.adapter, ["package_ref_override", "versioned_model_v2"])

        # Explicit package-qualified macro calls retain the custom v1 -> v2 and
        # package -> test rewriting, including their internal builtins.ref calls.
        check_relations_equal(
            project.adapter,
            [
                "explicit_version_ref_override",
                "explicit_package_ref_override",
                "explicit_package_version_ref_override",
                "versioned_model_v2",
            ],
        )
