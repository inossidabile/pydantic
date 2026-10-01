import os
import re
from collections.abc import Sequence
from functools import wraps
from inspect import Parameter, signature
from typing import Any, get_type_hints

import pytest

from pydantic_core import ArgsKwargs, SchemaError, SchemaValidator, ValidationError, core_schema
from pydantic_core import core_schema as cs

from ..conftest import Err, PyAndJson, plain_repr


def test_args_kwargs():
    ak = ArgsKwargs(('hello', True))
    assert str(ak) == "ArgsKwargs(('hello', True))"
    assert repr(ak) == "ArgsKwargs(('hello', True))"
    assert ak.args == ('hello', True)
    assert ak.kwargs is None
    ak2 = ArgsKwargs((), {'a': 123})
    assert repr(ak2) == "ArgsKwargs((), {'a': 123})"
    assert ak2.args == ()
    assert ak2.kwargs == {'a': 123}
    ak3 = ArgsKwargs(('hello', True), {'a': 123, 'b': b'bytes'})
    assert repr(ak3) == "ArgsKwargs(('hello', True), {'a': 123, 'b': b'bytes'})"

    assert ak != ak2

    assert ak == ArgsKwargs(('hello', True))
    assert ak3 == ArgsKwargs(('hello', True), {'a': 123, 'b': b'bytes'})
    assert ak3 != ArgsKwargs(('hello', True), {'a': 123, 'b': b'different'})
    assert ArgsKwargs((1,), {}) == ArgsKwargs((1,), None) == ArgsKwargs((1,))

    assert repr(ArgsKwargs((1,))) == 'ArgsKwargs((1,))'


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [(1, 'a', True), ((1, 'a', True), {})],
        [[1, 'a', True], ((1, 'a', True), {})],
        [ArgsKwargs((1, 'a', True)), ((1, 'a', True), {})],
        [(1, 'a', 'true'), ((1, 'a', True), {})],
        ['x', Err('type=arguments_type,')],
        [
            ArgsKwargs((1, 'a', True), {'x': 1}),
            Err(
                '1 validation error for arguments',
                [
                    {
                        'type': 'unexpected_keyword_argument',
                        'loc': ('x',),
                        'msg': 'Unexpected keyword argument',
                        'input': 1,
                    }
                ],
            ),
        ],
        [
            [1],
            Err(
                '2 validation errors for arguments',
                [
                    {
                        'type': 'missing_positional_only_argument',
                        'loc': (1,),
                        'msg': 'Missing required positional only argument',
                        'input': [1],
                    },
                    {
                        'type': 'missing_positional_only_argument',
                        'loc': (2,),
                        'msg': 'Missing required positional only argument',
                        'input': [1],
                    },
                ],
            ),
        ],
        [
            [1, 'a', True, 4],
            Err(
                '1 validation error for arguments',
                [
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (3,),
                        'msg': 'Unexpected positional argument',
                        'input': 4,
                    }
                ],
            ),
        ],
        [
            [1, 'a', True, 4, 5],
            Err(
                '2 validation errors for arguments',
                [
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (3,),
                        'msg': 'Unexpected positional argument',
                        'input': 4,
                    },
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (4,),
                        'msg': 'Unexpected positional argument',
                        'input': 5,
                    },
                ],
            ),
        ],
        [
            ('x', 'a', 'wrong'),
            Err(
                '2 validation errors for arguments',
                [
                    {
                        'type': 'int_parsing',
                        'loc': (0,),
                        'msg': 'Input should be a valid integer, unable to parse string as an integer',
                        'input': 'x',
                    },
                    {
                        'type': 'bool_parsing',
                        'loc': (2,),
                        'msg': 'Input should be a valid boolean, unable to interpret input',
                        'input': 'wrong',
                    },
                ],
            ),
        ],
        [
            ArgsKwargs(()),
            Err(
                '3 validation errors for arguments',
                [
                    {
                        'type': 'missing_positional_only_argument',
                        'loc': (0,),
                        'msg': 'Missing required positional only argument',
                        'input': ArgsKwargs(()),
                    },
                    {
                        'type': 'missing_positional_only_argument',
                        'loc': (1,),
                        'msg': 'Missing required positional only argument',
                        'input': ArgsKwargs(()),
                    },
                    {
                        'type': 'missing_positional_only_argument',
                        'loc': (2,),
                        'msg': 'Missing required positional only argument',
                        'input': ArgsKwargs(()),
                    },
                ],
            ),
        ],
    ],
    ids=repr,
)
def test_positional_args(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_only', 'schema': {'type': 'int'}},
                {'name': 'b', 'mode': 'positional_only', 'schema': {'type': 'str'}},
                {'name': 'c', 'mode': 'positional_only', 'schema': {'type': 'bool'}},
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((), {'a': 1, 'b': 'a', 'c': True}), ((), {'a': 1, 'b': 'a', 'c': True})],
        [{'a': 1, 'b': 'a', 'c': True}, ((), {'a': 1, 'b': 'a', 'c': True})],
        [ArgsKwargs((), {'a': '1', 'b': 'a', 'c': 'True'}), ((), {'a': 1, 'b': 'a', 'c': True})],
        [ArgsKwargs((1,), {'a': 1, 'b': 'a', 'c': True}), Err('type=unexpected_positional_argument,')],
        [
            ArgsKwargs((), {'a': 1, 'b': 'a', 'c': True, 'd': 'wrong'}),
            Err(
                'type=unexpected_keyword_argument,',
                [
                    {
                        'type': 'unexpected_keyword_argument',
                        'loc': ('d',),
                        'msg': 'Unexpected keyword argument',
                        'input': 'wrong',
                    }
                ],
            ),
        ],
        [
            ArgsKwargs((), {'a': 1, 'b': 'a'}),
            Err(
                'type=missing_keyword_only_argument,',
                [
                    {
                        'type': 'missing_keyword_only_argument',
                        'loc': ('c',),
                        'msg': 'Missing required keyword only argument',
                        'input': ArgsKwargs((), {'a': 1, 'b': 'a'}),
                    }
                ],
            ),
        ],
        [
            ArgsKwargs((), {'a': 'x', 'b': 'a', 'c': 'wrong'}),
            Err(
                '2 validation errors for arguments',
                [
                    {
                        'type': 'int_parsing',
                        'loc': ('a',),
                        'msg': 'Input should be a valid integer, unable to parse string as an integer',
                        'input': 'x',
                    },
                    {
                        'type': 'bool_parsing',
                        'loc': ('c',),
                        'msg': 'Input should be a valid boolean, unable to interpret input',
                        'input': 'wrong',
                    },
                ],
            ),
        ],
        [
            ArgsKwargs(()),
            Err(
                '3 validation errors for arguments',
                [
                    {
                        'type': 'missing_keyword_only_argument',
                        'loc': ('a',),
                        'msg': 'Missing required keyword only argument',
                        'input': ArgsKwargs(()),
                    },
                    {
                        'type': 'missing_keyword_only_argument',
                        'loc': ('b',),
                        'msg': 'Missing required keyword only argument',
                        'input': ArgsKwargs(()),
                    },
                    {
                        'type': 'missing_keyword_only_argument',
                        'loc': ('c',),
                        'msg': 'Missing required keyword only argument',
                        'input': ArgsKwargs(()),
                    },
                ],
            ),
        ],
    ],
    ids=repr,
)
def test_keyword_args(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'keyword_only', 'schema': {'type': 'int'}},
                {'name': 'b', 'mode': 'keyword_only', 'schema': {'type': 'str'}},
                {'name': 'c', 'mode': 'keyword_only', 'schema': {'type': 'bool'}},
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [{'a': 1, 'b': 'bb', 'c': True}, ((), {'a': 1, 'b': 'bb', 'c': True})],
        [ArgsKwargs((), {'a': 1, 'b': 'bb', 'c': True}), ((), {'a': 1, 'b': 'bb', 'c': True})],
        [ArgsKwargs((1, 'bb'), {'c': True}), ((1, 'bb'), {'c': True})],
        [ArgsKwargs((1,), {'b': 'bb', 'c': True}), ((1,), {'b': 'bb', 'c': True})],
        [
            ArgsKwargs((1,), {'a': 11, 'b': 'bb', 'c': True}),
            Err(
                'type=multiple_argument_values,',
                [
                    {
                        'type': 'multiple_argument_values',
                        'loc': ('a',),
                        'msg': 'Got multiple values for argument',
                        'input': 11,
                    }
                ],
            ),
        ],
        [
            ArgsKwargs((1, 'bb', 'cc'), {'b': 'bb', 'c': True}),
            Err(
                'type=unexpected_positional_argument,',
                [
                    {
                        'type': 'multiple_argument_values',
                        'loc': ('b',),
                        'msg': 'Got multiple values for argument',
                        'input': 'bb',
                    },
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (2,),
                        'msg': 'Unexpected positional argument',
                        'input': 'cc',
                    },
                ],
            ),
        ],
        [
            ArgsKwargs((1, 'b1'), {'a': 11, 'b': 'b2', 'c': True}),
            Err(
                'type=multiple_argument_values,',
                [
                    {
                        'type': 'multiple_argument_values',
                        'loc': ('a',),
                        'msg': 'Got multiple values for argument',
                        'input': 11,
                    },
                    {
                        'type': 'multiple_argument_values',
                        'loc': ('b',),
                        'msg': 'Got multiple values for argument',
                        'input': 'b2',
                    },
                ],
            ),
        ],
    ],
    ids=repr,
)
def test_positional_or_keyword(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {'name': 'b', 'schema': {'type': 'str'}},  # default mode is positional_or_keyword
                {'name': 'c', 'mode': 'keyword_only', 'schema': {'type': 'bool'}},
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected,arguments_schema',
    [
        (
            {'a': 1, 'b': 2, 'e': 3.14},
            ((), {'a': 1, 'b': 2, 'c': 5, 'd': 'default', 'e': 3.14}),
            [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {'name': 'b', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {
                    'name': 'c',
                    'mode': 'keyword_only',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default': 5},
                },
                {
                    'name': 'd',
                    'mode': 'keyword_only',
                    'schema': {'type': 'default', 'schema': {'type': 'str'}, 'default': 'default'},
                },
                {'name': 'e', 'mode': 'keyword_only', 'schema': {'type': 'float'}},
            ],
        ),
        (
            {'y': 'test'},
            ((), {'x': 1, 'y': 'test'}),
            [
                {
                    'name': 'x',
                    'mode': 'keyword_only',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default': 1},
                },
                {'name': 'y', 'mode': 'keyword_only', 'schema': {'type': 'str'}},
            ],
        ),
        (
            {'a': 1, 'd': 3.14},
            ((), {'a': 1, 'b': 10, 'c': 'hello', 'd': 3.14}),
            [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {
                    'name': 'b',
                    'mode': 'positional_or_keyword',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default': 10},
                },
                {
                    'name': 'c',
                    'mode': 'keyword_only',
                    'schema': {'type': 'default', 'schema': {'type': 'str'}, 'default': 'hello'},
                },
                {'name': 'd', 'mode': 'keyword_only', 'schema': {'type': 'float'}},
            ],
        ),
        (
            {'x': 3, 'y': 'custom', 'z': 4},
            ((), {'x': 3, 'y': 'custom', 'z': 4}),
            [
                {'name': 'x', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {
                    'name': 'y',
                    'mode': 'keyword_only',
                    'schema': {'type': 'default', 'schema': {'type': 'str'}, 'default': 'default'},
                },
                {'name': 'z', 'mode': 'keyword_only', 'schema': {'type': 'int'}},
            ],
        ),
    ],
)
def test_keyword_only_non_default(py_and_json: PyAndJson, input_value, expected, arguments_schema):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': arguments_schema,
        }
    )
    assert v.validate_test(input_value) == expected


