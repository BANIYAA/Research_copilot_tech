"""Failure recovery engine for ResearchPilot.

Implements autonomous self-healing strategies mapped to explicit failure types:
1. TIMEOUT -> Retry (up to MAX_RETRIES=2)
2. EMPTY_RESULTS -> Query Refinement (broader topical keywords)
3. IRRELEVANT_RESULTS -> Query Refinement (targeted domain/publisher anchors or news wire feeds)
4. SOURCE_READ_ERROR / INSUFFICIENT_CONTENT -> Fallback Source Substitution
5. REPEATED_FAILURE -> Graceful Bounded Replanning / Best-Effort Degradation
"""
from __future__ import annotations
import time
from typing import Dict, Any, Tuple, Optional
from models.report import AgentState
from models.plan import FailureType
from tools.url_reader import is_article_content
from tools.web_search import _fetch_live_news_articles

MAX_RETRIES = 2


def refine_query(original_query: str, intent_category: Optional[str] = None, failure_type: Optional[FailureType] = None) -> str:
    """Generate an intent-aware refined search query based on failure diagnostics."""
    clean = original_query.strip().replace('"', "").replace("'", "")
    lower = clean.lower()

    # Intent: CURRENT_NEWS or LANDING_PAGE_ONLY or IRRELEVANT_RESULTS on news
    if intent_category == "CURRENT_NEWS" or any(w in lower for w in ("news", "breaking", "today", "global news", "geopolitical")):
        if failure_type == FailureType.LANDING_PAGE_ONLY:
            return "latest world news event specific headlines individual articles reporting 2026"
        if failure_type == FailureType.IRRELEVANT_RESULTS or "technical" in lower or "arxiv" in lower:
            return "latest global news Reuters AP BBC international headlines today"
        return "latest world news international events breaking reporting today"

    # Intent: TECHNICAL_RESEARCH
    if intent_category == "TECHNICAL_RESEARCH" or any(w in lower for w in ("framework", "agent", "architecture", "langgraph")):
        return f"{clean} architecture documentation benchmarks overview 2026"

    # General Refinement
    if "latest" in lower:
        return f"{clean} major developments overview 2026"
    elif "trends" in lower:
        return f"{clean} industry benchmarks analysis"
    return f"{clean} authoritative overview documentation"


