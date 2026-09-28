"""Planner and goal validation module for ResearchPilot.

Handles natural-language goal validation, intent classification, and autonomous task decomposition
using Gemini API structured JSON generation with deterministic fallbacks.
"""
from __future__ import annotations
import os
import json
import re
from typing import Dict, Any, List, Optional
from models.plan import GoalValidationResult, GoalIntent, Plan, Task

# Non-actionable tokens / greetings
VAGUE_OR_GREETINGS = {
    "hi", "hello", "hey", "test", "testing", "yo", "sup", "what's up",
    "who are you", "help", "asdf", "123", "none", "ok", "okay"
}


def validate_goal(goal: str) -> GoalValidationResult:
    """Validate whether the user goal is substantive, actionable, and specific enough for research.
    
    Args:
        goal: Raw user-provided string.
        
    Returns:
        GoalValidationResult indicating validity and feedback.
    """
    clean = (goal or "").strip()
    
    if not clean:
        return GoalValidationResult(
            is_valid=False,
            reason="Goal is empty. Please enter a specific research topic or question.",
            refined_goal=None,
        )

    if len(clean) < 6:
        return GoalValidationResult(
            is_valid=False,
            reason="Goal is too brief to formulate an actionable research plan. Provide more context.",
            refined_goal=None,
        )

    normalized = clean.lower().strip("!.? \t\n")
    if normalized in VAGUE_OR_GREETINGS:
        return GoalValidationResult(
            is_valid=False,
            reason=f"'{clean}' is a greeting or placeholder, not a research goal. Try: 'Research recent developments in AI agents and identify key trends.'",
            refined_goal=None,
        )

    # Check for minimal semantic density
    words = clean.split()
    if len(words) < 3 and not any(w.lower() in ("ai", "quantum", "llm", "agent", "agents", "fusion", "crypto", "news") for w in words):
        return GoalValidationResult(
            is_valid=False,
            reason=f"Goal '{clean}' lacks enough specificity. Please specify what topics or aspects to investigate.",
            refined_goal=None,
        )

    return GoalValidationResult(
        is_valid=True,
        reason="Goal is well-formed, actionable, and ready for autonomous decomposition.",
        refined_goal=clean,
    )


def classify_intent(goal: str) -> GoalIntent:
    """Extract structured intent, scope, category, and freshness requirements from the goal."""
    clean = goal.strip()
    lower = clean.lower()

    # Attempt LLM Intent Classification if Gemini API key is available
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            prompt = f"""You are the Intent Classification engine of ResearchPilot.
Classify the following user research goal into a structured GoalIntent.
Categories:
- CURRENT_NEWS: Requests latest breaking/global/national events, headlines, or today's news.
- TECHNICAL_RESEARCH: In-depth engineering, software architecture, papers, code, or machine learning frameworks.
- COMPARISON: Explicit comparison between tools, frameworks, systems, or products.
- FACT_LOOKUP: Specific factual answer or quantitative lookup.
- GENERAL_RESEARCH: Broad exploration, overview, or multi-faceted topic review.

Goal: "{clean}"
"""
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GoalIntent,
                    temperature=0.0,
                ),
            )
            if response.text:
                data = json.loads(response.text)
                return GoalIntent(**data)
        except Exception:
            pass

    # Deterministic Rule-Based Intent Classifier
    news_terms = {"news", "breaking", "headlines", "today", "current events", "world news", "global news"}
    has_news = any(term in lower for term in news_terms)
    is_latest = "latest" in lower or "recent" in lower or "today" in lower

    if has_news or ("latest" in lower and "events" in lower):
        geo = "global" if any(g in lower for g in ("global", "world", "international")) else "general"
        return GoalIntent(
            category="CURRENT_NEWS",
            topic=clean,
            time_scope="latest/current",
            geographic_scope=geo,
            output_requirement="Identify and summarize major current global developments and headlines",
            freshness_required=True,
        )

    if any(k in lower for k in (" vs ", " versus ", "compare", "comparison")):
        return GoalIntent(
            category="COMPARISON",
            topic=clean,
            time_scope="contemporary",
            geographic_scope=None,
            output_requirement="Comparative evaluation of features, trade-offs, and architectures",
            freshness_required=False,
        )

    tech_terms = {"framework", "architecture", "agent", "agents", "langgraph", "autogen", "llm", "code", "benchmark", "quantum", "algorithm"}
    if any(t in lower for t in tech_terms):
        return GoalIntent(
            category="TECHNICAL_RESEARCH",
            topic=clean,
            time_scope="2026/recent",
            geographic_scope=None,
            output_requirement="Synthesize architectural advancements, state of the art benchmarks, and practical implementations",
            freshness_required=is_latest,
        )

    return GoalIntent(
        category="GENERAL_RESEARCH",
        topic=clean,
        time_scope="recent" if is_latest else None,
        geographic_scope=None,
        output_requirement="Comprehensive overview, key trends, and authoritative findings",
        freshness_required=is_latest,
    )


