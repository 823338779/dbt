from functools import partial
from typing import Any, Callable, Dict, Union

from dbt.config.runtime import RuntimeConfig
from dbt.context.base import contextproperty
from dbt.context.configured import SchemaYamlContext
from dbt.context.static_functions.doc import resolve_doc
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.graph.nodes import Macro, ResultNode


class DocsRuntimeContext(SchemaYamlContext):
    def __init__(
        self,
        config: RuntimeConfig,
        node: Union[Macro, ResultNode],
        manifest: Manifest,
        current_project: str,
    ) -> None:
        super().__init__(config, current_project, None)
        self.node = node
        self.manifest = manifest

    @contextproperty()
    def doc(self) -> Callable:
        """The `doc` function is used to reference docs blocks in schema.yml
        files. It is analogous to the `ref` function. For more information,
        consult the Documentation guide.

        > orders.md:

            {% docs orders %}
            # docs
            - go
            - here
            {% enddocs %}

        > schema.yml

            version: 2
                models:
                  - name: orders
                    description: "{{ doc('orders') }}"
        """
        return partial(resolve_doc, self)


def generate_runtime_docs_context(
    config: RuntimeConfig,
    target: Any,
    manifest: Manifest,
    current_project: str,
) -> Dict[str, Any]:
    ctx = DocsRuntimeContext(config, target, manifest, current_project)
    # This is not a Mashumaro to_dict call
    return ctx.to_dict()
