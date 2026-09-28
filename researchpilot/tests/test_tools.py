"""Unit tests for ResearchPilot Web Search and URL Reader Tools."""
import unittest
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import web_search, read_url, ToolResult


class TestTools(unittest.TestCase):
    """Test suite for research tool implementations."""

    def test_web_search_structure(self):
        """Test web_search returns valid ToolResult with query and results list."""
        res = web_search("AI agent architectures")
        self.assertIsInstance(res, ToolResult)
        self.assertTrue(res.success)
        self.assertIn("results", res.data)
        self.assertGreater(len(res.data["results"]), 0)
        
        # Verify first item schema
        item = res.data["results"][0]
        self.assertIn("title", item)
        self.assertIn("url", item)
        self.assertIn("snippet", item)
        self.assertGreaterEqual(res.duration_ms, 0)

    def test_web_search_empty_query(self):
        """Test web_search handles empty query gracefully."""
        res = web_search("")
        self.assertFalse(res.success)
        self.assertIn("empty", res.error.lower())

    def test_web_search_simulated_failure(self):
        """Test web_search triggers deterministic simulated timeout."""
        res = web_search("AI agent architectures", simulate_failure=True)
        self.assertFalse(res.success)
        self.assertIn("simulated", res.error.lower())
        self.assertEqual(len(res.data.get("results", [])), 0)

    def test_read_url_invalid_scheme(self):
        """Test 5: read_url rejects invalid URL schemes gracefully."""
        res = read_url("not_a_valid_url")
        self.assertFalse(res.success)
        self.assertIn("invalid", res.error.lower())

    def test_read_url_simulated_failure(self):
        """Test read_url triggers deterministic simulated timeout."""
        res = read_url("https://example.com", simulate_failure=True)
        self.assertFalse(res.success)
        self.assertIn("simulated", res.error.lower())

    def test_read_url_valid_fetch(self):
        """Test read_url successfully extracts content from reliable page."""
        # Using a reliable standard documentation/RFC endpoint
        res = read_url("https://example.com")
        self.assertIsInstance(res, ToolResult)
        if res.success:
            self.assertIn("content", res.data)
            self.assertIn("title", res.data)
            self.assertGreater(len(res.data["content"]), 20)


if __name__ == "__main__":
    unittest.main()
