# -*- coding: utf-8 -*-
"""Correspondência entre nomes técnicos de arquivo e nomes de legenda (Fase 6).

Arquivos .shp/.kml usam nome técnico com "_" (AREA_DO_IMOVEL); a legenda usa o
nome do padrão do escritório (coluna "Itens" do Guia de Padronização, igual ao
plugin "Norte Agro - Uso do Solo"). A tabela é um CSV editável:

    dados/correspondencia_camadas.csv  ->  arquivo;nome_legenda;apelidos;papel;grupo

Uma cópia editável pode ficar na pasta da biblioteca de modelos (ou no Drive);
se existir, ela tem prioridade sobre a de fábrica.

A comparação ignora acentos, maiúsculas, prefixos numéricos ("00_", "01 -"),
extensões e todos os separadores, então "AREA_DO_IMOVEL", "ÁREA DO IMÓVEL",
"AreaDoImovel.shp" e "00_AREA_DO_IMOVEL" casam com o mesmo item.
"""

import csv
import os
import re
import unicodedata

ARQUIVO_FABRICA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dados", "correspondencia_camadas.csv")
PAPEIS = ("imovel", "uso_solo", "app", "hidrografia", "municipio", "estado", "brasil")


def chave(nome):
    """Chave de comparação: só letras e números, sem acento, maiúsculas, sem prefixo numérico."""
    s = str(nome or "")
    s = os.path.basename(s)
    s = re.sub(r"\.(shp|kml|kmz|gpkg|geojson|json|csv|tab|dbf)$", "", s, flags=re.I)
    s = s.split("|")[0]
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").upper()
    s = re.sub(r"^\s*\d{1,3}\s*[-_.)\s]+", "", s)  # "00_", "01 - ", "3) "
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s


def _colapsar(s):
    """Colapsa letras repetidas (mesma regra lógica do plugin Uso do Solo: BARRAGEM ~ BARAGEM)."""
    return re.sub(r"(.)\1+", r"\1", s)


class Correspondencia:
    def __init__(self, itens=None):
        self.itens = list(itens or [])
        self._indice = {}
        self._indice_colapsado = {}
        for it in self.itens:
            for nome in [it["arquivo"], it["nome_legenda"]] + it["apelidos"]:
                k = chave(nome)
                if k:
                    self._indice.setdefault(k, it)
                    self._indice_colapsado.setdefault(_colapsar(k), it)

    @classmethod
    def carregar(cls, caminho=None):
        caminhos = [c for c in (caminho, ARQUIVO_FABRICA) if c]
        for c in caminhos:
            if c and os.path.isfile(c):
                return cls(ler_csv(c))
        return cls([])

    def procurar(self, nome_camada):
        k = chave(nome_camada)
        if not k:
            return None
        it = self._indice.get(k) or self._indice_colapsado.get(_colapsar(k))
        if it:
            return it
        # nomes com sufixo do imóvel: "AREA_DO_IMOVEL_FAZ_EXEMPLO" -> maior prefixo conhecido
        melhor = None
        for kk, item in self._indice.items():
            if len(kk) >= 6 and k.startswith(kk) and (melhor is None or len(kk) > len(melhor[0])):
                melhor = (kk, item)
        return melhor[1] if melhor else None

    def nome_legenda(self, nome_camada):
        it = self.procurar(nome_camada)
        return it["nome_legenda"] if it else None

    def papel(self, nome_camada):
        it = self.procurar(nome_camada)
        return it["papel"] if it else None


def ler_csv(caminho):
    with open(caminho, "rb") as fh:
        bruto = fh.read()
    texto = None
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = bruto.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    itens = []
    leitor = csv.DictReader(texto.splitlines(), delimiter=";")
    for linha in leitor:
        arq = (linha.get("arquivo") or "").strip()
        nome = (linha.get("nome_legenda") or "").strip()
        if not arq and not nome:
            continue
        papel = (linha.get("papel") or "uso_solo").strip().lower()
        itens.append({
            "arquivo": arq or nome,
            "nome_legenda": nome or arq,
            "apelidos": [a.strip() for a in (linha.get("apelidos") or "").split("|") if a.strip()],
            "papel": papel if papel in PAPEIS else "uso_solo",
            "grupo": (linha.get("grupo") or "").strip(),
        })
    return itens


def salvar_csv(itens, caminho):
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["arquivo", "nome_legenda", "apelidos", "papel", "grupo"])
        for it in itens:
            w.writerow([it["arquivo"], it["nome_legenda"], "|".join(it["apelidos"]), it["papel"], it.get("grupo", "")])
