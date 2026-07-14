"""Maps a BYOK (api_key, api_base, default_model) credential onto the env
vars Claude Code's bundled Anthropic SDK actually reads.

Shared by ExternalAgentBroker._apply_llm_config_env (control-plane native
run path) and WorkerRuntime (VM/worker relay path) so the auth-header-scheme
choice (ANTHROPIC_API_KEY vs ANTHROPIC_AUTH_TOKEN) lives in exactly one place.
"""

from __future__ import annotations


def anthropic_env_for(api_key: str, api_base: str, default_model: str = "") -> dict[str, str]:
    """Claude Code authenticates differently depending on which env var carries
    the key: ANTHROPIC_API_KEY is sent as the x-api-key header (what official
    first-party keys expect), while ANTHROPIC_AUTH_TOKEN is sent as
    Authorization: Bearer (what third-party Claude-compatible relays expect).
    Sending both makes the SDK emit both headers and the request is rejected
    outright, so a custom api_base (i.e. pointed at a relay, not
    api.anthropic.com) always prefers ANTHROPIC_AUTH_TOKEN.
    """
    env: dict[str, str] = {}
    api_key = (api_key or "").strip()
    api_base = (api_base or "").strip()
    default_model = (default_model or "").strip()

    if api_base:
        env["ANTHROPIC_BASE_URL"] = api_base
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if default_model:
            model_name = default_model.split("/", 1)[1] if "/" in default_model else default_model
            if model_name:
                env["ANTHROPIC_MODEL"] = model_name
    elif api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    return env
