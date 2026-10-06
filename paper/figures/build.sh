#!/usr/bin/env bash
# Rebuild every figure: src/figN_*.tex -> figN_*.pdf (vector) and figN_*.png (300 dpi).
# Needs pdflatex (TeX Live with pgfplots) and pdftoppm (poppler-utils).
set -euo pipefail
cd "$(dirname "$0")/src"
for f in fig*.tex; do
  stem="${f%.tex}"
  pdflatex -interaction=nonstopmode -halt-on-error "$f" >/dev/null
  mv "$stem.pdf" "../$stem.pdf"
  pdftoppm -r 300 -png -singlefile "../$stem.pdf" "../$stem"
  rm -f "$stem".aux "$stem".log
  echo "built $stem"
done