@pytest.mark.parametrize('input_value,expected', [[(1,), ((1,), {})], [(), ((42,), {})]], ids=repr)
def test_positional_optional(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'a',
                    'mode': 'positional_only',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default': 42},
                }
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [{'a': 1}, ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1}), ((), {'a': 1})],
        [ArgsKwargs(()), ((), {'a': 1})],
    ],
    ids=repr,
)
def test_p_or_k_optional(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'a',
                    'mode': 'positional_or_keyword',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default': 1},
                }
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [[1, 2, 3], ((1, 2, 3), {})],
        [ArgsKwargs((1, 2, 3)), ((1, 2, 3), {})],
        [[1], ((1,), {})],
        [[], ((), {})],
        [ArgsKwargs((1, 2, 3), {'a': 1}), Err('a\n  Unexpected keyword argument [type=unexpected_keyword_argument,')],
    ],
    ids=repr,
)
def test_var_args_only(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json({'type': 'arguments', 'arguments_schema': [], 'var_args_schema': {'type': 'int'}})
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [[1, 2, 3], ((1, 2, 3), {})],
        [['1', '2', '3'], ((1, 2, 3), {})],
        [[1], ((1,), {})],
        [[], Err('0\n  Missing required positional only argument')],
        [
            ['x'],
            Err(
                'type=int_parsing,',
                [
                    {
                        'type': 'int_parsing',
                        'loc': (0,),
                        'msg': 'Input should be a valid integer, unable to parse string as an integer',
                        'input': 'x',
                    }
                ],
            ),
        ],
        [
            [1, 'x', 'y'],
            Err(
                'type=int_parsing,',
                [
                    {
                        'type': 'int_parsing',
                        'loc': (1,),
                        'msg': 'Input should be a valid integer, unable to parse string as an integer',
                        'input': 'x',
                    },
                    {
                        'type': 'int_parsing',
                        'loc': (2,),
                        'msg': 'Input should be a valid integer, unable to parse string as an integer',
                        'input': 'y',
                    },
                ],
            ),
        ],
        [ArgsKwargs((1, 2, 3), {'a': 1}), Err('a\n  Unexpected keyword argument [type=unexpected_keyword_argument,')],
    ],
    ids=repr,
)
def test_args_var_args_only(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [{'name': 'a', 'mode': 'positional_only', 'schema': {'type': 'int'}}],
            'var_args_schema': {'type': 'int'},
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((1, 'a', 'true'), {'b': 'bb', 'c': 3}), ((1, 'a', True), {'b': 'bb', 'c': 3})],
        [ArgsKwargs((1, 'a'), {'a': 'true', 'b': 'bb', 'c': 3}), ((1, 'a'), {'a': True, 'b': 'bb', 'c': 3})],
        [
            ArgsKwargs((1, 'a', 'true', 4, 5), {'b': 'bb', 'c': 3}),
            Err(
                'type=unexpected_positional_argument,',
                [
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (3,),
                        'msg': 'Unexpected positional argument',
                        'input': 4,
                    },
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (4,),
                        'msg': 'Unexpected positional argument',
                        'input': 5,
                    },
                ],
            ),
        ],
    ],
    ids=repr,
)
def test_both(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': '1', 'mode': 'positional_only', 'schema': {'type': 'int'}},
                {'name': '2', 'mode': 'positional_only', 'schema': {'type': 'str'}},
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'bool'}},
                {'name': 'b', 'mode': 'keyword_only', 'schema': {'type': 'str'}},
                {'name': 'c', 'mode': 'keyword_only', 'schema': {'type': 'int'}},
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs(()), ((), {})],
        [[], ((), {})],
        [[1], Err('0\n  Unexpected positional argument [type=unexpected_positional_argument,')],
        [{'a': 1}, Err('a\n  Unexpected keyword argument [type=unexpected_keyword_argument,')],
        [
            ArgsKwargs((1,), {'a': 2}),
            Err(
                '[type=unexpected_keyword_argument,',
                [
                    {
                        'type': 'unexpected_positional_argument',
                        'loc': (0,),
                        'msg': 'Unexpected positional argument',
                        'input': 1,
                    },
                    {
                        'type': 'unexpected_keyword_argument',
                        'loc': ('a',),
                        'msg': 'Unexpected keyword argument',
                        'input': 2,
                    },
                ],
            ),
        ],
    ],
    ids=repr,
)
def test_no_args(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json({'type': 'arguments', 'arguments_schema': []})
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)) as exc_info:
            v.validate_test(input_value)
        # debug(exc_info.value.errors(include_url=False))
        if expected.errors is not None:
            assert exc_info.value.errors(include_url=False) == expected.errors
    else:
        assert v.validate_test(input_value) == expected


