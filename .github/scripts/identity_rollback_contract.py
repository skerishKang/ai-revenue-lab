"""Pure validation for identity Worker rollback metadata; no network or values output."""
import re

UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
SHA = re.compile(r'^[0-9a-f]{40}$')
FAIL = 'IDENTITY_ROLLBACK_POSTCHECK=FAIL'


def validate_confirmation(mode, sha, current, target, confirmation):
    if mode != 'rollback_identity_worker' or not SHA.fullmatch(sha) or not UUID.fullmatch(current) or not UUID.fullmatch(target):
        raise ValueError('rollback inputs invalid')
    if current == target or confirmation != f'ROLLBACK_PADIEM_CONTROL_PLANE_IDENTITY_{mode}_{sha}_{current}_{target}':
        raise ValueError('rollback authorization invalid')
    return True


def binding_identity(items):
    if not isinstance(items, list) or not items:
        raise ValueError('binding metadata unavailable')
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']:
            raise ValueError('invalid binding name')
        kind = item.get('type')
        if kind not in {'plain_text', 'secret_text', 'durable_object_namespace', 'service'}:
            raise ValueError('unsupported binding type')
        fields = ('class_name', 'script_name') if kind == 'durable_object_namespace' else ('service', 'environment', 'entrypoint') if kind == 'service' else ()
        result.append((item['name'], kind, tuple(item.get(k) for k in fields)))
    if len({x[0] for x in result}) != len(result):
        raise ValueError('duplicate binding name')
    return sorted(result)


def validate_post(deployments, target, before_bindings, after_bindings):
    try:
        if not isinstance(deployments, list) or not deployments:
            raise ValueError('deployment unavailable')
        versions = deployments[0].get('versions', [])
        if len(versions) != 1 or versions[0].get('version_id') != target or versions[0].get('percentage') != 100:
            raise ValueError('rollback version mismatch')
        if binding_identity(before_bindings) != binding_identity(after_bindings):
            raise ValueError('binding metadata mismatch')
        return True
    except (ValueError, TypeError, AttributeError, KeyError):
        raise ValueError(FAIL) from None
