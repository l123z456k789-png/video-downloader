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


class TestNetworkConfig:
    """network 配置节 — 下载引擎模式。"""

    def test_default_mode_is_auto(self):
        assert DEFAULTS["network"]["mode"] == "auto"

    def test_default_proxy_is_empty(self):
        assert DEFAULTS["network"]["proxy"] == ""

    def test_valid_modes_pass_validation(self):
        for mode in ("auto", "strict"):
            cfg = {
                "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 30},
                "logging": {"level": "INFO"},
                "network": {"mode": mode},
            }
            errors = validate_config(cfg)
            assert errors == [], f"mode={mode} should pass, got: {errors}"

    def test_invalid_mode_rejected(self):
        cfg = {
            "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 30},
            "logging": {"level": "INFO"},
            "network": {"mode": "turbo"},
        }
        errors = validate_config(cfg)
        assert any("network.mode" in e for e in errors)

    def test_network_section_in_defaults(self):
        assert "network" in DEFAULTS
        assert "mode" in DEFAULTS["network"]
        assert "proxy" in DEFAULTS["network"]


class TestCookiesConfig:
    """cookies 配置节 — Cookie 来源。"""

    def test_default_mode_is_none(self):
        assert DEFAULTS["cookies"]["mode"] == "none"

    def test_default_file_is_empty(self):
        assert DEFAULTS["cookies"]["file"] == ""

    def test_valid_modes_pass_validation(self):
        for mode in ("none", "browser", "file"):
            cfg = {
                "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 30},
                "logging": {"level": "INFO"},
                "cookies": {"mode": mode},
            }
            errors = validate_config(cfg)
            assert errors == [], f"mode={mode} should pass, got: {errors}"

    def test_invalid_cookie_mode_rejected(self):
        cfg = {
            "downloader": {"output_dir": "videos", "retries": 5, "socket_timeout": 30},
            "logging": {"level": "INFO"},
            "cookies": {"mode": "database"},
        }
        errors = validate_config(cfg)
        assert any("cookies.mode" in e for e in errors)

    def test_cookies_section_in_defaults(self):
        assert "cookies" in DEFAULTS
        assert "mode" in DEFAULTS["cookies"]
        assert "file" in DEFAULTS["cookies"]
