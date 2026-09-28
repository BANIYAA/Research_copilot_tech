"""Validation node for ResearchPilot.

Separates Tool Success from Task Success and Goal Success.
Performs deterministic structural validation followed by task-specific
semantic relevance and freshness checks before advancing state in the agent loop.
"""
from __future__ import annotations
import os
import json
from typing import Tuple, Dict, Any, Optional, List
from tools import ToolResult
from tools.url_reader import is_article_content
from models.plan import FailureType, SemanticValidation, SourceValidation
from models.report import AgentState

MIN_CONTENT_CHARS = 80
MIN_SEARCH_RESULTS = 1

# Non-news / purely technical academic domains
TECHNICAL_ONLY_DOMAINS = {"arxiv.org", "github.com", "huggingface.co", "pypi.org", "npmjs.com"}
NEWS_DOMAINS = {
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "cnn.com", "nytimes.com",
    "theguardian.com", "aljazeera.com", "bloomberg.com", "wsj.com", "ft.com", "lemonde.fr"
}
CURRENT_NEWS_KEYWORDS = {
    "news", "breaking", "summit", "election", "diplomacy", "treaty", "conflict",
    "minister", "president", "united nations", "aid", "foreign", "parliament",
    "crisis", "ceasefire", "economy", "protest", "sanctions", "bilateral"
}

GENERIC_PORTAL_PHRASES = [
    "cover diplomacy, multilateral accords",
    "covers diplomacy, multilateral accords",
    "cover diplomacy",
    "portal overview",
    "landing page descriptions",
    "navigational categories",
    "international news wires rather than concrete articles",
    "breaking international news, in-depth reports, and live analysis",
    "offers comprehensive coverage of",
    "provides comprehensive coverage of",
    "world news wire reporting on world leadership",
    "overview of what these websites cover"
]

GEOPOLITICAL_ACTORS = [
    "president", "prime minister", "foreign minister", "ambassador", "envoy", "diplomat", "officials",
    "government", "agency", "agencies", "un", "united nations", "security council", "nato", "eu",
    "european union", "white house", "kremlin", "pentagon", "state department", "fbi", "sec", "census",
    "us", "u.s.", "united states", "russia", "ukraine", "china", "iran", "israel", "gaza", "lebanon",
    "taiwan", "south africa", "uk", "britain", "france", "germany", "japan", "korea", "zelensky",
    "araghchi", "biden", "blinken", "macron", "scholz", "putin", "trump", "netanyahu",
    "yemen", "houthis", "serbia", "syria", "sudan", "rebels", "forces", "military", "troops",
    "leader", "leaders", "parliament", "opposition", "state", "minister"
]

GEOPOLITICAL_EVENTS = [
    "summit", "ceasefire", "treaty", "accord", "sanctions", "election", "elections", "talks", "agreement",
    "missile", "strike", "offensive", "conflict", "aid package", "border", "negotiations", "reopen",
    "dispute", "resolution", "alliance", "pact", "deal", "strait of hormuz", "data centres", "security",
    "diplomacy", "investigation", "inquiry", "breach", "hack", "cyber", "war", "defense", "military",
    "trade", "crisis", "disruption", "bilateral", "meddled", "attack", "policy", "battle", "clashes",
    "protests", "fighting", "resigns", "resignation", "front-line", "control"
]

TEMPORAL_REFERENCES = [
    "2026", "september", "today", "yesterday", "this week", "recently", "recent", "within a week",
    "in june", "emergency session", "published", "friday", "monday", "tuesday", "wednesday", "thursday",
    "days", "months", "hours", "past week", "current", "latest", "early"
]


def is_concrete_geopolitical_finding(finding: str) -> tuple[bool, str]:
    """Deterministically check if a synthesized finding represents a concrete geopolitical event.
    
    Rejects generic portal descriptions and summaries of wire coverage.
    Requires:
    1. Concrete event/development
    2. Identifiable actor(s)
    3. Recent temporal reference
    4. Substantive supporting content (>60 chars)
    """
    clean = (finding or "").strip()
    lower = clean.lower()

    if len(clean) < 60:
        return False, "Finding length is too short to provide substantive reporting context."

    # Check for disallowed generic portal descriptions
    for phrase in GENERIC_PORTAL_PHRASES:
        if phrase in lower:
            return False, f"Finding contains generic portal/wire description: '{phrase}'."

    # Must contain identifiable geopolitical actor
    has_actor = any(actor in lower for actor in GEOPOLITICAL_ACTORS)
    if not has_actor:
        return False, "Finding lacks identifiable geopolitical actors or state representatives."

    # Must contain concrete event / development
    has_event = any(event in lower for event in GEOPOLITICAL_EVENTS)
    if not has_event:
        return False, "Finding lacks a concrete geopolitical development, summit, treaty, or event."

    # Must contain recent temporal reference
    has_temporal = any(temp in lower for temp in TEMPORAL_REFERENCES)
    if not has_temporal:
        return False, "Finding lacks temporal reference anchoring it to recent/current reporting."

    return True, "Finding satisfies all concrete geopolitical event criteria."


