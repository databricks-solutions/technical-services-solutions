from migration_accelerator.discovery.lineage import get_lineage


def lineage_api() -> str:
    return get_lineage()
