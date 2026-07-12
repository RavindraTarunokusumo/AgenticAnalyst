"""Model gateway construction from validated provider settings."""

from analyst_engine.config import ModelProvider, Settings
from analyst_engine.models.dashscope import DashScopeAdapter
from analyst_engine.models.gateway import ModelGateway
from analyst_engine.models.openrouter import OpenRouterAdapter


def create_model_gateway(settings: Settings) -> ModelGateway:
    """Create the configured provider adapter."""
    if settings.model_provider is ModelProvider.OPENROUTER:
        return OpenRouterAdapter(settings)
    return DashScopeAdapter(settings)
