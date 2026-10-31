import importlib.util
from pathlib import Path
import unittest
import tomllib

spec = importlib.util.spec_from_file_location("staging_config", Path(__file__).parents[1] / "scripts/staging_config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DB = module.STAGING_DB
CHAT = "https://padiem-chat-staging.charliekant.workers.dev"
QUEUE = "https://queue-staging.padiem.net"

class StagingConfigTest(unittest.TestCase):
    def test_staging_is_explicit_and_no_production_bindings(self):
        config = module.make_config(DB, CHAT, QUEUE)
        self.assertEqual(config["name"], "padiem-chat-staging")
        self.assertEqual(config["d1_databases"][0]["database_id"], DB)
        self.assertEqual(config["vars"]["PADIEM_CHAT_SHARED_LOGIN_ENABLED"], "true")
        self.assertEqual(config["vars"]["PC_QUEUE_BACKEND"], "d1")
        self.assertEqual(config["vars"]["PADIEM_CHAT_SHARED_AUTH_CLIENT_ID"], "b62-staging")
        self.assertEqual(config["vars"]["PADIEM_CHAT_PUBLIC_BASE_URL"], CHAT)
        self.assertFalse({"routes", "services", "r2_buckets", "secrets_store_secrets"} & config.keys())

    def test_production_config_is_unchanged_and_login_defaults_off(self):
        manifest = Path(__file__).parents[1] / "wrangler.toml"
        before = manifest.read_bytes()
        config = module.make_config(DB, CHAT, QUEUE)
        self.assertEqual(manifest.read_bytes(), before)
        production_vars = tomllib.loads(before.decode("utf-8")).get("vars", {})
        self.assertNotEqual(production_vars.get("PADIEM_CHAT_SHARED_LOGIN_ENABLED", "false").lower(), "true")
        self.assertEqual(config["vars"]["PADIEM_CHAT_SHARED_LOGIN_ENABLED"], "true")

    def test_reject_production_or_invalid_destinations(self):
        for database, chat, queue in [
            (module.PRODUCTION_DB, CHAT, QUEUE), ("", CHAT, QUEUE), ("12345678-1234-1234-1234-123456789abc", CHAT, QUEUE),
            (DB, "https://chat.padiem.net", QUEUE),
            (DB, CHAT, "https://queue.padiem.net"),
            (DB, CHAT, QUEUE + "/path"),
        ]:
            with self.subTest(database=database, chat=chat, queue=queue), self.assertRaises(ValueError):
                module.make_config(database, chat, queue)

if __name__ == "__main__":
    unittest.main()
