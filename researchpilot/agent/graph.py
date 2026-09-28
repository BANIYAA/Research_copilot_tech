"""State machine and LangGraph orchestration for ResearchPilot.

Defines the core agent graph:
START -> validate_goal -> classify_intent -> plan -> execute_task -> validate_result -> [valid / recover] -> check_goal_completion -> generate_report -> END
"""
from __future__ import annotations
import time
from typing import Dict, Any, List, Optional
from models.report import AgentState, FinalReport, ExecutionStats, SourceAttribution, GoalCompletion
from models.plan import FailureType
from .planner import validate_goal, classify_intent, generate_plan
from .executor import execute_current_task
from .validator import validate_result, validate_current_news_evidence
from .recovery import handle_failure


def node_validate_goal(state: AgentState) -> AgentState:
    """Validate user input goal."""
    res = validate_goal(state.goal)
    timestamp = time.strftime("%H:%M:%S")
    if not res.is_valid:
        state.status = "FAILED"
        state.execution_trace.append(f"[{timestamp}] ✖ Goal Validation Failed: {res.reason}")
        state.final_report = {
            "goal": state.goal,
            "status": "FAILED",
            "summary": f"Research could not start: {res.reason}",
            "findings": [],
            "sources": [],
            "execution_stats": {"tasks": 0, "failures": 1, "retries": 0, "tool_calls": 0},
            "recovery_actions": ["User must provide an actionable, non-empty research goal."],
        }
    else:
        state.execution_trace.append(f"[{timestamp}] ✓ Goal Validated: {res.reason}")
        state.status = "VALIDATED"
    return state


def node_classify_intent(state: AgentState) -> AgentState:
    """Extract structured intent, category, and requirements from goal."""
    timestamp = time.strftime("%H:%M:%S")
    try:
        intent = classify_intent(state.goal)
        state.intent = intent.model_dump()
        state.execution_trace.append(
            f"[{timestamp}] ✓ Intent Detected: {intent.category} "
            f"(Freshness required: {intent.freshness_required}, Scope: {intent.geographic_scope or 'general'})"
        )
    except Exception as e:
        state.intent = {
            "category": "GENERAL_RESEARCH",
            "topic": state.goal,
            "output_requirement": "Summary of findings",
            "freshness_required": False,
        }
        state.execution_trace.append(f"[{timestamp}] ⚠ Defaulting intent: GENERAL_RESEARCH")
    return state


def node_plan(state: AgentState) -> AgentState:
    """Generate structured intent-aware multi-step plan."""
    timestamp = time.strftime("%H:%M:%S")
    state.status = "PLANNING"
    try:
        intent_obj = None
        if state.intent:
            from models.plan import GoalIntent
            intent_obj = GoalIntent(**state.intent)

        plan_obj = generate_plan(state.goal, intent=intent_obj)
        state.plan = [t.model_dump() for t in plan_obj.tasks]
        state.execution_trace.append(f"[{timestamp}] ✓ Plan Generated with {len(state.plan)} structured steps:")
        for t in state.plan:
            state.execution_trace.append(f"     Step {t['id']}: [{t['tool']}] {t['description']}")
        state.status = "EXECUTING"
    except Exception as e:
        state.status = "FAILED"
        state.execution_trace.append(f"[{timestamp}] ✖ Planning Exception: {str(e)}")
    return state


def node_execute(state: AgentState) -> AgentState:
    """Execute current task and validate output."""
    state, result = execute_current_task(state)
    timestamp = time.strftime("%H:%M:%S")

    current_task = state.current_task or {}
    tool_name = current_task.get("tool", "")

    # Store observation
    state.observations.append({
        "task_id": current_task.get("id"),
        "tool": tool_name,
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "duration_ms": result.duration_ms,
    })

    # Validate output (Task Success & Relevance Validation)
    is_valid, failure_type, val_reason = validate_result(
        tool_name=tool_name,
        result=result,
        current_task=current_task,
        intent=state.intent,
        goal=state.goal,
    )

    state.last_validation = {
        "task_id": current_task.get("id"),
        "tool": tool_name,
        "is_valid": is_valid,
        "failure_type": failure_type.value if failure_type else None,
        "reason": val_reason,
    }

    if is_valid:
        state.execution_trace.append(f"[{timestamp}] ✓ Validation Passed: {val_reason}")
        current_task["status"] = "COMPLETED"

        intent_cat = state.intent.get("category") if state.intent else ""
        is_news = intent_cat == "CURRENT_NEWS" or "news" in state.goal.lower()

        if tool_name == "synthesize":
            new_findings = result.data.get("findings", [])
            if new_findings:
                state.findings = list(new_findings)
            for s in result.data.get("sources", []):
                state.sources.append(s)
        elif tool_name == "web_search":
            for r in result.data.get("results", []):
                is_art = r.get("article_level", False)
                state.sources.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "url_valid": True,
                    "content_read": False,
                    "relevant": True,
                    "fresh_enough": True,
                    "article_level": is_art,
                    "validated": False,  # CRITICAL BUG 1: Cannot be validated when content_read is False!
                })
        elif tool_name == "read_url":
            is_art = result.data.get("article_level", False)
            state.sources.append({
                "title": result.data.get("title", ""),
                "url": result.data.get("url", ""),
                "snippet": result.data.get("content", "")[:240],
                "url_valid": True,
                "content_read": True,
                "relevant": True,
                "fresh_enough": True,
                "article_level": is_art,
                "validated": bool(is_art) if is_news else True,
            })

        # Advance to next task
        state.current_task_index += 1
        state.retries = 0
    else:
        ft_name = failure_type.value if failure_type else "UNKNOWN"
        state.execution_trace.append(f"[{timestamp}] ✖ Validation Failed [{ft_name}]: {val_reason}")
        # Route to recovery
        state, recovery_msg = handle_failure(state, val_reason, failure_type)

    return state


