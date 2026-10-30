import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("staging_config", Path(__file__).parents[1] / "scripts/staging_config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DB = module.STAGING_DB
CHAT = "https://padiem-chat-staging.example.workers.dev"
QUEUE = "https://queue-staging.padiem.net"

class StagingConfigTest(unittest.TestCase):
    def test_staging_is_explicit_and_no_production_bindings(self):
        config = module.make_config(DB, CHAT, QUEUE)
        self.assertEqual(config["name"], "padiem-chat-staging")
        self.assertEqual(config["d1_databases"][0]["database_id"], DB)
        self.assertEqual(config["vars"]["PADIEM_CHAT_SHARED_LOGIN_ENABLED"], "false")
        self.assertEqual(config["vars"]["PC_QUEUE_BACKEND"], "d1")
        self.assertFalse({"routes", "services", "r2_buckets", "secrets_store_secrets"} & config.keys())

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
