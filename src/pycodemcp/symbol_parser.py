"""Parser for compound Python symbols like Class.method or module.Class.method."""

import re


def is_compound_symbol(name: str) -> bool:
    """Check if a symbol name contains dots (is compound).

    Args:
        name: Symbol name to check

    Returns:
        True if the symbol contains dots (compound), False otherwise

    Examples:
        >>> is_compound_symbol("Model.__init__")
        True
        >>> is_compound_symbol("simple_function")
        False
    """
    return "." in name


def parse_compound_symbol(name: str) -> tuple[list[str], bool]:
    """Parse a compound symbol into its components.

    Args:
        name: Symbol name to parse (e.g., "Model.__init__", "module.Class.method")

    Returns:
        Tuple of (components list, is_valid bool)

    Examples:
        >>> parse_compound_symbol("Model.__init__")
        (['Model', '__init__'], True)
        >>> parse_compound_symbol("module.Class.method")
        (['module', 'Class', 'method'], True)
        >>> parse_compound_symbol("Model..method")
        ([], False)
    """
    # Check for invalid patterns
    if not name or name.startswith(".") or name.endswith(".") or ".." in name:
        return [], False

    # Split by dots
    components = name.split(".")

    # Validate each component
    if not all(components):  # Check for empty components
        return [], False

    # Validate that each component is a valid Python identifier
    if not all(validate_symbol_component(comp) for comp in components):
        return [], False

    return components, True


def validate_symbol_component(component: str) -> bool:
    """Validate that a single symbol component follows Python naming rules.

    Args:
        component: Single component of a symbol (e.g., "Model", "__init__", "method")

    Returns:
        True if the component is a valid Python identifier

    Examples:
        >>> validate_symbol_component("Model")
        True
        >>> validate_symbol_component("__init__")
        True
        >>> validate_symbol_component("123invalid")
        False
    """
    if not component:
        return False

    # Python identifier pattern: starts with letter or underscore,
    # followed by letters, digits, or underscores
    pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    return bool(re.match(pattern, component))


def get_parent_and_member(components: list[str]) -> tuple[str, str]:
    """Split components into parent and member parts.

    For a compound symbol, returns the parent (everything except the last part)
    and the member (the last part).

    Args:
        components: List of symbol components

    Returns:
        Tuple of (parent_path, member_name)

    Examples:
        >>> get_parent_and_member(["Model", "__init__"])
        ('Model', '__init__')
        >>> get_parent_and_member(["module", "Class", "method"])
        ('module.Class', 'method')
    """
    if len(components) < 2:
        raise ValueError("Need at least 2 components for parent/member split")

    parent = ".".join(components[:-1])
    member = components[-1]
    return parent, member


def classify_symbol_type(components: list[str]) -> str:
    """Classify the type of compound symbol based on naming patterns.

    Args:
        components: List of symbol components

    Returns:
        String indicating the likely symbol type

    Examples:
        >>> classify_symbol_type(["Model", "__init__"])
        'class_constructor'
        >>> classify_symbol_type(["module", "function"])
        'module_function'
    """
    if not components:
        return "unknown"

    last = components[-1]

    # Check for special methods
    if last == "__init__":
        return "class_constructor"
    elif last.startswith("__") and last.endswith("__"):
        return "magic_method"
    elif last.startswith("_"):
        return "private_member"

    # Check based on naming conventions
    if len(components) == 2:
        first = components[0]
        # If first component starts with uppercase, likely a class
        if first and first[0].isupper():
            return "class_member"
        else:
            return "module_function"
    elif len(components) > 2:
        # Likely module.Class.method or similar
        return "qualified_member"

    return "simple_member"
