from unittest.mock import MagicMock

import pytest

from dbt.contracts.graph.manifest import Manifest, ManifestMetadata
from dbt.contracts.graph.nodes import Documentation
from dbt.node_types import NodeType
from dbt.parser.manifest import _get_doc_blocks


class TestGetDocBlocks:
    def test_name_node_arg_does_not_raise(self):
        """doc() with a variable reference (Name node, no .value) must not raise AttributeError."""
        manifest = MagicMock()
        # {{ doc(my_variable) }} produces a jinja2.nodes.Name arg, not a Const
        result = _get_doc_blocks("{{ doc(my_variable) }}", manifest, "my_package")
        assert result == []

    def test_const_arg_resolves_doc_block(self):
        """doc() with a string literal still resolves to a doc_block unique_id."""
        manifest = MagicMock()
        manifest.metadata.project_name = "my_project"
        resolved = MagicMock()
        resolved.unique_id = "doc.my_project.my_doc"
        manifest.resolve_doc.return_value = resolved

        result = _get_doc_blocks("{{ doc('my_doc') }}", manifest, "my_package")

        assert result == ["doc.my_project.my_doc"]
        manifest.resolve_doc.assert_called_once_with("my_doc", None, "my_project", "my_package")

    def test_mixed_args_skips_name_nodes(self):
        """When one arg is a Name node and others are Const, only Const values are used."""
        manifest = MagicMock()
        manifest.metadata.project_name = "my_project"
        manifest.resolve_doc.return_value = None

        # doc(my_var) — one Name arg → doc_args becomes [] → falls through to else: continue
        result = _get_doc_blocks("{{ doc(my_var) }}", manifest, "my_package")
        assert result == []
        manifest.resolve_doc.assert_not_called()


@pytest.mark.parametrize(
    "description",
    [
        "{{ doc('my_doc') }}",
        "{% if true %}{{ doc('my_doc') }}{% endif %}",
        "{% if false %}unused{% else %}{{ doc('my_doc') }}{% endif %}",
        "{% if false %}unused{% elif true %}{{ doc('my_doc') }}{% endif %}",
        "{% for item in [1] %}{{ doc('my_doc') }}{% endfor %}",
        "{% if true %}{% for item in [1] %}{{ doc('my_doc') }}{% endfor %}{% endif %}",
        "{% set contents = doc('my_doc') %}{{ contents }}",
        "{{ doc('my_doc') | upper }}",
        "{{ doc('my_project', 'my_doc') }}",
    ],
)
def test_doc_blocks_in_jinja_statements(description):
    doc = Documentation(
        name="my_doc",
        unique_id="doc.my_project.my_doc",
        package_name="my_project",
        resource_type=NodeType.Documentation,
        path="docs.md",
        original_file_path="models/docs.md",
        block_contents="Documentation.",
    )
    manifest = Manifest(
        docs={doc.unique_id: doc}, metadata=ManifestMetadata(project_name="my_project")
    )
    assert _get_doc_blocks(description, manifest, "my_project") == ["doc.my_project.my_doc"]


def test_jinja_statements_without_doc_blocks():
    assert _get_doc_blocks("{% if true %}description{% endif %}", Manifest(), "my_project") == []


@pytest.mark.parametrize(
    "description",
    [
        "{{ doc(package_name, 'my_doc') }}",
        "{{ doc('my_project', doc_name) }}",
        "{{ doc('my_project', 'my_doc', extra_arg) }}",
        "{{ doc(*doc_args) }}",
        "{{ doc('my_doc', *extra_args) }}",
        "{{ namespace.doc('my_doc') }}",
    ],
)
def test_dynamic_or_namespaced_doc_calls_are_not_statically_resolved(description):
    manifest = MagicMock()
    manifest.metadata.project_name = "my_project"
    assert _get_doc_blocks(description, manifest, "my_project") == []
    manifest.resolve_doc.assert_not_called()


def test_unexecuted_missing_doc_does_not_raise_during_static_scan():
    manifest = Manifest(metadata=ManifestMetadata(project_name="my_project"))
    description = "{% if false %}{{ doc('missing') }}{% endif %}"
    assert _get_doc_blocks(description, manifest, "my_project") == []
