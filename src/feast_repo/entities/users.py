"""User entity for Feast."""

from feast import Entity
from feast.value_type import ValueType

user = Entity(
    name="user",
    join_keys=["user_id"],
    value_type=ValueType.STRING,
    description="End user of the application",
)
