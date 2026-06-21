"""Characterization tests for the API envelope unwrap + list-shape helpers.

These two pure functions carry the data layer's most carefully-tuned
decisions — the auth-vs-business-error classification (deliberately NARROW so a
quota/level gate isn't misreported as a bad key) and the tolerant list
extraction. They had zero tests; these lock the current behavior so a
"helpful" broadening can't silently regress it.
"""

import pytest

from mteam_cli.api._internal import MTeamAPIError, MTeamAuthError, _unwrap
from mteam_cli.api.public import as_list


# ── _unwrap: success paths ──────────────────────────────────────


def test_unwrap_success_code_zero_int_returns_data():
    assert _unwrap({"code": 0, "message": "", "data": {"x": 1}}, "/p") == {"x": 1}


def test_unwrap_success_code_zero_string():
    assert _unwrap({"code": "0", "data": [1, 2]}, "/p") == [1, 2]


def test_unwrap_success_code_200():
    assert _unwrap({"code": 200, "data": "ok"}, "/p") == "ok"


def test_unwrap_no_code_returns_data_field():
    # Envelope without a code: fall back to the data field (or whole payload).
    assert _unwrap({"data": {"y": 2}}, "/p") == {"y": 2}
    assert _unwrap({"foo": "bar"}, "/p") == {"foo": "bar"}


def test_unwrap_non_dict_payload_passthrough():
    assert _unwrap([1, 2, 3], "/p") == [1, 2, 3]
    assert _unwrap("raw", "/p") == "raw"


# ── _unwrap: auth classification (the narrow-match guard) ───────


def test_unwrap_auth_code_401_raises_auth_error():
    with pytest.raises(MTeamAuthError):
        _unwrap({"code": "401", "message": "unauthorized"}, "/p")


def test_unwrap_key_invalid_message_raises_auth_error():
    with pytest.raises(MTeamAuthError):
        _unwrap({"code": "1", "message": "key無效"}, "/p")


def test_unwrap_no_permission_message_raises_auth_error():
    with pytest.raises(MTeamAuthError):
        _unwrap({"code": "1", "message": "無許可權"}, "/p")


def test_unwrap_quota_level_gate_is_NOT_auth_error():
    # "您的等級不足，沒有下載權限" is a business quota gate, NOT a key problem.
    # It contains 權限 but must stay a generic MTeamAPIError (and crucially NOT
    # MTeamAuthError) — this is the whole point of the narrow _AUTH_HINTS list.
    with pytest.raises(MTeamAPIError) as exc_info:
        _unwrap({"code": "1", "message": "您的等級不足，沒有下載權限"}, "/p")
    assert not isinstance(exc_info.value, MTeamAuthError)


# ── _unwrap: signature + generic errors ─────────────────────────


def test_unwrap_signature_error_raises_generic_with_hint():
    with pytest.raises(MTeamAPIError) as exc_info:
        _unwrap({"code": "1", "message": "簽名錯誤"}, "/msg/search")
    # Not an auth error — a distinct, honest "signature not supported" message.
    assert not isinstance(exc_info.value, MTeamAuthError)
    assert "签名" in str(exc_info.value) or "_sgin" in str(exc_info.value)


def test_unwrap_generic_error_raises_api_error():
    with pytest.raises(MTeamAPIError) as exc_info:
        _unwrap({"code": "500", "message": "伺服器錯誤"}, "/p")
    assert not isinstance(exc_info.value, MTeamAuthError)
    assert "500" in str(exc_info.value)


# ── as_list: tolerant shape extraction ──────────────────────────


def test_as_list_bare_list_of_dicts():
    assert as_list([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_as_list_filters_non_dict_elements():
    assert as_list([{"a": 1}, 5, "x", {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_as_list_data_key():
    assert as_list({"data": [{"a": 1}]}) == [{"a": 1}]


def test_as_list_alternate_keys():
    assert as_list({"records": [{"r": 1}]}) == [{"r": 1}]
    assert as_list({"rows": [{"x": 1}]}) == [{"x": 1}]


def test_as_list_nested_data_dict():
    # Paginated shape: {"data": {"data": [...], "total": N}}
    assert as_list({"data": {"data": [{"a": 1}], "total": 1}}) == [{"a": 1}]


def test_as_list_no_list_returns_empty():
    assert as_list({"total": 0}) == []
    assert as_list(None) == []
    assert as_list("nope") == []
