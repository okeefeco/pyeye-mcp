"""Security layer (LEAF): permission and amount validation.

PLANT 2 lives here (validation_placement, HIGH stakes / LOW blast). This is a
LEAF module -- imported by ~nothing in app/ -- yet it handles
security/correctness-sensitive input. Its validation is in the WRONG place:
scattered through the core logic and missing at the boundary, unlike the rest
of the app which validates at the boundary.
"""
