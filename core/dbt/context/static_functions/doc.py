from typing import TYPE_CHECKING

from dbt.exceptions import DocArgsError, DocTargetNotFoundError

if TYPE_CHECKING:
    from dbt.context.docs import DocsRuntimeContext


def resolve_doc(context: "DocsRuntimeContext", *args: str) -> str:
    """Resolve a docs block and record its use for partial parsing."""
    if len(args) == 1:
        doc_package_name = None
        doc_name = args[0]
    elif len(args) == 2:
        doc_package_name, doc_name = args
    else:
        raise DocArgsError(context.node, args)

    target_doc = context.manifest.resolve_doc(
        doc_name,
        doc_package_name,
        context._project_name,
        context.node.package_name,
    )
    if target_doc:
        file_id = target_doc.file_id
        if file_id in context.manifest.files:
            source_file = context.manifest.files[file_id]
            # TODO CT-211
            source_file.add_node(context.node.unique_id)  # type: ignore[union-attr]
    else:
        raise DocTargetNotFoundError(
            node=context.node, target_doc_name=doc_name, target_doc_package=doc_package_name
        )

    return target_doc.block_contents
