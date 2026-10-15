import pytest
from dbt_common.dataclass_schema import ValidationError
from metricflow_semantic_interfaces.implementations.elements.dimension import (
    PydanticDimension,
)

from dbt.artifacts.resources import ColumnDimension, ColumnInfo, Dimension
from dbt.contracts.graph.unparsed import UnparsedDerivedDimensionV2, UnparsedDimension
from dbt.parser.schema_yaml_readers import SemanticModelParser

MAPPING = {
    "semantic_model": "status_codes",
    "value_dimension": "raw_value",
    "display_dimension": "display_value",
}


@pytest.mark.parametrize("kind", ["v1", "column", "derived"])
def test_parser_preserves_value_mapping(kind):
    """All supported YAML forms must reach both manifest contracts."""
    data = {"name": "status", "type": "categorical", "value_mapping": MAPPING}
    parser = object.__new__(SemanticModelParser)
    if kind == "v1":
        dimensions = parser._get_dimensions([UnparsedDimension.from_dict(data)])
    elif kind == "column":
        column = ColumnInfo(name="code", dimension=ColumnDimension.from_dict(data))
        dimensions = parser._parse_v2_column_dimensions({"code": column})
    else:
        dimensions = parser._parse_v2_derived_dimensions(
            [UnparsedDerivedDimensionV2.from_dict({**data, "expr": "cast(code as integer)"})]
        )
    raw = dimensions[0].to_dict()
    assert raw["value_mapping"] == MAPPING
    native = PydanticDimension.parse_obj(raw)
    assert native.value_mapping.dict() == MAPPING
    if kind == "column":
        assert dimensions[0].expr == "code"
    if kind == "derived":
        assert dimensions[0].expr == "cast(code as integer)"


def test_old_dimension_round_trip_has_no_mapping():
    dimension = Dimension.from_dict({"name": "status", "type": "categorical"})
    assert dimension.value_mapping is None
    assert Dimension.from_dict(dimension.to_dict()).value_mapping is None


@pytest.mark.parametrize(
    "mapping",
    [{}, {**MAPPING, "unknown": "bad"}, {**MAPPING, "value_dimension": 123}],
)
def test_mapping_schema_rejects_invalid_fields(mapping):
    with pytest.raises(ValidationError):
        UnparsedDimension.validate(
            {"name": "status", "type": "categorical", "value_mapping": mapping}
        )
