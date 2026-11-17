# -*- coding: utf-8 -*-
"""Funções cartográficas puras (sem QGIS): parâmetros do SRC, folha, escala, grade."""

import math
import re

FOLHAS = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}

ESCALAS_PADRAO = [500, 750, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7500, 8000, 10000, 12500, 15000,
                  17500, 20000, 25000, 30000, 35000, 40000, 45000, 50000, 60000, 75000, 80000, 100000,
                  125000, 150000, 200000, 250000, 300000, 400000, 500000, 750000, 1000000, 1500000,
                  2000000, 2500000, 3000000, 4000000, 5000000, 7500000, 10000000, 15000000, 20000000,
                  25000000, 30000000, 40000000, 50000000]


def nome_folha(largura_mm, altura_mm, tolerancia=2.0):
    a, b = sorted((largura_mm, altura_mm), reverse=True)
    for nome, (x, y) in FOLHAS.items():
        if abs(a - x) <= tolerancia and abs(b - y) <= tolerancia:
            return nome
    return f"{largura_mm:.0f} x {altura_mm:.0f} mm"


def escala_arredondada(escala):
    """Próxima escala 'redonda' maior ou igual (para o mapa caber na moldura)."""
    for e in ESCALAS_PADRAO:
        if e >= escala * 0.999:
            return float(e)
    passo = 10 ** int(math.floor(math.log10(escala)))
    return float(math.ceil(escala / passo) * passo)


def parametros_src(authid="", proj="", descricao="", geografico=False):
    """Texto dos parâmetros cartográficos a partir do SRC.

    Retorna dict com projecao, datum, meridiano, fuso (strings prontas para os rótulos).
    """
    authid = (authid or "").upper()
    proj = proj or ""
    desc = descricao or ""
    datum = "Sirgas 2000" if ("SIRGAS" in desc.upper() or "SIRGAS" in authid or "GRS80" in proj.upper()
                              or authid in ("EPSG:4674",)) else ""
    if not datum:
        m = re.search(r"\+datum=(\w+)", proj)
        datum = {"WGS84": "WGS 84"}.get(m.group(1).upper(), m.group(1)) if m else ""
        if not datum and "WGS 84" in desc.upper():
            datum = "WGS 84"
        if not datum and "SAD69" in desc.upper().replace(" ", ""):
            datum = "SAD 69"
    if geografico or "+proj=longlat" in proj:
        return {"projecao": "Coordenadas Geográficas", "datum": datum or "-", "meridiano": "-", "fuso": "-"}
    zona = None
    sul = "+south" in proj
    m = re.search(r"\+zone=(\d+)", proj)
    if m:
        zona = int(m.group(1))
    else:
        m = re.match(r"EPSG:(\d+)$", authid)
        if m:
            cod = int(m.group(1))
            if 31965 <= cod <= 31985:       # SIRGAS 2000 / UTM 11N..25S
                tabela = {31965: (11, False), 31966: (12, False), 31967: (13, False), 31968: (14, False),
                          31969: (15, False), 31970: (16, False), 31971: (17, False), 31972: (18, False),
                          31973: (19, False), 31974: (20, False), 31975: (21, False), 31976: (22, False),
                          31977: (17, True), 31978: (18, True), 31979: (19, True), 31980: (20, True),
                          31981: (21, True), 31982: (22, True), 31983: (23, True), 31984: (24, True),
                          31985: (25, True)}
                zona, sul = tabela[cod]
            elif 32601 <= cod <= 32660:
                zona, sul = cod - 32600, False
            elif 32701 <= cod <= 32760:
                zona, sul = cod - 32700, True
        m = re.search(r"UTM zone (\d+)([NS])", desc, re.I)
        if zona is None and m:
            zona, sul = int(m.group(1)), m.group(2).upper() == "S"
    if zona is None:
        m = re.search(r"\+lon_0=(-?[\d.]+)", proj)
        mc = f"{abs(float(m.group(1))):g}° {'W' if float(m.group(1)) < 0 else 'E'}" if m else "-"
        return {"projecao": desc or "-", "datum": datum or "-", "meridiano": mc, "fuso": "-"}
    mc = -183 + 6 * zona
    return {
        "projecao": "Projeção Universal Transversa de Mercator - UTM",
        "datum": datum or "-",
        "meridiano": f"{abs(mc)}° {'W' if mc < 0 else 'E'}",
        "fuso": f"{zona} {'Sul' if sul else 'Norte'}",
    }


def intervalo_grade(extensao_graus, divisoes=4):
    """Intervalo 'redondo' em graus para uma grade com ~divisoes linhas."""
    if extensao_graus <= 0:
        return 0.01
    alvo = extensao_graus / divisoes
    candidatos = [1 / 3600 * s for s in (1, 2, 5, 10, 15, 20, 30)] + \
                 [1 / 60 * m for m in (1, 2, 5, 10, 15, 20, 30)] + [1, 2, 5, 10, 15, 30]
    for c in candidatos:
        if c >= alvo:
            return c
    return candidatos[-1]
