"""Models package for ResearchPilot."""
from .plan import GoalValidationResult, GoalIntent, FailureType, FailureRecord, SemanticValidation, Task, Plan, ToolCallRecord
from .report import ExecutionStats, SourceAttribution, GoalCompletion, FinalReport, AgentState

__all__ = [
    "GoalValidationResult",
    "GoalIntent",
    "FailureType",
    "FailureRecord",
    "SemanticValidation",
    "GoalCompletion",
    "Task",
    "Plan",
    "ToolCallRecord",
    "ExecutionStats",
    "SourceAttribution",
    "FinalReport",
    "AgentState",
]

