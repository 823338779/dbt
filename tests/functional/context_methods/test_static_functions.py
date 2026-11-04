import pytest

from dbt.tests.util import check_relations_equal, get_artifact, run_dbt


class TestStaticRefDocBuild:
    @pytest.fixture(scope="class")
    def project_config_update(self):
        return {"name": "static_functions", "models": {"+materialized": "view"}}

    @pytest.fixture(scope="class")
    def models(self):
        return {
            "base.sql": "select {{ one() }} as id",
            "derived.sql": """
                {% if true %}
                    {% for model_name in ['base'] %}
                        select * from {{ ref(model_name) }}
                    {% endfor %}
                {% endif %}
            """,
            "schema.yml": """
version: 2
models:
  - name: derived
    description: "{% if true %}{{ doc('derived_doc') }}{% endif %}"
            """,
            "docs.md": "{% docs derived_doc %}Derived model documentation.{% enddocs %}",
        }

    @pytest.fixture(scope="class")
    def macros(self):
        return {
            "ref.sql": """
                {% macro ref(name) %}
                    {{ exceptions.raise_compiler_error('ref macro must not run') }}
                {% endmacro %}
            """,
            "one.sql": "{% macro one() %}1{% endmacro %}",
        }

    def test_build_uses_static_ref_and_doc(self, project):
        results = run_dbt(["--no-partial-parse", "build"])
        assert len(results) == 2
        check_relations_equal(project.adapter, ["base", "derived"])

        manifest = get_artifact(project.project_root, "target", "manifest.json")
        derived = manifest["nodes"]["model.static_functions.derived"]
        assert derived["depends_on"]["nodes"] == ["model.static_functions.base"]
        assert '"base"' in derived["compiled_code"]
        assert derived["description"] == "Derived model documentation."
