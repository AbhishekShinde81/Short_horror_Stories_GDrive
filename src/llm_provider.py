"""LLM provider abstraction: director_agent talks to this interface only,
never to the Gemini or Anthropic SDKs directly, so swapping providers is a
config change (llm.provider in config.yaml) rather than a code change.
"""

from __future__ import annotations

import abc
import os


class LLMProvider(abc.ABC):
    """generate_story is the entire contract both providers must satisfy."""

    @abc.abstractmethod
    def generate_story(self, prompt: str, system: str) -> str:
        ...


class GeminiProvider(LLMProvider):
    def __init__(self, model: str):
        # Imported lazily so an Anthropic-only run never needs this package
        # installed, and vice versa for AnthropicProvider.
        from google import genai

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set but llm.provider is 'gemini'."
            )
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate_story(self, prompt: str, system: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str):
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set but llm.provider is 'anthropic'."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate_story(self, prompt: str, system: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise RuntimeError("Anthropic returned no text content.")
        return "".join(text_blocks)


def get_provider(llm_config: dict) -> LLMProvider:
    """Factory selected purely by config value — no code edit required to switch."""
    provider_name = llm_config.get("provider", "gemini")
    if provider_name == "gemini":
        return GeminiProvider(model=llm_config["gemini"]["model"])
    if provider_name == "anthropic":
        return AnthropicProvider(model=llm_config["anthropic"]["model"])
    raise ValueError(f"Unknown llm.provider: {provider_name!r} (expected 'gemini' or 'anthropic')")
