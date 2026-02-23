#!/usr/bin/env bash
# TempleDB Nix Environment Launcher
# Enter a project's Nix FHS environment from database configuration

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${DB_PATH:-$HOME/.local/share/templedb/templedb.sqlite}"
ENV_DIR="${ENV_DIR:-$HOME/.local/share/templedb/nix-envs}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
Usage: $0 [PROJECT] [ENV_NAME]

Enter a Nix FHS environment for a TempleDB project.

Arguments:
    PROJECT     Project slug (default: templedb)
    ENV_NAME    Environment name (default: dev)

Examples:
    $0                          # Enter templedb dev environment
    $0 woofs_projects dev       # Enter woofs_projects dev environment
    $0 templedb test            # Enter templedb test environment

Commands:
    list                        # List all available environments
    generate PROJECT [ENV]      # Generate Nix expression for environment
    auto-detect PROJECT         # Auto-detect environment for project
    edit PROJECT ENV            # Edit environment in database (opens SQL)

Environment Variables:
    DB_PATH     Database path (default: ~/.local/share/templedb/templedb.sqlite)
    ENV_DIR     Nix environment output directory

EOF
    exit 1
}

list_environments() {
    echo -e "${CYAN}Available Nix Environments:${NC}"
    echo ""
    python3 "$SCRIPT_DIR/src/nix_env_generator.py" list
}

generate_environment() {
    local project="${1:-}"
    local env_name="${2:-dev}"

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: PROJECT required${NC}"
        usage
    fi

    echo -e "${CYAN}Generating Nix environment for ${project}:${env_name}...${NC}"
    python3 "$SCRIPT_DIR/src/nix_env_generator.py" generate -p "$project" -e "$env_name"
}

auto_detect_environment() {
    local project="${1:-}"

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: PROJECT required${NC}"
        usage
    fi

    python3 "$SCRIPT_DIR/src/nix_env_generator.py" auto-detect -p "$project"
}

edit_environment() {
    local project="${1:-}"
    local env_name="${2:-dev}"

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: PROJECT required${NC}"
        usage
    fi

    # Get environment ID
    local env_id=$(sqlite3 "$DB_PATH" "SELECT id FROM nix_environments ne JOIN projects p ON ne.project_id = p.id WHERE p.slug = '$project' AND ne.env_name = '$env_name'")

    if [[ -z "$env_id" ]]; then
        echo -e "${RED}Error: Environment '${env_name}' not found for project '${project}'${NC}"
        exit 1
    fi

    # Get current configuration
    local config=$(sqlite3 "$DB_PATH" "SELECT env_name, description, base_packages, profile FROM nix_environments WHERE id = $env_id")

    echo -e "${CYAN}Editing environment: ${project}:${env_name}${NC}"
    echo ""
    echo "Current configuration:"
    echo "$config"
    echo ""
    echo "Opening database in sqlite3..."
    echo "Run SQL commands to modify the environment, then .quit to exit"
    echo ""

    sqlite3 "$DB_PATH" <<EOF
.headers on
.mode column
SELECT * FROM nix_environments WHERE id = $env_id;
EOF
}

enter_environment() {
    local project="${1:-templedb}"
    local env_name="${2:-dev}"

    # Check if environment exists in database
    local exists=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM nix_environments ne JOIN projects p ON ne.project_id = p.id WHERE p.slug = '$project' AND ne.env_name = '$env_name' AND ne.is_active = 1")

    if [[ "$exists" != "1" ]]; then
        echo -e "${RED}Error: Environment '${env_name}' not found for project '${project}'${NC}"
        echo ""
        echo "Available environments:"
        list_environments
        exit 1
    fi

    # Generate Nix expression
    echo -e "${CYAN}Generating Nix environment...${NC}"
    python3 "$SCRIPT_DIR/src/nix_env_generator.py" generate -p "$project" -e "$env_name" > /dev/null

    local nix_file="$ENV_DIR/${project}-${env_name}.nix"

    if [[ ! -f "$nix_file" ]]; then
        echo -e "${RED}Error: Nix file not generated: $nix_file${NC}"
        exit 1
    fi

    # Log session start
    local env_id=$(sqlite3 "$DB_PATH" "SELECT id FROM nix_environments ne JOIN projects p ON ne.project_id = p.id WHERE p.slug = '$project' AND ne.env_name = '$env_name'")
    local session_id=$(sqlite3 "$DB_PATH" "INSERT INTO nix_env_sessions (environment_id) VALUES ($env_id); SELECT last_insert_rowid();")

    echo -e "${GREEN}✓ Entering ${project}:${env_name} environment${NC}"
    echo -e "${YELLOW}Environment file: $nix_file${NC}"
    echo ""

    # Enter environment
    nix-shell "$nix_file"
    local exit_code=$?

    # Log session end
    sqlite3 "$DB_PATH" "UPDATE nix_env_sessions SET ended_at = CURRENT_TIMESTAMP, exit_code = $exit_code WHERE id = $session_id"

    echo ""
    echo -e "${GREEN}✓ Exited ${project}:${env_name} environment (exit code: $exit_code)${NC}"

    return $exit_code
}

# Main command dispatch
case "${1:-enter}" in
    list)
        list_environments
        ;;
    generate)
        generate_environment "${2:-}" "${3:-dev}"
        ;;
    auto-detect)
        auto_detect_environment "${2:-}"
        ;;
    edit)
        edit_environment "${2:-}" "${3:-dev}"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        # Default: enter environment
        enter_environment "${1:-templedb}" "${2:-dev}"
        ;;
esac
