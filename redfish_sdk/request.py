"""Public method names and structural query types for generic requests."""
from enum import Enum
from typing import Any, Mapping, Sequence, Tuple, Union


class HttpMethod(str, Enum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


QueryParameters = Union[Mapping[str, Any], Sequence[Tuple[str, Any]]]
_UNSET_BODY = object()
_JSON_NULL = "null"
