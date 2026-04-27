from librariarr.inventory_snapshot import reset_inventory_snapshot_store


def pytest_runtest_teardown(item, nextitem):
    reset_inventory_snapshot_store()
