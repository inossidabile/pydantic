from __future__ import annotations

import re
from collections.abc import Sequence

import pytest

from pydantic_core import ArgsKwargs, SchemaValidator, ValidationError
from pydantic_core import core_schema as cs

from ...conftest import Err, PyAndJson


@pytest.mark.parametrize(
    ['input_value', 'expected'],
    (
        [ArgsKwargs((1,)), ((1,), {})],
        [ArgsKwargs((), {'Foo': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1}), Err('Foo\n  Missing required argument [type=missing_argument,')],
        [{'Foo': 1}, ((1,), {})],
        [{'a': 1}, Err('Foo\n  Missing required argument [type=missing_argument,')],
    ),
    ids=repr,
)
def test_alias(py_and_json: PyAndJson, input_value, expected) -> None:
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(name='a', schema=cs.int_schema(), alias='Foo', mode='positional_or_keyword'),
            ]
        )
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


def test_alias_path_wildcard(py_and_json: PyAndJson) -> None:
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ]
        )
    )
    assert v.validate_test({'authors': [{'name': 'Alice'}, {'name': 'Bob'}]}) == ((), {'field_a': ['Alice', 'Bob']})


def test_alias_path_wildcard_non_sequence_value_is_absent() -> None:
    # if the wildcard value is not a sequence, the whole path is absent rather than raising - a
    # required parameter with no default therefore reports an ordinary missing error, not a crash
    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ]
        )
    )
    with pytest.raises(ValidationError) as exc_info:
        v.validate_python(ArgsKwargs((), {'authors': 'not-a-sequence'}))
    assert exc_info.value.errors(include_url=False)[0]['type'] == 'missing_keyword_only_argument'


def test_alias_path_wildcard_sequence_enumeration_exception_propagates() -> None:
    # a genuine exception raised while enumerating a custom Sequence found at the wildcard
    # position itself (not just a plain lookup miss) must propagate too, exactly like any other
    # segment of the path - it must not be swallowed into "value absent"
    class RaisingSequence(Sequence):
        def __len__(self) -> int:
            return 2

        def __getitem__(self, index):
            if index == 1:
                raise RuntimeError('boom')
            return {'name': 'Alice'}

    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ]
        )
    )
    with pytest.raises(RuntimeError, match='boom'):
        v.validate_python(ArgsKwargs((), {'authors': RaisingSequence()}))


def test_alias_wildcard_extra_forbid(py_and_json: PyAndJson) -> None:
    # a wildcard alias's root key(s) must be excluded from extra='forbid' detection
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ],
            extra_behavior='forbid',
        )
    )
    assert v.validate_test({'authors': [{'name': 'Alice'}]}) == ((), {'field_a': ['Alice']})


def test_alias_wildcard_extra_forbid_by_name(py_and_json: PyAndJson) -> None:
    # the plain parameter name is also excluded from lookup once the parameter has a wildcard
    # alias, so it must be excluded from "extra" detection too
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ],
            extra_behavior='forbid',
        ),
        {'validate_by_name': True},
    )
    assert v.validate_test({'field_a': ['Alice']}) == ((), {'field_a': ['Alice']})


def test_alias_wildcard_extra_forbid_by_name_when_validate_by_name_disabled(py_and_json: PyAndJson) -> None:
    # regression test: the plain parameter name is exempt from extra='forbid' unconditionally,
    # not just when by-name lookup is enabled and actually consumes it - with validate_by_name
    # disabled and the alias's own root absent, the plain name is present but genuinely unused,
    # and must still not be flagged as extra
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.with_default_schema(cs.list_schema(cs.str_schema()), default=[]),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
            ],
            extra_behavior='forbid',
        ),
        {'validate_by_name': False},
    )
    assert v.validate_test({'field_a': ['Alice']}) == ((), {'field_a': []})


