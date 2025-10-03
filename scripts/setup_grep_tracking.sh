#!/bin/bash
# Setup grep usage tracking for dogfooding metrics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACKER_SCRIPT="$SCRIPT_DIR/grep_tracker.sh"

# Create a local bin directory for the user
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

echo "Setting up grep tracking..."

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo "Adding ~/.local/bin to PATH in shell configuration..."

    # Add to .bashrc if it exists
    if [[ -f "$HOME/.bashrc" ]]; then
        if ! grep -q "export PATH=\"\$HOME/.local/bin:\$PATH\"" "$HOME/.bashrc"; then
            echo "" >> "$HOME/.bashrc"
            echo "# Added by PyEye dogfooding setup" >> "$HOME/.bashrc"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$HOME/.bashrc"
        fi
    fi

    # Add to .zshrc if it exists
    if [[ -f "$HOME/.zshrc" ]]; then
        if ! grep -q "export PATH=\"\$HOME/.local/bin:\$PATH\"" "$HOME/.zshrc"; then
            echo "" >> "$HOME/.zshrc"
            echo "# Added by PyEye dogfooding setup" >> "$HOME/.zshrc"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$HOME/.zshrc"
        fi
    fi
fi

# Create wrapper scripts for common search commands
for cmd in grep egrep fgrep rg; do
    wrapper="$LOCAL_BIN/$cmd"

    # Create wrapper that calls our tracker
    cat > "$wrapper" << EOF
#!/bin/bash
# Auto-generated grep tracker wrapper for dogfooding metrics
export DOGFOODING_PROJECT_ROOT="$SCRIPT_DIR/.."
exec "$TRACKER_SCRIPT" "$cmd" "\$@"
EOF

    chmod +x "$wrapper"
    echo "✅ Created $cmd tracker: $wrapper"
done

echo ""
echo "🔍 Grep tracking setup complete!"
echo ""
echo "ℹ️  The following commands will now track usage:"
echo "   - grep, egrep, fgrep, rg (ripgrep)"
echo "   - Only when used for code searches (class, def, import, etc.)"
echo ""
echo "🔄 To activate tracking:"
echo "   source ~/.bashrc  # or ~/.zshrc"
echo "   # Or restart your terminal"
echo ""
echo "⚠️  Note: This only tracks usage in new shell sessions"
echo "   Existing terminals need to be restarted to see the changes"
