from typing import TYPE_CHECKING, Optional

from dbt.artifacts.resources import NodeVersion
from dbt.exceptions import RefArgsError

if TYPE_CHECKING:
    from dbt.context.providers import BaseRefResolver, RelationProxy


def resolve_ref(resolver: "BaseRefResolver", *args: str, **kwargs) -> "RelationProxy":
    """Validate a ref call and delegate to the context's parse or runtime resolver."""
    name: str
    package: Optional[str] = None
    version: Optional[NodeVersion] = None

    if len(args) == 1:
        name = args[0]
    elif len(args) == 2:
        package, name = args
    else:
        raise RefArgsError(node=resolver.model, args=args)

    version = kwargs.get("version") or kwargs.get("v")
    resolver.validate_args(name, package, version)
    return resolver.resolve(name, package, version)
