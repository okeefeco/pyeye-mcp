#!/bin/bash
# Setup script for Python Code Intelligence MCP Server development

echo "🚀 Setting up development environment..."

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install it first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
uv venv

# Activate virtual environment
echo "🔧 Installing dependencies..."
source .venv/bin/activate

# Install package with dev dependencies
uv pip install -e ".[dev]"

# Install pre-commit hooks
echo "🪝 Installing pre-commit hooks..."
pre-commit install
pre-commit install --hook-type commit-msg

# Generate secrets baseline
echo "🔒 Generating secrets baseline..."
detect-secrets scan > .secrets.baseline

# Run initial checks (optional)
echo "✅ Running initial quality checks..."
pre-commit run --all-files || true

echo ""
echo "✨ Setup complete! To activate the environment:"
echo "   source .venv/bin/activate"
echo ""
echo "📋 Next steps:"
echo "   1. Create a feature branch: git checkout -b feature/your-feature"
echo "   2. Make your changes"
echo "   3. Commit with conventional commits: git commit -m 'feat: description'"
echo "   4. Push and create PR: git push -u origin feature/your-feature && gh pr create"
