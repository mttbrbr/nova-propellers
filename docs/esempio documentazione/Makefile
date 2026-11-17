# Documentazione MetiX con Sphinx (requisiti in requirements.txt).
#   make html    sito in _build/html          make serve   anteprima che si aggiorna da sola
#   make pdf     manuale tecnico in _build/latex/metix-manuale-tecnico.pdf
SPHINX ?= ../.venv-docs/bin/sphinx-build
AUTOBUILD ?= ../.venv-docs/bin/sphinx-autobuild

.PHONY: html pdf serve figure

html:
	$(SPHINX) -b html . _build/html

serve:
	$(AUTOBUILD) . _build/html

pdf:
	$(SPHINX) -b latex . _build/latex
	cd _build/latex && for i in 1 2 3; do \
	  xelatex -interaction=nonstopmode -halt-on-error metix-manuale-tecnico.tex > /dev/null || \
	  { tail -40 metix-manuale-tecnico.log; exit 1; }; done
	@echo "PDF: _build/latex/metix-manuale-tecnico.pdf"

# Ricompila le figure TikZ (tecnico/figure/*.tikz) in PDF per il manuale e SVG per il sito;
# gli SVG sono ricolorati in nero/arancione (tools/svg_scuro.py), la copia per il tema scuro va
# in _static/figure-scuro.
figure:
	mkdir -p _build/figure _static/figure-scuro
	for f in tecnico/figure/*.tikz; do n=$$(basename $$f .tikz); \
	  xelatex -interaction=nonstopmode -halt-on-error -output-directory=_build/figure -jobname=$$n \
	    "\def\figura{$$f}\input{_latex/figura.tex}" > /dev/null && \
	  cp _build/figure/$$n.pdf tecnico/figure/ && \
	  pdftocairo -svg tecnico/figure/$$n.pdf _build/figure/$$n.svg && \
	  python3 tools/svg_scuro.py --chiaro _build/figure/$$n.svg tecnico/figure/$$n.svg && \
	  python3 tools/svg_scuro.py _build/figure/$$n.svg _static/figure-scuro/$$n.svg; done