def test_alias_choices_wildcard_extra_forbid_multiple_wildcards(py_and_json: PyAndJson) -> None:
    # regression test: with more than one wildcard choice (plus a plain one), every choice's root
    # key must be excluded from "extra" detection, not just a single special-cased wildcard root
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['authors', ..., 'name'], ['editors', ..., 'name'], ['writers']],
                    mode='keyword_only',
                ),
            ],
            extra_behavior='forbid',
        )
    )
    assert v.validate_test({'authors': [{'name': 'A'}]}) == ((), {'field_a': ['A']})
    assert v.validate_test({'editors': [{'name': 'E'}]}) == ((), {'field_a': ['E']})
    assert v.validate_test({'writers': ['W']}) == ((), {'field_a': ['W']})


def test_alias_choices_wildcard_extra_forbid_co_present_roots(py_and_json: PyAndJson) -> None:
    # regression test: a broken implementation might compute the extra-forbid exemption from
    # "was this specific root actually used" rather than "is this root declared as a choice on a
    # wildcard-bearing field" - those two only differ when more than one choice's root is present
    # at once. Here both the winning wildcard root and a losing, unused plain root are present
    # together; the losing root must still be exempt, not flagged as extra_forbidden.
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['authors', ..., 'name'], ['writers']],
                    mode='keyword_only',
                ),
            ],
            extra_behavior='forbid',
        )
    )
    assert v.validate_test({'authors': [{'name': 'A'}], 'writers': ['W']}) == ((), {'field_a': ['A']})


def test_alias_choices_wildcard_extra_allow_surfaces_unused_root() -> None:
    # under extra='allow', a wildcard/choice root that ends up unused because a different choice
    # resolved must still surface as an extra field, exactly as if it had never been exempted. A
    # `var_kwargs_uniform` parameter is declared here to give arguments-v3 somewhere to put an
    # extra at all (this holds for ordinary, non-wildcard extras too, not just wildcard ones).
    # ArgsKwargs input only: a plain dict goes through the separate `validate_from_mapping` path,
    # which - like its handling of `var_kwargs_unpacked_typed_dict` - has its own pre-existing,
    # wildcard-unrelated limitation around top-level spread into `var_kwargs_uniform` too.
    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['writers'], ['authors', ..., 'name']],
                    mode='keyword_only',
                ),
                cs.arguments_v3_parameter(name='kwargs', schema=cs.any_schema(), mode='var_kwargs_uniform'),
            ],
            extra_behavior='allow',
        )
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}]})) == (
        (),
        {'field_a': ['W'], 'authors': [{'name': 'A'}]},
    )


def test_alias_wildcard_exempt_key_not_forwarded_to_unpacked_typed_dict() -> None:
    # a wildcard alias's root key must be exempted from an unpacked-kwargs TypedDict's own
    # extra='forbid' check too, not only from the arguments validator's own extra check
    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=['authors', ..., 'name'],
                    mode='keyword_only',
                ),
                cs.arguments_v3_parameter(
                    name='kwargs',
                    schema=cs.typed_dict_schema({}, extra_behavior='forbid'),
                    mode='var_kwargs_unpacked_typed_dict',
                ),
            ]
        )
    )
    with pytest.raises(ValidationError) as exc_info:
        v.validate_python(ArgsKwargs((), {'authors': 'not-a-sequence'}))
    errors = exc_info.value.errors()
    assert [e['type'] for e in errors] == ['missing_keyword_only_argument']


def test_alias_wildcard_exempt_key_does_not_discard_sibling_unpacked_kwargs() -> None:
    # regression test: suppressing the exempt root's own extra_forbidden error must not discard
    # other, genuinely declared fields of the unpacked TypedDict that were validated successfully
    # in the same call - `authors` is present but unused (writers wins), and `x` is a real field.
    # Python input only: arguments-v3's JSON/mapping path has a separate, pre-existing limitation
    # around unpacked-kwargs-TypedDict top-level spread that's unrelated to wildcards entirely.
    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['writers'], ['authors', ..., 'name']],
                    mode='keyword_only',
                ),
                cs.arguments_v3_parameter(
                    name='kwargs',
                    schema=cs.typed_dict_schema({'x': cs.typed_dict_field(cs.int_schema())}, extra_behavior='forbid'),
                    mode='var_kwargs_unpacked_typed_dict',
                ),
            ]
        )
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}], 'x': '7'})) == (
        (),
        {'field_a': ['W'], 'x': 7},
    )