def handle_failure(
    state: AgentState,
    failure_reason: str,
    failure_type: Optional[FailureType] = None,
) -> Tuple[AgentState, str]:
    """Execute recovery strategy based on task, attempt count, failure type, and intent.
    
    Returns:
        Tuple of (updated_state, action_summary)
    """
    task = state.current_task or {}
    tool = task.get("tool", "")
    current_retries = state.retries
    timestamp_str = time.strftime("%H:%M:%S")

    # Inferred failure type if not provided
    if failure_type is None:
        lower_reason = failure_reason.lower()
        if "landing" in lower_reason or "portal" in lower_reason:
            failure_type = FailureType.LANDING_PAGE_ONLY
        elif "timeout" in lower_reason or "timed out" in lower_reason:
            failure_type = FailureType.TIMEOUT
        elif "empty" in lower_reason or "0 results" in lower_reason:
            failure_type = FailureType.EMPTY_RESULTS
        elif "irrelevant" in lower_reason or "technical" in lower_reason:
            failure_type = FailureType.IRRELEVANT_RESULTS
        elif "404" in lower_reason or "network" in lower_reason:
            failure_type = FailureType.SOURCE_READ_ERROR
        elif "short" in lower_reason or "insufficient" in lower_reason:
            failure_type = FailureType.INSUFFICIENT_CONTENT
        else:
            failure_type = FailureType.TOOL_ERROR

    # Record classified failure
    state.failures.append({
        "task_id": task.get("id"),
        "tool": tool,
        "failure_type": failure_type.value if hasattr(failure_type, "value") else str(failure_type),
        "reason": failure_reason,
        "retry_number": current_retries,
        "timestamp": timestamp_str,
    })

    # Intent context
    intent_category = state.intent.get("category") if state.intent else None

    # Check retry budget
    if current_retries < state.max_retries:
        state.retries += 1

        # Case 1: Deterministic Simulated Failure Reset
        if state.simulate_failure:
            state.simulate_failure = False
            recovery_msg = (
                f"Simulated failure detected on task #{task.get('id')} ({failure_type.value}). "
                f"Triggering Retry #{state.retries} with reset fault boundaries."
            )
            state.recovery_actions.append(recovery_msg)
            state.execution_trace.append(f"[{timestamp_str}] ⚠ Failure detected [{failure_type.value}]: {failure_reason}")
            state.execution_trace.append(f"[{timestamp_str}] ↻ Executing Retry #{state.retries} of {state.max_retries}")
            state.status = "RECOVERING"
            return state, recovery_msg

        # Case 2: TIMEOUT -> Direct retry
        if failure_type == FailureType.TIMEOUT:
            recovery_msg = f"Network timeout detected on task #{task.get('id')}. Executing Retry #{state.retries}/{state.max_retries} with backoff."
            state.recovery_actions.append(recovery_msg)
            state.execution_trace.append(f"[{timestamp_str}] ⚠ Timeout on {tool}: {failure_reason}")
            state.execution_trace.append(f"[{timestamp_str}] ↻ Retry #{state.retries}: Retrying request...")
            state.status = "RECOVERING"
            return state, recovery_msg

        # Case 3: EMPTY_RESULTS, IRRELEVANT_RESULTS, or LANDING_PAGE_ONLY -> Query Refinement
        if tool == "web_search" and failure_type in (FailureType.EMPTY_RESULTS, FailureType.IRRELEVANT_RESULTS, FailureType.LANDING_PAGE_ONLY):
            orig_input = task.get("input", "")
            refined = refine_query(orig_input, intent_category, failure_type)
            task["input"] = refined
            state.current_task = task
            recovery_msg = (
                f"Search validation failed ({failure_type.value}). "
                f"Applied Query Refinement: '{orig_input}' -> '{refined}'"
            )
            state.recovery_actions.append(recovery_msg)
            state.execution_trace.append(f"[{timestamp_str}] ⚠ Search issue [{failure_type.value}]: {failure_reason}")
            state.execution_trace.append(f"[{timestamp_str}] ↻ Query Refinement: Searching '{refined}' (Retry #{state.retries})")
            state.status = "RECOVERING"
            return state, recovery_msg

        # Case 4: SOURCE_READ_ERROR, INSUFFICIENT_CONTENT, LANDING_PAGE_ONLY, or IRRELEVANT URL -> Fallback Source
        if tool == "read_url":
            fallback_url = None
            old_url = task.get("input", "")

            # Search observations for secondary valid article URL
            for obs in state.observations:
                results = obs.get("data", {}).get("results", [])
                for r in results:
                    u = r.get("url", "")
                    if u and u != old_url and "special:search" not in u.lower():
                        if intent_category == "CURRENT_NEWS":
                            is_art = r.get("article_level")
                            if is_art is None:
                                is_art, _ = is_article_content(u, r.get("title", ""), r.get("snippet", ""))
                            if is_art:
                                fallback_url = u
                                break
                        else:
                            fallback_url = u
                            break
                if fallback_url:
                    break

            # If no article URL discovered from past observations for news intent, fetch live wire articles
            if not fallback_url and intent_category == "CURRENT_NEWS":
                live_arts = _fetch_live_news_articles(max_results=3)
                for la in live_arts:
                    if la.get("url") and la.get("url") != old_url:
                        fallback_url = la["url"]
                        break

            # Fallback anchor if still not resolved
            if not fallback_url:
                if intent_category == "CURRENT_NEWS":
                    fallback_url = "https://www.bbc.co.uk/news/articles/cqgmrr9ekr7ko"
                else:
                    fallback_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"

            task["input"] = fallback_url
            state.current_task = task
            recovery_msg = f"URL read failure ({failure_type.value}). Switched from '{old_url}' to article-level Fallback Source: '{fallback_url}'"
            state.recovery_actions.append(recovery_msg)
            state.execution_trace.append(f"[{timestamp_str}] ⚠ Source issue [{failure_type.value}]: {failure_reason}")
            state.execution_trace.append(f"[{timestamp_str}] ↻ Fallback Source Activated: {fallback_url} (Retry #{state.retries})")
            state.status = "RECOVERING"
            return state, recovery_msg

        # General Retry
        recovery_msg = f"Transient task #{task.get('id')} error ({failure_type.value}). Retrying (Attempt {state.retries}/{state.max_retries})."
        state.recovery_actions.append(recovery_msg)
        state.execution_trace.append(f"[{timestamp_str}] ↻ Retry #{state.retries}: {recovery_msg}")
        state.status = "RECOVERING"
        return state, recovery_msg

    # Exhausted retries: Circuit breaker prevents infinite loops
    recovery_msg = (
        f"Task #{task.get('id')} reached maximum retries ({state.max_retries}). "
        f"Gracefully advancing with best-effort observations."
    )
    state.recovery_actions.append(recovery_msg)
    state.execution_trace.append(f"[{timestamp_str}] ⚠ {recovery_msg}")
    state.retries = 0
    state.current_task_index += 1
    state.status = "EXECUTING"
    return state, recovery_msg
