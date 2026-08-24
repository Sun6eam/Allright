from io import StringIO

import pytest

from allright.mascot import (
    MASCOT_ERROR,
    MASCOT_NORMAL,
    MASCOT_OFFLINE,
    classify_mascot_state,
    mascot_art,
    render_mascot,
)
from allright.providers.clients import AnthropicCompatibleModelClient, OpenAICompatibleModelClient


class ApiClient:
    def __init__(self, api_key):
        self.api_key = api_key


def test_ascii_mascot_exists_for_each_state():
    for state in (MASCOT_NORMAL, MASCOT_ERROR, MASCOT_OFFLINE):
        art = mascot_art(state)
        assert len(art.splitlines()) == 5
        assert {len(line) for line in art.splitlines()} == {15}
        assert "A" in art

    assert "^.^" in mascot_art(MASCOT_NORMAL)
    assert "-.-" in mascot_art(MASCOT_OFFLINE)
    assert "x.x" in mascot_art(MASCOT_ERROR)


def test_mascot_state_uses_offline_for_missing_api_key_or_network_error():
    assert classify_mascot_state(ApiClient(None)) == MASCOT_OFFLINE
    assert classify_mascot_state(ApiClient("sk-test"), RuntimeError("Could not reach backend")) == MASCOT_OFFLINE
    assert classify_mascot_state(ApiClient("sk-test"), RuntimeError("HTTP 401 unauthorized")) == MASCOT_OFFLINE


def test_mascot_state_uses_error_for_other_failures():
    assert classify_mascot_state(ApiClient("sk-test"), RuntimeError("invalid response JSON")) == MASCOT_ERROR
    assert classify_mascot_state(ApiClient("sk-test")) == MASCOT_NORMAL


def test_ascii_mascot_can_be_forced_for_snapshot_or_pipe_output():
    rendered = render_mascot(
        MASCOT_NORMAL,
        stream=StringIO(),
        env={
            "ALLRIGHT_FORCE_MASCOT": "1",
        },
    )
    assert rendered == mascot_art(MASCOT_NORMAL)
    assert "\x1b" not in rendered


def test_mascot_stays_quiet_for_non_tty_and_supports_opt_out():
    assert render_mascot(MASCOT_NORMAL, stream=StringIO(), env={}) == ""
    assert (
        render_mascot(
            MASCOT_NORMAL,
            stream=StringIO(),
            env={"ALLRIGHT_FORCE_MASCOT": "1", "ALLRIGHT_MASCOT": "off"},
        )
        == ""
    )


def test_unknown_mascot_state_is_rejected():
    with pytest.raises(ValueError, match="unknown mascot state"):
        render_mascot("confused", stream=StringIO(), env={"ALLRIGHT_FORCE_MASCOT": "1"})


@pytest.mark.parametrize(
    "client",
    [
        OpenAICompatibleModelClient(
            model="test",
            base_url="https://example.test/v1",
            api_key=None,
            temperature=0.2,
            timeout=1,
        ),
        AnthropicCompatibleModelClient(
            model="test",
            base_url="https://example.test/v1",
            api_key=None,
            temperature=0.2,
            timeout=1,
        ),
    ],
)
def test_cloud_clients_reject_missing_api_key_before_network_request(client):
    with pytest.raises(RuntimeError, match="API key is missing"):
        client.complete("hello", 8)