def double_or_bust(input_value, info):
    if input_value == 1:
        raise RuntimeError('bust')
    return input_value * 2


def test_internal_error(py_and_json: PyAndJson):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_only', 'schema': {'type': 'int'}},
                {
                    'name': 'b',
                    'mode': 'positional_only',
                    'schema': core_schema.with_info_plain_validator_function(double_or_bust),
                },
            ],
        }
    )
    assert v.validate_test((1, 2)) == ((1, 4), {})
    with pytest.raises(RuntimeError, match='bust'):
        v.validate_test((1, 1))


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((1, 2)), ((1, 2), {})],
        [ArgsKwargs((1,)), ((1,), {'b': 42})],
        [ArgsKwargs((1,), {'b': 3}), ((1,), {'b': 3})],
        [ArgsKwargs((), {'a': 1}), ((), {'a': 1, 'b': 42})],
    ],
    ids=repr,
)
def test_default_factory(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
                {
                    'name': 'b',
                    'mode': 'positional_or_keyword',
                    'schema': {'type': 'default', 'schema': {'type': 'int'}, 'default_factory': lambda: 42},
                },
            ],
        }
    )
    assert v.validate_test(input_value) == expected


def test_repr():
    v = SchemaValidator(
        cs.arguments_schema(
            arguments=[
                {'name': 'b', 'mode': 'positional_or_keyword', 'schema': cs.int_schema()},
                {
                    'name': 'a',
                    'mode': 'keyword_only',
                    'schema': cs.with_default_schema(schema=cs.int_schema(), default_factory=lambda: 42),
                },
            ]
        )
    )
    assert 'positional_params_count:1,' in plain_repr(v)


