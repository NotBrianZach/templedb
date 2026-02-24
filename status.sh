#!/usr/bin/env bash
# Wrapper for templedb status command
# This script now just calls the unified CLI

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/templedb" status "$@"
