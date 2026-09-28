"""Pydantic models for reporting, execution statistics, and agent state."""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from ._compat import BaseModel, Field
from .plan import Task, ToolCallRecord, GoalIntent, FailureRecord



class ExecutionStats(BaseModel):
    """Execution metrics and audit statistics."""
    tasks: int = Field(default=0, description="Total number of tasks in plan")
    tasks_completed: int = Field(default=0, description="Tasks successfully executed")
    tool_calls: int = Field(default=0, description="Total number of tool calls invoked")
    retries: int = Field(default=0, description="Number of retries triggered")
    failures: int = Field(default=0, description="Number of failures encountered")
    recovery_count: int = Field(default=0, description="Successful recovery actions executed")
    duration_seconds: float = Field(default=0.0, description="Total wall-clock execution duration in seconds")


class SourceAttribution(BaseModel):
    """Source URL and metadata extracted during research."""
    title: str = Field(..., description="Document or page title")
    url: str = Field(..., description="Direct HTTP/HTTPS URL")
    snippet: Optional[str] = Field(None, description="Relevant excerpt or summary")
    url_valid: bool = Field(default=True, description="Whether URL structure and scheme are valid")
    content_read: bool = Field(default=False, description="Whether page body was successfully fetched and read")
    relevant: bool = Field(default=True, description="Whether source content is relevant to research intent")
    fresh_enough: bool = Field(default=True, description="Whether content satisfies freshness requirements")
    article_level: bool = Field(default=False, description="Whether source is an individual article rather than a category or portal landing page")
    validated: bool = Field(default=False, description="Whether source passed all validation checks")


class GoalCompletion(BaseModel):
    """Evaluation of whether user's original goal was actually satisfied."""
    completed: bool = Field(..., description="Whether user's original goal was satisfied")
    reason: str = Field(..., description="Detailed explanation of goal satisfaction or deficiency")
    missing_requirements: List[str] = Field(default_factory=list, description="Missing requirements or data points")


class FinalReport(BaseModel):
    """Structured research synthesis report."""
    goal: str = Field(..., description="Original user research goal")
    intent: Optional[Dict[str, Any]] = Field(None, description="Classified intent of the goal")
    status: str = Field(default="COMPLETED", description="COMPLETED, PARTIAL, or FAILED")
    summary: str = Field(..., description="High-level executive summary of findings")
    plan: List[Dict[str, Any]] = Field(default_factory=list, description="Original plan executed")
    findings: List[str] = Field(default_factory=list, description="Numbered bullet findings synthesized from research")
    sources: List[SourceAttribution] = Field(default_factory=list, description="Validated citations and sources")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="History of all tool calls")
    failures: List[Dict[str, Any]] = Field(default_factory=list, description="Recorded errors during execution")
    recovery_actions: List[str] = Field(default_factory=list, description="Explanations of recovery strategies employed")
    goal_completion: Optional[Dict[str, Any]] = Field(None, description="Verification of goal fulfillment")
    execution_stats: ExecutionStats = Field(default_factory=ExecutionStats, description="Execution metrics")


class AgentState(BaseModel):
    """Complete LangGraph state model."""
    goal: str = Field(default="", description="Target research goal")
    intent: Optional[Dict[str, Any]] = Field(default=None, description="Classified goal intent dictionary")
    plan: List[Dict[str, Any]] = Field(default_factory=list, description="List of planned tasks")
    current_task_index: int = Field(default=0, description="Pointer to current task in plan")
    current_task: Optional[Dict[str, Any]] = Field(default=None, description="Task currently under execution")
    observations: List[Dict[str, Any]] = Field(default_factory=list, description="Raw outputs collected from tools")
    findings: List[str] = Field(default_factory=list, description="Extracted research takeaways")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Collected sources")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Historical tool call records")
    failures: List[Dict[str, Any]] = Field(default_factory=list, description="Failure log entries")
    retries: int = Field(default=0, description="Current retry counter for active task")
    execution_trace: List[str] = Field(default_factory=list, description="User-visible human-readable audit trace")
    recovery_actions: List[str] = Field(default_factory=list, description="Descriptions of recoveries performed")
    last_validation: Optional[Dict[str, Any]] = Field(default=None, description="Details of latest validation decision")
    goal_completion: Optional[Dict[str, Any]] = Field(default=None, description="Goal completion evaluation result")
    status: str = Field(default="INITIALIZED", description="INITIALIZED, VALIDATING, PLANNING, EXECUTING, RECOVERING, COMPLETED, PARTIAL, FAILED")
    final_report: Optional[Dict[str, Any]] = Field(default=None, description="Completed FinalReport dictionary")
    simulate_failure: bool = Field(default=False, description="Flag for deliberate failure demonstration")
    max_retries: int = Field(default=2, description="Maximum allowed retries per task")