def test_build_non_default_follows():
    with pytest.raises(SchemaError, match="Non-default argument 'b' follows default argument"):
        SchemaValidator(
            schema=cs.arguments_schema(
                arguments=[
                    {
                        'name': 'a',
                        'mode': 'positional_or_keyword',
                        'schema': cs.with_default_schema(schema=cs.int_schema(), default_factory=lambda: 42),
                    },
                    {'name': 'b', 'mode': 'positional_or_keyword', 'schema': cs.int_schema()},
                ]
            )
        )


def test_build_missing_var_kwargs():
    with pytest.raises(
        SchemaError, match="`var_kwargs_schema` must be specified when `var_kwargs_mode` is `'unpacked-typed-dict'`"
    ):
        SchemaValidator(cs.arguments_schema(arguments=[], var_kwargs_mode='unpacked-typed-dict'))


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((1, 2)), ((1, 2), {})],
        [ArgsKwargs((1,), {'b': '4', 'c': 'a'}), ((1,), {'b': 4, 'c': 'a'})],
        [ArgsKwargs((1, 2), {'x': 'abc'}), ((1, 2), {'x': 'abc'})],
    ],
    ids=repr,
)
def test_kwargs_uniform(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_only', 'schema': {'type': 'int'}},
                {'name': 'b', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}},
            ],
            'var_kwargs_schema': {'type': 'str'},
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((), {'x': 1}), ((), {'x': 1})],
        [ArgsKwargs((), {'x': 1.0}), Err('x\n  Input should be a valid integer [type=int_type,')],
        [ArgsKwargs((), {'x': 1, 'z': 'str'}), ((), {'x': 1, 'y': 'str'})],
        [ArgsKwargs((), {'x': 1, 'y': 'str'}), Err('y\n  Extra inputs are not permitted [type=extra_forbidden,')],
    ],
)
def test_kwargs_typed_dict(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [],
            'var_kwargs_mode': 'unpacked-typed-dict',
            'var_kwargs_schema': {
                'type': 'typed-dict',
                'fields': {
                    'x': {
                        'type': 'typed-dict-field',
                        'schema': {'type': 'int', 'strict': True},
                        'required': True,
                    },
                    'y': {
                        'type': 'typed-dict-field',
                        'schema': {'type': 'str'},
                        'required': False,
                        'validation_alias': 'z',
                    },
                },
                'config': {'extra_fields_behavior': 'forbid'},
            },
        }
    )

    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


@pytest.mark.parametrize(
    'input_value,expected',
    [
        [ArgsKwargs((1,)), ((1,), {})],
        [ArgsKwargs((), {'Foo': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1}), Err('Foo\n  Missing required argument [type=missing_argument,')],
    ],
    ids=repr,
)
def test_alias(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}, 'alias': 'Foo'}
            ],
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


