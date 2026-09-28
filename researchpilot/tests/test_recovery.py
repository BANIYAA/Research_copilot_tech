"""Unit tests for ResearchPilot Failure Recovery, Retries, and State Machine."""
import unittest
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.graph import run_agent, node_check_goal_completion, node_generate_report
from agent.validator import validate_result, validate_current_news_evidence, is_concrete_geopolitical_finding
from agent.recovery import refine_query, handle_failure
from tools.url_reader import is_article_content
from models.report import AgentState
from models.plan import FailureType, GoalIntent, SourceValidation
from tools import ToolResult


class TestRecovery(unittest.TestCase):
    """Test suite for autonomous recovery, retries, relevance validation, and goal completion."""

    def test_normal_agent_execution(self):
        """Test A: Full normal agent execution loop produces completed report and sources."""
        goal = "Research recent developments in AI agents and identify three important trends."
        state = run_agent(goal, simulate_failure=False)

        self.assertEqual(state.status, "COMPLETED")
        self.assertIsNotNone(state.final_report)
        self.assertEqual(state.final_report["status"], "COMPLETED")
        self.assertGreater(len(state.final_report["findings"]), 0)
        self.assertGreater(len(state.final_report["sources"]), 0)
        self.assertGreater(len(state.tool_calls), 0)
        self.assertGreater(len(state.execution_trace), 3)

    def test_current_news_execution(self):
        """Test B1: Current news research identifies intent, gathers news reporting, and completes."""
        goal = "Research the latest global news"
        state = run_agent(goal, simulate_failure=False)

        self.assertIn(state.status, ("COMPLETED", "PARTIAL"))
        self.assertIsNotNone(state.intent)
        self.assertEqual(state.intent["category"], "CURRENT_NEWS")
        self.assertTrue(state.intent["freshness_required"])
        self.assertIsNotNone(state.goal_completion)
        self.assertIsNotNone(state.final_report)

    def test_irrelevant_search_results_detection(self):
        """Test B2: Web search returning only academic/technical sources for a news task is rejected as IRRELEVANT_RESULTS."""
        mock_technical_results = ToolResult(
            success=True,
            data={
                "query": "Research the latest global news",
                "results": [
                    {
                        "title": "Wikipedia Search: Research the latest global news",
                        "url": "https://en.wikipedia.org/wiki/Special:Search?search=news",
                        "snippet": "Search results index on Wikipedia.",
                        "source_domain": "wikipedia.org",
                    },
                    {
                        "title": "arXiv papers on multi-agent architectures",
                        "url": "https://arxiv.org/search/?query=agents",
                        "snippet": "Computer science research papers on distributed agents.",
                        "source_domain": "arxiv.org",
                    },
                    {
                        "title": "GitHub repository: Open source AI agents",
                        "url": "https://github.com/topics/ai-agents",
                        "snippet": "Software code repository for AI framework.",
                        "source_domain": "github.com",
                    },
                ],
            },
            duration_ms=250,
        )

        intent_dict = {"category": "CURRENT_NEWS", "freshness_required": True}
        is_valid, failure_type, reason = validate_result(
            tool_name="web_search",
            result=mock_technical_results,
            intent=intent_dict,
            goal="Research the latest global news",
        )

        self.assertFalse(is_valid, "Expected technical sources to be flagged invalid for current news")
        self.assertEqual(failure_type, FailureType.IRRELEVANT_RESULTS)
        self.assertIn("technical", reason.lower())

    def test_empty_search_results_detection(self):
        """Test C: Empty search results trigger EMPTY_RESULTS validation failure and query refinement."""
        mock_empty_results = ToolResult(
            success=True,
            data={"query": "obscure nonexistent query 9999", "results": []},
            duration_ms=100,
        )
        is_valid, failure_type, reason = validate_result(
            tool_name="web_search",
            result=mock_empty_results,
            goal="obscure nonexistent query 9999",
        )
        self.assertFalse(is_valid)
        self.assertEqual(failure_type, FailureType.EMPTY_RESULTS)

    def test_search_timeout_detection(self):
        """Test D: Search timeout is classified as TIMEOUT failure."""
        mock_timeout = ToolResult(
            success=False,
            data={},
            error="Connection timed out after 8 seconds",
            duration_ms=8000,
        )
        is_valid, failure_type, reason = validate_result(
            tool_name="web_search",
            result=mock_timeout,
        )
        self.assertFalse(is_valid)
        self.assertEqual(failure_type, FailureType.TIMEOUT)

    def test_url_failure_detection(self):
        """Test E: URL failure returns SOURCE_READ_ERROR or INSUFFICIENT_CONTENT."""
        mock_url_err = ToolResult(
            success=False,
            data={},
            error="HTTP 404 Not Found",
            duration_ms=500,
        )
        is_valid, failure_type, reason = validate_result(
            tool_name="read_url",
            result=mock_url_err,
        )
        self.assertFalse(is_valid)
        self.assertEqual(failure_type, FailureType.SOURCE_READ_ERROR)

    def test_deliberate_simulated_failure_recovery(self):
        """Test G: System detects simulated failure, retries, executes recovery, and finishes."""
        goal = "Research recent AI agent frameworks."
        state = run_agent(goal, simulate_failure=True)

        self.assertEqual(state.status, "COMPLETED")
        self.assertIsNotNone(state.final_report)

        # Verify failure was caught and recorded
        self.assertGreater(len(state.failures), 0)
        self.assertTrue(
            any("simulated" in str(f.get("reason", "")).lower() for f in state.failures),
            "Expected simulated failure recorded in failure log",
        )

        # Verify recovery actions occurred
        self.assertGreater(len(state.recovery_actions), 0)

        # Verify trace mentions retry or failure
        trace_str = " ".join(state.execution_trace)
        self.assertTrue("retry" in trace_str.lower() or "failure" in trace_str.lower())

    def test_goal_not_satisfied_prevents_completed_status(self):
        """Test H: When tools execute but goal requirements are not satisfied, status is PARTIAL/FAILED, never COMPLETED."""
        state = AgentState(
            goal="Research the latest global news",
            intent={"category": "CURRENT_NEWS", "freshness_required": True},
            plan=[{"id": 1, "description": "Search news", "tool": "web_search", "status": "COMPLETED"}],
            sources=[],  # Zero validated sources collected
            findings=[], # Zero findings
            observations=[],
            tool_calls=[{"task_id": 1, "tool": "web_search", "success": True}],
        )

        # Run completion check
        state = node_check_goal_completion(state)
        self.assertFalse(state.goal_completion["completed"])

        # Generate report
        state = node_generate_report(state)
        self.assertNotEqual(state.final_report["status"], "COMPLETED")
        self.assertIn(state.final_report["status"], ("PARTIAL", "FAILED"))

    def test_query_refinement_utility(self):
        """Test query refinement expands keywords for news intent."""
        original = "latest global news"
        refined = refine_query(original, intent_category="CURRENT_NEWS", failure_type=FailureType.IRRELEVANT_RESULTS)
        self.assertNotEqual(original, refined)
        self.assertTrue("reuters" in refined.lower() or "bbc" in refined.lower() or "headlines" in refined.lower())

    def test_max_retries_circuit_breaker(self):
        """Test that failure handler does not exceed max_retries and avoids infinite loops."""
        state = AgentState(
            goal="Test query",
            plan=[{"id": 1, "description": "Mock step", "tool": "mock_tool", "input": "test"}],
            max_retries=2,
            retries=2,  # Already at limit
            current_task={"id": 1, "description": "Mock step", "tool": "mock_tool"},
        )
        updated_state, msg = handle_failure(state, "Simulated recurring network down", FailureType.TIMEOUT)

        self.assertIn("maximum retries", msg.lower())
        self.assertEqual(updated_state.current_task_index, 1)


    # =========================================================================
    # MANDATORY REGRESSION TESTS FOR VALIDATION & EVIDENCE GATES
    # =========================================================================

    def test_regression_1_search_returns_landing_pages(self):
        """TEST 1: Search returns BBC/Reuters/AP landing pages.
        Expected: INVALID, article_level = False, validated = False, goal_completed = False.
        """
        landing_page_results = ToolResult(
            success=True,
            data={
                "query": "Research the latest geopolitical news",
                "results": [
                    {
                        "title": "BBC World News — International Headlines and Global Coverage",
                        "url": "https://www.bbc.com/news/world",
                        "snippet": "Breaking international news, in-depth reports, and live analysis of major political, economic, and humanitarian developments worldwide.",
                        "source_domain": "bbc.com",
                        "article_level": False,
                    },
                    {
                        "title": "Reuters World News — Breaking Global News & Financial Markets",
                        "url": "https://www.reuters.com/world/",
                        "snippet": "Live Reuters international reporting covering global diplomacy, geopolitical crises, economic summits, and multilateral accords.",
                        "source_domain": "reuters.com",
                        "article_level": False,
                    },
                    {
                        "title": "Associated Press International News Wire",
                        "url": "https://apnews.com/world-news",
                        "snippet": "Direct wire reporting on breaking global events, election results, environmental summits, and conflict updates.",
                        "source_domain": "apnews.com",
                        "article_level": False,
                    },
                ],
            },
            duration_ms=150,
        )

        intent_dict = {"category": "CURRENT_NEWS", "freshness_required": True}
        is_valid, failure_type, reason = validate_result(
            tool_name="web_search",
            result=landing_page_results,
            intent=intent_dict,
            goal="Research the latest geopolitical news",
        )

        # Expected: INVALID, failure_type = LANDING_PAGE_ONLY
        self.assertFalse(is_valid, "Expected search returning only landing pages to be rejected as INVALID")
        self.assertEqual(failure_type, FailureType.LANDING_PAGE_ONLY)

        # Expected: Sources created from landing pages have article_level = False and validated = False
        sources = [
            {
                "title": r["title"],
                "url": r["url"],
                "url_valid": True,
                "content_read": False,
                "relevant": True,
                "fresh_enough": True,
                "article_level": False,
                "validated": False,
            }
            for r in landing_page_results.data["results"]
        ]
        for s in sources:
            self.assertFalse(s["article_level"])
            self.assertFalse(s["validated"])

        # Expected: goal_completed = False
        state = AgentState(
            goal="Research the latest geopolitical news",
            intent=intent_dict,
            sources=sources,
            findings=[],
        )
        state = node_check_goal_completion(state)
        self.assertFalse(state.goal_completion["completed"])

    def test_regression_2_read_url_returns_only_navigation(self):
        """TEST 2: Search returns valid individual news articles but read_url returns only navigation.
        Expected: INVALID, content_read/content quality failure, recovery triggered.
        """
        nav_only_result = ToolResult(
            success=True,
            data={
                "url": "https://www.bbc.com/news/articles/cw62jje658dlo",
                "title": "BBC News Menu - World News",
                "content": "Home Video World US & Canada UK Business Tech Science Climate Sport Entertainment Health Sounds In Pictures Newsbeat BBC Verify Privacy Policy Cookie Settings Accessibility Help",
                "word_count": 30,
                "article_level": False,
            },
            duration_ms=180,
        )

        intent_dict = {"category": "CURRENT_NEWS", "freshness_required": True}
        is_valid, failure_type, reason = validate_result(
            tool_name="read_url",
            result=nav_only_result,
            intent=intent_dict,
            goal="Research the latest geopolitical news",
        )

        # Expected: INVALID, content failure (LANDING_PAGE_ONLY or INSUFFICIENT_CONTENT)
        self.assertFalse(is_valid)
        self.assertIn(failure_type, (FailureType.LANDING_PAGE_ONLY, FailureType.INSUFFICIENT_CONTENT))

        # Expected: Recovery triggered
        state = AgentState(
            goal="Research the latest geopolitical news",
            intent=intent_dict,
            current_task={
                "id": 2,
                "description": "Read article",
                "tool": "read_url",
                "input": "https://www.bbc.com/news/articles/cw62jje658dlo",
            },
            max_retries=2,
            retries=0,
            observations=[{
                "tool": "web_search",
                "data": {"results": [{"url": "https://www.bbc.co.uk/news/articles/cqgmrr9ekr7ko", "title": "Iran US Strait of Hormuz deal", "article_level": True}]},
            }],
        )
        updated_state, recovery_msg = handle_failure(state, reason, failure_type)
        self.assertEqual(updated_state.status, "RECOVERING")
        self.assertEqual(updated_state.retries, 1)
        self.assertGreater(len(updated_state.recovery_actions), 0)
        self.assertNotEqual(updated_state.current_task["input"], "https://www.bbc.com/news/world")

    def test_regression_3_two_valid_articles_completed(self):
        """TEST 3: Two or more valid recent articles are successfully read and produce concrete findings.
        Expected: goal_completed = true, status = COMPLETED.
        """
        valid_sources = [
            {
                "title": "Iran offers US deal to reopen Strait of Hormuz in seven days",
                "url": "https://www.bbc.co.uk/news/articles/cqgmrr9ekr7ko",
                "snippet": "Iranian Foreign Minister Abbas Araghchi says his country has proposed a deal to the US that would see the Strait of Hormuz reopened within a week.",
                "url_valid": True,
                "content_read": True,
                "relevant": True,
                "fresh_enough": True,
                "article_level": True,
                "validated": True,
            },
            {
                "title": "Russia targeting ordinary life with attacks on Ukraine data centres, Zelensky says",
                "url": "https://www.bbc.co.uk/news/articles/c84gkwgk7d06o",
                "snippet": "President Volodymyr Zelensky confirmed strikes aim to disrupt communication and civic infrastructure during September 2026 operations.",
                "url_valid": True,
                "content_read": True,
                "relevant": True,
                "fresh_enough": True,
                "article_level": True,
                "validated": True,
            },
        ]

        concrete_findings = [
            "1. Iranian Foreign Minister Abbas Araghchi proposed an accord to the US at the UN in September 2026 to reopen the Strait of Hormuz within seven days under the June bilateral MOU. [Source: https://www.bbc.co.uk/news/articles/cqgmrr9ekr7ko]",
            "2. Ukrainian President Volodymyr Zelensky confirmed that Russian military missile strikes targeted civic data centres and energy infrastructure this week. [Source: https://www.bbc.co.uk/news/articles/c84gkwgk7d06o]",
        ]

        state = AgentState(
            goal="Research the latest geopolitical news",
            intent={"category": "CURRENT_NEWS", "freshness_required": True},
            plan=[
                {"id": 1, "description": "Search news", "tool": "web_search", "status": "COMPLETED"},
                {"id": 2, "description": "Read article 1", "tool": "read_url", "status": "COMPLETED"},
                {"id": 3, "description": "Read article 2", "tool": "read_url", "status": "COMPLETED"},
                {"id": 4, "description": "Synthesize findings", "tool": "synthesize", "status": "COMPLETED"},
            ],
            sources=valid_sources,
            findings=concrete_findings,
            observations=[
                {"tool": "synthesize", "data": {"summary": "Verified geopolitical reporting synthesized from multiple article sources.", "findings": concrete_findings}},
            ],
            tool_calls=[{"task_id": 1, "tool": "web_search", "success": True}],
        )

        # Deterministic check
        valid_ev, reason, missing = validate_current_news_evidence(state)
        self.assertTrue(valid_ev, f"Expected evidence gate to pass: {reason}")

        # Goal completion node
        state = node_check_goal_completion(state)
        self.assertTrue(state.goal_completion["completed"])

        # Final report node
        state = node_generate_report(state)
        self.assertEqual(state.status, "COMPLETED")
        self.assertEqual(state.final_report["status"], "COMPLETED")

    def test_regression_4_tools_succeed_no_concrete_findings(self):
        """TEST 4: All tools technically succeed but no concrete findings exist.
        Expected: NOT COMPLETED.
        """
        state = AgentState(
            goal="Research the latest geopolitical news",
            intent={"category": "CURRENT_NEWS", "freshness_required": True},
            plan=[
                {"id": 1, "description": "Search news", "tool": "web_search", "status": "COMPLETED"},
                {"id": 2, "description": "Read url", "tool": "read_url", "status": "COMPLETED"},
                {"id": 3, "description": "Synthesize", "tool": "synthesize", "status": "COMPLETED"},
            ],
            # Sources are present, but findings are generic portal descriptions, NOT concrete events
            sources=[
                {
                    "title": "BBC World News",
                    "url": "https://www.bbc.com/news/world",
                    "url_valid": True,
                    "content_read": True,
                    "relevant": True,
                    "fresh_enough": True,
                    "article_level": False,
                    "validated": False,
                },
                {
                    "title": "Reuters World News",
                    "url": "https://www.reuters.com/world/",
                    "url_valid": True,
                    "content_read": True,
                    "relevant": True,
                    "fresh_enough": True,
                    "article_level": False,
                    "validated": False,
                },
            ],
            findings=[
                "BBC, Reuters and AP cover diplomacy, multilateral accords, geopolitical crises...",
                "The retrieved observations contain only portal overviews, landing page descriptions, and navigational categories from international news wires rather than concrete articles or reporting.",
            ],
            observations=[
                {"tool": "synthesize", "data": {"summary": "Portal summary", "findings": ["BBC, Reuters and AP cover diplomacy..."]}},
            ],
            tool_calls=[
                {"task_id": 1, "tool": "web_search", "success": True},
                {"task_id": 2, "tool": "read_url", "success": True},
                {"task_id": 3, "tool": "synthesize", "success": True},
            ],
        )

        # Deterministic check must fail
        valid_ev, reason, missing = validate_current_news_evidence(state)
        self.assertFalse(valid_ev)

        # Goal completion node must set completed = False
        state = node_check_goal_completion(state)
        self.assertFalse(state.goal_completion["completed"])

        # Final report must NOT be COMPLETED
        state = node_generate_report(state)
        self.assertNotEqual(state.final_report["status"], "COMPLETED")
        self.assertIn(state.final_report["status"], ("PARTIAL", "FAILED"))

    def test_regression_5_recovery_cannot_find_articles_partial_or_failed(self):
        """TEST 5: Recovery cannot find article-level evidence.
        Expected: PARTIAL or FAILED, never COMPLETED.
        """
        state = AgentState(
            goal="Research the latest geopolitical news",
            intent={"category": "CURRENT_NEWS", "freshness_required": True},
            plan=[
                {"id": 1, "description": "Search news", "tool": "web_search", "status": "COMPLETED"},
                {"id": 2, "description": "Read url", "tool": "read_url", "status": "COMPLETED"},
            ],
            max_retries=2,
            retries=2,  # Retries exhausted
            recovery_actions=["Exhausted retry budget searching for article URLs."],
            sources=[],
            findings=[],
            observations=[],
            tool_calls=[{"task_id": 1, "tool": "web_search", "success": True}],
        )

        # Check goal completion
        state = node_check_goal_completion(state)
        self.assertFalse(state.goal_completion["completed"])

        # Generate report
        state = node_generate_report(state)
        self.assertNotEqual(state.status, "COMPLETED")
        self.assertNotEqual(state.final_report["status"], "COMPLETED")
        self.assertIn(state.final_report["status"], ("PARTIAL", "FAILED"))


if __name__ == "__main__":
    unittest.main()