def validate_current_news_evidence(state: AgentState) -> tuple[bool, str, List[str]]:
    """Deterministic goal-completion gate for CURRENT_NEWS intent.
    
    Verifies:
    1. At least 2 validated article-level sources.
    2. content_read == True for those sources.
    3. Sources are relevant to requested geopolitical topic.
    4. Sources satisfy freshness requirement.
    5. At least 2 concrete event-level findings exist.
    6. Findings are based on actual article content, not homepage/category descriptions.
    
    Returns:
        (is_valid: bool, reason: str, missing_requirements: List[str])
    """
    missing_reqs: List[str] = []

    # 1. Inspect article-level validated sources
    sources = state.sources or []
    validated_article_sources = []

    for s in sources:
        url = s.get("url", "")
        title = s.get("title", "")
        snippet = s.get("snippet", "")
        is_art = s.get("article_level", False)
        if not is_art:
            # Re-verify through classifier
            is_art, _ = is_article_content(url, title, snippet)
        
        url_valid = bool(s.get("url_valid", True))
        content_read = bool(s.get("content_read", False))
        relevant = bool(s.get("relevant", True))
        fresh_enough = bool(s.get("fresh_enough", True))

        # Enforce strict validation formula:
        # validated = url_valid AND content_read AND relevant AND fresh_enough AND article_level
        is_validated = url_valid and content_read and relevant and fresh_enough and is_art

        if is_validated and url:
            validated_article_sources.append(url)

    unique_validated = set(validated_article_sources)
    if len(unique_validated) < 2:
        missing_reqs.append(
            f"Requires at least 2 validated article-level sources with content_read=True (found {len(unique_validated)})"
        )

    # 2. Inspect concrete event-level findings
    findings = state.findings or []
    concrete_findings = []
    rejected_findings_reasons = []

    for f in findings:
        valid_f, f_reason = is_concrete_geopolitical_finding(f)
        if valid_f:
            concrete_findings.append(f)
        else:
            rejected_findings_reasons.append(f"'{f[:60]}...': {f_reason}")

    if len(concrete_findings) < 2:
        missing_reqs.append(
            f"Requires at least 2 concrete event-level findings based on article content (found {len(concrete_findings)})"
        )

    if missing_reqs:
        reason = "Deterministic evidence verification failed: " + "; ".join(missing_reqs)
        return False, reason, missing_reqs

    return (
        True,
        f"Deterministic evidence gate passed: {len(validated_article_sources)} validated article-level sources and {len(concrete_findings)} concrete event findings verified.",
        [],
    )