def test_alias_path_wildcard(py_and_json: PyAndJson):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
        }
    )
    assert v.validate_test({'authors': [{'name': 'Alice'}, {'name': 'Bob'}]}) == ((), {'field_a': ['Alice', 'Bob']})


def test_alias_path_wildcard_non_sequence_value_is_absent():
    # if the wildcard value is not a sequence, the whole path is absent rather than raising - a
    # required argument with no default therefore reports an ordinary missing error, not a crash
    v = SchemaValidator(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
        }
    )
    with pytest.raises(ValidationError) as exc_info:
        v.validate_python(ArgsKwargs((), {'authors': 'not-a-sequence'}))
    assert exc_info.value.errors(include_url=False)[0]['type'] == 'missing_keyword_only_argument'


def test_alias_path_wildcard_sequence_enumeration_exception_propagates():
    # a genuine exception raised while enumerating a custom Sequence found at the wildcard
    # position itself (not just a plain lookup miss) must propagate too, exactly like any other
    # segment of the path - it must not be swallowed into "value absent"
    class RaisingSequence(Sequence):
        def __len__(self):
            return 2

        def __getitem__(self, index):
            if index == 1:
                raise RuntimeError('boom')
            return {'name': 'Alice'}

    v = SchemaValidator(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
        }
    )
    with pytest.raises(RuntimeError, match='boom'):
        v.validate_python(ArgsKwargs((), {'authors': RaisingSequence()}))


def test_alias_wildcard_extra_forbid(py_and_json: PyAndJson):
    # a wildcard alias's root key(s) must be excluded from extra='forbid' detection - the legacy
    # `arguments` validator has no per-field `extra_behavior`, only the global `extra_fields_behavior`
    # config key, but the same wildcard exemption mechanism still applies against it
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
        },
        config={'extra_fields_behavior': 'forbid'},
    )
    assert v.validate_test({'authors': [{'name': 'Alice'}]}) == ((), {'field_a': ['Alice']})


def test_alias_wildcard_extra_forbid_by_name(py_and_json: PyAndJson):
    # the plain parameter name is also excluded from lookup once the parameter has a wildcard
    # alias, so it must be excluded from "extra" detection too
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
        },
        config={'extra_fields_behavior': 'forbid', 'validate_by_name': True},
    )
    assert v.validate_test({'field_a': ['Alice']}) == ((), {'field_a': ['Alice']})


def test_alias_wildcard_extra_forbid_by_name_when_validate_by_name_disabled(py_and_json: PyAndJson):
    # regression test: the plain parameter name is exempt from extra='forbid' unconditionally,
    # not just when by-name lookup is enabled and actually consumes it - with validate_by_name
    # disabled and the alias's own root absent, the plain name is present but genuinely unused,
    # and must still not be flagged as extra
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {
                        'type': 'default',
                        'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                        'default': [],
                    },
                    'alias': ['authors', ..., 'name'],
                }
            ],
        },
        config={'extra_fields_behavior': 'forbid', 'validate_by_name': False},
    )
    assert v.validate_test({'field_a': ['Alice']}) == ((), {'field_a': []})


def test_alias_choices_wildcard_extra_forbid_multiple_wildcards(py_and_json: PyAndJson):
    # regression test: with more than one wildcard choice (plus a plain one), every choice's root
    # key must be excluded from "extra" detection, not just a single special-cased wildcard root
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['authors', ..., 'name'], ['editors', ..., 'name'], ['writers']],
                }
            ],
        },
        config={'extra_fields_behavior': 'forbid'},
    )
    assert v.validate_test({'authors': [{'name': 'A'}]}) == ((), {'field_a': ['A']})
    assert v.validate_test({'editors': [{'name': 'E'}]}) == ((), {'field_a': ['E']})
    assert v.validate_test({'writers': ['W']}) == ((), {'field_a': ['W']})


def test_alias_choices_wildcard_extra_forbid_co_present_roots(py_and_json: PyAndJson):
    # regression test: a broken implementation might compute the extra-forbid exemption from
    # "was this specific root actually used" rather than "is this root declared as a choice on a
    # wildcard-bearing field" - those two only differ when more than one choice's root is present
    # at once. Here both the winning wildcard root and a losing, unused plain root are present
    # together; the losing root must still be exempt, not flagged as extra_forbidden.
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['authors', ..., 'name'], ['writers']],
                }
            ],
        },
        config={'extra_fields_behavior': 'forbid'},
    )
    assert v.validate_test({'authors': [{'name': 'A'}], 'writers': ['W']}) == ((), {'field_a': ['A']})


def test_alias_choices_wildcard_extra_allow_surfaces_unused_root(py_and_json: PyAndJson):
    # under extra='allow', a wildcard/choice root that ends up unused because a different choice
    # resolved must still surface as an extra field, exactly as if it had never been exempted.
    # The legacy `arguments` validator has no place to put an extra without a declared
    # `var_kwargs_schema` (this holds for ordinary, non-wildcard extras too, not just wildcard
    # ones), so a `var_kwargs_mode: 'uniform'` schema is declared here to give it somewhere to go.
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['writers'], ['authors', ..., 'name']],
                }
            ],
            'var_kwargs_mode': 'uniform',
            'var_kwargs_schema': {'type': 'any'},
        },
        config={'extra_fields_behavior': 'allow'},
    )
    assert v.validate_test({'writers': ['W'], 'authors': [{'name': 'A'}]}) == (
        (),
        {'field_a': ['W'], 'authors': [{'name': 'A'}]},
    )


