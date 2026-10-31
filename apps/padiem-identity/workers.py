"""CPython-only host adapter for the identity DO's platform base classes.

Only identity RPC methods are used; Worker fetch and bindings are not hosted.
"""
class DurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


class WorkerEntrypoint:
    pass


class Response:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("Cloudflare response unavailable on CPython")
