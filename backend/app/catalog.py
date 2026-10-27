"""Provider templates and seed catalog.

Together model IDs and prices were taken from https://api.together.xyz/v1/models (2026-10-22, audio + extra chat
models 2026-10-27); every Together model below answered a real test call. Template model lists for the other
providers are starting points: prices come from the providers' price pages where they could be fetched (OpenAI
pricing page, DeepSeek pricing page, Groq models page, 2026-10-27) and otherwise from LiteLLM's bundled cost map;
entries tagged "unverified" could not be confirmed against an official page - verify and edit them in the UI.

Units: chat prices are USD per 1M tokens; transcription uses price_per_minute (USD per audio minute); speech uses
price_per_m_chars (USD per 1M input characters); realtime / audio-chat models add audio-token prices per 1M tokens.
"""

PROVIDER_KINDS = {
    # kind: (litellm prefix, default api base, needs api_base override for litellm)
    "together": ("together_ai", "https://api.together.xyz/v1", False),
    "openai": ("openai", "https://api.openai.com/v1", False),
    "anthropic": ("anthropic", "https://api.anthropic.com", False),
    "openrouter": ("openrouter", "https://openrouter.ai/api/v1", False),
    "xai": ("xai", "https://api.x.ai/v1", False),
    "zai": ("openai", "https://api.z.ai/api/paas/v4", True),
    "groq": ("groq", "https://api.groq.com/openai/v1", False),
    "mistral": ("mistral", "https://api.mistral.ai/v1", False),
    "gemini": ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", True),  # OpenAI-compatible endpoint
    "deepseek": ("deepseek", "https://api.deepseek.com", False),
    "deepinfra": ("deepinfra", "https://api.deepinfra.com/v1/openai", False),
    "fireworks": ("fireworks_ai", "https://api.fireworks.ai/inference/v1", False),
    "cerebras": ("cerebras", "https://api.cerebras.ai/v1", False),
    "sambanova": ("sambanova", "https://api.sambanova.ai/v1", False),
    "hyperbolic": ("hyperbolic", "https://api.hyperbolic.xyz/v1", False),
    "nebius": ("nebius", "https://api.studio.nebius.com/v1", False),
    "novita": ("novita", "https://api.novita.ai/v3/openai", False),
    "baseten": ("baseten", "https://inference.baseten.co/v1", False),
    "vercel": ("openai", "https://ai-gateway.vercel.sh/v1", True),  # Vercel AI Gateway, OpenAI-compatible
    "openai_compatible": ("openai", "", True),
    # the gateway's own cascaded voice pipeline (STT -> chat -> TTS) behind /v1/realtime; never sent to LiteLLM
    "pipeline": ("pipeline", "", False),
}

# how "Sync models" reads a provider's catalog (prices/capabilities where the provider publishes them)
SYNC_STYLE = {"together": "together", "openrouter": "openrouter", "vercel": "vercel"}
SKIP_SYNC = {"pipeline", "anthropic"}

KINDS = ("chat", "transcription", "input", "speech", "realtime", "embedding")
# LiteLLM model_info.mode per kind (exposed by /model/info; clients such as malac use it to detect audio models)
KIND_MODE = {"chat": "chat", "input": "chat", "transcription": "audio_transcription", "speech": "audio_speech",
             "realtime": "realtime", "embedding": "embedding"}


def M(model_name, upstream_id, display, inp, out, ctx=None, tags=None, enabled=True, **caps):
    return dict(model_name=model_name, upstream_id=upstream_id, display_name=display,
                input_price_per_m=inp, output_price_per_m=out, context_window=ctx, tags=tags or [], enabled=enabled,
                **caps)


UNVERIFIED = "unverified"


def STT(model_name, upstream_id, display, per_min, tags=None, enabled=True, **extra):
    """Transcription model, priced per audio minute."""
    return M(model_name, upstream_id, display, 0, 0, None, ["audio", *(tags or [])], enabled, kind="transcription",
             price_per_minute=per_min, **extra)