def test_alias_wildcard_exempt_key_not_forwarded_to_unpacked_typed_dict():
    # a wildcard alias's root key must be exempted from an unpacked-kwargs TypedDict's own
    # extra='forbid' check too, not only from the arguments validator's own extra check - the
    # legacy `arguments` validator supports `var_kwargs_mode: 'unpacked-typed-dict'` exactly like
    # arguments-v3 does, but only arguments-v3 had a test for this interaction
    v = SchemaValidator(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': ['authors', ..., 'name'],
                }
            ],
            'var_kwargs_mode': 'unpacked-typed-dict',
            'var_kwargs_schema': {'type': 'typed-dict', 'fields': {}, 'extra_behavior': 'forbid'},
        }
    )
    with pytest.raises(ValidationError) as exc_info:
        v.validate_python(ArgsKwargs((), {'authors': 'not-a-sequence'}))
    errors = exc_info.value.errors()
    assert [e['type'] for e in errors] == ['missing_keyword_only_argument']


def test_alias_wildcard_exempt_key_does_not_discard_sibling_unpacked_kwargs(py_and_json: PyAndJson):
    # regression test: suppressing the exempt root's own extra_forbidden error must not discard
    # other, genuinely declared fields of the unpacked TypedDict that were validated successfully
    # in the same call - `authors` is present but unused (writers wins), and `x` is a real field
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['writers'], ['authors', ..., 'name']],
                }
            ],
            'var_kwargs_mode': 'unpacked-typed-dict',
            'var_kwargs_schema': {
                'type': 'typed-dict',
                'fields': {'x': {'type': 'typed-dict-field', 'schema': {'type': 'int'}}},
                'extra_behavior': 'forbid',
            },
        }
    )
    assert v.validate_test({'writers': ['W'], 'authors': [{'name': 'A'}], 'x': '7'}) == (
        (),
        {'field_a': ['W'], 'x': 7},
    )


def test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once():
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
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['writers'], ['authors', ..., 'name']],
                }
            ],
            'var_kwargs_mode': 'unpacked-typed-dict',
            'var_kwargs_schema': {
                'type': 'typed-dict',
                'fields': {
                    'x': {
                        'type': 'typed-dict-field',
                        'schema': core_schema.with_info_after_validator_function(
                            fails_on_second_call, core_schema.int_schema()
                        ),
                        'required': False,
                    }
                },
                'extra_behavior': 'forbid',
            },
        }
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}], 'x': '7'})) == (
        (),
        {'field_a': ['W'], 'x': 7},
    )
    assert calls == 1


def test_alias_wildcard_exempt_key_sibling_default_factory_runs_exactly_once():
    # same as above, but for a sibling field that's *absent* from input and relies on a
    # default_factory instead of being present with a validator - the factory must not be
    # invoked more than once either
    factory_calls = 0

    def stateful_default_factory():
        nonlocal factory_calls
        factory_calls += 1
        return factory_calls

    v = SchemaValidator(
        {
            'type': 'arguments',
            'arguments_schema': [
                {
                    'name': 'field_a',
                    'mode': 'keyword_only',
                    'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                    'alias': [['writers'], ['authors', ..., 'name']],
                }
            ],
            'var_kwargs_mode': 'unpacked-typed-dict',
            'var_kwargs_schema': {
                'type': 'typed-dict',
                'fields': {
                    'x': {
                        'type': 'typed-dict-field',
                        'schema': core_schema.with_default_schema(
                            core_schema.int_schema(), default_factory=stateful_default_factory
                        ),
                        'required': False,
                    }
                },
                'extra_behavior': 'forbid',
            },
        }
    )
    assert v.validate_python(ArgsKwargs((), {'writers': ['W'], 'authors': [{'name': 'A'}]})) == (
        (),
        {'field_a': ['W'], 'x': 1},
    )
    assert factory_calls == 1


