"""Configuration validation and environment loading."""

from __future__ import annotations

import pytest

from marvind.config import BrainConfig, ConfigError


def test_urls_are_derived_from_the_base_url_without_a_double_slash():
    config = BrainConfig(base_url="http://127.0.0.1:8080/")
    assert config.chat_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert config.health_url == "http://127.0.0.1:8080/health"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "127.0.0.1:8080"},
        {"temperature": 2.5},
        {"top_p": 0.0},
        {"max_tokens": 0},
        {"max_turns": 0},
        {"request_timeout_s": 0.0},
    ],
)
def test_out_of_range_settings_are_rejected_at_construction(kwargs):
    with pytest.raises(ConfigError):
        BrainConfig(**kwargs)


def test_from_env_reads_marvin_variables():
    config = BrainConfig.from_env({"MARVIN_LLM_URL": "http://box:9000", "MARVIN_TEMPERATURE": "0.4"})
    assert config.base_url == "http://box:9000"
    assert config.temperature == 0.4


def test_from_env_falls_back_to_defaults_when_unset():
    assert BrainConfig.from_env({}).base_url == BrainConfig().base_url


def test_from_env_rejects_a_non_numeric_value():
    with pytest.raises(ConfigError, match="MARVIN_TEMPERATURE"):
        BrainConfig.from_env({"MARVIN_TEMPERATURE": "warm"})


def test_config_is_frozen():
    with pytest.raises(Exception):
        BrainConfig().temperature = 0.1