def test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once() -> None:
    # regression test: recovering the sibling `x` field after suppressing the exempt root's
    # extra_forbidden error must not re-invoke x's own validator a second time - a validator
    # that fails if called more than once proves this without relying on a side-channel counter
    calls = 0

    def fails_on_second_call(value, info):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError('called more than once')
        return value

    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['writers'], ['authors', ..., 'name']],
                    mode='keyword_only',
                ),
                cs.arguments_v3_parameter(
                    name='kwargs',
                    schema=cs.typed_dict_schema(
                        {
                            'x': cs.typed_dict_field(
                                cs.with_info_after_validator_function(fails_on_second_call, cs.int_schema()),
                                required=False,
                            )
                        },
                        extra_behavior='forbid',
                    ),
                    mode='var_kwargs_unpacked_typed_dict',
                ),
            ]
        )
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}], 'x': '7'})) == (
        (),
        {'field_a': ['W'], 'x': 7},
    )
    assert calls == 1


def test_alias_wildcard_exempt_key_sibling_default_factory_runs_exactly_once() -> None:
    # same as above, but for a sibling field that's *absent* from input and relies on a
    # default_factory instead of being present with a validator - the factory must not be
    # invoked more than once either
    factory_calls = 0

    def stateful_default_factory():
        nonlocal factory_calls
        factory_calls += 1
        return factory_calls

    v = SchemaValidator(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='field_a',
                    schema=cs.list_schema(cs.str_schema()),
                    alias=[['writers'], ['authors', ..., 'name']],
                    mode='keyword_only',
                ),
                cs.arguments_v3_parameter(
                    name='kwargs',
                    schema=cs.typed_dict_schema(
                        {
                            'x': cs.typed_dict_field(
                                cs.with_default_schema(cs.int_schema(), default_factory=stateful_default_factory),
                                required=False,
                            )
                        },
                        extra_behavior='forbid',
                    ),
                    mode='var_kwargs_unpacked_typed_dict',
                ),
            ]
        )
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}]})) == (
        (),
        {'field_a': ['W'], 'x': 1},
    )
    assert factory_calls == 1


def test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once_through_definition_ref() -> None:
    # regression test: the same guarantee as
    # test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once must hold when the
    # unpacked TypedDict's schema is a `definition_reference_schema` rather than embedded directly
    # as the parameter's own schema - a broken implementation might only recognize the TypedDict
    # when it's the *direct* value there, silently falling back to a retry that re-invokes `x`'s
    # validator a second time once a definition ref is involved
    calls = 0

    def fails_on_second_call(value, info):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError('called more than once')
        return value

    v = SchemaValidator(
        cs.definitions_schema(
            cs.arguments_v3_schema(
                [
                    cs.arguments_v3_parameter(
                        name='field_a',
                        schema=cs.list_schema(cs.str_schema()),
                        alias=[['writers'], ['authors', ..., 'name']],
                        mode='keyword_only',
                    ),
                    cs.arguments_v3_parameter(
                        name='kwargs',
                        schema=cs.definition_reference_schema('unpacked-kwargs-ref'),
                        mode='var_kwargs_unpacked_typed_dict',
                    ),
                ]
            ),
            [
                cs.typed_dict_schema(
                    {
                        'x': cs.typed_dict_field(
                            cs.with_info_after_validator_function(fails_on_second_call, cs.int_schema()),
                            required=False,
                        )
                    },
                    extra_behavior='forbid',
                    ref='unpacked-kwargs-ref',
                )
            ],
        )
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}], 'x': '7'})) == (
        (),
        {'field_a': ['W'], 'x': 7},
    )
    assert calls == 1


