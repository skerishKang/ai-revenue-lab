"""Direct Google and existing handoff preserve one canonical user."""
import hashlib

from test_lovetree_identity_registration import authority, run, B62, LOVETREE


def _google_link(do, product, user, subject):
    return run(do.resolve_or_create_product_link({
        'product_id': product, 'product_user_id': user,
        'auth_provider': 'google', 'provider_subject': subject,
    }))


def test_direct_google_reuses_existing_handoff_canonical_identity():
    do = authority()
    subject = 'synthetic-google-subject'
    uid = 'usr_' + hashlib.sha256(('google:' + subject).encode()).hexdigest()[:32]
    chat = _google_link(do, B62, uid, subject)
    old_handoff = _google_link(do, LOVETREE, uid, subject)
    direct = _google_link(do, LOVETREE, uid, subject)
    assert chat['ok'] and old_handoff['ok'] and direct['ok']
    assert chat['link']['canonical_subject_id'] == old_handoff['link']['canonical_subject_id']
    assert direct['link']['canonical_subject_id'] == old_handoff['link']['canonical_subject_id']
    assert direct['link']['product_user_id'] == uid
