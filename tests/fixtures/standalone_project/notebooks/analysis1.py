"""Notebook-style analysis script.

This is a standalone script that uses MyClass from the mypackage module.
"""

from mypackage.models import MyClass, helper_function


def run_analysis():
    """Run some analysis using MyClass."""
    obj = MyClass("Analysis")
    print(obj.greet())

    result = helper_function(42)
    print(f"Result: {result}")


if __name__ == "__main__":
    run_analysis()
