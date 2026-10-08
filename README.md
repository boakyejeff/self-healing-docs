# Self-Healing Technical Docs

`docwatch` detects drift between a Python codebase and its documentation, then
**proposes** doc updates for human review. It never auto-applies changes: every
fix lands in a review queue as a unified diff, and `apply` requires an explicit
`--i-reviewed` flag.

## Why

Docs rot. Functions get renamed, parameters get added, examples go stale, and
nobody notices until a user files a confused issue. This tool closes the loop
mechanically: it scans the code's actual API surface with the `ast` module,
scans the docs for references to that surface, and flags the mismatches —
with a concrete proposed fix attached to each one.

## Install

Requires Python 3.10+. No dependencies beyond the standard library, except
`pytest` for the test suite.

```bash
git clone <repo>
cd self-healing-docs
pip install -r requirements.txt   # pytest only
```

## Quickstart

```bash
# 1. Scan: --src points at the directory CONTAINING your top-level package(s),
#    so scanned module names match how docs reference them.
./docwatch scan --src ./examples --docs ./examples/docs --out ./reviews

# 2. Review the proposals (each is a Markdown file with a diff + rationale).
ls reviews/pending
cat reviews/pending/signature_drift-001.md

# 3. Apply one you agree with (refuses without the flag).
./docwatch apply --proposal reviews/pending/signature_drift-001.md --i-reviewed

# 4. List what's still pending.
./docwatch apply --list --out ./reviews
```

Or run the bundled demo (fully offline):

```bash
./examples/demo.sh
```

## How the review queue works

`scan` writes one file per fixable finding into `<out>/pending/*.md`. Each file
contains the finding, the rationale, a unified diff, and accept/reject
instructions. A proposal file also carries a machine-readable edit list, so
`apply` replays exactly the change you reviewed — and verifies every edited
line still matches before touching it. If the file changed underneath the
proposal, apply aborts instead of guessing.

- **Accept**: `docwatch apply --proposal <file> --i-reviewed` (applied files
  move to `<out>/applied/` as an audit trail).
- **Reject**: delete the proposal file. Nothing happens otherwise.

Safety is structural, not a warning banner: without `--i-reviewed`, apply
exits with an error and changes nothing.

## The three detectors

1. **missing_symbol** — a documented symbol no longer exists. The docs
   reference `shopex.apply_promotion`, the code only has
   `shopex.pricing.apply_promo`; you get the finding plus a fuzzy-match rename
   suggestion.
2. **signature_drift** — a signature changed but the docstring didn't. Compares
   documented parameters (Google, NumPy, and Sphinx docstring styles) against
   the real signature; reports added, removed, and likely-renamed params, and
   proposes docstring edits (renames applied, stale lines removed, `TODO:
   document.` placeholders for new params).
3. **stale_example** — a fenced Python code example calls a name that no
   longer exists (e.g. `shopex.apply_promotion(0.2)` after the rename).

Dotted references are only checked when their first component is a module
from the scanned tree, so `json.dumps` and `pd.read_csv` in your docs are
left alone. Python builtins and keywords are skipped.

## Project structure

```
self_healing_docs/
  scan.py    # AST scanner: public functions/classes/methods, signatures, docstrings
  drift.py   # the three detectors + Markdown reference extraction
  propose.py # diff generation, review-queue files, guarded apply
  cli.py     # docwatch scan / docwatch apply
examples/
  shopex/    # sample package with intentional drift
  docs/      # sample docs with intentional drift
  demo.sh    # offline end-to-end demo
tests/       # pytest suite (29 tests)
```

## Limitations (honest)

- **Python only.** Scanning is AST-based; other languages are out of scope.
- **Heuristic matching can misfire.** Rename suggestions come from
  `difflib` similarity, not from version history. A suggestion is a guess
  dressed as a diff — which is exactly why a human must review it.
- **Docstring parsing is style-limited.** Google, NumPy, and Sphinx parameter
  styles are recognized; exotic formats are not.
- **Only what it can see.** It compares docstrings and Markdown docs against
  the scanned tree. Tutorials on external sites, docstrings without any
  parameter section, and dynamically generated APIs are invisible to it.
- **Human review is mandatory, by design.** The tool proposes; it never
  decides. `apply` without `--i-reviewed` is a hard error, not a prompt.
