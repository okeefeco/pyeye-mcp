"""Test dogfooding integration functionality."""

import json

import pytest

from pycodemcp.dogfooding_integration import DogfoodingIntegration
from pycodemcp.metrics import MetricsCollector


@pytest.fixture
def temp_metrics_dir(tmp_path):
    """Create temporary metrics directory."""
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    return metrics_dir


@pytest.fixture
def integration(temp_metrics_dir):
    """Create dogfooding integration instance."""
    return DogfoodingIntegration(temp_metrics_dir)


@pytest.fixture
def mock_metrics():
    """Create metrics collector with test data."""
    metrics = MetricsCollector()

    # Simulate some MCP tool calls
    metrics.metrics["find_symbol"].add_value(50.0)
    metrics.metrics["find_symbol"].add_value(35.0)
    metrics.metrics["find_references"].add_value(120.0)

    # Simulate cache activity
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    metrics.record_cache_miss()

    return metrics


def test_export_mcp_metrics_for_session(integration, mock_metrics, monkeypatch):
    """Test exporting MCP metrics for dogfooding session."""
    # Mock the global metrics instance
    import pycodemcp.dogfooding_integration

    monkeypatch.setattr(pycodemcp.dogfooding_integration, "mcp_metrics", mock_metrics)

    # Override the get_performance_report method to return test data
    def mock_get_performance_report():
        return {
            "operations": {
                "symbol_search": {
                    "find_symbol": {"count": 2, "avg_ms": 42.5, "errors": 0},
                    "find_references": {"count": 1, "avg_ms": 120.0, "errors": 0},
                },
                "file_operations": {},
                "other": {},
            },
            "cache": {"hits": 2, "misses": 1, "hit_rate": 0.67},
            "memory": {"rss_mb": 64.0, "percent": 0.4},
        }

    mock_metrics.get_performance_report = mock_get_performance_report

    result = integration.export_mcp_metrics_for_session()

    assert result["total_mcp_calls"] == 3  # 2 find_symbol + 1 find_references
    assert len(result["tool_calls"]) == 2

    # Check tools are sorted by usage count
    assert result["tool_calls"][0]["tool"] == "find_symbol"
    assert result["tool_calls"][0]["count"] == 2
    assert result["tool_calls"][1]["tool"] == "find_references"
    assert result["tool_calls"][1]["count"] == 1

    assert "cache_stats" in result
    assert "memory_stats" in result
    assert "timestamp" in result


def test_log_mcp_call(integration):
    """Test logging individual MCP tool calls."""
    integration.log_mcp_call("find_symbol", {"name": "TestClass", "fuzzy": False})

    # Check log file was created
    assert integration.mcp_log_file.exists()

    with open(integration.mcp_log_file) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["tool"] == "find_symbol"
    assert log_entry["params"]["name"] == "TestClass"
    assert log_entry["params"]["fuzzy"] is False
    assert "timestamp" in log_entry


def test_update_session_with_mcp_stats_no_session(integration):
    """Test updating session when no active session exists."""
    result = integration.update_session_with_mcp_stats()
    assert result is False


def test_update_session_with_mcp_stats_with_session(integration):
    """Test updating session with MCP statistics."""
    # Create a mock session file
    session_data = {
        "id": "test-session",
        "issue": 170,
        "start_time": "2025-08-24T10:00:00",
        "mcp_queries_count": 0,
    }

    with open(integration.session_file, "w") as f:
        json.dump(session_data, f)

    # Mock the export function to return test data
    def mock_export():
        return {
            "total_mcp_calls": 5,
            "tool_calls": [
                {"tool": "find_symbol", "count": 3},
                {"tool": "find_references", "count": 2},
            ],
            "timestamp": "2025-08-24T10:30:00",
        }

    integration.export_mcp_metrics_for_session = mock_export

    result = integration.update_session_with_mcp_stats()
    assert result is True

    # Check session was updated
    with open(integration.session_file) as f:
        updated_session = json.load(f)

    assert updated_session["mcp_queries_count"] == 5
    assert "mcp_metrics" in updated_session
    assert "last_mcp_update" in updated_session


def test_get_mcp_adoption_rate_no_session(integration):
    """Test adoption rate calculation when no session exists."""
    result = integration.get_mcp_adoption_rate()
    assert "error" in result


def test_get_mcp_adoption_rate_with_session(integration):
    """Test adoption rate calculation with active session."""
    session_data = {"id": "test-session", "issue": 170, "mcp_queries_count": 8, "grep_count": 2}

    with open(integration.session_file, "w") as f:
        json.dump(session_data, f)

    result = integration.get_mcp_adoption_rate()

    assert result["mcp_queries"] == 8
    assert result["grep_usage"] == 2
    assert result["total_searches"] == 10
    assert result["mcp_adoption_rate"] == 80.0  # 8/10 * 100
    assert result["session_id"] == "test-session"
    assert result["issue"] == 170


def test_sync_mcp_metrics_function(monkeypatch):
    """Test the sync_mcp_metrics convenience function."""
    from pycodemcp.dogfooding_integration import sync_mcp_metrics

    # Mock the integration methods
    def mock_update(self):  # noqa: ARG001
        return True

    monkeypatch.setattr(DogfoodingIntegration, "update_session_with_mcp_stats", mock_update)

    result = sync_mcp_metrics()
    assert result is True


class TestIntegrationWithRealMetrics:
    """Integration tests with real metrics collection."""

    def test_real_metrics_integration(self, integration):
        """Test integration with real MetricsCollector."""
        # Create real metrics collector
        from pycodemcp.metrics import MetricsCollector

        real_metrics = MetricsCollector()

        # Simulate some operations
        with real_metrics.timer("test_operation"):
            pass

        real_metrics.record_cache_hit()
        real_metrics.record_cache_miss()

        # Export metrics
        result = integration.export_mcp_metrics_for_session()

        # Should have structure even if no MCP tools were called
        assert "total_mcp_calls" in result
        assert "tool_calls" in result
        assert "cache_stats" in result
        assert "memory_stats" in result
        assert "timestamp" in result
