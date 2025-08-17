"""Example Python file for testing code intelligence features."""

import math
from typing import Any


class Calculator:
    """A simple calculator class for demonstration."""

    def __init__(self, precision: int = 2):
        """Initialize calculator with given precision.

        Args:
            precision: Number of decimal places for results
        """
        self.precision = precision
        self.history: list[str] = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            Sum of a and b
        """
        result = round(a + b, self.precision)
        self.history.append(f"{a} + {b} = {result}")
        return result

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            Product of a and b
        """
        result = round(a * b, self.precision)
        self.history.append(f"{a} * {b} = {result}")
        return result

    def divide(self, a: float, b: float) -> float | None:
        """Divide two numbers.

        Args:
            a: Dividend
            b: Divisor

        Returns:
            Quotient or None if division by zero
        """
        if b == 0:
            self.history.append("Error: Division by zero")
            return None

        result = round(a / b, self.precision)
        self.history.append(f"{a} / {b} = {result}")
        return result

    def get_history(self) -> list[str]:
        """Get calculation history.

        Returns:
            List of calculation history entries
        """
        return self.history.copy()


def calculate_area(shape: str, **dimensions: float) -> float:
    """Calculate area of various shapes.

    Args:
        shape: Type of shape (circle, square, rectangle, triangle)
        **dimensions: Shape dimensions (radius, side, width, height, base)

    Returns:
        Area of the shape

    Raises:
        ValueError: If shape is unknown or dimensions are invalid
    """
    shape = shape.lower()

    if shape == "circle":
        radius = dimensions.get("radius", 0)
        return math.pi * radius**2

    elif shape == "square":
        side = dimensions.get("side", 0)
        return side**2

    elif shape == "rectangle":
        width = dimensions.get("width", 0)
        height = dimensions.get("height", 0)
        return width * height

    elif shape == "triangle":
        base = dimensions.get("base", 0)
        height = dimensions.get("height", 0)
        return 0.5 * base * height

    else:
        raise ValueError(f"Unknown shape: {shape}")


def process_data(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Process a list of data dictionaries.

    Args:
        data: List of dictionaries to process

    Returns:
        Summary statistics of the data
    """
    if not data:
        return {"count": 0, "items": []}

    summary: dict[str, Any] = {"count": len(data), "items": data, "field_counts": {}}

    # Count occurrences of each field
    field_counts = summary["field_counts"]
    for item in data:
        for field in item:
            if field not in field_counts:
                field_counts[field] = 0
            field_counts[field] += 1

    return summary


# Example usage
if __name__ == "__main__":
    calc = Calculator(precision=3)

    # Test calculator
    print(calc.add(10.5, 20.3))
    print(calc.multiply(5, 7))
    print(calc.divide(100, 3))

    # Test area calculation
    circle_area = calculate_area("circle", radius=5)
    print(f"Circle area: {circle_area}")

    rect_area = calculate_area("rectangle", width=10, height=5)
    print(f"Rectangle area: {rect_area}")

    # Show history
    print("\nCalculation history:")
    for entry in calc.get_history():
        print(f"  {entry}")
