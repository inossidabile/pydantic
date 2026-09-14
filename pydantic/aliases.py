"""Support for alias configurations."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from types import EllipsisType
from typing import Any, Literal

from pydantic_core import PydanticUndefined

__all__ = ('AliasGenerator', 'AliasPath', 'AliasChoices')


def _resolve_path(value: Any, path: list[int | str | EllipsisType]) -> Any:
    v = value
    for i, k in enumerate(path):
        if k is Ellipsis:
            # map the rest of the path over every element of the list/tuple found so far, and
            # collect the results (dropping elements where the rest of the path doesn't resolve)
            if not isinstance(v, (list, tuple)):
                return PydanticUndefined
            rest = path[i + 1 :]
            resolved = (_resolve_path(item, rest) for item in v)
            return [item for item in resolved if item is not PydanticUndefined]
        if isinstance(v, str):
            # disallow indexing into a str, like for AliasPath('x', 0) and x='abc'
            return PydanticUndefined
        try:
            v = v[k]
        except (KeyError, IndexError, TypeError):
            return PydanticUndefined
    return v


@dataclasses.dataclass(slots=True)
class AliasPath:
    """!!! abstract "Usage Documentation"
        [`AliasPath` and `AliasChoices`](../concepts/alias.md#aliaspath-and-aliaschoices)

    A data class used by `validation_alias` as a convenience to create aliases.

    Attributes:
        path: A list of string or integer aliases, optionally containing a single `...` (`Ellipsis`)
            wildcard item. The wildcard maps the rest of the path over every element of the list found
            at that point and collects the results into a new list, e.g.
            `AliasPath('authors', ..., 'name')` reads `data['authors'][i]['name']` for every `i` and
            validates the field against the resulting list of names.
    """

    path: list[int | str | EllipsisType]

    def __init__(self, first_arg: str, *args: str | int | EllipsisType) -> None:
        self.path = [first_arg] + list(args)

    def convert_to_aliases(self) -> list[str | int | EllipsisType]:
        """Converts arguments to a list of string or integer aliases.

        Returns:
            The list of aliases.
        """
        return self.path

    def search_dict_for_path(self, d: dict) -> Any:
        """Searches a dictionary for the path specified by the alias.

        Returns:
            The value at the specified path, or `PydanticUndefined` if the path is not found. If the
            path contains a `...` wildcard, this is instead the (possibly empty) list of values
            collected from every element the wildcard matched.
        """
        return _resolve_path(d, self.path)


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
