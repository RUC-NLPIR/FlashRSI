from contextvars import ContextVar
sink = ContextVar('hermes_compaction_event_sink', default=None)

def publish_micro(*args, **kwargs):
    callback = sink.get()
    if callback:
        callback({'type': 'micro_compaction', 'args': args, **kwargs})