def test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once_through_definition_ref():
    # regression test: the same guarantee as
    # test_alias_wildcard_exempt_key_sibling_validator_runs_exactly_once must hold when
    # `var_kwargs_schema` is a `definition_reference_schema` pointing at the unpacked TypedDict
    # rather than embedding it directly - a broken implementation might only recognize the
    # TypedDict when it's the *direct* value of `var_kwargs_schema`, silently falling back to a
    # retry that re-invokes `x`'s validator a second time once a definition ref is involved
    calls = 0

    def fails_on_second_call(value, info):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError('called more than once')
        return value

    v = SchemaValidator(
        core_schema.definitions_schema(
            {
                'type': 'arguments',
                'arguments_schema': [
                    {
                        'name': 'field_a',
                        'mode': 'keyword_only',
                        'schema': {'type': 'list', 'items_schema': {'type': 'str'}},
                        'alias': [['writers'], ['authors', ..., 'name']],
                    }
                ],
                'var_kwargs_mode': 'unpacked-typed-dict',
                'var_kwargs_schema': core_schema.definition_reference_schema('unpacked-kwargs-ref'),
            },
            [
                core_schema.typed_dict_schema(
                    {
                        'x': core_schema.typed_dict_field(
                            core_schema.with_info_after_validator_function(
                                fails_on_second_call, core_schema.int_schema()
                            ),
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
    'input_value,expected',
    [
        [ArgsKwargs((1,)), ((1,), {})],
        [ArgsKwargs((), {'Foo': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1}), ((), {'a': 1})],
        [ArgsKwargs((), {'a': 1, 'b': 2}), Err('b\n  Unexpected keyword argument [type=unexpected_keyword_argument,')],
        [
            ArgsKwargs((), {'a': 1, 'Foo': 2}),
            Err('a\n  Unexpected keyword argument [type=unexpected_keyword_argument,'),
        ],
    ],
    ids=repr,
)
def test_alias_validate_by_name(py_and_json: PyAndJson, input_value, expected):
    v = py_and_json(
        {
            'type': 'arguments',
            'arguments_schema': [
                {'name': 'a', 'mode': 'positional_or_keyword', 'schema': {'type': 'int'}, 'alias': 'Foo'}
            ],
            'validate_by_name': True,
        }
    )
    if isinstance(expected, Err):
        with pytest.raises(ValidationError, match=re.escape(expected.message)):
            v.validate_test(input_value)
    else:
        assert v.validate_test(input_value) == expected


def test_only_validate_by_name(py_and_json) -> None:
    schema = core_schema.arguments_schema(
        [
            core_schema.arguments_parameter(name='a', schema=core_schema.str_schema(), alias='FieldA'),
        ],
        validate_by_name=True,
        validate_by_alias=False,
    )
    v = py_and_json(schema)
    assert v.validate_test(ArgsKwargs((), {'a': 'hello'})) == ((), {'a': 'hello'})
    with pytest.raises(ValidationError, match=r'a\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test(ArgsKwargs((), {'FieldA': 'hello'}))


def test_only_allow_alias(py_and_json) -> None:
    schema = core_schema.arguments_schema(
        [
            core_schema.arguments_parameter(name='a', schema=core_schema.str_schema(), alias='FieldA'),
        ],
        validate_by_name=False,
        validate_by_alias=True,
    )
    v = py_and_json(schema)
    assert v.validate_test(ArgsKwargs((), {'FieldA': 'hello'})) == ((), {'a': 'hello'})
    with pytest.raises(ValidationError, match=r'FieldA\n +Missing required argument \[type=missing_argument,'):
        assert v.validate_test(ArgsKwargs((), {'a': 'hello'}))


def validate(config=None):
    def decorator(function):
        parameters = signature(function).parameters
        type_hints = get_type_hints(function)
        mode_lookup = {
            Parameter.POSITIONAL_ONLY: 'positional_only',
            Parameter.POSITIONAL_OR_KEYWORD: 'positional_or_keyword',
            Parameter.KEYWORD_ONLY: 'keyword_only',
        }

        arguments_schema = []
        schema = {'type': 'arguments', 'arguments_schema': arguments_schema}
        for i, (name, p) in enumerate(parameters.items()):
            if p.annotation is p.empty:
                annotation = Any
            else:
                annotation = type_hints[name]

            assert annotation in (bool, int, float, str, Any), f'schema for {annotation} not implemented'
            if annotation in (bool, int, float, str):
                arg_schema = {'type': annotation.__name__}
            else:
                assert annotation is Any
                arg_schema = {'type': 'any'}

            if p.kind in mode_lookup:
                if p.default is not p.empty:
                    arg_schema = {'type': 'default', 'schema': arg_schema, 'default': p.default}
                s = {'name': name, 'mode': mode_lookup[p.kind], 'schema': arg_schema}
                arguments_schema.append(s)
            elif p.kind == Parameter.VAR_POSITIONAL:
                schema['var_args_schema'] = arg_schema
            else:
                assert p.kind == Parameter.VAR_KEYWORD, p.kind
                schema['var_kwargs_schema'] = arg_schema

        validator = SchemaValidator(schema, config=config)

        @wraps(function)
        def wrapper(*args, **kwargs):
            # Validate arguments using the original schema
            validated_args, validated_kwargs = validator.validate_python(ArgsKwargs(args, kwargs))
            return function(*validated_args, **validated_kwargs)

        return wrapper

    return decorator


def test_function_any():
    @validate()
    def foobar(a, b, c):
        return a, b, c

    assert foobar(1, 2, 3) == (1, 2, 3)
    assert foobar(1, 2, 3) == (1, 2, 3)
    assert foobar(a=1, b=2, c=3) == (1, 2, 3)
    assert foobar(1, b=2, c=3) == (1, 2, 3)

    with pytest.raises(ValidationError, match='Unexpected positional argument'):
        foobar(1, 2, 3, 4)

    with pytest.raises(ValidationError, match='d\n  Unexpected keyword argument'):
        foobar(1, 2, 3, d=4)


def test_function_types():
    @validate()
    def foobar(a: int, b: int, *, c: int):
        return a, b, c

    assert foobar(1, 2, c='3') == (1, 2, 3)
    assert foobar(a=1, b='2', c=3) == (1, 2, 3)

    with pytest.raises(ValidationError, match='Unexpected positional argument'):
        foobar(1, 2, 3)

    with pytest.raises(ValidationError) as exc_info:
        foobar(1, 'b')

    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'int_parsing',
            'loc': (1,),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'input': 'b',
        },
        {
            'type': 'missing_keyword_only_argument',
            'loc': ('c',),
            'msg': 'Missing required keyword only argument',
            'input': ArgsKwargs((1, 'b')),
        },
    ]

    with pytest.raises(ValidationError) as exc_info:
        foobar(1, 'b', c='c')

    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'int_parsing',
            'loc': (1,),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'input': 'b',
        },
        {
            'type': 'int_parsing',
            'loc': ('c',),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'input': 'c',
        },
    ]


def test_function_positional_only(import_execute):
    # language=Python
    m = import_execute(
        """
def create_function(validate, config = None):
    @validate(config = config)
    def foobar(a: int, b: int, /, c: int):
        return a, b, c
    return foobar
"""
    )
    foobar = m.create_function(validate)
    assert foobar('1', 2, 3) == (1, 2, 3)
    assert foobar('1', 2, c=3) == (1, 2, 3)
    with pytest.raises(ValidationError) as exc_info:
        foobar('1', b=2, c=3)
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'missing_positional_only_argument',
            'loc': (1,),
            'msg': 'Missing required positional only argument',
            'input': ArgsKwargs(('1',), {'b': 2, 'c': 3}),
        },
        {'type': 'unexpected_keyword_argument', 'loc': ('b',), 'msg': 'Unexpected keyword argument', 'input': 2},
    ]
    # Allowing extras using the config
    foobar = m.create_function(validate, config={'title': 'func', 'extra_fields_behavior': 'allow'})
    assert foobar('1', '2', c=3, d=4) == (1, 2, 3)
    # Ignore works similar than allow
    foobar = m.create_function(validate, config={'title': 'func', 'extra_fields_behavior': 'ignore'})
    assert foobar('1', '2', c=3, d=4) == (1, 2, 3)


