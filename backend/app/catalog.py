"""Provider templates and seed catalog.

Together model IDs and prices were taken from https://api.together.xyz/v1/models (2026-10-22).
Template model lists for the other providers are starting points (prices USD per 1M tokens,
from public price lists / OpenRouter at setup time) - verify and edit in the UI.
"""

PROVIDER_KINDS = {
    # kind: (litellm prefix, default api base, needs api_base override for litellm)
    "together": ("together_ai", "https://api.together.xyz/v1", False),
    "openai": ("openai", "https://api.openai.com/v1", False),
    "anthropic": ("anthropic", "https://api.anthropic.com", False),
    "openrouter": ("openrouter", "https://openrouter.ai/api/v1", False),
    "xai": ("xai", "https://api.x.ai/v1", False),
    "zai": ("openai", "https://api.z.ai/api/paas/v4", True),
    "openai_compatible": ("openai", "", True),
}


def M(model_name, upstream_id, display, inp, out, ctx=None, tags=None, enabled=True, **caps):
    return dict(model_name=model_name, upstream_id=upstream_id, display_name=display,
                input_price_per_m=inp, output_price_per_m=out, context_window=ctx, tags=tags or [], enabled=enabled,
                **caps)


# Capabilities of the Together models, measured 2026-10-25 with test calls (see README; scripts/playground_fix_test.py re-checks):
# * vision: every model read a generated image correctly (4 colour quadrants + the digits "3846"; prompt tokens grow
#   by ~190 with the image). Together's /v1/models exposes no capability or max-output fields.
# * reasoning: all five return reasoning_content on every request (reasoning tokens 100-6000 on small puzzles).
# * reasoning control: reasoning={"enabled": false} turns thinking off for DeepSeek, Muse Spark and Nemotron (0 reasoning
#   tokens), not for GLM. reasoning_effort only measurably changes Muse Spark (low < medium < high); it is accepted but
#   has no measurable effect on DeepSeek/Nemotron and is erratic on GLM, so it is not offered there.
# * max output: Together only limits max_tokens by the context window; the Playground caps it at 131072.
def caps(default_max, efforts, vision=True, reasoning=True, max_out=131072):
    return dict(max_output_tokens=max_out, default_max_tokens=default_max, supports_reasoning=reasoning,
                supports_vision=vision, reasoning_efforts=efforts)


TOGETHER_CAPS = {
    "deepseek-v4.1-flash-1017": caps(8192, ["off"]),
    "deepseek-v4.1-flash": caps(8192, ["off"]),
    "glm-5.3-flash": caps(16384, []),
    "muse-spark-open": caps(16384, ["off", "low", "medium", "high"]),
    "nemotron-3.5-super-vl": caps(16384, ["off"]),
}


