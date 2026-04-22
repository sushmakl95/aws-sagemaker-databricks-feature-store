"""Product entity for Feast."""

from feast import Entity
from feast.value_type import ValueType

product = Entity(
    name="product",
    join_keys=["product_id"],
    value_type=ValueType.STRING,
    description="A purchasable product in the catalog",
)
