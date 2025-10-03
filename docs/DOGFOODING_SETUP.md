# Dogfooding Metrics Setup Guide

This guide helps you set up automatic metrics tracking for the Python Code Intelligence MCP dogfooding initiative.

## 🚀 Quick Setup (Recommended)

Run the automated setup script:

```bash
bash scripts/setup_dogfooding.sh
```

This will:

- Install git hooks for automatic session management
- Set up shell aliases for tracking grep usage
- Create the metrics directory
- Test the installation

## ⚡ What Gets Automated

After setup, these things happen automatically:

### 1. Branch Switching

```bash
git checkout feat/123-new-feature
# 📊 Starting dogfooding metrics for issue #123...
```

### 2. Manual Search Tracking

```bash
grep "function_name" src/
# (automatically logs grep usage)
```

### 3. Commit-Time Metrics

```bash
git commit -m "Add new feature"
# 📊 Ending dogfooding metrics session...
#
# === Session Summary ===
# Duration: 45.2 minutes
# MCP queries: 12
# Grep/manual searches: 3
# MCP adoption rate: 80.0%
# Bugs prevented: 1
# Time saved: 15 minutes
```

### 4. Project Entry

```bash
cd ~/repos/pyeye-mcp
# 📊 Auto-starting dogfooding metrics for issue #135...
```

## 🔧 Manual Commands

Even with automation, you have manual control:

```bash
# Start/stop sessions manually
mcp-start --issue 123
mcp-end

# Log specific events
mcp-saved 10 "Found all references with MCP instead of grep"
mcp-bug "MCP caught circular dependency that grep missed"

# Generate reports
mcp-report --days 7
```

## 📁 Files Created

The setup creates these files:

### Git Hooks

- `.git/hooks/post-checkout` - Auto-start sessions on branch switch
- `.git/hooks/pre-commit` - Auto-end sessions on commit
- `.git/hooks/prepare-commit-msg` - Add metrics to commit messages

### Shell Aliases (in ~/.bashrc or ~/.zshrc)

- `grep` wrapper - Tracks manual search usage
- `cd` wrapper - Auto-starts sessions when entering project
- `mcp-*` commands - Quick access to metrics functions

### Metrics Data

- `~/.pyeye/metrics/` - Directory for all metrics data
- `current_session.json` - Active session data
- `history.jsonl` - All completed sessions
- `last_session_stats.json` - Stats for commit message hook

## 🛠️ Troubleshooting

### Aliases Not Working

```bash
# Reload your shell config
source ~/.bashrc  # or ~/.zshrc

# Or restart your terminal
```

### Git Hooks Not Working

```bash
# Check if hooks are executable
ls -la .git/hooks/post-checkout
# Should show -rwxr-xr-x

# Manually make executable if needed
chmod +x .git/hooks/post-checkout
```

### Metrics Not Tracking

```bash
# Check if metrics directory exists
ls -la ~/.pyeye/metrics/

# Test the metrics script directly
python scripts/dogfooding_metrics.py --help
```

### Worktree Issues

The setup handles git worktrees automatically, but if you have issues:

```bash
# Find your actual git directory
cat .git
# Follow the gitdir path and check hooks there
```

## 🔄 Updating

To update the automation setup:

```bash
# Remove old aliases from ~/.bashrc or ~/.zshrc
# (Look for "# Dogfooding Metrics Aliases" section)

# Re-run setup
bash scripts/setup_dogfooding.sh
```

## 🛠️ Individual Components

If you prefer to set up components individually:

```bash
# Install just git hooks
bash scripts/install_hooks.sh

# Install just shell aliases
bash scripts/setup_aliases.sh

# Test the metrics CLI directly
python scripts/dogfooding_metrics.py --help
```

## 🎯 Expected Metrics

After setup, you should see:

**Week 1**: 30% MCP adoption rate
**Week 2**: 50% MCP adoption, 5+ time-saving examples
**Week 3**: 70% MCP adoption, identified feature gaps
**Week 4**: 80% MCP adoption, measurable productivity gains

## 📊 Checking Your Progress

```bash
# Daily check
mcp-report --days 1

# Weekly check
mcp-report --days 7

# See specific session details
cat ~/.pyeye/metrics/history.jsonl | tail -1 | python -m json.tool
```

## 🚨 Important Notes

- The automation only works when you're in a project with `scripts/dogfooding_metrics.py`
- Git hooks are installed per-repository (not global)
- Shell aliases work across all directories but only track in MCP projects
- All tracking is local to your machine - no data leaves your system

## 🆘 Getting Help

If you encounter issues:

1. Check the troubleshooting section above
2. Test individual components manually
3. Create an issue with error details
4. Ask in team chat with logs

Happy dogfooding! 🐕‍🦺