@pytest.mark.parametrize(
    ['input_value', 'expected'],
    (
        [ArgsKwargs((1,)), ((1,), {})],
        [ArgsKwargs((), {'Foo': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1, 'b': 2}), Err('b\n  Unexpected keyword argument [type=unexpected_keyword_argument,')],
        [
            ArgsKwargs((), {'a': 1, 'Foo': 2}),
            Err('a\n  Unexpected keyword argument [type=unexpected_keyword_argument,'),
        ],
        [{'Foo': 1}, ((1,), {})],
        [{'a': 1}, ((1,), {})],
    ),
    ids=repr,
)
def test_alias_validate_by_name(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(name='a', schema=cs.int_schema(), alias='Foo', mode='positional_or_keyword'),
            ],
            validate_by_name=True,
        )
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


def test_only_validate_by_name(py_and_json) -> None:
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='a', schema=cs.str_schema(), alias='FieldA', mode='positional_or_keyword'
                ),
            ],
            validate_by_name=True,
            validate_by_alias=False,
        )
    )

    assert v.validate_test(ArgsKwargs((), {'a': 'hello'})) == ((), {'a': 'hello'})
    assert v.validate_test({'a': 'hello'}) == (('hello',), {})

    with pytest.raises(ValidationError, match=r'a\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test(ArgsKwargs((), {'FieldA': 'hello'}))
    with pytest.raises(ValidationError, match=r'a\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test({'FieldA': 'hello'})


def test_only_allow_alias(py_and_json) -> None:
    v = py_and_json(
        cs.arguments_v3_schema(
            [
                cs.arguments_v3_parameter(
                    name='a', schema=cs.str_schema(), alias='FieldA', mode='positional_or_keyword'
                ),
            ],
            validate_by_name=False,
            validate_by_alias=True,
        )
    )
    assert v.validate_test(ArgsKwargs((), {'FieldA': 'hello'})) == ((), {'a': 'hello'})
    assert v.validate_test({'FieldA': 'hello'}) == (('hello',), {})

    with pytest.raises(ValidationError, match=r'FieldA\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test(ArgsKwargs((), {'a': 'hello'}))
    with pytest.raises(ValidationError, match=r'FieldA\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test({'a': 'hello'})


@pytest.mark.parametrize('config_by_alias', [None, True, False])
@pytest.mark.parametrize('config_by_name', [None, True, False])
@pytest.mark.parametrize('runtime_by_alias', [None, True, False])
@pytest.mark.parametrize('runtime_by_name', [None, True, False])
def test_by_alias_and_name_config_interaction(
    config_by_alias: bool | None,
    config_by_name: bool | None,
    runtime_by_alias: bool | None,
    runtime_by_name: bool | None,
) -> None:
    """This test reflects the priority that applies for config vs runtime validation alias configuration.

    Runtime values take precedence over config values, when set.
    By default, by_alias is True and by_name is False.
    """

    if config_by_alias is False and config_by_name is False and runtime_by_alias is False and runtime_by_name is False:
        pytest.skip("Can't have both by_alias and by_name as effectively False")

    schema = cs.arguments_v3_schema(
        arguments=[
            cs.arguments_v3_parameter(name='my_field', schema=cs.int_schema(), alias='my_alias'),
        ],
        **({'validate_by_alias': config_by_alias} if config_by_alias is not None else {}),
        **({'validate_by_name': config_by_name} if config_by_name is not None else {}),
    )
    s = SchemaValidator(schema)

    alias_allowed = next(x for x in (runtime_by_alias, config_by_alias, True) if x is not None)
    name_allowed = next(x for x in (runtime_by_name, config_by_name, False) if x is not None)

    if alias_allowed:
        assert s.validate_python(
            ArgsKwargs((), {'my_alias': 1}), by_alias=runtime_by_alias, by_name=runtime_by_name
        ) == (
            (),
            {'my_field': 1},
        )
    if name_allowed:
        assert s.validate_python(
            ArgsKwargs((), {'my_field': 1}), by_alias=runtime_by_alias, by_name=runtime_by_name
        ) == (
            (),
            {'my_field': 1},
        )
