#!/usr/bin/env bash
# Demo: detect drift between code and docs, propose fixes for human review.
# Fully offline. Nothing is changed: the tool proposes, a human decides.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rm -rf examples/reviews

echo "== 1. docwatch scan =="
# NOTE: --src points at the directory *containing* the package, so module
# names (shopex.cart, ...) match how the docs reference them.
python3 -m self_healing_docs.cli scan \
  --src examples \
  --docs examples/docs \
  --out examples/reviews

echo
echo "== 2. proposals waiting in the review queue =="
ls examples/reviews/pending

echo
FIRST="$(ls examples/reviews/pending | head -n 1)"
echo "== 3. sample proposal: $FIRST =="
cat "examples/reviews/pending/$FIRST"

echo
echo "== 4. safety gate: apply without --i-reviewed =="
if python3 -m self_healing_docs.cli apply --proposal "examples/reviews/pending/$FIRST"; then
  echo "UNEXPECTED: apply succeeded without the review flag"
else
  echo "OK: apply refused without --i-reviewed (nothing was changed)"
fi

echo
echo "Done. Review a proposal file, then apply it with:"
echo "  python3 -m self_healing_docs.cli apply --proposal examples/reviews/pending/<id>.md --i-reviewed"
