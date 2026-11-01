"""Explicit runtime boundaries: no Hermes installation, HOME or ambient profile access."""
from contextvars import ContextVar

secrets = ContextVar('hermes_compression_secrets', default=())
compression_config = ContextVar('hermes_compression_config', default={})
TODO_INJECTION_HEADER = '[Your active task list was preserved across context compression]'

def redact_registered_vault_values(text):
    for value in sorted(secrets.get(), key=len, reverse=True):
        if value:
            text = text.replace(value, '«redacted-vault-secret»')
    return text

def _redact_enabled():
    return True

def trim_memory(**kwargs):
    return None

def get_provider_profile(provider):
    return None

def _nous_inference_env_override():
    return None
