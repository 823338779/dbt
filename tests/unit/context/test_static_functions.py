from functools import partial

import pytest

from dbt.artifacts.resources import RefArgs
from dbt.clients.jinja import get_rendered
from dbt.context.docs import DocsRuntimeContext
from dbt.context.macro_resolver import MacroResolver
from dbt.context.providers import (
    ModelContext,
    OperationProvider,
    ParseProvider,
    RuntimeProvider,
    RuntimeUnitTestProvider,
)
from dbt.context.providers import TestContext as GenericTestContext
from dbt.contracts.files import FileHash, FilePath, SourceFile
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.graph.nodes import Documentation, UnitTestNode
from dbt.exceptions import (
    CompilationError,
    DocArgsError,
    DocTargetNotFoundError,
    OperationsCannotRefEphemeralNodesError,
    RefArgsError,
    RefBadContextError,
    TargetNotFoundError,
)
from dbt.node_types import NodeType
from tests.unit.utils.manifest import make_macro, make_model


@pytest.fixture
def model(runtime_config):
    return make_model(runtime_config.project_name, "derived", "select 1")


@pytest.fixture
def manifest(model):
    upstream = make_model(model.package_name, "upstream", "select 1")
    model.depends_on.nodes.append(upstream.unique_id)
    return Manifest(nodes={model.unique_id: model, upstream.unique_id: upstream})


@pytest.fixture
def parse_context(model, runtime_config, manifest, postgres_adapter):
    return ModelContext(model, runtime_config, manifest, ParseProvider(), None)


@pytest.fixture
def docs_context(model, runtime_config, manifest):
    doc = Documentation(
        name="derived_doc",
        unique_id=f"doc.{model.package_name}.derived_doc",
        package_name=model.package_name,
        resource_type=NodeType.Documentation,
        path="docs.md",
        original_file_path="models/docs.md",
        block_contents="Documentation for the derived model.",
    )
    manifest.docs[doc.unique_id] = doc
    source_file = SourceFile(
        path=FilePath("models", "docs.md", 0.0, "/project"),
        checksum=FileHash.from_contents(doc.block_contents),
        project_name=model.package_name,
    )
    manifest.files[doc.file_id] = source_file
    return DocsRuntimeContext(runtime_config, model, manifest, model.package_name)


def test_static_ref_entry_point_records_dependency(parse_context):
    from dbt.context.static_functions.ref import resolve_ref

    ref = parse_context.to_dict()["ref"]
    assert isinstance(ref, partial)
    assert ref.func is resolve_ref
    relation = resolve_ref(ref.args[0], "upstream", version=2)
    assert parse_context.model.refs == [RefArgs(name="upstream", package=None, version=2)]
    assert relation.identifier == "derived"


def test_static_doc_entry_point_records_file_reference(docs_context):
    from dbt.context.static_functions.doc import resolve_doc

    doc = docs_context.to_dict()["doc"]
    assert isinstance(doc, partial)
    assert doc.func is resolve_doc
    assert resolve_doc(docs_context, "derived_doc") == "Documentation for the derived model."
    source_file = next(iter(docs_context.manifest.files.values()))
    assert source_file.nodes == [docs_context.node.unique_id]


@pytest.mark.parametrize("test_namespace", [False, True])
def test_ref_macro_cannot_override_builtin(
    model, runtime_config, manifest, postgres_adapter, test_namespace
):
    custom_macros = [
        make_macro(model.package_name, "ref", "{% macro ref(name) %}overridden{% endmacro %}"),
        make_macro(
            model.package_name, "source", "{% macro source(a, b) %}custom source{% endmacro %}"
        ),
        make_macro(
            model.package_name, "caller", "{% macro caller() %}{{ ref('upstream') }}{% endmacro %}"
        ),
    ]
    manifest.macros.update({macro.unique_id: macro for macro in custom_macros})
    model.depends_on.macros.extend(manifest.macros)
    if test_namespace:
        context = GenericTestContext(
            model,
            runtime_config,
            manifest,
            ParseProvider(),
            None,
            MacroResolver(manifest.macros, model.package_name, ["dbt"]),
        )
    else:
        context = ModelContext(model, runtime_config, manifest, ParseProvider(), None)
    ctx = context.to_dict()

    assert ctx["ref"] is ctx["builtins"]["ref"]
    assert ctx["context"] is ctx
    assert ctx["ref"]("upstream").identifier == "derived"
    assert get_rendered("{{ caller() }}", ctx) == '"dbt"."dbt_schema"."derived"'
    assert model.refs == [RefArgs(name="upstream"), RefArgs(name="upstream")]
    assert ctx[model.package_name]["ref"]("upstream") == "overridden"
    assert ctx["source"]("a", "b") == "custom source"


