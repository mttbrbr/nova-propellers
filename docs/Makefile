# NOVA documentation with Sphinx (requirements in requirements.txt, environment in ../.venv-docs).
#   make venv    create ../.venv-docs and install the requirements
#   make html    site in _build/html          make serve   live preview that rebuilds itself
#   make pdf     technical manual in _build/latex/nova-technical-manual.pdf
#   make logo    regenerate the logo (_static/ and _latex/) from tools/Geist-800.ttf
SPHINX ?= ../.venv-docs/bin/sphinx-build
AUTOBUILD ?= ../.venv-docs/bin/sphinx-autobuild
PYTHON ?= ../.venv-docs/bin/python

.PHONY: venv html pdf serve logo clean

venv:
	python3 -m venv ../.venv-docs
	../.venv-docs/bin/pip install -r requirements.txt

html:
	$(SPHINX) -b html . _build/html

serve:
	$(AUTOBUILD) . _build/html

# Some TeX Live installations (e.g. Arch Linux) find array-2024-06-01.sty in the latex-dev
# tree but array.sty in the stable one, without the v2.6 release Sphinx requires: in that
# case, for this build only, array.sty is taken from the latex-dev tree.
pdf:
	$(SPHINX) -b latex . _build/latex
	cd _build/latex && \
	dev=$$(kpsewhich array-2024-06-01.sty); \
	if [ -n "$$dev" ] && ! grep -q 'DeclareRelease{v2\.6}' "$$(kpsewhich array.sty)"; then \
	  export TEXINPUTS="$$(dirname "$$dev")//:"; fi; \
	for i in 1 2 3; do \
	  xelatex -interaction=nonstopmode -halt-on-error nova-technical-manual.tex > /dev/null || \
	  { tail -40 nova-technical-manual.log; exit 1; }; done
	@echo "PDF: _build/latex/nova-technical-manual.pdf"

logo:
	$(PYTHON) -I tools/logo.py tools/Geist-800.ttf

clean:
	rm -rf _build
