"""Another analysis script.

This script imports mypackage to show import tracking.
"""

import mypackage


def process_data():
    """Process some data using mypackage."""
    instance = mypackage.MyClass("Data Processor")
    return instance.greet()


if __name__ == "__main__":
    result = process_data()
    print(result)
