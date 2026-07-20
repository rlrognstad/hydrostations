#!/usr/bin/env bash
# Publish site/ to the gh-pages branch for GitHub Pages hosting.
#
# The two viz embeds (site/assets/coverage-map.html, crosswalk-map.html) are
# manually-regenerated static snapshots -- see packages/hydrostations/examples/
# render_coverage_map.py and packages/hydrocrosswalk/examples/render_map.py.
# Re-run and re-copy those before publishing if the data or visuals changed.
#
# Usage: scripts/publish-site.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain site/)" ]]; then
  echo "error: site/ has uncommitted changes -- commit or stash before publishing" >&2
  exit 1
fi

remote="origin"
branch="gh-pages"

echo "Publishing site/ to ${remote}/${branch}..."
git subtree push --prefix site "$remote" "$branch"
echo "Done. GitHub Pages will rebuild from ${branch} shortly."
