"""Compare only binding name/type metadata against an approved baseline.

No binding values are emitted or persisted. This verifier is only one piece of
an update gate; no live read, update, or rollback is performed here.
"""
import json
import hashlib
import sys


def binding_pairs(bindings):
    if not isinstance(bindings, list):
        raise ValueError('bindings missing')
    pairs = []
    for item in bindings:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('type'), str):
            raise ValueError('invalid binding metadata')
        kind = item['type']
        if kind == 'service':
            target = tuple(item.get(k) for k in ('service', 'environment', 'entrypoint'))
            if not target[0]:
                raise ValueError('service target missing')
        elif kind == 'durable_object_namespace':
            target = tuple(item.get(k) for k in ('class_name', 'script_name', 'namespace_id'))
            if not target[0]:
                raise ValueError('durable object class missing')
        elif kind == 'plain_text':
            # Baseline uses a digest. Never emit or persist the raw value here.
            if isinstance(item.get('sha256'), str):
                target = (item['sha256'],)
            elif isinstance(item.get('text'), str):
                target = (hashlib.sha256(item['text'].encode()).hexdigest(),)
            else:
                raise ValueError('plain binding digest missing')
        elif kind == 'secret_text':
            target = ()  # Secret values are never read or compared.
        else:
            raise ValueError('unreviewed binding type')
        pairs.append((item['name'], kind, target))
    if len({pair[0] for pair in pairs}) != len(pairs):
        raise ValueError('duplicate binding name')
    return sorted(pairs)


def verify(settings, baseline):
    if not isinstance(baseline, dict) or baseline.get('status') != 'approved':
        raise ValueError('baseline not approved')
    if not isinstance(settings, dict) or settings.get('success') is not True or not isinstance(settings.get('result'), dict):
        raise ValueError('settings unavailable')
    if binding_pairs(settings['result'].get('bindings')) != binding_pairs(baseline.get('bindings')):
        raise ValueError('binding metadata mismatch')
    return True


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: checker SETTINGS BASELINE')
    with open(sys.argv[1], encoding='utf-8') as f:
        settings = json.load(f)
    with open(sys.argv[2], encoding='utf-8') as f:
        baseline = json.load(f)
    verify(settings, baseline)
    print('binding metadata matches approved baseline')


if __name__ == '__main__':
    main()
