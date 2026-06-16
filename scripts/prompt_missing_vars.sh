#!/usr/bin/env bash
#
# Interactive prompt for missing environment variables
# Usage: ./prompt_missing_vars.sh <project> [profile] [--check-only]
#

set -euo pipefail

PROJECT="${1:-}"
PROFILE="${2:-production}"
CHECK_ONLY="${3:-}"

if [ -z "$PROJECT" ]; then
  echo "Usage: $0 <project> [profile] [--check-only]" >&2
  exit 1
fi

DB="${TEMPLEDB_PATH:-$HOME/.local/share/templedb/templedb.sqlite}"

if [ ! -f "$DB" ]; then
  echo "Error: Database not found at $DB" >&2
  exit 1
fi

# Get required variables for project
REQUIRED_JSON=$(sqlite3 "$DB" \
  "SELECT COALESCE(env_vars_required, '[]')
   FROM deployment_configs
   WHERE project_id = (SELECT id FROM projects WHERE slug = '$PROJECT')
   LIMIT 1" 2>/dev/null || echo "[]")

if [ "$REQUIRED_JSON" = "[]" ] || [ -z "$REQUIRED_JSON" ]; then
  echo "ℹ️  No required environment variables defined for $PROJECT"
  exit 0
fi

# Get existing variables
EXISTING=$(sqlite3 "$DB" \
  "SELECT var_name FROM environment_variables
   WHERE (scope_type = 'project' AND scope_id = (SELECT id FROM projects WHERE slug = '$PROJECT'))
      OR scope_type = 'global'" | tr '\n' '|')

# Parse required variables
REQUIRED=$(echo "$REQUIRED_JSON" | jq -r '.[]' 2>/dev/null || echo "")

if [ -z "$REQUIRED" ]; then
  echo "ℹ️  No required environment variables defined"
  exit 0
fi

MISSING=()
while IFS= read -r var; do
  if ! echo "$EXISTING" | grep -q "^${var}$\|^${var}|"; then
    MISSING+=("$var")
  fi
done <<< "$REQUIRED"

# If check-only mode, just print missing vars
if [ "$CHECK_ONLY" = "--check-only" ]; then
  if [ ${#MISSING[@]} -eq 0 ]; then
    exit 0
  else
    printf '%s\n' "${MISSING[@]}"
    exit 1
  fi
fi

# Interactive mode
echo "🔐 Checking required environment variables for $PROJECT (profile: $PROFILE)"
echo ""

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "✅ All required variables are configured!"
  exit 0
fi

echo "Found ${#MISSING[@]} missing variable(s):"
for var in "${MISSING[@]}"; do
  echo "  ❌ $var"
done
echo ""

read -p "Would you like to configure them now? (Y/n): " response
if [[ "$response" =~ ^[Nn]$ ]]; then
  echo "Skipping configuration. Run this script again when ready."
  exit 0
fi

echo ""

for var in "${MISSING[@]}"; do
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Variable: $var"
  echo ""

  # Prompt for value
  read -p "Enter value for $var: " -s value
  echo ""

  if [ -z "$value" ]; then
    echo "⚠️  Skipping empty value"
    continue
  fi

  # Determine if it's a secret
  read -p "Is this a secret? (requires encryption) (y/N): " is_secret
  echo ""

  # Add description
  read -p "Description (optional): " description
  echo ""

  if [[ "$is_secret" =~ ^[Yy]$ ]]; then
    # Add to encrypted secrets
    echo "🔐 Adding to encrypted secret blob..."

    # Check if secret blob exists
    HAS_BLOB=$(sqlite3 "$DB" \
      "SELECT COUNT(*) FROM secret_blobs
       WHERE project_id = (SELECT id FROM projects WHERE slug = '$PROJECT')
       AND profile = '$PROFILE'" 2>/dev/null || echo "0")

    if [ "$HAS_BLOB" = "0" ]; then
      echo "⚠️  No encrypted secret blob exists for this project/profile."
      echo "   Please run: templedb secret init $PROJECT --profile $PROFILE --age-recipient <key>"
      echo "   Then: templedb secret edit $PROJECT --profile $PROFILE"
      echo "   Add: $var: $value"
      echo ""
      continue
    else
      echo "ℹ️  Secret blob exists. Please add manually with:"
      echo "   templedb secret edit $PROJECT --profile $PROFILE"
      echo "   Add to 'env:' section:"
      echo "     $var: <your-value>"
      echo ""
    fi
  else
    # Add as regular environment variable
    echo "📝 Adding as environment variable..."

    PROJECT_ID=$(sqlite3 "$DB" "SELECT id FROM projects WHERE slug = '$PROJECT'")

    DESC_CLAUSE=""
    if [ -n "$description" ]; then
      DESC_CLAUSE=", description = '$description'"
    fi

    sqlite3 "$DB" "
      INSERT INTO environment_variables (
        scope_type,
        scope_id,
        var_name,
        var_value,
        value_type,
        is_secret,
        description,
        created_at,
        updated_at
      ) VALUES (
        'project',
        $PROJECT_ID,
        '$var',
        '$value',
        'static',
        0,
        '$description',
        datetime('now'),
        datetime('now')
      )
      ON CONFLICT(scope_type, scope_id, var_name) DO UPDATE
        SET var_value = excluded.var_value,
            updated_at = datetime('now')
            $DESC_CLAUSE
    "

    echo "✅ Added: $var"
  fi
  echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Configuration complete!"
echo ""
echo "To verify:"
echo "  templedb env ls"
echo "  templedb secret export $PROJECT --profile $PROFILE"
