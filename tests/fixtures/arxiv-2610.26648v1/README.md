# Test data: arXiv:2610.26648v1

Source files of the paper

> Sang Hwan Kim, Hae Barg Kang, Seodong Shin,
> "Dark Matter Interpretations of the Galactic Center Gamma-Ray Excess with 18 Years of
> Fermi-LAT Data and the FL16Y Source Catalog", arXiv:2610.26648v1 (2026).

The paper is on arXiv under CC0 1.0 Universal, and one of its authors maintains this
repository. It is the only paper text in the repository: text of other papers is
downloaded when needed and never committed.

| File | From the arXiv source download |
|---|---|
| `FermiLAT-main.tex` | unchanged, 149,776 bytes |
| `00README.json` | unchanged, 467 bytes |

Left out: `Figures/` (59 PNG files), `FermiLAT-main.bbl`, `JHEP.bst`, `ref.bib`. The
section parser does not read them.

SHA-256 of the complete download (`arXiv-2610.26648v1.tar.gz`, 11,731,982 bytes):
`357ca8323f7bb53d59df76818549440746d64ff21b3d95d3f351633882c21608`

The tests pack these two files into a tar.gz in memory, so the same code path runs
as for a real download.
