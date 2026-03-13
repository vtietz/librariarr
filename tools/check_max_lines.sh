#!/usr/bin/env bash
set -euo pipefail

MAX_LINES="${1:-700}"
shift || true

EXTENSIONS=("py")
LABEL="Python"
SEARCH_PATHS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --extensions)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --extensions requires a comma-separated value (example: --extensions ts,tsx)" >&2
        exit 1
      fi
      IFS=',' read -r -a EXTENSIONS <<< "$2"
      shift 2
      ;;
    --label)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --label requires a value" >&2
        exit 1
      fi
      LABEL="$2"
      shift 2
      ;;
    *)
      SEARCH_PATHS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#SEARCH_PATHS[@]} -eq 0 ]]; then
  if [[ ${#EXTENSIONS[@]} -eq 1 && "${EXTENSIONS[0]}" == "py" ]]; then
    SEARCH_PATHS=(librariarr tests)
  else
    SEARCH_PATHS=(.)
  fi
fi

for index in "${!EXTENSIONS[@]}"; do
  ext="${EXTENSIONS[$index]}"
  ext="${ext#.}"
  ext="${ext// /}"
  if [[ -z "$ext" ]]; then
    echo "Error: --extensions contains an empty value" >&2
    exit 1
  fi
  EXTENSIONS[$index]="$ext"
done

ext_regex=""
for ext in "${EXTENSIONS[@]}"; do
  if [[ -n "$ext_regex" ]]; then
    ext_regex+="|"
  fi
  ext_regex+="$ext"
done

violations=0

while IFS= read -r -d '' file; do
  if [[ ! "$file" =~ \.(${ext_regex})$ ]]; then
    continue
  fi

  line_count=$(wc -l < "$file")
  if (( line_count > MAX_LINES )); then
    echo "Max-lines violation ($LABEL): $file has $line_count lines (limit=$MAX_LINES)"
    violations=1
  fi
done < <(find "${SEARCH_PATHS[@]}" -type f -print0)

if (( violations > 0 )); then
  exit 1
fi

echo "Max-lines check passed ($LABEL): no matching file exceeds $MAX_LINES lines"
