import json
from collections.abc import Sequence
from typing import Annotated

import pytest
from typing_extensions import TypedDict

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator


class TestAliasPathWildcard:
    @pytest.fixture
    def model(self):
        class Blog(BaseModel):
            name: str
            authors: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        return Blog

    @pytest.fixture
    def data(self):
        return {'name': 'Blog entry', 'authors': [{'name': 'Alice'}, {'name': 'Bob'}]}

    def test_validate_python(self, model, data):
        result = model.model_validate(data)
        assert (result.name, result.authors) == ('Blog entry', ['Alice', 'Bob'])

    def test_validate_json(self, model, data):
        result = model.model_validate_json(json.dumps(data))
        assert (result.name, result.authors) == ('Blog entry', ['Alice', 'Bob'])

    def test_model_construct(self, model, data):
        # model_construct() bypasses the compiled validator entirely and resolves validation
        # aliases via the pure-Python AliasPath.search_dict_for_path (pydantic/main.py's
        # model_construct calls it directly) - a wildcard must be supported there too, not just
        # in the Rust-backed validation path exercised by model_validate/model_validate_json
        result = model.model_construct(**data)
        assert (result.name, result.authors) == ('Blog entry', ['Alice', 'Bob'])

    def test_model_construct_omits_element_failing_past_wildcard(self, model):
        # the same per-element omission rule applies in the pure-Python model_construct path:
        # an element that doesn't resolve past the wildcard is dropped, not an error
        data = {'name': 'x', 'authors': [{'name': 'Alice'}, {}]}
        assert model.model_construct(**data).authors == ['Alice']

    def test_model_construct_nested_wildcards(self):
        # model_construct resolves aliases via the pure-Python AliasPath.search_dict_for_path /
        # _resolve_wildcard_path, a separate implementation from the compiled validator's
        # recursive resolution - recursion must hold there too, not just for a single wildcard
        class Model(BaseModel):
            names: list[list[str]] = Field(validation_alias=AliasPath('groups', ..., ..., 'name'))

        data = {'groups': [[{'name': 'A'}, {'name': 'B'}], [{'name': 'C'}]]}
        assert Model.model_construct(**data).names == [['A', 'B'], ['C']]

    def test_model_construct_nested_wildcard_partial_omission(self):
        # same recursive-omission rule as the compiled validator: only the inner element that
        # fails to resolve past the second wildcard is omitted, via model_construct
        class Model(BaseModel):
            names: list[list[str]] = Field(validation_alias=AliasPath('groups', ..., ..., 'name'))

        data = {'groups': [[{'name': 'A'}, {}], [{'name': 'C'}]]}
        assert Model.model_construct(**data).names == [['A'], ['C']]

    def test_empty_list(self, model):
        data = {'name': 'x', 'authors': []}
        assert model.model_validate(data).authors == []
        assert model.model_validate_json(json.dumps(data)).authors == []

    def test_extra_forbid_does_not_flag_wildcard_root_key_as_extra(self, model, data):
        class Blog(model):
            model_config = ConfigDict(extra='forbid')

        assert Blog.model_validate(data).authors == ['Alice', 'Bob']
        assert Blog.model_validate_json(json.dumps(data)).authors == ['Alice', 'Bob']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_extra_forbid_does_not_flag_any_root_of_multiple_wildcard_choices(self, validate):
        # regression test: with more than one wildcard choice (plus a plain one), every choice's
        # root key must be excluded from extra-forbid detection, not just a single special-cased one
        class Model(BaseModel):
            model_config = ConfigDict(extra='forbid')
            names: list[str] = Field(
                validation_alias=AliasChoices(
                    AliasPath('authors', ..., 'name'),
                    AliasPath('editors', ..., 'name'),
                    'writers',
                )
            )

        for data, expected in [
            ({'authors': [{'name': 'A'}]}, ['A']),
            ({'editors': [{'name': 'E'}]}, ['E']),
            ({'writers': ['W']}, ['W']),
        ]:
            if validate == 'python':
                assert Model.model_validate(data).names == expected
            else:
                assert Model.model_validate_json(json.dumps(data)).names == expected

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_extra_allow_surfaces_unused_wildcard_choice_root(self, validate):
        # under extra='allow', a wildcard choice's root key that goes unused because a different
        # choice resolved instead must still surface as an extra field, exactly as if it had never
        # been exempted - the exemption only ever suppresses the extra='forbid' error, never makes
        # the key vanish
        class Model(BaseModel):
            model_config = ConfigDict(extra='allow')
            names: list[str] = Field(validation_alias=AliasChoices('writers', AliasPath('authors', ..., 'name')))

        data = {'writers': ['X'], 'authors': [{'name': 'A'}]}
        if validate == 'python':
            m = Model.model_validate(data)
        else:
            m = Model.model_validate_json(json.dumps(data))
        assert m.names == ['X']
        assert m.model_extra == {'authors': [{'name': 'A'}]}

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_extra_allow_surfaces_unused_plain_choice_root_when_wildcard_wins(self, validate):
        # the reverse of the above: when the wildcard choice is listed first and wins, the losing
        # plain choice's root key must still surface as an extra field too - the exemption applies
        # symmetrically to every choice's root, not just to a wildcard root specifically
        class Model(BaseModel):
            model_config = ConfigDict(extra='allow')
            field_a: list[str] = Field(validation_alias=AliasChoices(AliasPath('authors', ..., 'name'), 'writers'))

        data = {'authors': [{'name': 'A'}], 'writers': ['X']}
        if validate == 'python':
            m = Model.model_validate(data)
        else:
            m = Model.model_validate_json(json.dumps(data))
        assert m.field_a == ['A']
        assert m.model_extra == {'writers': ['X']}

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_missing_key_in_one_element_is_omitted(self, model, validate):
        # an element that doesn't resolve past the wildcard is omitted, not an error
        data = {'name': 'x', 'authors': [{'name': 'Alice'}, {}]}
        if validate == 'python':
            assert model.model_validate(data).authors == ['Alice']
        else:
            assert model.model_validate_json(json.dumps(data)).authors == ['Alice']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_resolved_value_failing_item_schema_still_raises(self, model, validate):
        # unlike a missing key, a value that resolves and then fails its item schema still errors,
        # with the wildcard segment shown as '*'
        data = {'name': 'x', 'authors': [{'name': 'Alice'}, {'name': 123}]}
        with pytest.raises(ValidationError) as exc_info:
            if validate == 'python':
                model.model_validate(data)
            else:
                model.model_validate_json(json.dumps(data))
        errors = exc_info.value.errors(include_url=False)
        assert errors[0]['type'] == 'string_type'
        assert errors[0]['loc'] == ('authors', '*', 'name', 1)

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_nested_wildcard_error_loc(self, validate):
        # with two wildcard segments, both must be rendered as '*' in the error loc, in order,
        # followed by the nested item indices (outer list index, then inner list index)
        class Model(BaseModel):
            names: list[list[str]] = Field(validation_alias=AliasPath('groups', ..., ..., 'name'))

        data = {'groups': [[{'name': 'A'}, {'name': 123}]]}
        with pytest.raises(ValidationError) as exc_info:
            if validate == 'python':
                Model.model_validate(data)
            else:
                Model.model_validate_json(json.dumps(data))
        errors = exc_info.value.errors(include_url=False)
        assert errors[0]['type'] == 'string_type'
        assert errors[0]['loc'] == ('groups', '*', '*', 'name', 0, 1)

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_non_list_value_at_wildcard_raises_when_required(self, model, validate):
        # a non-list value at the wildcard position is not found; for a required field that's a missing
        # error whose loc still passes through the wildcard segment as '*'
        data = {'name': 'x', 'authors': 'not-a-list'}
        with pytest.raises(ValidationError) as exc_info:
            if validate == 'python':
                model.model_validate(data)
            else:
                model.model_validate_json(json.dumps(data))
        errors = exc_info.value.errors(include_url=False)
        assert errors[0]['type'] == 'missing'
        assert errors[0]['loc'] == ('authors', '*', 'name')

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_non_list_value_at_wildcard_is_treated_as_not_found(self, validate):
        class Model(BaseModel):
            authors: list[str] | None = Field(None, validation_alias=AliasPath('authors', ..., 'name'))

        data = {'authors': 'not-a-list'}
        if validate == 'python':
            assert Model.model_validate(data).authors is None
        else:
            assert Model.model_validate_json(json.dumps(data)).authors is None

    @pytest.mark.parametrize('required', [True, False])
    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_nested_wildcard_non_sequence_at_inner_wildcard_is_omitted(self, required, validate):
        # the outer wildcard resolves fine (one group), but that group's inner wildcard hits a
        # non-sequence, so that single element is omitted per the standard omission rule - the
        # field ends up with an empty list, for both a defaulted field and a required one (an empty
        # list still satisfies a required list field, so no error is raised)
        if required:

            class Model(BaseModel):
                names: list[str] = Field(validation_alias=AliasPath('groups', ..., 'inner', ..., 'name'))
        else:

            class Model(BaseModel):
                names: list[str] | None = Field(None, validation_alias=AliasPath('groups', ..., 'inner', ..., 'name'))

        data = {'groups': [{'inner': 'not-a-list'}]}
        if validate == 'python':
            assert Model.model_validate(data).names == []
        else:
            assert Model.model_validate_json(json.dumps(data)).names == []

    def test_tuple_value_at_wildcard(self, model):
        # a wildcard should map over any sequence, not just lists
        data = {'name': 'x', 'authors': ({'name': 'Alice'},)}
        assert model.model_validate(data).authors == ['Alice']

    def test_generic_sequence_value_at_wildcard(self, model):
        # a wildcard must map over any `collections.abc.Sequence`, not just list/tuple specifically -
        # Python input only, since a custom Sequence type has no JSON representation
        class Seq(Sequence):
            def __init__(self, items):
                self._items = list(items)

            def __getitem__(self, i):
                return self._items[i]

            def __len__(self) -> int:
                return len(self._items)

        data = {'name': 'x', 'authors': Seq([{'name': 'Alice'}, {'name': 'Bob'}])}
        assert model.model_validate(data).authors == ['Alice', 'Bob']

    def test_bare_wildcard_passes_through_the_list(self):
        class Model(BaseModel):
            authors: list[dict] = Field(validation_alias=AliasPath('authors', ...))

        data = {'authors': [{'name': 'Alice'}]}
        assert Model.model_validate(data).authors == [{'name': 'Alice'}]
        assert Model.model_validate_json(json.dumps(data)).authors == [{'name': 'Alice'}]

    def test_nested_wildcards(self):
        class Model(BaseModel):
            names: list[list[str]] = Field(validation_alias=AliasPath('groups', ..., ..., 'name'))

        data = {'groups': [[{'name': 'A'}, {'name': 'B'}], [{'name': 'C'}]]}
        assert Model.model_validate(data).names == [['A', 'B'], ['C']]
        assert Model.model_validate_json(json.dumps(data)).names == [['A', 'B'], ['C']]

    def test_three_wildcard_levels(self):
        # recursion isn't capped at two wildcard levels
        class Model(BaseModel):
            values: list[list[list[str]]] = Field(validation_alias=AliasPath('a', ..., ..., ..., 'v'))

        data = {'a': [[[{'v': 'x'}, {'v': 'y'}], [{'v': 'z'}]], [[{'v': 'w'}]]]}
        assert Model.model_validate(data).values == [[['x', 'y'], ['z']], [['w']]]
        assert Model.model_validate_json(json.dumps(data)).values == [[['x', 'y'], ['z']], [['w']]]

    def test_nested_terminal_wildcard(self):
        # a terminal wildcard (identity projection) applies at any wildcard depth, not only when
        # it's the sole/first wildcard in the path
        class Model(BaseModel):
            groups: list[list[dict]] = Field(validation_alias=AliasPath('groups', ..., 'members', ...))

        data = {'groups': [{'members': [{'name': 'A'}, {'name': 'B'}]}, {'members': [{'name': 'C'}]}]}
        expected = [[{'name': 'A'}, {'name': 'B'}], [{'name': 'C'}]]
        assert Model.model_validate(data).groups == expected
        assert Model.model_validate_json(json.dumps(data)).groups == expected

    def test_nested_wildcard_partial_omission(self):
        # only the inner element that fails to resolve past the second wildcard is omitted; the
        # surrounding nested-list shape (including the untouched second group) is otherwise preserved
        class Model(BaseModel):
            names: list[list[str]] = Field(validation_alias=AliasPath('groups', ..., ..., 'name'))

        data = {'groups': [[{'name': 'A'}, {}], [{'name': 'C'}]]}
        assert Model.model_validate(data).names == [['A'], ['C']]
        assert Model.model_validate_json(json.dumps(data)).names == [['A'], ['C']]

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_integer_index_failure_after_wildcard_is_omitted(self, validate):
        # omission on a post-wildcard resolution failure applies to integer-index lookups too, not
        # just dict-key lookups
        class Model(BaseModel):
            items: list[str] = Field(validation_alias=AliasPath('groups', ..., 0))

        data = {'groups': [['first'], []]}
        if validate == 'python':
            assert Model.model_validate(data).items == ['first']
        else:
            assert Model.model_validate_json(json.dumps(data)).items == ['first']

    def test_from_attributes_failure_after_wildcard_is_omitted(self):
        # omission on a post-wildcard resolution failure applies to attribute lookups
        # (from_attributes) too, not just dict-key lookups - Python input only, since
        # from_attributes is a Python-object input mode with no JSON equivalent
        class Author:
            def __init__(self, name: str | None = None) -> None:
                if name is not None:
                    self.name = name

        class Source:
            def __init__(self, authors: list[Author]) -> None:
                self.authors = authors

        class Model(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            authors: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        data = Source([Author('Alice'), Author()])
        assert Model.model_validate(data).authors == ['Alice']

    def test_prefix_exception_propagates(self):
        # omission only covers ordinary lookup misses (a missing key/index/attribute) - a genuine
        # exception raised while resolving a segment *before* the wildcard is reached must still
        # propagate as an error, exactly as it does for a wildcard-free path, rather than being
        # swallowed into a "missing" field. Python input only (from_attributes has no JSON
        # equivalent).
        class Broken:
            @property
            def broken(self):
                raise RuntimeError('boom')

        class Root:
            def __init__(self):
                self.root = Broken()

        class ModelWildcard(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            names: list[str] = Field(validation_alias=AliasPath('root', 'broken', ..., 'name'))

        with pytest.raises(ValidationError) as exc_info:
            ModelWildcard.model_validate(Root())
        assert exc_info.value.errors(include_url=False)[0]['type'] == 'get_attribute_error'

        # the plain (wildcard-free) path must behave identically for the same prefix
        class ModelPlain(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            name: str = Field(validation_alias=AliasPath('root', 'broken', 'name'))

        with pytest.raises(ValidationError) as exc_info:
            ModelPlain.model_validate(Root())
        assert exc_info.value.errors(include_url=False)[0]['type'] == 'get_attribute_error'

    def test_suffix_exception_propagates(self):
        # omission only covers ordinary lookup misses - a genuine exception raised while
        # resolving the remaining path *against an element discovered by the wildcard* must
        # still propagate as an error too, exactly like a prefix exception does, rather than
        # being caught by whatever per-element resolution loop maps the remaining path over
        # each element. Python input only (from_attributes has no JSON equivalent).
        class Broken:
            @property
            def name(self):
                raise RuntimeError('boom')

        class Root:
            def __init__(self):
                self.authors = [Broken()]

        class ModelWildcard(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        with pytest.raises(ValidationError) as exc_info:
            ModelWildcard.model_validate(Root())
        assert exc_info.value.errors(include_url=False)[0]['type'] == 'get_attribute_error'

        # the plain (wildcard-free) path must behave identically for the same suffix
        class RootPlain:
            def __init__(self):
                self.author = Broken()

        class ModelPlain(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            name: str = Field(validation_alias=AliasPath('author', 'name'))

        with pytest.raises(ValidationError) as exc_info:
            ModelPlain.model_validate(RootPlain())
        assert exc_info.value.errors(include_url=False)[0]['type'] == 'get_attribute_error'

    def test_sequence_enumeration_exception_propagates(self):
        # a genuine exception raised while enumerating a custom Sequence found at the wildcard
        # position itself (not just a plain lookup miss) must propagate too, exactly like any
        # other segment of the path - it must not be swallowed into "value absent".
        class RaisingSequence(Sequence):
            def __len__(self):
                return 2

            def __getitem__(self, index):
                if index == 1:
                    raise RuntimeError('boom')
                return {'name': 'Alice'}

        class Model(BaseModel):
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        with pytest.raises(RuntimeError, match='boom'):
            Model.model_validate({'authors': RaisingSequence()})

    def test_model_construct_sequence_enumeration_exception_propagates(self):
        # same guarantee as test_sequence_enumeration_exception_propagates, but via
        # model_construct()'s separate pure-Python resolution path (AliasPath.search_dict_for_path /
        # _resolve_wildcard_path) rather than the compiled validator - a broken implementation might
        # catch broad exceptions only in that pure-Python helper and treat the alias as absent
        class RaisingSequence(Sequence):
            def __len__(self):
                return 2

            def __getitem__(self, index):
                if index == 1:
                    raise RuntimeError('boom')
                return {'name': 'Alice'}

        class Model(BaseModel):
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        with pytest.raises(RuntimeError, match='boom'):
            Model.model_construct(authors=RaisingSequence())

    def test_sequence_enumeration_type_error_propagates(self):
        # same as above, but with TypeError specifically - a plausible implementation mistake is
        # to treat TypeError as an ordinary lookup miss (it is one elsewhere, e.g. applying a
        # string key to a list during normal segment resolution), but during wildcard enumeration
        # it is not: a len-1 Sequence raising TypeError from a valid index is a genuine exception.
        class RaisingTypeError(Sequence):
            def __len__(self):
                return 1

            def __getitem__(self, index):
                raise TypeError('boom')

        class Model(BaseModel):
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        with pytest.raises(TypeError, match='boom'):
            Model.model_validate({'authors': RaisingTypeError()})

    def test_bytes_value_at_wildcard_is_not_treated_as_a_sequence(self):
        # bytes and bytearray are technically registered as collections.abc.Sequence, but must
        # not be iterated element-by-element at a wildcard position, exactly like str
        class Model(BaseModel):
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        for value in (b'ab', bytearray(b'ab')):
            with pytest.raises(ValidationError) as exc_info:
                Model.model_validate({'authors': value})
            assert exc_info.value.errors(include_url=False)[0]['type'] == 'missing'

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_wildcard_field_visible_to_later_field_via_info_data(self, validate):
        # a wildcard-aliased field must keep its normal place in field declaration order: a later
        # field's validator must see its already-resolved value through `info.data`, exactly as it
        # would for a plain alias
        class Model(BaseModel):
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))
            other: str

            @field_validator('other')
            @classmethod
            def check(cls, v, info):
                assert info.data.get('names') == ['A'], info.data
                return v

        data = {'authors': [{'name': 'A'}], 'other': 'x'}
        if validate == 'python':
            assert Model.model_validate(data).names == ['A']
        else:
            assert Model.model_validate_json(json.dumps(data)).names == ['A']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_earlier_field_visible_to_wildcard_field_via_info_data(self, validate):
        # same as above but in the other direction: a field declared *before* a wildcard-aliased
        # field must still be visible to a validator running as part of resolving that later,
        # wildcard-aliased field
        class Model(BaseModel):
            other: str
            names: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

            @field_validator('names')
            @classmethod
            def check(cls, v, info):
                assert info.data.get('other') == 'x', info.data
                return v

        data = {'other': 'x', 'authors': [{'name': 'A'}]}
        if validate == 'python':
            assert Model.model_validate(data).names == ['A']
        else:
            assert Model.model_validate_json(json.dumps(data)).names == ['A']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_wildcard_as_alias_choice(self, validate):
        class Model(BaseModel):
            authors: list[str] = Field(validation_alias=AliasChoices('writers', AliasPath('authors', ..., 'name')))

        by_plain_key = {'writers': ['X', 'Y']}
        by_wildcard = {'authors': [{'name': 'A'}]}
        if validate == 'python':
            assert Model.model_validate(by_plain_key).authors == ['X', 'Y']
            assert Model.model_validate(by_wildcard).authors == ['A']
        else:
            assert Model.model_validate_json(json.dumps(by_plain_key)).authors == ['X', 'Y']
            assert Model.model_validate_json(json.dumps(by_wildcard)).authors == ['A']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_wildcard_as_alias_choice_precedence(self, validate):
        # when both aliases match, the first one listed wins
        class Model(BaseModel):
            authors: list[str] = Field(validation_alias=AliasChoices('writers', AliasPath('authors', ..., 'name')))

        data = {'writers': ['X', 'Y'], 'authors': [{'name': 'A'}]}
        if validate == 'python':
            assert Model.model_validate(data).authors == ['X', 'Y']
        else:
            assert Model.model_validate_json(json.dumps(data)).authors == ['X', 'Y']

    @pytest.mark.parametrize('validate', ['python', 'json'])
    def test_wildcard_as_alias_choice_precedence_wildcard_first(self, validate):
        # same as above but with the wildcard alias listed first, so it must win instead - this is the
        # case the json path previously got wrong, since its lookup tree only tracked the plain 'writers'
        # alias and never even attempted the wildcard fallback once that alias matched
        class Model(BaseModel):
            authors: list[str] = Field(validation_alias=AliasChoices(AliasPath('authors', ..., 'name'), 'writers'))

        data = {'writers': ['X', 'Y'], 'authors': [{'name': 'A'}]}
        if validate == 'python':
            assert Model.model_validate(data).authors == ['A']
        else:
            assert Model.model_validate_json(json.dumps(data)).authors == ['A']

    def test_from_attributes(self):
        class Author:
            def __init__(self, name: str) -> None:
                self.name = name

        class Source:
            def __init__(self, authors: list[Author]) -> None:
                self.authors = authors

        class Model(BaseModel):
            model_config = ConfigDict(from_attributes=True)
            authors: list[str] = Field(validation_alias=AliasPath('authors', ..., 'name'))

        assert Model.model_validate(Source([Author('A'), Author('B')])).authors == ['A', 'B']

    def test_typed_dict(self):
        class BlogDict(TypedDict):
            authors: Annotated[list[str], Field(validation_alias=AliasPath('authors', ..., 'name'))]

        ta = TypeAdapter(BlogDict)
        data = {'authors': [{'name': 'A'}, {'name': 'B'}]}
        assert ta.validate_python(data) == {'authors': ['A', 'B']}
        assert ta.validate_json(json.dumps(data)) == {'authors': ['A', 'B']}
