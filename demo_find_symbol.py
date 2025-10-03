#!/usr/bin/env python3
"""Demonstration of the pyeye MCP server's find_symbol capability.

This script shows what the find_symbol tool would return when searching for "Calculator"
in the project. Since we can't directly call the MCP server tools in this environment,
this demonstrates the expected functionality.
"""

import json
from typing import Any

import jedi


def find_symbol_demo(
    name: str, project_path: str = ".", fuzzy: bool = False
) -> list[dict[str, Any]]:
    """Demonstration of the find_symbol tool from the pyeye MCP server.

    This replicates the functionality that would be available via the MCP server's
    find_symbol tool.

    Args:
        name: Symbol name to search for
        project_path: Root path of the project to search
        fuzzy: Whether to use fuzzy matching

    Returns:
        List of symbol locations with file, line, column, and type
    """
    project = jedi.Project(path=project_path)
    results = []

    try:
        print(f"🔍 Searching for symbol '{name}' in project: {project_path}")
        print(f"📊 Fuzzy matching: {'enabled' if fuzzy else 'disabled'}")
        print()

        # Search for the symbol
        search_results = project.search(name, all_scopes=True)

        for result in search_results:
            # Check if fuzzy matching or exact match
            if not fuzzy and result.name != name:
                continue

            symbol_info = {
                "name": result.name,
                "file": str(result.module_path) if result.module_path else None,
                "line": result.line,
                "column": result.column,
                "type": result.type,
                "description": result.description,
                "full_name": result.full_name,
            }
            results.append(symbol_info)

    except Exception as e:
        print(f"❌ Error searching for symbol {name}: {e}")

    return results


def pretty_print_results(results: list[dict[str, Any]]) -> None:
    """Pretty print the search results."""
    if not results:
        print("📭 No symbols found matching the search criteria.")
        return

    print(f"✅ Found {len(results)} symbol(s):")
    print()

    for i, result in enumerate(results, 1):
        print(f"  {i}. Symbol: {result['name']}")
        print(f"     Type: {result['type']}")
        print(f"     File: {result['file']}")
        print(f"     Location: Line {result['line']}, Column {result['column']}")
        print(f"     Description: {result['description']}")
        print(f"     Full name: {result['full_name']}")
        print()


def demonstrate_additional_capabilities() -> None:
    """Demonstrate other capabilities of the pyeye MCP server."""
    print("🚀 Additional PyEye Server Capabilities:")
    print()
    print("1. 📍 goto_definition(file, line, column, project_path)")
    print("   - Navigate to symbol definitions from any position")
    print()
    print("2. 🔗 find_references(file, line, column, project_path)")
    print("   - Find all references to a symbol throughout the project")
    print()
    print("3. 🏷️  get_type_info(file, line, column, project_path)")
    print("   - Get detailed type information and docstrings")
    print()
    print("4. 📦 find_imports(module_name, project_path)")
    print("   - Find all import statements for a specific module")
    print()
    print("5. 📞 get_call_hierarchy(function_name, file, project_path)")
    print("   - Analyze function call relationships (callers and callees)")
    print()
    print("6. 🌳 list_project_structure(project_path, max_depth)")
    print("   - Get organized view of Python project structure")
    print()


if __name__ == "__main__":
    # Demonstrate finding the Calculator symbol
    print("=" * 60)
    print("🧮 PyEye Server Demo")
    print("=" * 60)
    print()

    # Search for Calculator symbol
    results = find_symbol_demo("Calculator", ".")
    pretty_print_results(results)

    print("-" * 60)
    demonstrate_additional_capabilities()

    # Show the raw JSON that would be returned by the MCP server
    print("-" * 60)
    print("📄 Raw JSON Response (as returned by MCP server):")
    print(json.dumps(results, indent=2))
