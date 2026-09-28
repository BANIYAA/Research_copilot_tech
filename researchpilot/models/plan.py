"""Pydantic models for goal validation, task definition, and autonomous planning."""
from __future__ import annotations
from typing import List, Optional, Any, Dict, Literal
from enum import Enum
from ._compat import BaseModel, Field



class GoalValidationResult(BaseModel):
    """Result of validating a user-provided research goal."""
    is_valid: bool = Field(..., description="Whether the goal is substantive and executable")
    reason: str = Field(..., description="Explanation if invalid, or confirmation if valid")
    refined_goal: Optional[str] = Field(None, description="Refined or normalized goal text")


class GoalIntent(BaseModel):
    """Structured understanding of user's research intent."""
    category: Literal[
        "CURRENT_NEWS",
        "GENERAL_RESEARCH",
        "TECHNICAL_RESEARCH",
        "COMPARISON",
        "FACT_LOOKUP"
    ] = Field(..., description="Categorization of the research intent")
    topic: str = Field(..., description="Primary extracted research topic")
    time_scope: Optional[str] = Field(None, description="Temporal constraint (e.g., 'latest/current', '2026', 'historical')")
    geographic_scope: Optional[str] = Field(None, description="Geographic context (e.g., 'global', 'US', 'international')")
    output_requirement: str = Field(..., description="Expected output summary specification")
    freshness_required: bool = Field(default=False, description="Whether recent/live information is strictly required")


class FailureType(str, Enum):
    """Explicit taxonomy of tool and task failures."""
    TOOL_ERROR = "TOOL_ERROR"
    TIMEOUT = "TIMEOUT"
    EMPTY_RESULTS = "EMPTY_RESULTS"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    IRRELEVANT_RESULTS = "IRRELEVANT_RESULTS"
    STALE_RESULTS = "STALE_RESULTS"
    SOURCE_READ_ERROR = "SOURCE_READ_ERROR"
    INSUFFICIENT_CONTENT = "INSUFFICIENT_CONTENT"
    LANDING_PAGE_ONLY = "LANDING_PAGE_ONLY"
    GOAL_NOT_SATISFIED = "GOAL_NOT_SATISFIED"


class SourceValidation(BaseModel):
    """Structured evaluation of an individual source's usability and quality."""
    url_valid: bool = Field(default=True, description="Whether URL structure and scheme are valid")
    content_read: bool = Field(default=False, description="Whether page body was successfully fetched and read")
    relevant: bool = Field(default=True, description="Whether source content is relevant to research topic")
    fresh_enough: bool = Field(default=True, description="Whether content satisfies freshness requirements")
    article_level: bool = Field(default=False, description="Whether source is an individual article rather than a category or portal landing page")
    validated: bool = Field(default=False, description="Whether source passed all validation checks")
    reason: str = Field(default="", description="Detailed explanation of the validation outcome")


class FailureRecord(BaseModel):
    """Audit log of a classified failure."""
    task_id: int = Field(..., description="Task ID where failure occurred")
    tool: str = Field(..., description="Tool name associated with failure")
    failure_type: FailureType = Field(..., description="Categorized failure type")
    reason: str = Field(..., description="Detailed description of failure")
    recovery_action: str = Field(..., description="Recovery action invoked")
    retry_number: int = Field(default=0, description="Retry attempt count")
    timestamp: str = Field(..., description="Timestamp of failure")


class SemanticValidation(BaseModel):
    """Result of semantic relevance and freshness validation."""
    valid: bool = Field(..., description="Whether result satisfies task requirements")
    relevance_score: float = Field(default=1.0, description="Estimated relevance between 0.0 and 1.0")
    freshness_adequate: bool = Field(default=True, description="Whether information meets freshness requirement")
    reason: str = Field(..., description="Explanation of validation outcome")
    recovery_strategy: Optional[Literal["retry", "query_refinement", "fallback", "replan"]] = Field(
        None, description="Recommended recovery strategy if invalid"
    )


class Task(BaseModel):
    """An actionable step within the generated research plan."""
    id: int = Field(..., description="Unique sequential task identifier (1-based)")
    description: str = Field(..., description="Human-readable description of what this task accomplishes")
    tool: str = Field(..., description="Tool to invoke: 'web_search', 'read_url', or 'synthesize'")
    input: str = Field(..., description="Input parameters or query for the tool")
    status: str = Field(default="PENDING", description="Status: PENDING, RUNNING, COMPLETED, FAILED, SKIPPED")
    fallback_input: Optional[str] = Field(None, description="Alternative input to try if primary fails")


class Plan(BaseModel):
    """Structured plan decomposed from the research goal."""
    goal: str = Field(..., description="The user's original research goal")
    intent: Optional[GoalIntent] = Field(None, description="Classified intent guiding this plan")
    tasks: List[Task] = Field(..., description="Sequential list of actionable tasks (min 2 steps)")


class ToolCallRecord(BaseModel):
    """Audit log of a single tool invocation."""
    task_id: int = Field(..., description="ID of the task triggering this call")
    tool: str = Field(..., description="Name of the tool called")
    input_data: str = Field(..., description="Input passed to the tool")
    output_preview: Optional[str] = Field(None, description="Truncated preview of output")
    success: bool = Field(..., description="Whether tool execution succeeded")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    duration_ms: int = Field(default=0, description="Execution duration in milliseconds")
    timestamp: str = Field(..., description="ISO timestamp of invocation")
    retry_number: int = Field(default=0, description="Attempt number (0 for initial try)")

