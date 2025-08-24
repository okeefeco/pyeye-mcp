#!/bin/bash
# Check the current release status of the project

echo "🔍 Python Code Intelligence MCP - Release Status"
echo "================================================"

echo -e "\n📦 Current Version:"
echo "-------------------"
grep "^version = " pyproject.toml | head -1

echo -e "\n🏷️  Recent Tags:"
echo "---------------"
git tag -l "v*" | tail -5

echo -e "\n🚀 Recent Releases:"
echo "-------------------"
gh release list --limit=5 2>/dev/null || echo "No releases found or gh CLI not configured"

echo -e "\n⚙️  Recent Release Workflow Runs:"
echo "----------------------------------"
gh run list --workflow=release.yml --limit=5 2>/dev/null || echo "No workflow runs found or gh CLI not configured"

echo -e "\n📝 Unreleased Changes:"
echo "----------------------"
# Show commits since last tag
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$LAST_TAG" ]; then
    echo "Commits since $LAST_TAG:"
    git log --oneline "$LAST_TAG"..HEAD | head -10
    COMMIT_COUNT=$(git log --oneline "$LAST_TAG"..HEAD | wc -l)
    if [ "$COMMIT_COUNT" -gt 10 ]; then
        echo "... and $((COMMIT_COUNT - 10)) more commits"
    fi
else
    echo "No tags found. Showing recent commits:"
    git log --oneline -10
fi

echo -e "\n✅ Version Sync Status:"
echo "------------------------"
python scripts/check_version_sync.py 2>/dev/null || echo "Version sync script not found or Python error"

echo -e "\n📊 Test Coverage:"
echo "-----------------"
pytest --cov=src/pycodemcp --cov-report=term-missing:skip-covered --no-header --tb=no -q 2>/dev/null | tail -3 || echo "Coverage data not available"

echo -e "\n================================================"
echo "Use 'scripts/prepare_release.py' to prepare a new release"
