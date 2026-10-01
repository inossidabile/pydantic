"""Support for alias configurations."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from types import EllipsisType
from typing import Any, Literal

from pydantic_core import PydanticUndefined

__all__ = ('AliasGenerator', 'AliasPath', 'AliasChoices')


@dataclasses.dataclass(slots=True)
class AliasPath:
    """!!! abstract "Usage Documentation"
        [`AliasPath` and `AliasChoices`](../concepts/alias.md#aliaspath-and-aliaschoices)

    A data class used by `validation_alias` as a convenience to create aliases.

    Attributes:
        path: A list of string or integer aliases, or `...` (`Ellipsis`) segments. `...` acts as a
            wildcard that maps the remaining path over every item of the sequence found there - see
            [`search_dict_for_path`][pydantic.aliases.AliasPath.search_dict_for_path] for details.
    """

    path: list[int | str | EllipsisType]

    def __init__(self, first_arg: str, *args: str | int | EllipsisType) -> None:
        self.path = [first_arg] + list(args)

    def convert_to_aliases(self) -> list[str | int | EllipsisType]:
        """Converts arguments to a list of string or integer aliases, or `...` (`Ellipsis`) segments.

        Returns:
            The list of aliases.
        """
        return self.path

    def search_dict_for_path(self, d: dict) -> Any:
        """Searches a dictionary for the path specified by the alias.

        A `...` (`Ellipsis`) segment acts as a wildcard: the remaining path is mapped over every item
        of the sequence found there (a bare trailing `...` returns each item unchanged), and items for
        which the remaining path can't be resolved are omitted rather than causing the whole lookup to
        fail. If the value at a wildcard position isn't a sequence, the lookup is treated as not found.

        Returns:
            The value at the specified path, or `PydanticUndefined` if the path is not found.
        """
        v = d
        for i, k in enumerate(self.path):
            if k is ...:
                return _resolve_wildcard_path(v, self.path[i:])
            if isinstance(v, str):
                # disallow indexing into a str, like for AliasPath('x', 0) and x='abc'
                return PydanticUndefined
            try:
                v = v[k]
            except (KeyError, IndexError, TypeError):
                return PydanticUndefined
        return v


def _resolve_wildcard_path(value: Any, rest: list[int | str | EllipsisType]) -> Any:
    """Resolves `rest` (whose first element must be `...`) against `value`, forking at each wildcard
    segment by mapping the remaining path over every item of the sequence found there. Items for which
    the remaining path can't be resolved are omitted rather than causing the whole lookup to fail.
    """
    if not rest:
        return value
    first, remaining = rest[0], rest[1:]
    if first is ...:
        items = _wildcard_items(value)
        if items is None:
            return PydanticUndefined
        resolved = [
            r for item in items if (r := _resolve_wildcard_path(item, remaining)) is not PydanticUndefined
        ]
        return resolved
    if isinstance(value, str):
        return PydanticUndefined
    try:
        next_value = value[first]
    except (KeyError, IndexError, TypeError):
        return PydanticUndefined
    return _resolve_wildcard_path(next_value, remaining)


def _wildcard_items(value: Any) -> list[Any] | None:
    """If `value` isn't a sequence, it's not found (not an error) - we never want to iterate over e.g.
    strings, bytes, bytearrays or mappings as if they were a sequence of items.

    Enumerates via an explicit `len()` followed by indexing, rather than `list(value)`, so that any
    exception raised by `__len__` propagates unconditionally - `list()` would otherwise swallow a
    `TypeError` from `__len__` internally (via `operator.length_hint`), unlike the core validator.
    """
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    length = len(value)
    return [value[i] for i in range(length)]


@dataclasses.dataclass(slots=True)
class AliasChoices:
    """!!! abstract "Usage Documentation"
        [`AliasPath` and `AliasChoices`](../concepts/alias.md#aliaspath-and-aliaschoices)

    A data class used by `validation_alias` as a convenience to create aliases.

    Attributes:
        choices: A list containing a string or `AliasPath`.
    """

    choices: list[str | AliasPath]

    def __init__(self, first_choice: str | AliasPath, *choices: str | AliasPath) -> None:
        self.choices = [first_choice] + list(choices)

    def convert_to_aliases(self) -> list[list[str | int | EllipsisType]]:
        """Converts arguments to a list of lists containing string or integer aliases.

        Returns:
            The list of aliases.
        """
        aliases: list[list[str | int | EllipsisType]] = []
        for c in self.choices:
            if isinstance(c, AliasPath):
                aliases.append(c.convert_to_aliases())
            else:
                aliases.append([c])
        return aliases


@dataclasses.dataclass(slots=True)
class AliasGenerator:
    """!!! abstract "Usage Documentation"
        [Using an `AliasGenerator`](../concepts/alias.md#using-an-aliasgenerator)

    A data class used by `alias_generator` as a convenience to create various aliases.

    Attributes:
        alias: A callable that takes a field name and returns an alias for it.
        validation_alias: A callable that takes a field name and returns a validation alias for it.
        serialization_alias: A callable that takes a field name and returns a serialization alias for it.
    """

    alias: Callable[[str], str] | None = None
    validation_alias: Callable[[str], str | AliasPath | AliasChoices] | None = None
    serialization_alias: Callable[[str], str] | None = None

    def _generate_alias(
        self,
        alias_kind: Literal['alias', 'validation_alias', 'serialization_alias'],
        allowed_types: tuple[type[str] | type[AliasPath] | type[AliasChoices], ...],
        field_name: str,
    ) -> str | AliasPath | AliasChoices | None:
        """Generate an alias of the specified kind. Returns None if the alias generator is None.

        Raises:
            TypeError: If the alias generator produces an invalid type.
        """
        alias = None
        alias_generator = getattr(self, alias_kind)

        if alias_generator is not None:
            alias = alias_generator(field_name)
            if alias is not None and not isinstance(alias, allowed_types):
                raise TypeError(
                    f'Invalid `{alias_kind}` type. `{alias_kind}` generator must produce one of `{allowed_types}`'
                )
        return alias

    def generate_aliases(self, field_name: str) -> tuple[str | None, str | AliasPath | AliasChoices | None, str | None]:
        """Generate `alias`, `validation_alias`, and `serialization_alias` for a field.

        Returns:
            A tuple of three aliases - alias, validation, and serialization.
        """
        alias = self._generate_alias('alias', (str,), field_name)
        validation_alias = self._generate_alias('validation_alias', (str, AliasChoices, AliasPath), field_name)
        serialization_alias = self._generate_alias('serialization_alias', (str,), field_name)

        return alias, validation_alias, serialization_alias  # type: ignore