def generate_plan(goal: str, intent: Optional[GoalIntent] = None) -> Plan:
    """Decompose the validated research goal into an intent-aware structured multi-step execution plan."""
    validation = validate_goal(goal)
    if not validation.is_valid:
        raise ValueError(f"Cannot plan for invalid goal: {validation.reason}")

    if intent is None:
        intent = classify_intent(goal)

    api_key = os.getenv("GEMINI_API_KEY")
    clean_goal = goal.strip()

    # Attempt LLM Planning if API key is configured
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            prompt = f"""You are the Planning Module of ResearchPilot.
Decompose this research goal into 3 distinct actionable steps tailored to its intent:
Intent Category: {intent.category}
Freshness Required: {intent.freshness_required}
Topic: {intent.topic}

Rules:
1. Tool for discovering information MUST be 'web_search'.
2. Tool for reading sources MUST be 'read_url'.
3. Tool for synthesizing MUST be 'synthesize'.
4. If intent is CURRENT_NEWS:
   - Search query MUST target live news, reputable news agencies, and current events (do NOT use academic/arxiv/technical papers).
   - Reading step should extract confirmed facts, timestamps, and quotes from live articles.
5. If intent is TECHNICAL_RESEARCH:
   - Search query should target technical benchmarks, documentation, and architecture.
6. Provide explicit search query in input, placeholder 'discovered_sources[0]' for read_url, and synthesis instructions.

Goal: "{clean_goal}"
"""
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Plan,
                    temperature=0.2,
                ),
            )
            if response.text:
                plan_dict = json.loads(response.text)
                plan_obj = Plan(**plan_dict)
                plan_obj.intent = intent
                return plan_obj
        except Exception:
            pass

    # Deterministic High-Quality Intent-Aware Decomposition
    if intent.category == "CURRENT_NEWS":
        return Plan(
            goal=clean_goal,
            intent=intent,
            tasks=[
                Task(
                    id=1,
                    description="Search the web for major breaking world events, headlines, and live international news updates",
                    tool="web_search",
                    input="latest global news major world events today",
                    fallback_input="latest world news international developments current events",
                ),
                Task(
                    id=2,
                    description="Read primary international news reporting from first discovered article",
                    tool="read_url",
                    input="discovered_sources[0]",
                    fallback_input="discovered_sources[1]",
                ),
                Task(
                    id=3,
                    description="Read corroborating news reporting from second discovered article to verify event details",
                    tool="read_url",
                    input="discovered_sources[1]",
                    fallback_input="discovered_sources[2]",
                ),
                Task(
                    id=4,
                    description="Cross-check and synthesize the major global developments, verified headlines, and source attributions",
                    tool="synthesize",
                    input="observations_history",
                ),
            ],
        )

    # General or Technical Research Decomposition
    return Plan(
        goal=clean_goal,
        intent=intent,
        tasks=[
            Task(
                id=1,
                description=f"Search the web for authoritative information and recent findings on: {clean_goal}",
                tool="web_search",
                input=f"{clean_goal} key developments overview 2026" if "latest" in clean_goal.lower() else clean_goal,
                fallback_input=f"{clean_goal} analysis overview 2026",
            ),
            Task(
                id=2,
                description="Extract and read detailed content from primary research sources discovered in step 1",
                tool="read_url",
                input="discovered_sources[0]",
                fallback_input="discovered_sources[1]",
            ),
            Task(
                id=3,
                description="Synthesize observed findings into structured conclusions, trends, and citations",
                tool="synthesize",
                input="observations_history",
            ),
        ],
    )