def TTS(model_name, upstream_id, display, per_m_chars, voices, default_voice, tags=None, enabled=True, text_in=0, **extra):
    """Speech (text-to-speech) model, priced per 1M input characters."""
    return M(model_name, upstream_id, display, text_in, 0, None, ["audio", *(tags or [])], enabled, kind="speech",
             price_per_m_chars=per_m_chars, voices=voices, default_voice=default_voice, **extra)


def AUDIO(kind, model_name, display, text_in, text_out, audio_in, audio_out, ctx=None, voices=None,
          default_voice=None, tags=None, enabled=True):
    """Realtime or audio-chat ("input") model: text + audio token prices per 1M tokens."""
    return M(model_name, model_name.split("/", 1)[-1], display, text_in, text_out, ctx, ["audio", *(tags or [])], enabled, kind=kind,
             audio_input_price_per_m=audio_in, audio_output_price_per_m=audio_out, voices=voices,
             default_voice=default_voice, supports_vision=False)


# voices: Together GET /v1/voices (2026-10-27); OpenAI voices from the OpenAI TTS / Realtime docs
SONIC_VOICES = ["german conversational woman", "nonfiction man", "friendly sidekick", "french conversational lady", "french narrator lady", "german reporter woman", "indian lady", "british reading lady", "british narration lady", "japanese children book", "japanese woman conversational", "japanese male conversational", "reading lady", "newsman", "child", "meditation lady", "maria", "1920's radioman", "newslady", "calm lady", "helpful woman", "mexican woman", "korean narrator woman", "russian calm lady", "russian narrator man 1", "russian narrator man 2", "russian narrator woman", "hinglish speaking lady", "italian narrator woman", "polish narrator woman", "chinese female conversational", "pilot over intercom", "chinese commercial man", "french narrator man", "spanish narrator man", "reading man", "new york man", "friendly french man", "barbershop man", "indian man", "australian customer support man", "friendly australian man", "wise man", "friendly reading man", "customer support man", "dutch confident man", "dutch man", "hindi reporter man", "italian calm man", "italian narrator man", "swedish narrator man", "polish confident man", "spanish-speaking storyteller man", "kentucky woman", "chinese commercial woman", "middle eastern woman", "hindi narrator woman", "sarah", "sarah curious", "laidback woman", "reflective woman", "helpful french lady", "pleasant brazilian lady", "customer support lady", "british lady", "wise lady", "australian narrator lady", "indian customer support lady", "swedish calm lady", "spanish narrator lady", "salesman", "yogaman", "movieman", "wizardman", "australian woman", "korean calm woman", "friendly german man", "announcer man", "wise guide man", "midwestern man", "kentucky man", "brazilian young man", "chinese call center man", "german reporter man", "confident british man", "southern man", "classy british man", "polite man", "mexican man", "korean narrator man", "turkish narrator man", "turkish calm man", "hindi calm man", "hindi narrator man", "polish narrator man", "polish young man", "alabama male", "australian male", "anime girl", "japanese man book", "sweet lady", "commercial lady", "teacher lady", "princess", "commercial man", "asmr lady", "professional woman", "tutorial man", "calm french woman", "new york woman", "spanish-speaking lady", "midwestern woman", "sportsman", "storyteller lady", "spanish-speaking man", "doctor mischief", "spanish-speaking reporter man", "young spanish-speaking woman", "the merchant", "stern french man", "madame mischief", "german storyteller man", "female nurse", "german conversation man", "friendly brazilian man", "german woman", "southern woman", "british customer support lady", "chinese woman narrator", "pleasant man", "california girl", "john", "anna"]
KOKORO_VOICES = ["af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo", "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang", "ef_dora", "em_alex", "em_santa", "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi", "if_sara", "im_nicola", "pf_dora", "pm_alex", "pm_santa"]
OPENAI_TTS_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"]
OPENAI_TTS1_VOICES = ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]
OPENAI_REALTIME_VOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
GROQ_ORPHEUS_VOICES = ["troy", "autumn", "diana", "hannah", "austin", "daniel"]


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
# added 2026-10-27: reasoning measured with a test call (all return reasoning_content); vision measured with a solid-red
# PNG: Kimi K3 and MiniMax M3.1 Flash answer "Red"; gpt-oss says it cannot see images; DeepSeek V4 Pro, GLM 5.3 and
# Qwen3.8 reject image parts (multimodal_not_supported / multimodal_processing_failed). Reasoning control not offered.
TOGETHER_CAPS_2 = {
    "qwen3.8-2.4t": caps(16384, [], vision=False),
    "kimi-k3": caps(16384, [], vision=True),
    "gpt-oss-120b": caps(8192, [], vision=False),
    "deepseek-v4-pro": caps(16384, [], vision=False),
    "glm-5.3": caps(16384, [], vision=False),
    "minimax-m3.1-flash": caps(8192, [], vision=True),
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
             M("qwen3.8-2.4t", "Qwen/Qwen3.8-2.4T-A95B", "Qwen3.8 2.4T A95B", 2.00, 6.00, 1010000, ["chat", "smart"], **TOGETHER_CAPS_2["qwen3.8-2.4t"]),
             M("kimi-k3", "moonshotai/Kimi-K3", "Kimi K3", 3.00, 15.00, 1048576, ["chat", "code"], **TOGETHER_CAPS_2["kimi-k3"]),
             M("gpt-oss-120b", "openai/gpt-oss-120b", "gpt-oss 120B", 0.15, 0.60, 131072, ["chat", "fast"], **TOGETHER_CAPS_2["gpt-oss-120b"]),
             M("deepseek-v4-pro", "deepseek-ai/DeepSeek-V4-Pro-0813", "DeepSeek V4 Pro 0813", 1.32, 3.96, 1048576, ["chat", "code"], **TOGETHER_CAPS_2["deepseek-v4-pro"]),
             M("glm-5.3", "zai-org/GLM-5.3", "GLM 5.3", 1.40, 4.40, 1048575, ["chat"], **TOGETHER_CAPS_2["glm-5.3"]),
             M("minimax-m3.1-flash", "MiniMaxAI/MiniMax-M3.1-Flash", "MiniMax M3.1 Flash", 0.15, 0.60, 1048576, ["chat", "fast"], **TOGETHER_CAPS_2["minimax-m3.1-flash"]),
             # audio (Together pricing: transcription per audio minute, TTS per 1M characters)
             STT("whisper-large-v3", "openai/whisper-large-v3", "Whisper large v3", 0.0015),
             STT("parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3", "NVIDIA Parakeet TDT 0.6B v3", 0.0015),
             TTS("sonic-3", "cartesia/sonic-3", "Cartesia Sonic 3", 65.0, SONIC_VOICES, "helpful woman"),
             TTS("kokoro-82m", "hexgrad/Kokoro-82M", "Kokoro 82M", 4.0, KOKORO_VOICES, "af_heart"),
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
             # audio - prices from the OpenAI pricing page (2026-10-27)
             STT("openai/gpt-4o-transcribe", "gpt-4o-transcribe", "GPT-4o Transcribe", 0.006),
             STT("openai/gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe", "GPT-4o mini Transcribe", 0.003),
             STT("openai/whisper-1", "whisper-1", "Whisper (OpenAI)", 0.006),
             # gpt-4o-mini-tts is billed per token ($0.60/1M text in, $12/1M audio out, ~$0.015/min); the per-character
             # price is an estimate (~1000 characters per spoken minute) so cost tracking works
             TTS("openai/gpt-4o-mini-tts", "gpt-4o-mini-tts", "GPT-4o mini TTS", 15.0, OPENAI_TTS_VOICES, "coral", audio_output_price_per_m=12.0, text_in=0.60),
             TTS("openai/tts-1", "tts-1", "TTS-1", 15.0, OPENAI_TTS1_VOICES, "alloy"),
             TTS("openai/tts-1-hd", "tts-1-hd", "TTS-1 HD", 30.0, OPENAI_TTS1_VOICES, "alloy"),
             AUDIO("realtime", "openai/gpt-realtime", "gpt-realtime", 4.0, 16.0, 32.0, 64.0, 32000, OPENAI_REALTIME_VOICES, "marin"),
             AUDIO("realtime", "openai/gpt-realtime-mini", "gpt-realtime mini", 0.60, 2.40, 10.0, 20.0, 32000, OPENAI_REALTIME_VOICES, "marin"),
             AUDIO("realtime", "openai/gpt-realtime-2.1", "gpt-realtime 2.1", 4.0, 24.0, 32.0, 64.0, 128000, OPENAI_REALTIME_VOICES, "marin"),
             AUDIO("input", "openai/gpt-audio-mini", "gpt-audio mini", 0.60, 2.40, 10.0, 20.0, 128000, OPENAI_REALTIME_VOICES, "marin"),
             AUDIO("input", "openai/gpt-audio", "gpt-audio", 2.50, 10.0, 32.0, 64.0, 128000, OPENAI_REALTIME_VOICES, "marin"),
             # older preview names: not on the current pricing page; kept disabled for accounts that still have them
             AUDIO("input", "openai/gpt-4o-audio-preview", "GPT-4o audio preview", 2.50, 10.0, 40.0, 80.0, 128000, OPENAI_REALTIME_VOICES, "alloy", [UNVERIFIED], enabled=False),
             AUDIO("input", "openai/gpt-4o-mini-audio-preview", "GPT-4o mini audio preview", 0.15, 0.60, 10.0, 20.0, 128000, OPENAI_REALTIME_VOICES, "alloy", [UNVERIFIED], enabled=False),
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
    dict(slug="groq", name="Groq", kind="groq", enabled=False,
         description="Very fast inference: Whisper transcription, Orpheus TTS and open-weight LLMs. Prices from console.groq.com/docs/models.",
         models=[
             STT("groq/whisper-large-v3", "whisper-large-v3", "Whisper large v3 (Groq)", 0.00185),
             STT("groq/whisper-large-v3-turbo", "whisper-large-v3-turbo", "Whisper large v3 turbo (Groq)", 0.000667),
             TTS("groq/orpheus-v1-english", "canopylabs/orpheus-v1-english", "Orpheus v1 English (Groq)", 22.0, GROQ_ORPHEUS_VOICES, "troy"),
             M("groq/gpt-oss-120b", "openai/gpt-oss-120b", "gpt-oss 120B (Groq)", 0.15, 0.60, 131072, ["fast"], max_output_tokens=65536),
             M("groq/gpt-oss-20b", "openai/gpt-oss-20b", "gpt-oss 20B (Groq)", 0.075, 0.30, 131072, ["fast"], max_output_tokens=65536),
             M("groq/qwen3.8-27b", "qwen/qwen3.8-27b", "Qwen3.8 27B (Groq)", 0.80, 4.00, 131072, max_output_tokens=16384),
         ]),
    dict(slug="mistral", name="Mistral", kind="mistral", enabled=False,
         description="Mistral chat models plus Voxtral transcription and speech. Prices from LiteLLM's cost map.",
         models=[
             M("mistral/mistral-large-latest", "mistral-large-latest", "Mistral Large", 0.50, 1.50, 262144),
             M("mistral/mistral-medium-latest", "mistral-medium-latest", "Mistral Medium", 1.50, 7.50, 262144),
             M("mistral/mistral-small-latest", "mistral-small-latest", "Mistral Small", 0.15, 0.60, 262144, ["fast"]),
             M("mistral/magistral-medium-latest", "magistral-medium-latest", "Magistral Medium", 1.50, 7.50, 262144, supports_reasoning=True),
             M("mistral/devstral-latest", "devstral-latest", "Devstral", 0.40, 2.00, 256000, ["code"]),
             STT("mistral/voxtral-mini-transcribe", "voxtral-mini-transcribe-3-0", "Voxtral Mini Transcribe 3", 0.0035, [UNVERIFIED]),
             STT("mistral/voxtral-small-transcribe", "voxtral-small-transcribe-3-0", "Voxtral Small Transcribe 3", 0.004, [UNVERIFIED]),
             TTS("mistral/voxtral-tts", "voxtral-mini-tts-3-0", "Voxtral TTS 3", 13.0, [], None, [UNVERIFIED]),
         ]),
    dict(slug="gemini", name="Google Gemini", kind="gemini", enabled=False, api_base="https://generativelanguage.googleapis.com/v1beta/openai",
         description="Gemini through Google's OpenAI-compatible endpoint (AI Studio API key). Model IDs and prices from LiteLLM's cost map - verify on ai.google.dev.",
         models=[
             M("gemini/gemini-3.8-flash", "gemini-3.8-flash", "Gemini 3.8 Flash", 0.75, 3.75, 1048576, [UNVERIFIED], supports_vision=True, supports_reasoning=True, max_output_tokens=65536),
             M("gemini/gemini-3.5-flash-lite", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", 0.30, 2.50, 1048576, ["fast", UNVERIFIED], supports_vision=True, max_output_tokens=65536),
             M("gemini/gemini-3.1-pro-preview", "gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)", 2.00, 12.00, 1048576, ["smart", UNVERIFIED], supports_vision=True, supports_reasoning=True, max_output_tokens=65536),
         ]),
    dict(slug="deepseek", name="DeepSeek", kind="deepseek", enabled=False,
         description="DeepSeek's own API. Peak-hour prices from api-docs.deepseek.com (off-peak is half).",
         models=[
             M("deepseek/deepseek-flash", "deepseek-flash", "DeepSeek Flash (V4.1-Flash-1017)", 0.30, 1.20, 1000000, supports_reasoning=True, max_output_tokens=393216),
             M("deepseek/deepseek-v4-pro", "deepseek-v4-pro", "DeepSeek V4 Pro", 1.32, 3.96, 1000000, supports_reasoning=True, max_output_tokens=393216),
         ]),
    dict(slug="deepinfra", name="DeepInfra", kind="deepinfra", enabled=False,
         description="Open-weight models incl. Whisper and Kokoro TTS. Use Sync models to import the full list with prices.",
         models=[
             STT("deepinfra/whisper-large-v3-turbo", "openai/whisper-large-v3-turbo", "Whisper large v3 turbo (DeepInfra)", 0.0002, [UNVERIFIED]),
             TTS("deepinfra/kokoro-82m", "hexgrad/Kokoro-82M", "Kokoro 82M (DeepInfra)", 0.62, KOKORO_VOICES, "af_heart", [UNVERIFIED]),
         ]),
    dict(slug="fireworks", name="Fireworks AI", kind="fireworks", enabled=False,
         description="Fast open-weight inference; Whisper runs on separate audio hosts (set per model). Sync models imports the chat list.",
         models=[
             STT("fireworks/whisper-v3", "whisper-v3", "Whisper v3 (Fireworks)", 0.0015, [UNVERIFIED], api_base="https://audio-prod.api.fireworks.ai/v1"),
             STT("fireworks/whisper-v3-turbo", "whisper-v3-turbo", "Whisper v3 turbo (Fireworks)", 0.0009, [UNVERIFIED], api_base="https://audio-turbo.api.fireworks.ai/v1"),
         ]),
    dict(slug="cerebras", name="Cerebras", kind="cerebras", enabled=False, models=[],
         description="Very fast open-weight chat models. Add a key, then Sync models."),
    dict(slug="sambanova", name="SambaNova", kind="sambanova", enabled=False, models=[],
         description="Fast open-weight chat models (and Whisper on some plans). Add a key, then Sync models."),
    dict(slug="hyperbolic", name="Hyperbolic", kind="hyperbolic", enabled=False, models=[],
         description="Open-weight models at low prices. Add a key, then Sync models."),
    dict(slug="nebius", name="Nebius AI Studio", kind="nebius", enabled=False, models=[],
         description="Open-weight models on Nebius. Check the base URL in your Nebius console (it may differ by region/product), then Sync models."),
    dict(slug="novita", name="Novita AI", kind="novita", enabled=False, models=[],
         description="Open-weight models, OpenAI-compatible endpoint. Add a key, then Sync models."),
    dict(slug="baseten", name="Baseten", kind="baseten", enabled=False, models=[],
         description="Baseten Model APIs (OpenAI-compatible). Add a key, then Sync models."),
    dict(slug="vercel", name="Vercel AI Gateway", kind="vercel", enabled=False, api_base="https://ai-gateway.vercel.sh/v1",
         description="Hundreds of models from many labs through one key. Sync models imports the full list with prices from the gateway's /v1/models.", models=[]),
    dict(slug="pipeline", name="Lora voice pipeline", kind="pipeline", enabled=True,
         description="Open-weight realtime voice: speech-to-text, a chat model and text-to-speech, served at /v1/realtime with the OpenAI Realtime protocol. Upstream ID = \"<stt> | <chat> | <tts>\" (any gateway model names or aliases).",
         models=[
             {**AUDIO("realtime", "lora-talk", "Lora talk (Whisper + chat + Kokoro)", 0, 0, 0, 0, None, KOKORO_VOICES, "af_heart"),
              "upstream_id": "whisper-large-v3 | deepseek-v4.1-flash | kokoro-82m"},
         ]),
    dict(slug="local", name="Local / Ollama", kind="openai_compatible", enabled=False, api_base="http://host.docker.internal:11434/v1",
         description="Any local OpenAI-compatible server (Ollama, vLLM, LM Studio, speaches). Set the base URL; Ollama ignores the key, so enter any value such as 'ollama'. Model IDs are whatever you pulled.",
         models=[
             M("local/llama3.2", "llama3.2", "Llama 3.2 (local)", 0, 0, 131072, [UNVERIFIED]),
             M("local/qwen3", "qwen3", "Qwen3 (local)", 0, 0, 40960, [UNVERIFIED]),
         ]),
]

# bump when CATALOG / DEFAULT_ALIASES gain entries; existing installs get the new providers, models and aliases once
CATALOG_VERSION = 3

DEFAULT_ALIASES = [
    ("default", "deepseek-v4.1-flash-1017", "General-purpose default model"),
    ("fast", "glm-5.3-flash", "Cheapest / lowest latency"),
    ("smart", "muse-spark-open", "Most capable model"),
    ("vision", "nemotron-3.5-super-vl", "Image understanding"),
    ("stt", "whisper-large-v3", "Speech to text (open-weight Whisper)"),
    ("listener", "parakeet-tdt-0.6b-v3", "Transcription example (declare audio = \"transcription\")"),
    ("tts", "kokoro-82m", "Text to speech (open-weight Kokoro)"),
    ("talk", "lora-talk", "Realtime voice conversation (open-weight pipeline)"),
    ("stt-openai", "openai/gpt-4o-mini-transcribe", "Speech to text (OpenAI)"),
    ("tts-openai", "openai/gpt-4o-mini-tts", "Text to speech (OpenAI)"),
    ("talk-openai", "openai/gpt-realtime", "Realtime voice conversation (OpenAI)"),
]
