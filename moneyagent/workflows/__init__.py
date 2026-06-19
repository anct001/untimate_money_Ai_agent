"""Pluggable money-making workflows that run on top of the agent framework.

Each workflow is a thin, honest layer: it uses the router/agent to do real
work, and where money or external action is involved it keeps a human in the
loop. None of these promise income — they make legitimate work faster.
"""
from .base import Workflow, WorkflowResult
from .content import ContentWorkflow
from .trading_signals import TradingSignalsWorkflow

__all__ = ["Workflow", "WorkflowResult", "ContentWorkflow", "TradingSignalsWorkflow"]
