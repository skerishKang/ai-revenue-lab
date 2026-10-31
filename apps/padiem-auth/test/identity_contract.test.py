"""Synthetic data against the real identity authority implementation, not production."""
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'packages/padiem-control-plane/tests'))
from test_lovetree_identity_registration import authority, run, B62, LOVETREE


def link(do, product, uid, subject):
    return run(do.resolve_or_create_product_link({
        'product_id': product, 'product_user_id': uid,
        'auth_provider': 'google', 'provider_subject': subject,
    }))


def test_existing_handoff_and_new_worker_preserve_workspace_owner():
    subject = 'synthetic-google-subject'
    uid = 'usr_' + hashlib.sha256(('google:' + subject).encode()).hexdigest()[:32]
    source = "import {googleProductUserId} from './apps/padiem-auth/worker.mjs'; console.log(await googleProductUserId('synthetic-google-subject'));"
    actual = subprocess.check_output(['node', '--input-type=module', '-e', source], cwd=ROOT, text=True).strip()
    assert actual == uid
    do = authority()
    chat = link(do, B62, uid, subject)
    old = link(do, LOVETREE, uid, subject)
    new = link(do, LOVETREE, actual, subject)
    assert chat['ok'] and old['ok'] and new['ok']
    assert chat['link']['canonical_subject_id'] == old['link']['canonical_subject_id'] == new['link']['canonical_subject_id']
    assert new['link']['product_user_id'] == uid


if __name__ == '__main__':
    test_existing_handoff_and_new_worker_preserve_workspace_owner()
    print('identity contract: PASS')