@pytest.mark.parametrize(
    "args,kwargs,expected",
    [
        (("upstream",), {}, RefArgs(name="upstream")),
        (("package", "upstream"), {}, RefArgs(name="upstream", package="package")),
        (("upstream",), {"version": 2}, RefArgs(name="upstream", version=2)),
        (("upstream",), {"v": "2"}, RefArgs(name="upstream", version="2")),
        (("upstream",), {"version": 2, "v": 3}, RefArgs(name="upstream", version=2)),
        (("upstream",), {"version": 0, "v": 3}, RefArgs(name="upstream", version=3)),
        (("upstream",), {"custom_kwarg": "value"}, RefArgs(name="upstream")),
    ],
)
def test_static_ref_preserves_arguments(parse_context, args, kwargs, expected):
    parse_context.to_dict()["ref"](*args, **kwargs)
    assert parse_context.model.refs == [expected]


@pytest.mark.parametrize(
    "args,kwargs,error",
    [
        ((), {}, RefArgsError),
        (("a", "b", "c"), {}, RefArgsError),
        ((123,), {}, CompilationError),
        ((123, "upstream"), {}, CompilationError),
        (("upstream",), {"version": [2]}, CompilationError),
    ],
)
def test_static_ref_preserves_validation(parse_context, args, kwargs, error):
    with pytest.raises(error):
        parse_context.to_dict()["ref"](*args, **kwargs)
    assert parse_context.model.refs == []


@pytest.mark.parametrize("provider", [RuntimeProvider, OperationProvider, RuntimeUnitTestProvider])
def test_static_ref_uses_runtime_resolver(
    model, runtime_config, manifest, postgres_adapter, provider
):
    if provider is RuntimeUnitTestProvider:
        model = UnitTestNode.from_dict({**model.to_dict(), "resource_type": NodeType.Unit})
    ctx = ModelContext(model, runtime_config, manifest, provider(), None).to_dict()
    relation = ctx["ref"]("upstream")
    assert relation.identifier == "upstream"
    assert relation.schema == "dbt_schema"
    assert model.refs == []


@pytest.mark.parametrize("provider", [RuntimeProvider, RuntimeUnitTestProvider])
def test_static_ref_keeps_runtime_dependency_validation(
    model, runtime_config, manifest, postgres_adapter, provider
):
    model.depends_on.nodes.clear()
    if provider is RuntimeUnitTestProvider:
        model = UnitTestNode.from_dict({**model.to_dict(), "resource_type": NodeType.Unit})
    ctx = ModelContext(model, runtime_config, manifest, provider(), None).to_dict()
    with pytest.raises(RefBadContextError):
        ctx["ref"]("upstream")


def test_static_ref_operation_can_resolve_without_parse_dependency(
    model, runtime_config, manifest, postgres_adapter
):
    model.depends_on.nodes.clear()
    ctx = ModelContext(model, runtime_config, manifest, OperationProvider(), None).to_dict()
    assert ctx["ref"]("upstream").identifier == "upstream"


def test_static_ref_operation_rejects_ephemeral(model, runtime_config, manifest, postgres_adapter):
    upstream = manifest.nodes[f"model.{model.package_name}.upstream"]
    upstream.config.materialized = "ephemeral"
    ctx = ModelContext(model, runtime_config, manifest, OperationProvider(), None).to_dict()
    with pytest.raises(OperationsCannotRefEphemeralNodesError):
        ctx["ref"]("upstream")


