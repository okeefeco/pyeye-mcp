"""#624 goto-policy fixture: a try/except fallback binding (two live definitions)."""

try:
    from gp._fast import VALUE, helper
except ImportError:  # pragma: no cover - fallback binding
    from gp._slow import VALUE, helper

__all__ = ["VALUE", "helper"]
