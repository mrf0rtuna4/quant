# Configuration file for the Sphinx documentation builder.

# -- Project information
import sys
import os

sys.path.append(os.path.abspath("../.."))
sys.path.append(os.path.abspath("extensions"))

project = 'Quant'
copyright = '2024, MagM1go and contributors'
author = 'MagM1go'

release = '0.1'
version = '0.1.0'

# -- General configuration

extensions = [
    'sphinx.ext.duration',
    'sphinx.ext.doctest',
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'sphinx': ('https://www.sphinx-doc.org/en/master/', None),
}
intersphinx_disabled_domains = ['std']

templates_path = ['_templates']

# -- Options for HTML output

html_theme = 'sphinx_rtd_theme'
pygments_style = "monokai"
default_dark_mode = True

# -- Options for EPUB output
epub_show_urls = 'footnote'
