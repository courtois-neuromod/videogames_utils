#!/usr/bin/env bash
# Render docs/EVENT_REFERENCE.md to PDF. Goes through HTML + headless Chrome rather than
# LaTeX because the reference is mostly wide tables, which pandoc's LaTeX output lets run
# off the page. Requires pandoc and google-chrome (or chromium) on PATH.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/EVENT_REFERENCE.pdf}"
tmp="$(mktemp -d)"
pandoc "$here/EVENT_REFERENCE.md" --from gfm-tex_math_dollars -s --css "$here/event_reference.css" \
    --metadata title="Event annotation reference" -o "$tmp/ref.html"
# pandoc adds a title block on top of the document's own H1; drop it
sed -i '0,/<h1 class="title">Event annotation reference<\/h1>/s///' "$tmp/ref.html"
chrome="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"
"$chrome" --headless=new --disable-gpu --no-sandbox --no-pdf-header-footer \
    --print-to-pdf="$out" "file://$tmp/ref.html" 2>/dev/null
rm -rf "$tmp"
echo "wrote $out"