def test_static_ref_runtime_rejects_missing_target(
    model, runtime_config, manifest, postgres_adapter
):
    ctx = ModelContext(model, runtime_config, manifest, RuntimeProvider(), None).to_dict()
    with pytest.raises(TargetNotFoundError):
        ctx["ref"]("missing")


def test_static_ref_in_jinja_control_flow(parse_context):
    rendered = get_rendered(
        "{% if false %}{{ ref('ignored') }}{% endif %}"
        "{% for name in ['upstream', 'another'] %}{{ ref(name) }};{% endfor %}",
        parse_context.to_dict(),
    )
    assert rendered == '"dbt"."dbt_schema"."derived";"dbt"."dbt_schema"."derived";'
    assert parse_context.model.refs == [RefArgs(name="upstream"), RefArgs(name="another")]


@pytest.mark.parametrize("qualified", [False, True])
def test_static_doc_in_jinja_if(docs_context, qualified):
    args = "'derived_doc'"
    if qualified:
        args = f"'{docs_context.node.package_name}', {args}"
    rendered = get_rendered(
        "{% if false %}{{ doc('missing') }}{% else %}{{ doc(" + args + ") }}{% endif %}",
        docs_context.to_dict(),
    )
    assert rendered == "Documentation for the derived model."
    source_file = next(iter(docs_context.manifest.files.values()))
    assert source_file.nodes == [docs_context.node.unique_id]


@pytest.mark.parametrize("args", [(), ("a", "b", "c")])
def test_static_doc_preserves_argument_validation(docs_context, args):
    with pytest.raises(DocArgsError):
        docs_context.to_dict()["doc"](*args)


def test_static_doc_rejects_missing_target(docs_context):
    with pytest.raises(DocTargetNotFoundError):
        docs_context.to_dict()["doc"]("missing")


def test_static_doc_allows_missing_source_file(docs_context):
    docs_context.manifest.files.clear()
    assert docs_context.to_dict()["doc"]("derived_doc") == "Documentation for the derived model."


def test_static_doc_returns_empty_contents(docs_context):
    next(iter(docs_context.manifest.docs.values())).block_contents = ""
    assert docs_context.to_dict()["doc"]("derived_doc") == ""
    assert next(iter(docs_context.manifest.files.values())).nodes == [docs_context.node.unique_id]


def test_static_doc_deduplicates_file_references(docs_context):
    doc = docs_context.to_dict()["doc"]
    doc("derived_doc")
    doc(docs_context.node.package_name, "derived_doc")
    assert next(iter(docs_context.manifest.files.values())).nodes == [docs_context.node.unique_id]


def test_static_doc_respects_package(docs_context):
    with pytest.raises(DocTargetNotFoundError):
        docs_context.to_dict()["doc"]("other_package", "derived_doc")


def test_direct_ref_resolver_remains_callable(parse_context):
    resolver = ParseProvider.ref(
        parse_context.db_wrapper,
        parse_context.model,
        parse_context.config,
        parse_context.manifest,
    )
    assert resolver("package", "upstream", v=2).identifier == "derived"
    assert parse_context.model.refs == [RefArgs(name="upstream", package="package", version=2)]
    with pytest.raises(CompilationError):
        resolver(123)


@pytest.mark.parametrize("provider", [RuntimeProvider, RuntimeUnitTestProvider])
def test_static_ref_preserves_ephemeral_ctes(
    model, runtime_config, manifest, postgres_adapter, provider
):
    if provider is RuntimeUnitTestProvider:
        model = UnitTestNode.from_dict({**model.to_dict(), "resource_type": NodeType.Unit})
    upstream = manifest.nodes[f"model.{model.package_name}.upstream"]
    upstream.config.materialized = "ephemeral"
    ctx = ModelContext(model, runtime_config, manifest, provider(), None).to_dict()
    assert ctx["ref"]("upstream").identifier == "__dbt__cte__upstream"
    assert [cte.id for cte in model.extra_ctes] == [upstream.unique_id]
