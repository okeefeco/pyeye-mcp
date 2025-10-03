"""Tests for performance settings configuration."""

import os
from unittest.mock import patch

from pyeye.settings import PerformanceSettings


class TestPerformanceSettings:
    """Test the PerformanceSettings class."""

    def test_default_settings(self):
        """Test default settings are loaded correctly."""
        settings = PerformanceSettings()

        assert settings.max_projects == 10
        assert settings.cache_ttl == 300
        assert settings.watcher_debounce == 0.5
        assert settings.max_file_size == 1048576
        assert settings.max_workers == 4
        assert settings.analysis_timeout == 30.0
        assert settings.enable_memory_profiling is False
        assert settings.enable_performance_metrics is False

    def test_env_var_override(self):
        """Test environment variables override defaults."""
        env_vars = {
            "PYEYE_MAX_PROJECTS": "20",
            "PYEYE_CACHE_TTL": "600",
            "PYEYE_WATCHER_DEBOUNCE": "1.5",
            "PYEYE_MAX_FILE_SIZE": "2097152",
            "PYEYE_MAX_WORKERS": "8",
            "PYEYE_ANALYSIS_TIMEOUT": "60.0",
            "PYEYE_ENABLE_MEMORY_PROFILING": "true",
            "PYEYE_ENABLE_PERFORMANCE_METRICS": "yes",
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()

            assert settings.max_projects == 20
            assert settings.cache_ttl == 600
            assert settings.watcher_debounce == 1.5
            assert settings.max_file_size == 2097152
            assert settings.max_workers == 8
            assert settings.analysis_timeout == 60.0
            assert settings.enable_memory_profiling is True
            assert settings.enable_performance_metrics is True

    def test_min_value_validation(self):
        """Test minimum value validation."""
        env_vars = {
            "PYEYE_MAX_PROJECTS": "0",  # Below min of 1
            "PYEYE_CACHE_TTL": "-1",  # Below min of 0
            "PYEYE_WATCHER_DEBOUNCE": "-0.5",  # Below min of 0.0
            "PYEYE_MAX_FILE_SIZE": "500",  # Below min of 1024
            "PYEYE_MAX_WORKERS": "0",  # Below min of 1
            "PYEYE_ANALYSIS_TIMEOUT": "0.5",  # Below min of 1.0
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()

            # Should use minimum values
            assert settings.max_projects == 1
            assert settings.cache_ttl == 0
            assert settings.watcher_debounce == 0.0
            assert settings.max_file_size == 1024
            assert settings.max_workers == 1
            assert settings.analysis_timeout == 1.0

    def test_max_value_validation(self):
        """Test maximum value validation."""
        env_vars = {
            "PYEYE_MAX_PROJECTS": "2000",  # Above max of 1000
            "PYEYE_CACHE_TTL": "100000",  # Above max of 86400
            "PYEYE_WATCHER_DEBOUNCE": "20.0",  # Above max of 10.0
            "PYEYE_MAX_FILE_SIZE": "200000000",  # Above max of 104857600
            "PYEYE_MAX_WORKERS": "50",  # Above max of 32
            "PYEYE_ANALYSIS_TIMEOUT": "500.0",  # Above max of 300.0
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()

            # Should use maximum values
            assert settings.max_projects == 1000
            assert settings.cache_ttl == 86400
            assert settings.watcher_debounce == 10.0
            assert settings.max_file_size == 104857600
            assert settings.max_workers == 32
            assert settings.analysis_timeout == 300.0

    def test_invalid_value_handling(self):
        """Test handling of invalid environment variable values."""
        env_vars = {
            "PYEYE_MAX_PROJECTS": "not_a_number",
            "PYEYE_CACHE_TTL": "invalid",
            "PYEYE_WATCHER_DEBOUNCE": "abc",
            "PYEYE_MAX_FILE_SIZE": "",
            "PYEYE_MAX_WORKERS": "null",
            "PYEYE_ANALYSIS_TIMEOUT": "undefined",
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()

            # Should use default values for invalid inputs
            assert settings.max_projects == 10
            assert settings.cache_ttl == 300
            assert settings.watcher_debounce == 0.5
            assert settings.max_file_size == 1048576
            assert settings.max_workers == 4
            assert settings.analysis_timeout == 30.0

    def test_boolean_env_vars(self):
        """Test boolean environment variable parsing."""
        # Test various true values
        true_values = ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]
        for value in true_values:
            with patch.dict(os.environ, {"PYEYE_ENABLE_MEMORY_PROFILING": value}):
                settings = PerformanceSettings()
                assert settings.enable_memory_profiling is True, f"Failed for value: {value}"

        # Test various false values
        false_values = ["false", "False", "FALSE", "0", "no", "NO", "off", "OFF", ""]
        for value in false_values:
            with patch.dict(os.environ, {"PYEYE_ENABLE_MEMORY_PROFILING": value}):
                settings = PerformanceSettings()
                assert settings.enable_memory_profiling is False, f"Failed for value: {value}"

    def test_get_summary(self):
        """Test the summary output."""
        settings = PerformanceSettings()
        summary = settings.get_summary()

        # Check that summary contains all settings
        assert "Performance Settings:" in summary
        assert "max_projects: 10" in summary
        assert "cache_ttl: 300s" in summary
        assert "watcher_debounce: 0.5s" in summary
        assert "max_file_size: 1048576 bytes (1.00 MB)" in summary
        assert "max_workers: 4" in summary
        assert "analysis_timeout: 30.0s" in summary
        assert "enable_memory_profiling: False" in summary
        assert "enable_performance_metrics: False" in summary

    def test_performance_tuning_scenarios(self):
        """Test different performance tuning scenarios from documentation."""
        # Large codebase with stable files
        env_vars = {
            "PYEYE_MAX_PROJECTS": "50",
            "PYEYE_CACHE_TTL": "1800",
            "PYEYE_WATCHER_DEBOUNCE": "2.0",
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()
            assert settings.max_projects == 50
            assert settings.cache_ttl == 1800
            assert settings.watcher_debounce == 2.0

        # Active development with frequent changes
        env_vars = {
            "PYEYE_MAX_PROJECTS": "5",
            "PYEYE_CACHE_TTL": "60",
            "PYEYE_WATCHER_DEBOUNCE": "0.1",
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()
            assert settings.max_projects == 5
            assert settings.cache_ttl == 60
            assert settings.watcher_debounce == 0.1

        # Memory-constrained environment
        env_vars = {
            "PYEYE_MAX_PROJECTS": "3",
            "PYEYE_MAX_FILE_SIZE": "524288",
            "PYEYE_MAX_WORKERS": "2",
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()
            assert settings.max_projects == 3
            assert settings.max_file_size == 524288
            assert settings.max_workers == 2

    def test_edge_cases(self):
        """Test edge cases and boundary values."""
        # Test exact boundary values
        env_vars = {
            "PYEYE_MAX_PROJECTS": "1",  # Minimum
            "PYEYE_CACHE_TTL": "86400",  # Maximum
            "PYEYE_WATCHER_DEBOUNCE": "0.0",  # Minimum
            "PYEYE_MAX_FILE_SIZE": "104857600",  # Maximum
        }

        with patch.dict(os.environ, env_vars):
            settings = PerformanceSettings()
            assert settings.max_projects == 1
            assert settings.cache_ttl == 86400
            assert settings.watcher_debounce == 0.0
            assert settings.max_file_size == 104857600

    def test_mixed_case_boolean_env(self):
        """Test mixed case boolean values."""
        mixed_case_values = ["Yes", "yEs", "On", "oN", "TrUe"]
        for value in mixed_case_values:
            with patch.dict(os.environ, {"PYEYE_ENABLE_PERFORMANCE_METRICS": value}):
                settings = PerformanceSettings()
                assert settings.enable_performance_metrics is True, f"Failed for value: {value}"
