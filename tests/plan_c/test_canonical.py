"""Canonical JSON v1 (BUILD_SPEC §6, R005): the same logical payload must always hash to the same bytes.

Catches: a serialiser option drifting (key order, separators, escaping), NFC not applied, two keys that collide under
NFC being silently merged, floats or non-finite numbers sneaking into a hashed payload, and duplicate JSON keys being
silently collapsed by the parser.
"""

import json
import unicodedata
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ops_core.canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    canonical_json,
    canonical_sha256,
    parse_json_strict,
    sha256_hex,
)

# Values that can appear in a hashed payload: no floats (integers only, BUILD_SPEC §6), keys are strings. Keys are
# drawn already NFC-normalised so two generated keys never collide under NFC (a collision is an error, tested below).
nfc_keys = st.text(max_size=12).map(lambda s: unicodedata.normalize("NFC", s))
scalars = st.none() | st.booleans() | st.integers(min_value=-(2**63), max_value=2**63 - 1) | st.text(max_size=40)
payloads = st.recursive(
    scalars,
    lambda inner: st.lists(inner, max_size=5) | st.dictionaries(nfc_keys, inner, max_size=5),
    max_leaves=25,
)


def test_version_is_one():
    assert CANONICALIZATION_VERSION == 1


def test_known_bytes_and_hash():
    assert canonical_json({"b": 1, "a": [True, None, "é"]}) == b'{"a":[true,null,"\xc3\xa9"],"b":1}'
    # The reference's test_canonical_hash_order: key order never changes the hash.
    assert canonical_sha256({"a": 2, "b": 1}) == canonical_sha256({"b": 1, "a": 2})
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@settings(max_examples=200)
@given(payloads)
def test_round_trip_and_key_order_independence(value):
    first = canonical_json(value)
    assert canonical_json(parse_json_strict(first.decode("utf-8"))) == first
    if isinstance(value, dict):
        reordered = dict(reversed(list(value.items())))
        assert canonical_json(reordered) == first


@given(st.text(min_size=1, max_size=20))
def test_strings_are_nfc_normalised(s):
    nfd = unicodedata.normalize("NFD", s)
    assert canonical_json({"k": nfd}) == canonical_json({"k": unicodedata.normalize("NFC", s)})
    assert json.loads(canonical_json({"k": nfd}))["k"] == unicodedata.normalize("NFC", s)


def test_keys_that_collide_under_nfc_are_rejected():
    # The first key is "e" + combining acute (NFD), the second the precomposed "\u00e9" (NFC): two different Python
    # keys that collide after normalisation. Escapes, not literals, so retyping cannot turn both into NFC.
    with pytest.raises(CanonicalizationError, match="key collision after NFC"):
        canonical_json({"e\u0301": 1, "\u00e9": 2})


@pytest.mark.parametrize(
    "bad", [1.5, float("nan"), float("inf"), {"k": 1.0}, [0.0]], ids=["float", "nan", "inf", "nested", "list"]
)
def test_floats_are_rejected(bad):
    with pytest.raises(CanonicalizationError, match="float"):
        canonical_json(bad)


def test_non_string_keys_are_rejected():
    with pytest.raises(CanonicalizationError, match="key"):
        canonical_json({1: "a"})


@pytest.mark.parametrize(
    "text",
    ['{"a": 1, "a": 2}', "NaN", "[Infinity]", '{"a": 1.5}', '{"a": -0.0}', "1e3", "1E2"],
    ids=["duplicate-key", "nan", "infinity", "float", "neg-zero", "exp-lower", "exp-upper"],
)
def test_strict_parser_rejects(text):
    with pytest.raises(CanonicalizationError):
        parse_json_strict(text)


def test_strict_parser_accepts_ints_and_unicode():
    assert parse_json_strict('{"n": 12345678901234567890, "s": "\\u00e9"}') == {"n": 12345678901234567890, "s": "é"}


def test_tuples_become_arrays():
    assert canonical_json((1, 2)) == b"[1,2]"


def test_bool_is_never_an_int():
    assert canonical_json({"a": True, "b": 1}) == b'{"a":true,"b":1}'


@pytest.mark.parametrize("bad", [{1}, b"x", datetime(2026, 1, 1, tzinfo=UTC)], ids=["set", "bytes", "datetime"])
def test_unsupported_types_are_rejected(bad):
    with pytest.raises(CanonicalizationError, match="unsupported type"):
        canonical_json(bad)


def test_oversized_int_is_a_canonicalization_error():
    # CPython refuses ints over 4300 digits with a bare ValueError; callers must only ever see CanonicalizationError.
    with pytest.raises(CanonicalizationError):
        parse_json_strict("1" * 5000)
    with pytest.raises(CanonicalizationError):
        canonical_json(10**5000)