CATALOG = [
    dict(slug="together", name="Together AI", kind="together", enabled=True,
         description="Open-weight models served by Together AI.",
         models=[
             M("deepseek-v4.1-flash-1017", "deepseek-ai/DeepSeek-V4.1-Flash-1017", "DeepSeek V4.1 Flash 1017", 0.30, 1.20, 1048576, ["chat", "code"], **TOGETHER_CAPS["deepseek-v4.1-flash-1017"]),
             M("deepseek-v4.1-flash", "deepseek-ai/DeepSeek-V4.1-Flash", "DeepSeek V4.1 Flash", 0.30, 1.20, 1048576, ["chat", "code"], **TOGETHER_CAPS["deepseek-v4.1-flash"]),
             M("glm-5.3-flash", "zai-org/GLM-5.3-Flash", "GLM 5.3 Flash", 0.15, 0.50, 1048575, ["chat", "fast"], **TOGETHER_CAPS["glm-5.3-flash"]),
             M("muse-spark-open", "meta-models/Muse-Spark-Open-816B-A42B", "Muse Spark Open 816B A42B", 1.25, 4.25, 1048576, ["chat", "smart"], **TOGETHER_CAPS["muse-spark-open"]),
             M("nemotron-3.5-super-vl", "nvidia/NVIDIA-Nemotron-3.5-Super-VL", "NVIDIA Nemotron 3.5 Super VL", 0.15, 0.50, 262144, ["chat", "vision"], **TOGETHER_CAPS["nemotron-3.5-super-vl"]),
         ]),
    dict(slug="zai", name="Z.ai (GLM)", kind="zai", enabled=False, api_base="https://api.z.ai/api/paas/v4",
         description="Zhipu Z.ai GLM models via the OpenAI-compatible PaaS v4 endpoint.",
         models=[
             M("zai/glm-5.3", "glm-5.3", "GLM 5.3", 1.40, 4.40, 1048576),
             M("zai/glm-5.3-prime", "glm-5.3-prime", "GLM 5.3 Prime", 2.80, 8.80, 1000000),
             M("zai/glm-5.3-flashx", "glm-5.3-flashx", "GLM 5.3 FlashX", 0.37, 1.25, 1048576),
             M("zai/glm-5.3-flash", "glm-5.3-flash", "GLM 5.3 Flash", 0.15, 0.50, 1048576),
             M("zai/glm-5.2", "glm-5.2", "GLM 5.2", 1.40, 4.40, 1048576),
             M("zai/glm-5v-turbo", "glm-5v-turbo", "GLM 5V Turbo (vision)", 1.20, 4.00, 202752),
         ]),
    dict(slug="openrouter", name="OpenRouter", kind="openrouter", enabled=False,
         description="Hundreds of models through one key. Add any model id from openrouter.ai/models.",
         models=[
             M("openrouter/anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5 (OpenRouter)", 2.0, 10.0, 1000000),
             M("openrouter/anthropic/claude-opus-5.5", "anthropic/claude-opus-5.5", "Claude Opus 5.5 (OpenRouter)", 4.0, 20.0, 1000000),
             M("openrouter/openai/gpt-6.1-sol", "openai/gpt-6.1-sol", "GPT-6.1 Sol (OpenRouter)", 2.0, 10.0, 1050000),
             M("openrouter/x-ai/grok-4.7", "x-ai/grok-4.7", "Grok 4.7 (OpenRouter)", 2.0, 6.0, 500000),
             M("openrouter/z-ai/glm-5.3", "z-ai/glm-5.3", "GLM 5.3 (OpenRouter)", 1.40, 4.40, 1048576),
         ]),
    dict(slug="anthropic", name="Anthropic", kind="anthropic", enabled=False,
         description="Claude models via the native Anthropic API. Verify exact model ids in the Anthropic console.",
         models=[
             M("anthropic/claude-opus-5.5", "claude-opus-5-5", "Claude Opus 5.5", 4.0, 20.0, 1000000),
             M("anthropic/claude-sonnet-5.5", "claude-sonnet-5-5", "Claude Sonnet 5.5", 2.0, 10.0, 1000000),
             M("anthropic/claude-haiku-5.5", "claude-haiku-5-5", "Claude Haiku 5.5", 0.10, 0.50, 1000000),
             M("anthropic/claude-opus-5", "claude-opus-5", "Claude Opus 5", 5.0, 25.0, 1000000),
             M("anthropic/claude-sonnet-5", "claude-sonnet-5", "Claude Sonnet 5", 2.0, 10.0, 1000000),
         ]),
    dict(slug="openai", name="OpenAI", kind="openai", enabled=False,
         description="OpenAI GPT and Codex models.",
         models=[
             M("openai/gpt-6.1-sol", "gpt-6.1-sol", "GPT-6.1 Sol", 2.0, 10.0, 1050000),
             M("openai/gpt-6.1-sol-pro", "gpt-6.1-sol-pro", "GPT-6.1 Sol Pro", 2.0, 10.0, 1050000),
             M("openai/gpt-6-sol", "gpt-6-sol", "GPT-6 Sol", 2.0, 10.0, 1050000),
             M("openai/gpt-6-luna", "gpt-6-luna", "GPT-6 Luna", 0.10, 0.50, 1050000),
             M("openai/gpt-6-astra", "gpt-6-astra", "GPT-6 Astra", 10.0, 50.0, 1050000),
             M("openai/gpt-5.3-codex", "gpt-5.3-codex", "GPT-5.3 Codex", 1.75, 14.0, 400000, ["code"]),
             M("openai/gpt-5.2-codex", "gpt-5.2-codex", "GPT-5.2 Codex", 1.75, 14.0, 400000, ["code"]),
             M("openai/gpt-5.1-codex-max", "gpt-5.1-codex-max", "GPT-5.1 Codex Max", 1.25, 10.0, 400000, ["code"]),
             M("openai/gpt-5.1-codex-mini", "gpt-5.1-codex-mini", "GPT-5.1 Codex Mini", 0.25, 2.0, 400000, ["code"]),
         ]),
    dict(slug="xai", name="xAI Grok", kind="xai", enabled=False,
         description="xAI Grok models.",
         models=[
             M("xai/grok-4.7", "grok-4.7", "Grok 4.7", 2.0, 6.0, 500000),
             M("xai/grok-4.6", "grok-4.6", "Grok 4.6", 2.0, 6.0, 500000),
             M("xai/grok-4.5", "grok-4.5", "Grok 4.5", 2.0, 6.0, 500000),
             M("xai/grok-4.3", "grok-4.3", "Grok 4.3", 1.25, 2.5, 1000000),
             M("xai/grok-build-0.1", "grok-build-0.1", "Grok Build 0.1", 1.0, 2.0, 256000, ["code"]),
         ]),
]

DEFAULT_ALIASES = [
    ("default", "deepseek-v4.1-flash-1017", "General-purpose default model"),
    ("fast", "glm-5.3-flash", "Cheapest / lowest latency"),
    ("smart", "muse-spark-open", "Most capable model"),
    ("vision", "nemotron-3.5-super-vl", "Image understanding"),
]
