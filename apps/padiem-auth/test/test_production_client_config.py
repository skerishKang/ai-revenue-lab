import json
import pathlib
import tomllib
import unittest

class AuthClientConfigTest(unittest.TestCase):
    def test_lovetree_callbacks_and_public_keys(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text())
        client = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])['lovetree-4-0']
        self.assertNotIn('profile_claims', client)
        self.assertEqual(set(client['redirect_uris']), {
            'https://lovetree-4-0.pages.dev/auth/callback',
            'https://ai-astra4-preview-auth-callb.lovetree-4-0.pages.dev/auth/callback',
            'https://lovetree.padiem.net/auth/callback',
        })
        keys = client['jwks']['keys']
        self.assertEqual(len(keys), 2)
        self.assertEqual(len({key['kid'] for key in keys}), 2)
        self.assertTrue(all(key.get('kty') == 'EC' and key.get('crv') == 'P-256' and 'd' not in key for key in keys))


    def test_b62_matches_public_production_snapshot_6bb56bcf(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text(encoding='utf-8'))
        clients = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])
        # Public b62 fields read from deployed plain_text version 6bb56bcf.
        expected = {
            'id': 'b62',
            'redirect_uris': [
                'https://chat.padiem.net/_test/auth/account-comparison/callback',
                'https://chat.padiem.net/auth/shared/callback',
            ],
            'jwks': {'keys': [
                {
                    'kty': 'EC', 'crv': 'P-256',
                    'x': 'Fxm4tj33RhnExqImO8jYVT-o4WL3GuhSQ2XE3M77Apg',
                    'y': '0atl60nlUhdPeWcd0LGBICEFmXqeB7nAIQhZFaVT6Jg',
                    'kid': 'b62-42c57a6725c907f7f3cf', 'alg': 'ES256', 'use': 'sig',
                },
                {
                    'kty': 'EC', 'crv': 'P-256',
                    'x': 'UArI-7kWK28QEWtpXb6sNzapK4H2faShz9ryQQuCpAs',
                    'y': '43lklNmEhpaARWNss_HwCPNupm0lu3eSZncBp-4qZnA',
                    'kid': 'b62-com2-2cc5a6a0b3f010ded2e9', 'alg': 'ES256', 'use': 'sig',
                },
            ]},
        }
        self.assertEqual(clients['b62'], expected)
        self.assertEqual(len({key['kid'] for key in clients['b62']['jwks']['keys']}), 2)
        for key in clients['b62']['jwks']['keys']:
            self.assertEqual(set(key), {'kty', 'crv', 'x', 'y', 'kid', 'alg', 'use'})
            self.assertNotIn('d', key)
        self.assertEqual(
            clients['b62-staging']['profile_claims'],
            ['email', 'email_verified', 'name', 'picture'],
        )


if __name__ == '__main__':
    unittest.main()


class BookAiClientConfigTest(unittest.TestCase):
    def test_b61_bookai_callback_and_public_key_only(self):
        config = tomllib.loads((pathlib.Path(__file__).parents[1] / 'wrangler.toml').read_text(encoding='utf-8'))
        client = json.loads(config['vars']['PADIEM_AUTH_CLIENTS'])['b61']
        self.assertEqual(client['redirect_uris'], ['https://bookai.padiem.net/auth/callback'])
        keys = client['jwks']['keys']
        self.assertEqual([key['kid'] for key in keys], ['b61-bookai-6affe050'])
        self.assertTrue(all(key.get('kty') == 'EC' and key.get('crv') == 'P-256' and 'd' not in key for key in keys))

