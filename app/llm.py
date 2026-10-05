"""Provider-agnostic structured output (Claude or OpenAI).

Every LLM step in LeadScout returns JSON that matches a schema. We force this with tool calling:
the model must call a single tool whose input schema is the schema we want, so we never parse free text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import Settings


class ProviderConfigError(RuntimeError):
    """Raised when a provider is selected but not configured (e.g. missing API key)."""


@dataclass
class StructuredResult:
    data: dict
    input_tokens: int
    output_tokens: int
    cost_usd: float


class BaseProvider:
    name = "base"

    def __init__(self, model: str, price_in: float, price_out: float, temperature: float | None):
        self.model, self.price_in, self.price_out, self.temperature = model, price_in, price_out, temperature

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000

    def _create(self, create_fn, kwargs: dict):
        """Calls the SDK; if it rejects `temperature`, retries without it for the rest of the session."""
        try:
            return create_fn(**kwargs)
        except Exception as exc:
            if "temperature" in kwargs and "temperature" in str(exc).lower():
                kwargs.pop("temperature")
                self.temperature = None
                return create_fn(**kwargs)
            raise

    def structured(self, system: str, user: str, name: str, schema: dict,
                   max_tokens: int = 2000) -> StructuredResult:  # pragma: no cover
        raise NotImplementedError


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise ProviderConfigError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        super().__init__(settings.anthropic_model, settings.anthropic_price_input,
                         settings.anthropic_price_output, settings.temperature)
        import anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def structured(self, system, user, name, schema, max_tokens=2000):
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}],
                      tools=[{"name": name, "description": f"Submit the {name} result.", "input_schema": schema}],
                      tool_choice={"type": "tool", "name": name})
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = self._create(self.client.messages.create, kwargs)
        data = next((dict(b.input) for b in resp.content if b.type == "tool_use"), {})
        i, o = resp.usage.input_tokens, resp.usage.output_tokens
        return StructuredResult(data, i, o, self.cost(i, o))


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ProviderConfigError("OPENAI_API_KEY is not set. Add it to your .env file.")
        super().__init__(settings.openai_model, settings.openai_price_input,
                         settings.openai_price_output, settings.temperature)
        import openai
        self.client = openai.OpenAI(api_key=settings.openai_api_key)

    def structured(self, system, user, name, schema, max_tokens=2000):
        kwargs = dict(model=self.model,
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                      tools=[{"type": "function", "function": {"name": name, "description": f"Submit the {name} result.",
                                                               "parameters": schema}}],
                      tool_choice={"type": "function", "function": {"name": name}})
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = self._create(self.client.chat.completions.create, kwargs)
        calls = resp.choices[0].message.tool_calls or []
        try:
            data = json.loads(calls[0].function.arguments) if calls else {}
        except json.JSONDecodeError:
            data = {}
        i = getattr(resp.usage, "prompt_tokens", 0) or 0
        o = getattr(resp.usage, "completion_tokens", 0) or 0
        return StructuredResult(data, i, o, self.cost(i, o))


def get_provider(settings: Settings, name: str | None = None) -> BaseProvider:
    name = (name or settings.llm_provider).lower()
    if name in ("anthropic", "claude"):
        return AnthropicProvider(settings)
    if name in ("openai", "gpt"):
        return OpenAIProvider(settings)
    raise ProviderConfigError(f"Unknown LLM_PROVIDER '{name}'. Use 'anthropic' or 'openai'.")
