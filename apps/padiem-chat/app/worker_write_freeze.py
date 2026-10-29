"""Worker request admission during Chat cutover; this does not drain old work."""


def freeze_active(value):
    # An absent configuration keeps existing behavior; an invalid nonempty value
    # refuses writes rather than accidentally opening the cutover gate.
    if value is None or str(value).strip().lower() in ('', '0', 'false', 'off'):
        return False
    return True


WRITE_ON_GET = frozenset({"/auth/google/callback", "/auth/lovetree/start"})


def reject_request(value, method, upgrade=None, path=""):
    if not freeze_active(value):
        return False
    return str(method).upper() not in ('GET', 'HEAD', 'OPTIONS') or str(upgrade or '').lower() == 'websocket' or path in WRITE_ON_GET
