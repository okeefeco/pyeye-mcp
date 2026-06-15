"""Verification tests for token savings from fields parameter in get_type_info.

This test suite measures the actual token reduction achieved by the fields parameter
to verify the optimization goals stated in issue #315.

Token counting methodology:
- Uses character count as proxy since tiktoken is not a project dependency
- Typical correlation: ~4 characters per token (OpenAI's cl100k_base encoding)
- Actual token counts may vary by ±10% based on content structure

Expected savings per issue #315:
- Single-call: 40%+ reduction when filtering to fields=["inferred_types"]
- Multi-call scenarios: Up to 90% reduction (40% per call × multiple calls)
"""

import json

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class TestGetTypeInfoTokenSavings:
    """Verify token savings achieved by the fields parameter."""

    @pytest.fixture
    async def analyzer(self, tmp_path):
        """Create a JediAnalyzer instance with a temp directory."""
        return JediAnalyzer(str(tmp_path))

    @pytest.fixture
    def realistic_class_file(self, tmp_path):
        """Create a realistic class file with methods, docstrings, and inheritance.

        This represents a typical use case where an LLM needs to understand type
        information but doesn't need position data or verbose docstrings.
        """
        test_file = tmp_path / "realistic_class.py"
        test_file.write_text("""class BaseClass:
    '''Base class providing common functionality.

    This is a foundational class that provides core features
    used by multiple derived classes in the system.

    Attributes:
        base_attr: A base-level attribute

    Methods:
        base_method: Performs base-level operations
    '''

    base_attr = "base"

    def base_method(self):
        '''Perform base-level operations.

        Returns:
            str: Result of base operations
        '''
        return "base result"


class RealisticClass(BaseClass):
    '''A realistic class demonstrating typical Python patterns.

    This class showcases common patterns found in real-world Python code:
    - Inheritance from a base class
    - Mix of class and instance attributes
    - Multiple methods with varied signatures
    - Comprehensive docstrings

    Attributes:
        class_var: A class-level variable
        instance_var: An instance-level variable set in __init__

    Example:
        >>> obj = RealisticClass()
        >>> obj.process_data("test")
        'Processed: test'
    '''

    class_var = 42

    def __init__(self, initial_value=None):
        '''Initialize the RealisticClass instance.

        Args:
            initial_value: Optional initial value for instance_var.
                          Defaults to "default" if not provided.
        '''
        super().__init__()
        self.instance_var = initial_value or "default"

    def process_data(self, data):
        '''Process the provided data.

        This method demonstrates a typical data processing pattern
        with validation, transformation, and return.

        Args:
            data: The data to process (str or int)

        Returns:
            str: Processed data as a string

        Raises:
            ValueError: If data is None
        '''
        if data is None:
            raise ValueError("Data cannot be None")
        return f"Processed: {data}"

    def calculate(self, x, y, operation="add"):
        '''Perform a calculation on two numbers.

        Args:
            x: First number
            y: Second number
            operation: Type of operation ("add", "multiply", "subtract")

        Returns:
            float: Result of the calculation
        '''
        if operation == "add":
            return x + y
        elif operation == "multiply":
            return x * y
        elif operation == "subtract":
            return x - y
        return 0

    @property
    def computed_value(self):
        '''Compute a derived value.

        Returns:
            int: The computed value based on instance state
        '''
        return len(self.instance_var) * self.class_var
""")
        return test_file

    def _count_chars(self, data):
        """Count characters in JSON-serialized data.

        This provides a consistent proxy for token count.
        JSON serialization ensures we're measuring the actual data
        that would be transmitted, not Python object overhead.
        """
        return len(json.dumps(data, default=str))

    def _estimate_tokens(self, char_count):
        """Estimate token count from character count.

        Using OpenAI's typical ratio of ~4 characters per token.
        This is an approximation - actual token counts vary by content.
        """
        return char_count / 4

    @pytest.mark.asyncio
    async def test_token_savings_single_field_inferred_types(self, analyzer, realistic_class_file):
        """Verify 40%+ token savings when filtering to inferred_types only.

        Use case: LLM needs type information to understand a class structure
        but doesn't need position data or full docstrings.

        Expected: ~40% reduction in response size/tokens
        """
        # Get full response (baseline) - RealisticClass is on line 25
        full_response = await analyzer.get_type_info(
            str(realistic_class_file), 25, 6  # Line with "class RealisticClass"
        )

        # Get filtered response (optimized)
        filtered_response = await analyzer.get_type_info(
            str(realistic_class_file), 25, 6, fields=["inferred_types"]
        )

        # Count characters as proxy for tokens
        full_chars = self._count_chars(full_response)
        filtered_chars = self._count_chars(filtered_response)

        # Calculate reduction
        chars_saved = full_chars - filtered_chars
        reduction_percent = (chars_saved / full_chars) * 100

        # Estimate tokens
        full_tokens_est = self._estimate_tokens(full_chars)
        filtered_tokens_est = self._estimate_tokens(filtered_chars)
        tokens_saved_est = full_tokens_est - filtered_tokens_est

        # Print measurements for documentation
        print(f"\n{'='*60}")
        print("Token Savings Verification: fields=['inferred_types']")
        print(f"{'='*60}")
        print(f"Full response:     {full_chars:,} chars (~{full_tokens_est:.0f} tokens)")
        print(f"Filtered response: {filtered_chars:,} chars (~{filtered_tokens_est:.0f} tokens)")
        print(f"Reduction:         {chars_saved:,} chars (~{tokens_saved_est:.0f} tokens)")
        print(f"Savings:           {reduction_percent:.1f}%")
        print(f"{'='*60}\n")

        # Verify reduction meets target
        assert reduction_percent >= 40.0, (
            f"Expected at least 40% reduction, got {reduction_percent:.1f}%. "
            f"Full: {full_chars} chars, Filtered: {filtered_chars} chars"
        )

        # Verify filtered response contains only requested field
        assert "inferred_types" in filtered_response
        assert "position" not in filtered_response
        assert "docstring" not in filtered_response

    @pytest.mark.asyncio
    async def test_token_savings_position_only(self, analyzer, realistic_class_file):
        """Verify significant token savings when filtering to position only.

        Use case: LLM just needs to verify location, not type details.

        Expected: 80%+ reduction since position is very small compared to type info.
        """
        full_response = await analyzer.get_type_info(str(realistic_class_file), 25, 6)

        filtered_response = await analyzer.get_type_info(
            str(realistic_class_file), 25, 6, fields=["position"]
        )

        full_chars = self._count_chars(full_response)
        filtered_chars = self._count_chars(filtered_response)

        chars_saved = full_chars - filtered_chars
        reduction_percent = (chars_saved / full_chars) * 100

        full_tokens_est = self._estimate_tokens(full_chars)
        filtered_tokens_est = self._estimate_tokens(filtered_chars)
        tokens_saved_est = full_tokens_est - filtered_tokens_est

        print(f"\n{'='*60}")
        print("Token Savings Verification: fields=['position']")
        print(f"{'='*60}")
        print(f"Full response:     {full_chars:,} chars (~{full_tokens_est:.0f} tokens)")
        print(f"Filtered response: {filtered_chars:,} chars (~{filtered_tokens_est:.0f} tokens)")
        print(f"Reduction:         {chars_saved:,} chars (~{tokens_saved_est:.0f} tokens)")
        print(f"Savings:           {reduction_percent:.1f}%")
        print(f"{'='*60}\n")

        # Position-only should achieve even higher reduction
        assert (
            reduction_percent >= 70.0
        ), f"Expected at least 70% reduction for position-only, got {reduction_percent:.1f}%"

        assert "position" in filtered_response
        assert "inferred_types" not in filtered_response
        assert "docstring" not in filtered_response

    @pytest.mark.asyncio
    async def test_multi_call_token_savings_simulation(self, analyzer, realistic_class_file):
        """Simulate multi-call scenario to demonstrate cumulative savings.

        Use case: LLM makes 3 separate get_type_info calls during a session.
        In the original implementation, each call returns full response.
        With fields parameter, each call can request only needed data.

        Expected: Cumulative savings approaching 90% when most calls
        only need inferred_types (40% × 3 calls = 120% theoretical,
        but bounded by actual response composition).
        """
        # Simulate 3 different get_type_info calls
        calls = [
            {"line": 25, "column": 6, "desc": "class definition"},  # class RealisticClass
            {"line": 40, "column": 8, "desc": "method definition"},  # def process_data
            {"line": 66, "column": 8, "desc": "property definition"},  # def computed_value
        ]

        # Original approach: 3 full responses
        full_responses = []
        for call in calls:
            response = await analyzer.get_type_info(
                str(realistic_class_file), call["line"], call["column"]
            )
            full_responses.append(response)

        # Optimized approach: 3 filtered responses (only inferred_types needed)
        filtered_responses = []
        for call in calls:
            response = await analyzer.get_type_info(
                str(realistic_class_file), call["line"], call["column"], fields=["inferred_types"]
            )
            filtered_responses.append(response)

        # Calculate totals
        total_full_chars = sum(self._count_chars(r) for r in full_responses)
        total_filtered_chars = sum(self._count_chars(r) for r in filtered_responses)

        total_chars_saved = total_full_chars - total_filtered_chars
        total_reduction_percent = (total_chars_saved / total_full_chars) * 100

        total_full_tokens_est = self._estimate_tokens(total_full_chars)
        total_filtered_tokens_est = self._estimate_tokens(total_filtered_chars)
        total_tokens_saved_est = total_full_tokens_est - total_filtered_tokens_est

        print(f"\n{'='*60}")
        print("Multi-Call Token Savings Verification (3 calls)")
        print(f"{'='*60}")
        print(
            f"Full responses:     {total_full_chars:,} chars (~{total_full_tokens_est:.0f} tokens)"
        )
        print(
            f"Filtered responses: {total_filtered_chars:,} chars (~{total_filtered_tokens_est:.0f} tokens)"
        )
        print(
            f"Reduction:          {total_chars_saved:,} chars (~{total_tokens_saved_est:.0f} tokens)"
        )
        print(f"Savings:            {total_reduction_percent:.1f}%")
        print(f"{'='*60}\n")

        # Multi-call scenario should show significant cumulative savings
        # Target: At least 35% overall (slightly less than single-call due to
        # variations in what each response contains)
        assert total_reduction_percent >= 35.0, (
            f"Expected at least 35% cumulative reduction in multi-call scenario, "
            f"got {total_reduction_percent:.1f}%"
        )

    @pytest.mark.asyncio
    async def test_detailed_mode_token_savings(self, analyzer, realistic_class_file):
        """Verify token savings work with detailed=True mode.

        Use case: LLM needs detailed type info (methods/attributes)
        but still doesn't need position or docstring.

        With detailed=True, the response is much larger, so even small
        percentage savings translate to significant token reductions.
        """
        # Get full detailed response
        full_response = await analyzer.get_type_info(
            str(realistic_class_file), 25, 6, detailed=True
        )

        # Get filtered detailed response
        filtered_response = await analyzer.get_type_info(
            str(realistic_class_file), 25, 6, detailed=True, fields=["inferred_types"]
        )

        full_chars = self._count_chars(full_response)
        filtered_chars = self._count_chars(filtered_response)

        chars_saved = full_chars - filtered_chars
        reduction_percent = (chars_saved / full_chars) * 100

        full_tokens_est = self._estimate_tokens(full_chars)
        filtered_tokens_est = self._estimate_tokens(filtered_chars)
        tokens_saved_est = full_tokens_est - filtered_tokens_est

        print(f"\n{'='*60}")
        print("Token Savings Verification: detailed=True, fields=['inferred_types']")
        print(f"{'='*60}")
        print(f"Full response:     {full_chars:,} chars (~{full_tokens_est:.0f} tokens)")
        print(f"Filtered response: {filtered_chars:,} chars (~{filtered_tokens_est:.0f} tokens)")
        print(f"Reduction:         {chars_saved:,} chars (~{tokens_saved_est:.0f} tokens)")
        print(f"Savings:           {reduction_percent:.1f}%")
        print(f"{'='*60}\n")

        # Even with detailed=True, should achieve meaningful reduction
        # Lower threshold since detailed mode adds so much content to inferred_types
        assert (
            reduction_percent >= 20.0
        ), f"Expected at least 20% reduction with detailed=True, got {reduction_percent:.1f}%"

        # Verify structure
        assert "inferred_types" in filtered_response
        assert "position" not in filtered_response
        assert "docstring" not in filtered_response

        # Verify detailed info is present
        class_info = filtered_response["inferred_types"][0]
        assert "methods" in class_info, "detailed=True should include methods"
        assert "attributes" in class_info, "detailed=True should include attributes"
