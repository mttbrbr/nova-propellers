# Sphinx configuration of the MetiX documentation: HTML site (Shibuya theme) and PDF manual
# (XeLaTeX with the MetiX style in _latex/). Build with `make -C docs html` and `make -C docs pdf`.
import os
import sys

sys.path.insert(0, os.path.abspath("_ext"))

project = "MetiX"
author = "Progetto MetiX"
copyright = "2026, Progetto MetiX"
language = "it"

extensions = [
    "myst_parser",
    "sphinxcontrib.bibtex",
    "sphinxcontrib.mermaid",
    "metix_docs",
]

# The Markdown pages stay readable on GitHub and by mdBook (book.toml, SUMMARY.md): Sphinx reads
# the same files and ignores the mdBook-only ones and the hand-written LaTeX manual.
exclude_patterns = ["_build", "book", "manual", "README.md", "SUMMARY.md", "tools", "_latex",
                    "**/.venv*"]
source_suffix = {".md": "markdown"}
templates_path = ["_templates"]

myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence", "deflist", "attrs_inline"]
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 3

numfig = True
math_numfig = True
numfig_secnum_depth = 1
numfig_format = {"figure": "Figura %s", "table": "Tabella %s", "code-block": "Listato %s",
                 "section": "%s", "algoritmo": "Algoritmo %s"}

bibtex_bibfiles = ["tecnico/riferimenti.bib"]
bibtex_default_style = "plain"

# ---------------------------------------------------------------------------- HTML
html_theme = "shibuya"
html_title = "MetiX"
html_static_path = ["_static"]
html_css_files = ["metix.css"]
html_js_files = ["metix.js"]
html_theme_options = {
    "accent_color": "orange",
    "color_mode": "auto",
    # indice a sinistra: i capitoli si aprono sulle loro sezioni
    "toctree_titles_only": False,
    "toctree_maxdepth": 3,
}
html_favicon = "_static/favicon.svg"
# Il PDF del manuale, se è già stato compilato (make pdf), si scarica dalla barra in alto.
_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_build", "latex",
                    "metix-manuale-tecnico.pdf")
html_extra_path = [_pdf] if os.path.exists(_pdf) else []
html_context = {"metix_pdf": bool(html_extra_path)}
# Diagrammi Mermaid: tema neutro sul chiaro, scuro sul tema scuro, font del sito.
mermaid_light_theme = "neutral"
mermaid_dark_theme = "dark"
mermaid_init_config = {"startOnLoad": False, "fontFamily": "Geist, Inter, sans-serif"}
html_last_updated_fmt = "%d/%m/%Y"
mathjax3_config = {"tex": {"macros": {"vect": [r"\boldsymbol{#1}", 1], "R": r"\mathbb{R}"}}}

# ---------------------------------------------------------------------------- PDF
latex_engine = "xelatex"
latex_documents = [
    ("tecnico/pdf", "metix-manuale-tecnico.tex", "MetiX — manuale tecnico", author, "manual"),
]
latex_appendices = ["tecnico/A-parametri", "tecnico/B-mappa"]
latex_additional_files = [
    "_latex/preambolo.tex",
    "_latex/colori.tex",
    "_latex/copertina.tex",
    "_latex/sillabazione.tex",
    "_latex/marchio-bianco.pdf",
    "_latex/marchio-inchiostro.pdf",
]
latex_table_style = ["booktabs"]
latex_show_urls = "no"
latex_domain_indices = False

# EL10 TeX Live has neither babel-italian nor the Italian hyphenation patterns: fall back to
# English babel with Italian captions and a generated \hyphenation list (_latex/sillabazione.tex).
_babel = r"""
\IfFileExists{italian.ldf}{\usepackage[italian]{babel}}{%
  \usepackage[english]{babel}%
  \addto\captionsenglish{%
    \renewcommand{\chaptername}{Capitolo}\renewcommand{\appendixname}{Appendice}%
    \renewcommand{\contentsname}{Indice}\renewcommand{\bibname}{Bibliografia}%
    \renewcommand{\figurename}{Figura}\renewcommand{\tablename}{Tabella}}%
  \AtBeginDocument{\input{sillabazione}\lefthyphenmin=2 \righthyphenmin=2 }}
"""

latex_elements = {
    "papersize": "a4paper",
    "pointsize": "11pt",
    "extraclassoptions": "openany",
    "geometry": r"\usepackage[a4paper,inner=28mm,outer=26mm,top=28mm,bottom=30mm,"
                r"headheight=14pt]{geometry}",
    "fontenc": r"\usepackage{fontspec}",
    "amsmath": r"\usepackage{amsmath}",
    "polyglossia": "",
    "babel": _babel,
    "fontpkg": r"""
\usepackage{unicode-math}
\setmainfont{texgyrepagella}[Extension=.otf,UprightFont=*-regular,BoldFont=*-bold,
  ItalicFont=*-italic,BoldItalicFont=*-bolditalic]
\setmathfont{texgyrepagella-math.otf}
\setmonofont{lmmono10-regular.otf}[BoldFont=lmmonolt10-bold.otf,ItalicFont=lmmono10-italic.otf,
  HyphenChar=None]
""",
    "fncychap": "",
    "sphinxsetup": "TitleColor={HTML}{18181B}, InnerLinkColor={HTML}{18181B}, "
                   "OuterLinkColor={HTML}{18181B}, VerbatimColor={HTML}{F7F7F8}, "
                   "VerbatimBorderColor={HTML}{E4E4E7}",
    "preamble": r"\input{preambolo.tex}",
    "maketitle": r"\input{copertina.tex}",
    "printindex": "",
}
