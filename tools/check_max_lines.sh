#!/usr/bin/env bash
set -euo pipefail

MAX_LINES="${1:-700}"
shift || true

if [[ $# -gt 0 ]]; then
  SEARCH_PATHS=("$@")
else
  SEARCH_PATHS=(librariarr tests)
fi

violations=0

while IFS= read -r -d '' file; do
  line_count=$(wc -l < "$file")
  if (( line_count > MAX_LINES )); then
    echo "Max-lines violation: $file has $line_count lines (limit=$MAX_LINES)"
    violations=1
  fi
done < <(find "${SEARCH_PATHS[@]}" -type f -name "*.py" -print0)

if (( violations > 0 )); then
  exit 1
fi

echo "Max-lines check passed: no Python file exceeds $MAX_LINES lines"
