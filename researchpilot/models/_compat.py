"""Lightweight fallback compatibility layer for Pydantic in environments without external pip packages."""
from __future__ import annotations
from typing import Any, Callable, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    class _FieldInfo:
        def __init__(self, default: Any = None, default_factory: Optional[Callable[[], Any]] = None):
            self.default = default
            self.default_factory = default_factory

    def Field(default: Any = ..., default_factory: Optional[Callable[[], Any]] = None, **kwargs: Any) -> Any:
        return _FieldInfo(default=default, default_factory=default_factory)

    class BaseModel:
        def __init__(self, **kwargs: Any):
            # 1. Populate class annotations & defaults
            for cls in reversed(self.__class__.__mro__):
                for attr, val in cls.__dict__.items():
                    if not attr.startswith("_") and not callable(val):
                        if isinstance(val, _FieldInfo):
                            if val.default_factory is not None:
                                setattr(self, attr, val.default_factory())
                            elif val.default is not ...:
                                setattr(self, attr, val.default)
                        else:
                            setattr(self, attr, val)

            # 2. Populate passed kwargs
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_dump(self) -> dict:
            out = {}
            for k, v in self.__dict__.items():
                if not k.startswith("_"):
                    if isinstance(v, BaseModel):
                        out[k] = v.model_dump()
                    elif isinstance(v, list):
                        out[k] = [item.model_dump() if isinstance(item, BaseModel) else item for item in v]
                    elif isinstance(v, dict):
                        out[k] = {
                            sub_k: sub_v.model_dump() if isinstance(sub_v, BaseModel) else sub_v
                            for sub_k, sub_v in v.items()
                        }
                    else:
                        out[k] = v
            return out

        def __repr__(self) -> str:
            attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items() if not k.startswith("_"))
            return f"{self.__class__.__name__}({attrs})"
