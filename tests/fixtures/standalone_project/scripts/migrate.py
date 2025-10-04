"""Migration script.

This standalone script uses MyClass for data migration.
"""

from mypackage import MyClass


class DataMigrator:
    """Handles data migration."""

    def __init__(self):
        """Initialize migrator."""
        self.processor = MyClass("Migrator")

    def migrate(self):
        """Run migration."""
        print(self.processor.greet())
        print("Migration complete!")


if __name__ == "__main__":
    migrator = DataMigrator()
    migrator.migrate()