def validate_result(
    tool_name: str,
    result: ToolResult,
    current_task: Optional[Dict[str, Any]] = None,
    intent: Optional[Dict[str, Any]] = None,
    goal: str = "",
) -> Tuple[bool, Optional[FailureType], str]:
    """Inspect tool result for operational errors, schema completeness, and task-specific semantic relevance.
    
    Args:
        tool_name: 'web_search', 'read_url', or 'synthesize'.
        result: ToolResult instance returned from executor.
        current_task: Dictionary of the task definition.
        intent: Classified GoalIntent dictionary (if any).
        goal: The user's original research goal.
        
    Returns:
        Tuple of (is_valid: bool, failure_type: Optional[FailureType], reason: str).
    """
    # -------------------------------------------------------------
    # LEVEL 1: TOOL SUCCESS (Operational / Protocol Validation)
    # -------------------------------------------------------------
    if not isinstance(result, ToolResult):
        return (
            False,
            FailureType.INVALID_RESPONSE,
            f"Malformed output: Expected ToolResult instance, received {type(result).__name__}",
        )

    if not result.success:
        err_msg = result.error or "Unknown tool execution failure"
        err_lower = err_msg.lower()
        if "timeout" in err_lower or "timed out" in err_lower:
            return False, FailureType.TIMEOUT, err_msg
        if "404" in err_lower or "status code" in err_lower or "network error" in err_lower:
            return False, FailureType.SOURCE_READ_ERROR, err_msg
        return False, FailureType.TOOL_ERROR, f"Tool reported failure: {err_msg}"

    if result.data is None:
        return False, FailureType.INVALID_RESPONSE, "Tool result payload is None"

    if not isinstance(result.data, dict):
        return False, FailureType.INVALID_RESPONSE, f"Expected dictionary payload, got {type(result.data).__name__}"

    # -------------------------------------------------------------
    # LEVEL 2: TASK SUCCESS (Payload Usability & Semantic Relevance)
    # -------------------------------------------------------------
    category = (intent.get("category") if intent else "") or ""
    goal_lower = goal.lower()
    is_news_goal = category == "CURRENT_NEWS" or any(k in goal_lower for k in ("news", "today's news", "global news", "breaking"))

    if tool_name == "web_search":
        results = result.data.get("results")
        if results is None:
            return False, FailureType.INVALID_RESPONSE, "Search payload missing 'results' key"
        if not isinstance(results, list):
            return False, FailureType.INVALID_RESPONSE, f"'results' must be a list, got {type(results).__name__}"
        if len(results) < MIN_SEARCH_RESULTS:
            return False, FailureType.EMPTY_RESULTS, f"Search returned 0 usable results"

        # Check for valid URLs in results
        valid_results = [r for r in results if isinstance(r, dict) and r.get("url") and r.get("url").startswith("http")]
        if not valid_results:
            return False, FailureType.INVALID_RESPONSE, "All search results contain missing or malformed URLs"

        # Semantic & Relevance Validation for CURRENT_NEWS Intent
        if is_news_goal:
            # Detect if results are purely technical/academic (like arXiv, GitHub, Wikipedia search pages)
            domains = [r.get("source_domain", "").lower() or r.get("url", "").lower() for r in valid_results]
            has_news_domain = any(any(nd in d for nd in NEWS_DOMAINS) for d in domains)
            
            # Check snippet/title vocabulary
            all_text = " ".join([f"{r.get('title', '')} {r.get('snippet', '')}" for r in valid_results]).lower()
            news_keyword_matches = sum(1 for kw in CURRENT_NEWS_KEYWORDS if kw in all_text)
            
            is_technical_dump = all(
                any(td in d for td in TECHNICAL_ONLY_DOMAINS) or "special:search" in r.get("url", "").lower()
                for r, d in zip(valid_results, domains)
            )

            if is_technical_dump or (not has_news_domain and news_keyword_matches < 2):
                return (
                    False,
                    FailureType.IRRELEVANT_RESULTS,
                    "Search returned technical/academic repositories or generic search indexes instead of current global news reporting",
                )

            # Check if all returned results are homepages or category landing pages
            all_landing = all(
                not r.get("article_level", False)
                and not is_article_content(r.get("url", ""), r.get("title", ""), r.get("snippet", ""))[0]
                for r in valid_results
            )
            if all_landing:
                return (
                    False,
                    FailureType.LANDING_PAGE_ONLY,
                    "Search returned only portal homepages/category landing pages rather than individual article links",
                )

        return True, None, "Search results passed relevance, schema, and source validity checks"

    elif tool_name == "read_url":
        url = result.data.get("url", "")
        content = result.data.get("content", "")
        title = result.data.get("title", "")
        
        if not isinstance(content, str):
            return False, FailureType.INVALID_RESPONSE, f"'content' must be a string, got {type(content).__name__}"
        
        clean_content = content.strip()
        if len(clean_content) < MIN_CONTENT_CHARS:
            return (
                False,
                FailureType.INSUFFICIENT_CONTENT,
                f"Extracted content length is insufficient ({len(clean_content)} chars < minimum {MIN_CONTENT_CHARS})",
            )

        # Check if URL is merely a search index/query page rather than an informative article
        url_lower = url.lower()
        if "special:search" in url_lower or "search/?query=" in url_lower or "duckduckgo.com" in url_lower:
            return (
                False,
                FailureType.IRRELEVANT_RESULTS,
                f"URL '{url}' is a search index/query page rather than an informative source article",
            )

        # Content relevance and article-level gate for CURRENT_NEWS
        if is_news_goal:
            content_lower = clean_content.lower()
            if any(term in content_lower for term in ("pip install", "import torch", "def __init__", "arxiv.org/abs")):
                return (
                    False,
                    FailureType.IRRELEVANT_RESULTS,
                    "Source content contains software code or academic machine learning abstractions instead of news coverage",
                )

            # Must be an individual article, not a portal or navigation shell
            is_art = result.data.get("article_level")
            art_reason = result.data.get("classification_reason", "")
            if is_art is None or not is_art:
                is_art, art_reason = is_article_content(url, title, clean_content)

            if not is_art:
                return (
                    False,
                    FailureType.LANDING_PAGE_ONLY,
                    f"URL '{url}' rejected for CURRENT_NEWS: {art_reason}. Individual article reporting required.",
                )

        return True, None, "Source document verified for length, readability, and topical relevance"

    elif tool_name == "synthesize":
        summary = result.data.get("summary", "")
        findings = result.data.get("findings", [])
        if not summary or len(findings) == 0:
            return (
                False,
                FailureType.GOAL_NOT_SATISFIED,
                "Synthesis result missing executive summary or key findings",
            )

        return True, None, "Synthesis successfully condensed findings and citations"

    return True, None, "Result passed all deterministic validation criteria"