def test_function_positional_only_default(import_execute):
    # language=Python
    m = import_execute(
        """
def create_function(validate):
    @validate()
    def foobar(a: int, b: int = 42, /):
        return a, b
    return foobar
"""
    )
    foobar = m.create_function(validate)
    assert foobar('1', 2) == (1, 2)
    assert foobar('1') == (1, 42)


def test_function_positional_kwargs(import_execute):
    # language=Python
    m = import_execute(
        """
def create_function(validate):
    @validate()
    def foobar(a: int, b: int, /, **kwargs: bool):
        return a, b, kwargs
    return foobar
"""
    )
    foobar = m.create_function(validate)
    assert foobar('1', 2) == (1, 2, {})
    assert foobar('1', 2, c=True) == (1, 2, {'c': True})
    assert foobar('1', 2, a='false') == (1, 2, {'a': False})


def test_function_args_kwargs():
    @validate()
    def foobar(*args, **kwargs):
        return args, kwargs

    assert foobar(1, 2, 3, a=4, b=5) == ((1, 2, 3), {'a': 4, 'b': 5})
    assert foobar(1, 2, 3) == ((1, 2, 3), {})
    assert foobar(a=1, b=2, c=3) == ((), {'a': 1, 'b': 2, 'c': 3})
    assert foobar() == ((), {})


def test_invalid_schema():
    with pytest.raises(SchemaError, match="'default' and 'default_factory' cannot be used together"):
        SchemaValidator(
            schema=cs.arguments_schema(
                arguments=[
                    {
                        'name': 'a',
                        'mode': 'positional_or_keyword',
                        'schema': cs.with_default_schema(schema=cs.int_schema(), default=1, default_factory=lambda: 2),
                    }
                ]
            )
        )


def test_error_display(pydantic_version):
    v = SchemaValidator(
        core_schema.arguments_schema(
            [
                core_schema.arguments_parameter('a', core_schema.int_schema()),
                core_schema.arguments_parameter('b', core_schema.int_schema()),
            ]
        )
    )
    assert v.validate_python(ArgsKwargs((1,), {'b': '2'})) == ((1,), {'b': 2})

    with pytest.raises(ValidationError) as exc_info:
        v.validate_python(ArgsKwargs((), {'a': 1}))

    # insert_assert(exc_info.value.errors(include_url=False))
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'missing_argument',
            'loc': ('b',),
            'msg': 'Missing required argument',
            'input': ArgsKwargs((), {'a': 1}),
        }
    ]
    # insert_assert(str(exc_info.value))
    assert str(exc_info.value) == (
        '1 validation error for arguments\n'
        'b\n'
        '  Missing required argument [type=missing_argument, '
        "input_value=ArgsKwargs((), {'a': 1}), input_type=ArgsKwargs]"
        + (
            f'\n    For further information visit https://errors.pydantic.dev/{pydantic_version}/v/missing_argument'
            if os.environ.get('PYDANTIC_ERRORS_INCLUDE_URL') != 'false'
            else ''
        )
    )
    # insert_assert(exc_info.value.json(include_url=False))
    assert exc_info.value.json(include_url=False) == (
        '[{"type":"missing_argument","loc":["b"],"msg":"Missing required argument",'
        '"input":"ArgsKwargs((), {\'a\': 1})"}]'
    )


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

    schema = core_schema.arguments_schema(
        arguments=[
            core_schema.arguments_parameter(name='my_field', schema=core_schema.int_schema(), alias='my_alias'),
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