def node_check_goal_completion(state: AgentState) -> AgentState:
    """Verify whether the original user research goal was actually satisfied.
    
    Enforces deterministic completion gates: LLM may not override evidence requirements.
    """
    timestamp = time.strftime("%H:%M:%S")
    intent_cat = state.intent.get("category") if state.intent else ""
    is_news = intent_cat == "CURRENT_NEWS" or "news" in state.goal.lower()

    completed = True
    missing_reqs = []
    reason = "Goal requirements successfully satisfied."

    if is_news:
        valid_ev, gate_reason, gate_missing = validate_current_news_evidence(state)
        if not valid_ev:
            completed = False
            missing_reqs = gate_missing
            reason = gate_reason
    else:
        # Validate evidence substance for general goals
        validated_sources = [s for s in state.sources if s.get("validated")]
        if len(validated_sources) == 0:
            completed = False
            missing_reqs.append("No verified sources collected")
            reason = "Execution completed tasks but failed to obtain verified sources."

        if len(state.findings) == 0:
            completed = False
            missing_reqs.append("Synthesized findings")
            reason = "No substantive research findings could be formulated."

    state.goal_completion = {
        "completed": completed,
        "reason": reason,
        "missing_requirements": missing_reqs,
    }

    if completed:
        state.execution_trace.append(f"[{timestamp}] ✓ Goal Completion Verified: {reason}")
    else:
        state.execution_trace.append(f"[{timestamp}] ⚠ Goal Completion Gate INCOMPLETE: {reason}")

    return state


def node_generate_report(state: AgentState) -> AgentState:
    """Synthesize complete structured report and compute metrics."""
    timestamp = time.strftime("%H:%M:%S")
    state.execution_trace.append(f"[{timestamp}] ▶ Compiling Final Research Report...")

    # Calculate stats
    total_tasks = len(state.plan)
    completed_tasks = sum(1 for t in state.plan if t.get("status") == "COMPLETED")
    total_tools = len(state.tool_calls)
    total_failures = len(state.failures)
    total_recoveries = len(state.recovery_actions)

    # Unique sources (prefer validated and read records)
    sources_by_url: Dict[str, Dict[str, Any]] = {}
    for s in state.sources:
        u = s.get("url")
        if not u:
            continue
        if u not in sources_by_url:
            sources_by_url[u] = dict(s)
        else:
            existing = sources_by_url[u]
            if s.get("content_read"):
                existing["content_read"] = True
                existing["snippet"] = s.get("snippet", existing.get("snippet"))
            if s.get("validated"):
                existing["validated"] = True
            if s.get("article_level"):
                existing["article_level"] = True

    deduped_sources = [SourceAttribution(**src) for src in sources_by_url.values()]

    # Summary
    summary = ""
    for obs in reversed(state.observations):
        if obs.get("tool") == "synthesize" and obs.get("data", {}).get("summary"):
            summary = obs["data"]["summary"]
            break
    if not summary:
        summary = (
            f"Autonomous research on '{state.goal}' completed with "
            f"{completed_tasks}/{total_tasks} tasks executed, {total_tools} tool calls, "
            f"and {len(deduped_sources)} verified sources."
        )

    # Status Determination (Rule: Never claim COMPLETED if goal completion is false!)
    goal_completed = state.goal_completion.get("completed", False) if state.goal_completion else (completed_tasks == total_tasks)
    
    if goal_completed and completed_tasks > 0:
        final_status = "COMPLETED"
    elif completed_tasks > 0 or len(state.findings) > 0:
        final_status = "PARTIAL"
    else:
        final_status = "FAILED"

    report = FinalReport(
        goal=state.goal,
        intent=state.intent,
        status=final_status,
        summary=summary,
        plan=state.plan,
        findings=state.findings,
        sources=deduped_sources,
        tool_calls=state.tool_calls,
        failures=state.failures,
        recovery_actions=state.recovery_actions,
        goal_completion=state.goal_completion,
        execution_stats=ExecutionStats(
            tasks=total_tasks,
            tasks_completed=completed_tasks,
            tool_calls=total_tools,
            retries=state.retries,
            failures=total_failures,
            recovery_count=total_recoveries,
        ),
    )

    state.final_report = report.model_dump()
    state.status = final_status
    state.execution_trace.append(f"[{timestamp}] ✓ Research Report Generated (Status: {report.status})")
    return state


