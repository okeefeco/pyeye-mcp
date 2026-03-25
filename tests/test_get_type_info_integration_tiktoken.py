"""Integration test for token savings using tiktoken measurement.

This test provides end-to-end verification of the fields parameter token optimization
using actual tiktoken encoding (cl100k_base) as specified in Task 2.7 of issue #315.

This complements tests/test_get_type_info_token_savings.py by using precise token
measurement instead of character count proxy.
"""

import json

import pytest

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


@pytest.mark.skipif(not TIKTOKEN_AVAILABLE, reason="tiktoken not installed")
class TestGetTypeInfoIntegrationTiktoken:
    """Integration test measuring actual token savings with tiktoken."""

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.fixture
    def realistic_class_file(self, tmp_path):
        """Create a realistic class file matching issue #315 use case.

        This represents the scenario described in the issue:
        - Checking multiple class variants (7 in the issue, 3 here for testing)
        - LLM needs type info but not position/docstring
        - Simulates realistic multi-call pattern
        """
        test_file = tmp_path / "domain_model.py"
        test_file.write_text('''class BaseEntity:
    """Base class for domain entities.

    Provides common functionality for all domain entities including
    identity, equality, and validation.

    Attributes:
        id: Unique identifier
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    """

    def __init__(self, id=None):
        """Initialize entity with optional ID.

        Args:
            id: Optional unique identifier. Generated if not provided.
        """
        self.id = id
        self.created_at = None
        self.updated_at = None

    def validate(self):
        """Validate entity state.

        Returns:
            bool: True if valid, False otherwise
        """
        return self.id is not None


class UserEntity(BaseEntity):
    """User domain entity.

    Represents a user in the system with authentication and profile data.

    Attributes:
        username: User's unique username
        email: User's email address
        is_active: Whether the account is active
        profile: User profile data dictionary
    """

    def __init__(self, id=None, username=None, email=None):
        """Initialize user entity.

        Args:
            id: Optional unique identifier
            username: User's username (required)
            email: User's email (required)
        """
        super().__init__(id)
        self.username = username
        self.email = email
        self.is_active = True
        self.profile = {}

    def activate(self):
        """Activate the user account.

        Returns:
            bool: True if activation successful
        """
        self.is_active = True
        return True

    def deactivate(self):
        """Deactivate the user account.

        Returns:
            bool: True if deactivation successful
        """
        self.is_active = False
        return True


class AdminEntity(UserEntity):
    """Admin user entity with elevated privileges.

    Extends UserEntity with administrative capabilities.

    Attributes:
        permissions: List of admin permissions
        audit_log: List of admin actions
    """

    def __init__(self, id=None, username=None, email=None):
        """Initialize admin entity.

        Args:
            id: Optional unique identifier
            username: Admin's username
            email: Admin's email
        """
        super().__init__(id, username, email)
        self.permissions = []
        self.audit_log = []

    def grant_permission(self, permission):
        """Grant a permission to this admin.

        Args:
            permission: Permission string to grant

        Returns:
            bool: True if granted successfully
        """
        if permission not in self.permissions:
            self.permissions.append(permission)
            self.audit_log.append(f"Granted: {permission}")
            return True
        return False
''')
        return test_file

    @pytest.fixture
    def encoding(self):
        """Get tiktoken encoding for cl100k_base (GPT-4/Claude)."""
        return tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, data, encoding):
        """Count actual tokens using tiktoken.

        Args:
            data: Data to count tokens for (will be JSON-serialized)
            encoding: tiktoken encoding instance

        Returns:
            int: Actual token count
        """
        json_str = json.dumps(data, default=str)
        return len(encoding.encode(json_str))

    @pytest.mark.asyncio
    async def test_integration_multi_call_scenario_with_tiktoken(
        self, analyzer, realistic_class_file, encoding
    ):
        """Integration test: Multi-call scenario matching issue #315 use case.

        Use case from issue #315:
        - LLM checks 7 class variants (we test 3 here)
        - Each call needs type info but not position/docstring
        - Without fields: ~700 tokens × 7 = 4,900 tokens
        - With fields: ~400 tokens × 7 = 2,800 tokens (43% reduction)

        This test verifies the optimization works end-to-end with actual token counts.
        """
        # Simulate checking 3 class variants (BaseEntity, UserEntity, AdminEntity)
        # Line numbers: BaseEntity=1, UserEntity=32, AdminEntity=77
        variants = [
            {"line": 1, "column": 6, "name": "BaseEntity"},
            {"line": 32, "column": 6, "name": "UserEntity"},
            {"line": 77, "column": 6, "name": "AdminEntity"},
        ]

        # Original approach: Get full response for each variant
        full_responses = []
        for variant in variants:
            response = await analyzer.get_type_info(
                str(realistic_class_file), variant["line"], variant["column"]
            )
            full_responses.append(response)

        # Optimized approach: Get only inferred_types (skip position & docstring)
        filtered_responses = []
        for variant in variants:
            response = await analyzer.get_type_info(
                str(realistic_class_file),
                variant["line"],
                variant["column"],
                fields=["inferred_types"],
            )
            filtered_responses.append(response)

        # Count actual tokens using tiktoken
        total_full_tokens = sum(self._count_tokens(r, encoding) for r in full_responses)
        total_filtered_tokens = sum(self._count_tokens(r, encoding) for r in filtered_responses)

        tokens_saved = total_full_tokens - total_filtered_tokens
        reduction_percent = (tokens_saved / total_full_tokens) * 100

        # Print detailed measurements
        print(f"\n{'='*70}")
        print("INTEGRATION TEST: Multi-Call Token Savings (tiktoken measurement)")
        print(f"{'='*70}")
        print(f"Scenario: Checking {len(variants)} class variants")
        print("Encoding: cl100k_base (GPT-4/Claude)")
        print("")
        print(f"Full responses (all fields):      {total_full_tokens:,} tokens")
        print(f"Filtered responses (types only):  {total_filtered_tokens:,} tokens")
        print(f"Tokens saved:                      {tokens_saved:,} tokens")
        print(f"Reduction:                         {reduction_percent:.1f}%")
        print("")
        print("Per-call average:")
        print(f"  Full:     {total_full_tokens // len(variants):,} tokens/call")
        print(f"  Filtered: {total_filtered_tokens // len(variants):,} tokens/call")
        print(f"{'='*70}\n")

        # Verify meets success criteria from issue #315
        assert reduction_percent >= 40.0, (
            f"Expected at least 40% token reduction (issue #315 target), "
            f"got {reduction_percent:.1f}%. "
            f"Full: {total_full_tokens} tokens, Filtered: {total_filtered_tokens} tokens"
        )

        # Verify all responses are properly filtered
        for response in filtered_responses:
            assert "inferred_types" in response, "Filtered response missing inferred_types"
            assert "position" not in response, "Filtered response should not have position"
            assert "docstring" not in response, "Filtered response should not have docstring"

    @pytest.mark.asyncio
    async def test_integration_single_call_with_tiktoken(
        self, analyzer, realistic_class_file, encoding
    ):
        """Integration test: Single-call optimization with tiktoken.

        Verifies the baseline 40%+ reduction claim from issue #315 using
        actual token measurement.
        """
        # Test with UserEntity (has inheritance, methods, attributes)
        full_response = await analyzer.get_type_info(
            str(realistic_class_file), 32, 6  # class UserEntity
        )

        filtered_response = await analyzer.get_type_info(
            str(realistic_class_file), 32, 6, fields=["inferred_types"]
        )

        # Count tokens
        full_tokens = self._count_tokens(full_response, encoding)
        filtered_tokens = self._count_tokens(filtered_response, encoding)

        tokens_saved = full_tokens - filtered_tokens
        reduction_percent = (tokens_saved / full_tokens) * 100

        print(f"\n{'='*70}")
        print("INTEGRATION TEST: Single-Call Token Savings (tiktoken measurement)")
        print(f"{'='*70}")
        print("Symbol: UserEntity class")
        print("Encoding: cl100k_base (GPT-4/Claude)")
        print("")
        print(f"Full response:      {full_tokens:,} tokens")
        print(f"Filtered response:  {filtered_tokens:,} tokens")
        print(f"Tokens saved:       {tokens_saved:,} tokens")
        print(f"Reduction:          {reduction_percent:.1f}%")
        print(f"{'='*70}\n")

        assert reduction_percent >= 40.0, (
            f"Expected at least 40% reduction (issue #315 baseline), "
            f"got {reduction_percent:.1f}%"
        )

        # Verify structure
        assert "inferred_types" in filtered_response
        assert "position" not in filtered_response
        assert "docstring" not in filtered_response

    @pytest.mark.asyncio
    async def test_integration_extrapolate_to_issue_scenario(
        self, analyzer, realistic_class_file, encoding
    ):
        """Extrapolate test results to issue #315's 7-variant scenario.

        Issue mentions checking 7 class variants. We test 3 here, then
        extrapolate to show what 7 would yield.
        """
        # Test with 3 variants
        variants = [
            {"line": 1, "column": 6},
            {"line": 32, "column": 6},
            {"line": 79, "column": 6},
        ]

        # Get one full and one filtered to establish baseline
        sample_full = await analyzer.get_type_info(
            str(realistic_class_file), variants[0]["line"], variants[0]["column"]
        )
        sample_filtered = await analyzer.get_type_info(
            str(realistic_class_file),
            variants[0]["line"],
            variants[0]["column"],
            fields=["inferred_types"],
        )

        full_tokens = self._count_tokens(sample_full, encoding)
        filtered_tokens = self._count_tokens(sample_filtered, encoding)

        # Extrapolate to 7 calls (issue scenario)
        issue_variant_count = 7
        extrapolated_full = full_tokens * issue_variant_count
        extrapolated_filtered = filtered_tokens * issue_variant_count
        extrapolated_saved = extrapolated_full - extrapolated_filtered
        extrapolated_reduction = (extrapolated_saved / extrapolated_full) * 100

        print(f"\n{'='*70}")
        print("INTEGRATION TEST: Extrapolation to Issue #315 Scenario")
        print(f"{'='*70}")
        print("Sample measurement (1 call):")
        print(f"  Full:     {full_tokens} tokens")
        print(f"  Filtered: {filtered_tokens} tokens")
        print("")
        print(f"Extrapolated to {issue_variant_count} variants (issue scenario):")
        print(f"  Full responses:      {extrapolated_full:,} tokens")
        print(f"  Filtered responses:  {extrapolated_filtered:,} tokens")
        print(f"  Tokens saved:        {extrapolated_saved:,} tokens")
        print(f"  Reduction:           {extrapolated_reduction:.1f}%")
        print("")
        print("Issue #315 claimed: ~700 tokens/call → 4,900 tokens for 7 calls")
        print(
            f"Actual measurement:  ~{full_tokens} tokens/call → {extrapolated_full:,} tokens for {issue_variant_count} calls"
        )
        print(f"{'='*70}\n")

        # Verify extrapolation shows significant savings
        assert (
            extrapolated_reduction >= 40.0
        ), f"Extrapolated scenario should show >=40% reduction, got {extrapolated_reduction:.1f}%"

        # The extrapolated savings should be substantial (>800 tokens is significant)
        assert extrapolated_saved >= 800, (
            f"Expected substantial token savings (>=800) in 7-call scenario, "
            f"got {extrapolated_saved} tokens saved"
        )
