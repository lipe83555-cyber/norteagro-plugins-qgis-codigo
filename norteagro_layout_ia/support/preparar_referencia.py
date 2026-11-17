# -*- coding: utf-8 -*-
"""Ambiente de SUPORTE (fora do Python do QGIS): converte página de PDF em PNG.

Uso: python preparar_referencia.py pdf <arquivo.pdf> <pagina> <dpi> <saida.png>

Só é necessário quando o GDAL do QGIS não abre o PDF (o plugin tenta o GDAL primeiro).
Requer PyMuPDF (instalado por Preparar_PDF_Windows.cmd).
"""
import sys


def main(argv):
    if len(argv) != 6 or argv[1] != "pdf":
        print("uso: preparar_referencia.py pdf <arquivo.pdf> <pagina> <dpi> <saida.png>", file=sys.stderr)
        return 2
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("PyMuPDF não instalado neste Python. Rode support/Preparar_PDF_Windows.cmd.", file=sys.stderr)
        return 3
    _, _, arquivo, pagina, dpi, saida = argv
    doc = fitz.open(arquivo)
    p = int(pagina)
    if p < 1 or p > doc.page_count:
        print(f"O PDF tem {doc.page_count} página(s).", file=sys.stderr)
        return 4
    pix = doc[p - 1].get_pixmap(dpi=int(dpi))
    pix.save(saida)
    print(saida)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
