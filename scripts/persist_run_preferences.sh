#!/usr/bin/env bash
set -euo pipefail

python scripts/save_run_preferences.py

if [[ -n "$(git status --porcelain -- config/aoi/current.geojson config/defaults.json)" ]]; then
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
  git add -- config/aoi/current.geojson config/defaults.json
  git commit -m 'chore: save Seyd Yar map and timezone preferences [skip ci]'
  branch="${DEFAULT_BRANCH:-main}"
  git push origin "HEAD:refs/heads/${branch}" || {
    echo "::error::Could not persist coordinates on ${branch}. Ensure Actions has contents: write and branch rules allow github-actions[bot] to push." >&2
    exit 1
  }
else
  echo 'No new AOI/timezone input to commit; reusing stored preferences.'
fi
