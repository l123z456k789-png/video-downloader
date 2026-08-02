"""config.py 模块测试。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from config import (
    DEFAULTS,
    _merge_dicts,
    load_config,
    reload_config,
    validate_config,
)


class TestMergeDicts:
    def test_shallow_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _merge_dicts(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 4}}
        result = _merge_dicts(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 4}, "b": 3}

    def test_override_adds_new_top_level(self):
        base = {"a": 1}
        override = {"b": {"x": 2}}
        result = _merge_dicts(base, override)
        assert result == {"a": 1, "b": {"x": 2}}


class TestDefaults:
    def test_defaults_have_required_keys(self):
        assert "downloader" in DEFAULTS
        assert "tools" in DEFAULTS
        assert "browser" in DEFAULTS
        assert "audio" in DEFAULTS
        assert "logging" in DEFAULTS

    def test_default_output_dir(self):
        assert DEFAULTS["downloader"]["output_dir"] == "videos"

    def test_default_format(self):
        assert "bestvideo" in DEFAULTS["downloader"]["format"]

    def test_default_retries(self):
        assert DEFAULTS["downloader"]["retries"] == 5

    def test_default_socket_timeout(self):
        assert DEFAULTS["downloader"]["socket_timeout"] == 30


class TestValidateConfig:
    def test_valid_config_passes(self):
        errors = validate_config(DEFAULTS)
        assert errors == []

    def test_missing_output_dir(self):
        cfg = {
            "downloader": {"output_dir": "", "retries": 5, "socket_timeout": 30},
            "logging": {"level": "INFO"},
        }
        errors = validate_config(cfg)
        assert any("output_dir" in e for e in errors)

    def test_retries_out_of_range(self):
        cfg = {
            "downloader": {"output_dir": "videos", "retries": 100, "socket_timeout": 30},
            "logging": {"level": "INFO"},
        }
        errors = validate_config(cfg)
        assert any("retries" in e for e in errors)

    def test_timeout_too_low(self):
        cfg = {
            "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 1},
            "logging": {"level": "INFO"},
        }
        errors = validate_config(cfg)
        assert any("socket_timeout" in e for e in errors)

    def test_invalid_log_level(self):
        cfg = {
            "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 30},
            "logging": {"level": "TRACE"},
        }
        errors = validate_config(cfg)
        assert any("logging.level" in e for e in errors)