def build_langgraph_agent():
    """Construct LangGraph StateGraph instance."""
    try:
        from langgraph.graph import StateGraph, START, END

        builder = StateGraph(AgentState)
        builder.add_node("validate_goal", node_validate_goal)
        builder.add_node("classify_intent", node_classify_intent)
        builder.add_node("plan", node_plan)
        builder.add_node("execute_task", node_execute)
        builder.add_node("check_goal_completion", node_check_goal_completion)
        builder.add_node("generate_report", node_generate_report)

        def route_after_validation(state: AgentState) -> str:
            return END if state.status == "FAILED" else "classify_intent"

        def route_after_plan(state: AgentState) -> str:
            return END if state.status == "FAILED" else "execute_task"

        def route_after_execute(state: AgentState) -> str:
            if state.current_task_index < len(state.plan):
                return "execute_task"
            return "check_goal_completion"

        builder.add_edge(START, "validate_goal")
        builder.add_conditional_edges("validate_goal", route_after_validation)
        builder.add_edge("classify_intent", "plan")
        builder.add_conditional_edges("plan", route_after_plan)
        builder.add_conditional_edges("execute_task", route_after_execute)
        builder.add_edge("check_goal_completion", "generate_report")
        builder.add_edge("generate_report", END)

        return builder.compile()
    except ImportError:
        return None


def run_agent(goal: str, simulate_failure: bool = False, max_retries: int = 2) -> AgentState:
    """Execute complete ResearchPilot agent loop deterministically end-to-end."""
    state = AgentState(
        goal=goal,
        simulate_failure=simulate_failure,
        max_retries=max_retries,
    )

    # 1. Validate Goal
    state = node_validate_goal(state)
    if state.status == "FAILED":
        return state

    # 2. Classify Intent
    state = node_classify_intent(state)

    # 3. Plan
    state = node_plan(state)
    if state.status == "FAILED":
        return state

    # 4. Execution & Recovery Loop
    max_steps = 15  # Safety circuit breaker against infinite loops
    step_count = 0
    while state.current_task_index < len(state.plan) and step_count < max_steps:
        step_count += 1
        state = node_execute(state)

    # 5. Check Goal Completion
    state = node_check_goal_completion(state)

    # Route to recovery if goal completion not satisfied and recovery budget remains
    intent_cat = state.intent.get("category") if state.intent else ""
    is_news = intent_cat == "CURRENT_NEWS" or "news" in state.goal.lower()

    if not state.goal_completion.get("completed") and state.retries < state.max_retries and is_news:
        timestamp = time.strftime("%H:%M:%S")
        state.retries += 1
        recovery_msg = (
            f"Deterministic goal gate rejected output ({state.goal_completion.get('reason')}). "
            f"Triggering autonomous recovery to discover and read concrete articles (Attempt {state.retries}/{state.max_retries})."
        )
        state.recovery_actions.append(recovery_msg)
        state.execution_trace.append(f"[{timestamp}] ↻ Evidence Recovery Triggered: {recovery_msg}")

        # Add recovery tasks targeting individual articles
        next_id = len(state.plan) + 1
        recovery_tasks = [
            {
                "id": next_id,
                "description": "Refined search targeting concrete breaking news headlines and individual event articles",
                "tool": "web_search",
                "input": "latest world news international events breaking reporting today",
                "status": "PENDING"
            },
            {
                "id": next_id + 1,
                "description": "Read concrete event reporting from newly discovered article",
                "tool": "read_url",
                "input": f"discovered_sources[{next_id - 1}]",
                "status": "PENDING"
            },
            {
                "id": next_id + 2,
                "description": "Re-synthesize concrete findings and cross-check against verified reporting",
                "tool": "synthesize",
                "input": "observations_history",
                "status": "PENDING"
            }
        ]
        state.plan.extend(recovery_tasks)

        # Execute recovery tasks
        while state.current_task_index < len(state.plan) and step_count < max_steps:
            step_count += 1
            state = node_execute(state)

        # Re-check goal completion
        state = node_check_goal_completion(state)

    # 6. Generate Final Report
    state = node_generate_report(state)
    return state
