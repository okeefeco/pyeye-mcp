"""Service layer: business logic on top of handlers + core.

PLANT 5 lives across these modules (ambiguous result-shape fork): the SAME
conceptual "operation result" is returned as a plain dict, a @dataclass, and
a tuple by different services. There is no documented decision and no stdlib
idiom that settles it -> the correct auditor output is NO recommendation.
"""
