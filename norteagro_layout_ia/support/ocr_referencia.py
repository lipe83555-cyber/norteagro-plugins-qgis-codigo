# -*- coding: utf-8 -*-
"""Ambiente de SUPORTE (fora do Python do QGIS): OCR opcional da referência ou de documento digitalizado.

Uso: python ocr_referencia.py <imagem_ou_pdf> <saida.json> [pagina]

Gera JSON: {"textos": [{"texto": "...", "caixa": [x0, y0, x1, y1], "confianca": 0.9}, ...]}
Requer rapidocr-onnxruntime (instalado por Instalar_OCR_Windows.cmd). Para PDF digitalizado
também usa PyMuPDF.
"""
import json
import os
import sys
import tempfile


def main(argv):
    if len(argv) < 3:
        print("uso: ocr_referencia.py <imagem_ou_pdf> <saida.json> [pagina]", file=sys.stderr)
        return 2
    entrada, saida = argv[1], argv[2]
    pagina = int(argv[3]) if len(argv) > 3 else 1
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("rapidocr-onnxruntime não instalado. Rode support/Instalar_OCR_Windows.cmd.", file=sys.stderr)
        return 3
    if entrada.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(entrada)
        img = os.path.join(tempfile.mkdtemp(), "pagina.png")
        doc[pagina - 1].get_pixmap(dpi=200).save(img)
        entrada = img
    motor = RapidOCR()
    resultado, _ = motor(entrada)
    textos = []
    for caixa, texto, conf in resultado or []:
        xs = [p[0] for p in caixa]
        ys = [p[1] for p in caixa]
        textos.append({"texto": texto, "caixa": [min(xs), min(ys), max(xs), max(ys)], "confianca": float(conf)})
    with open(saida, "w", encoding="utf-8") as fh:
        json.dump({"textos": textos}, fh, ensure_ascii=False, indent=1)
    print(f"{len(textos)} textos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
