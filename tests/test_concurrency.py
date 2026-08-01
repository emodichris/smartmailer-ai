import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.tenant_store import TenantStore


class TenantStoreConcurrencyTests(unittest.TestCase):
    def test_five_users_can_write_and_read_concurrently(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            store = TenantStore(Path(temp_directory) / "concurrency.sqlite3")

            def create_workspace(user_number: int):
                tenant, api_key = store.create_tenant(
                    f"Concurrent workspace {user_number}",
                    f"user-{user_number}",
                )
                store.save_contacts(
                    tenant["id"],
                    [{"email": f"user{user_number}@example.com", "first_name": f"User {user_number}"}],
                )
                return tenant, api_key

            with ThreadPoolExecutor(max_workers=5) as executor:
                workspaces = list(executor.map(create_workspace, range(5)))

            self.assertEqual(len(workspaces), 5)
            for tenant, api_key in workspaces:
                self.assertEqual(store.tenant_for_api_key(api_key)["id"], tenant["id"])
                self.assertEqual(len(store.list_contacts(tenant["id"])), 1)


if __name__ == "__main__":
    unittest.main()
