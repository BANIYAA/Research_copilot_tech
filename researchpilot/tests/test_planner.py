"""Unit tests for ResearchPilot Goal Validation, Intent Classification, and Autonomous Planner."""
import unittest
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.planner import validate_goal, classify_intent, generate_plan
from models.plan import Plan, GoalIntent, GoalValidationResult


class TestPlanner(unittest.TestCase):
    """Test suite for Goal Validation, Intent Detection, and Planning modules."""

    def test_valid_goal_validation(self):
        """Test that actionable research goals pass validation."""
        goal = "Research the latest developments in AI agents and identify three important trends."
        result = validate_goal(goal)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.refined_goal, goal)
        self.assertIn("ready", result.reason.lower())

    def test_empty_goal_rejection(self):
        """Test that empty or whitespace-only goals are rejected."""
        result = validate_goal("")
        self.assertFalse(result.is_valid)
        self.assertIn("empty", result.reason.lower())

        result_spaces = validate_goal("   \n\t  ")
        self.assertFalse(result_spaces.is_valid)

    def test_greeting_or_vague_goal_rejection(self):
        """Test F: Reject non-actionable greetings and placeholders (e.g. 'hello', 'asdf')."""
        for greeting in ["hello", "hi", "test", "hey", "asdf"]:
            result = validate_goal(greeting)
            self.assertFalse(result.is_valid, f"Failed for {greeting}")
            self.assertTrue(len(result.reason) > 10)

    def test_short_vague_goal_rejection(self):
        """Test rejection of goals lacking minimum descriptive length."""
        result = validate_goal("car")
        self.assertFalse(result.is_valid)

    def test_intent_classification_current_news(self):
        """Test that news requests are classified as CURRENT_NEWS with freshness required."""
        goal = "Research the latest global news"
        intent = classify_intent(goal)
        self.assertIsInstance(intent, GoalIntent)
        self.assertEqual(intent.category, "CURRENT_NEWS")
        self.assertTrue(intent.freshness_required)
        self.assertEqual(intent.geographic_scope, "global")

    def test_intent_classification_technical(self):
        """Test that agent framework questions are classified as TECHNICAL_RESEARCH."""
        goal = "Research recent AI agent frameworks and LangGraph state architecture."
        intent = classify_intent(goal)
        self.assertEqual(intent.category, "TECHNICAL_RESEARCH")

    def test_intent_aware_plan_for_news(self):
        """Test that planning for news requests targets live news rather than academic papers."""
        goal = "Research the latest global news"
        intent = classify_intent(goal)
        plan = generate_plan(goal, intent=intent)

        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.intent.category, "CURRENT_NEWS")
        # Check task 1 input targets news
        task1_input = plan.tasks[0].input.lower()
        self.assertTrue("news" in task1_input or "events" in task1_input)
        self.assertFalse("arxiv" in task1_input)

    def test_plan_generation_structure(self):
        """Test A: Plan generation creates structured Plan with >=2 distinct tasks and tools."""
        goal = "Research the latest developments in AI agents and identify three trends."
        plan = generate_plan(goal)

        self.assertIsInstance(plan, Plan)
        self.assertGreaterEqual(len(plan.tasks), 2)

        # Verify tool diversity
        tools = [t.tool for t in plan.tasks]
        self.assertIn("web_search", tools)
        self.assertIn("read_url", tools)

        # Verify task attributes
        for task in plan.tasks:
            self.assertIsNotNone(task.id)
            self.assertIsNotNone(task.description)
            self.assertIsNotNone(task.input)


if __name__ == "__main__":
    unittest.main()
