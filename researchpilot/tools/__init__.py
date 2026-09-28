"""Tools package for ResearchPilot."""
from typing import Dict, Any, Optional
from models._compat import BaseModel, Field

class ToolResult(BaseModel):

    """Standardized result returned by all tools."""
    success: bool = Field(..., description="Whether tool execution succeeded")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured tool payload")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    duration_ms: int = Field(default=0, description="Execution duration in milliseconds")

class ToolExecutionError(Exception):
    """Raised when a tool encounters an unrecoverable or deliberate execution error."""
    pass

from .web_search import web_search
from .url_reader import read_url

__all__ = ["ToolResult", "ToolExecutionError", "web_search", "read_url"]
