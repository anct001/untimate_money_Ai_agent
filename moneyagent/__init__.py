"""moneyagent — a multi-provider AI agent framework.

Combines small local models (Ollama) with free-tier hosted APIs (Groq, Gemini,
OpenRouter, Cerebras, ...) behind a single router that handles model selection,
quota tracking and automatic fallback, then runs task workflows on top.

The framework is the product. Earning money is up to the *workflows* you plug
in and the real, lawful work they help you deliver — see workflows/.
"""

__version__ = "0.1.0"

from .config import Config, load_config
from .router import LLMRouter
from .providers.base import Message, CompletionResult

__all__ = [
    "Config",
    "load_config",
    "LLMRouter",
    "Message",
    "CompletionResult",
    "__version__",
]
