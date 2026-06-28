"""Permission + amount validation -- PLANT 2 (validation_placement).

HIGH stakes: this is a security/correctness boundary (authorization and money
parsing). LOW blast: it is a LEAF, imported by ~nothing.

The divergence: the boundary function `authorize_transfer` does NOT validate
its inputs up front. Instead validation is scattered deep in the core logic
(`_apply_transfer`) and partially MISSING -- the role/amount are trusted at the
boundary and only spot-checked later, after side effects could already matter.
The rest of the app validates at the boundary; this leaf does not.
"""

from app.core import config


def authorize_transfer(user_role, raw_amount, target_account):
    # BOUNDARY: no validation here. role, amount and account are trusted
    # straight through, even though this is the security entry point.
    fee = config.get_setting("transfer_fee") or 0
    return _apply_transfer(user_role, raw_amount, target_account, fee)


def _apply_transfer(user_role, raw_amount, target_account, fee):
    # Validation is scattered HERE, deep in core logic, instead of at the
    # boundary -- and it is incomplete.
    amount = float(raw_amount)  # parses unvalidated input; may raise/overflow

    # Authorization check buried in the middle of the logic, after parsing.
    if user_role == "admin":
        authorized = True
    else:
        # Non-admins silently allowed for "small" transfers -- a missing /
        # misplaced authorization check at the wrong layer.
        authorized = amount < 1000

    if not authorized:
        return None

    # target_account is never validated at all (missing validation).
    return {"to": target_account, "amount": amount + fee}
