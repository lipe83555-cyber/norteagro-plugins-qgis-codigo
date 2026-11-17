# -*- coding: utf-8 -*-
"""Testes puros do reconhecimento e da consistência do catálogo.

Executar fora do QGIS:
    python testes_reconhecimento.py
"""
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
PAI = BASE.parent
if str(PAI) not in sys.path:
    sys.path.insert(0, str(PAI))

# O diretório da instalação pode ter outro nome. Criamos um pacote temporário pelo nome real.
PACOTE = BASE.name
catalogo = __import__(f"{PACOTE}.catalogo", fromlist=["*"])
rec = __import__(f"{PACOTE}.reconhecimento", fromlist=["*"])

ENTRADAS = catalogo.catalogo_fixo_lista({})
INDICE = {e["arquivo"]: e for e in ENTRADAS}
APELIDOS = rec.gerar_apelidos_padrao(ENTRADAS)
ALIAS, AMBIGUOS = rec.indice_apelidos(APELIDOS, {}, set(INDICE))
MUNICIPIOS = {rec.normalizar_chave(x) for x in catalogo.MUNICIPIOS_GOIAS_NOMES}


def reconhecer(texto):
    return rec.reconhecer_texto([texto], INDICE, ALIAS, APELIDOS, MUNICIPIOS)


def sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def duplicar_letra(texto):
    # Duplica uma letra no fim do último token (LEGALL, CONSOLIDADAA etc.).
    # Para APP, usa explicitamente APPP, caso real coberto pelo normalizador.
    if texto.startswith("APP_"):
        return "APPP_" + texto[4:]
    for i in range(len(texto)-1, -1, -1):
        c = texto[i]
        if c.isalpha():
            return texto[:i+1] + c + texto[i+1:]
    return texto


def assert_destino(texto, esperado):
    got = reconhecer(texto)
    assert got.get("arquivo") == esperado, f"{texto!r}: esperado {esperado}; obtido {got}"


def testar_catalogo_inteiro():
    """Cada fixa volta ao mesmo ARQUIVO pelas variações exigidas."""
    for e in ENTRADAS:
        arq = e["arquivo"]
        nome = e["nome"]
        pasta = catalogo.limpar_nome_pasta(nome)
        variacoes = {
            arq,
            arq.lower(),
            "00_" + arq,
            arq.replace("_", " "),
            nome,
            nome.lower(),
            sem_acento(nome),
            pasta,
            duplicar_letra(arq),
        }
        if "SUPRIMIDA" in arq:
            variacoes.add(arq.replace("SUPRIMIDA", "ANTROPIZADA"))
            variacoes.add(arq.replace("SUPRIMIDA", "SUPRESSAO"))
        for texto in variacoes:
            assert_destino(texto, arq)


def testar_tokens_criticos():
    for e in ENTRADAS:
        arq = e["arquivo"]
        if "ANTES" in arq:
            got = reconhecer(arq.replace("ANTES", "DEPOIS"))
            assert got.get("arquivo") != arq, f"ANTES/DEPOIS confundidos em {arq}: {got}"
        if arq.startswith("APP_"):
            got = reconhecer(arq.replace("APP", "RESERVA", 1))
            assert got.get("arquivo") != arq, f"APP/RESERVA confundidos em {arq}: {got}"


def testar_totais_e_familias():
    casos = {
        "ÁREA ANTROPIZADA": "AREA_SUPRIMIDA",
        "area_antropizada": "AREA_SUPRIMIDA",
        "AREA SUPRIMIDA": "AREA_SUPRIMIDA",
        "SUPRESSAO": "AREA_SUPRIMIDA",
        "APP ANTROPIZADA": "APP_SUPRIMIDA",
        "app_suprimida": "APP_SUPRIMIDA",
        "SUPRESSÃO EM RESERVA LEGAL": "RESERVA_SUPRIMIDA",
        "SUPRESSÃO EM ÁREA PASSÍVEL": "SUPRESSAO_PASSIVEL_TOTAL",
        "SUPRESSÃO EM ÁREA PASSÍVEL - ANTES DE 2019": "SUPRESSAO_PASSIVEL_ANTES_2019",
        "SUPRESSÃO EM ÁREA PASSÍVEL - APÓS 2019": "SUPRESSAO_PASSIVEL_DEPOIS_2019",
        "ÁREA ANTROPIZADA ANTES DE 2019": "AREA_SUPRIMIDA_ANTES_2019",
        "ÁREA ANTROPIZADA APÓS 2019": "AREA_SUPRIMIDA_DEPOIS_2019",
    }
    for texto, destino in casos.items():
        assert_destino(texto, destino)

    # Área Passível nunca deve cair na família Área Suprimida.
    for texto in (
        "SUPRESSÃO EM ÁREA PASSÍVEL",
        "SUPRESSÃO EM ÁREA PASSÍVEL - ANTES DE 2019",
        "SUPRESSÃO EM ÁREA PASSÍVEL - APÓS 2019",
    ):
        got = reconhecer(texto)
        assert not got.get("arquivo", "").startswith("AREA_SUPRIMIDA"), (texto, got)


def testar_casos_reais():
    casos = {
        "reserva_legall": "RESERVA_LEGAL",
        "appp": "APP_TOTAL",
        "area_consoolidada": "AREA_CONSOLIDADA",
        "area_de_vegetacao_nativaa": "AREA_DE_VEGETACAO",
        "REMANESCENTE DE VEGETAÇÃO NATIVA": "AREA_DE_VEGETACAO",
        "Cacimbaa": "CACIMBA",
        "imovel": "AREA_DO_IMOVEL",
        "AREA DE IMOVEL": "AREA_DO_IMOVEL",
        "ÁREA DO IMÓVEL": "AREA_DO_IMOVEL",
        "area_suprimida_depois_de_20199": "AREA_SUPRIMIDA_DEPOIS_2019",
        "area_suprimida_totall": "AREA_SUPRIMIDA",
        "SUPRESSAO_APOS_2019_DAI": "AREA_SUPRIMIDA_DEPOIS_2019",
        "ÁREA ANTROPIZADA": "AREA_SUPRIMIDA",
        "ÁREA ANTROPIZADA APÓS 2019": "AREA_SUPRIMIDA_DEPOIS_2019",
        "AREA_ANTROPIZADA_ANTES_DE_2019": "AREA_SUPRIMIDA_ANTES_2019",
        "APP_ANTROPIZADA_APOS_2019": "APP_ANTROPIZADA_APOS_2019",
        "APP_ANTROPIZADA_ANTES_DE_2019": "APP_ANTROPIZADA_ANTES_2019",
        "SUPRESSÃO EM RESERVA LEGAL": "RESERVA_SUPRIMIDA",
        "SUPRESSÃO EM ÁREA PASSÍVEL": "SUPRESSAO_PASSIVEL_TOTAL",
        "SUPRESSÃO EM ÁREA PASSÍVEL - ANTES DE 2019": "SUPRESSAO_PASSIVEL_ANTES_2019",
        "SUPRESSÃO EM ÁREA PASSÍVEL - APÓS 2019": "SUPRESSAO_PASSIVEL_DEPOIS_2019",
        "barramento": "BARRAGEM",
        "Barramentos": "BARRAGEM",
        "nascente": "NASCENTE",
        "Nascentes": "NASCENTE",
    }
    for texto, destino in casos.items():
        assert_destino(texto, destino)

    # Não existem as variantes temporais de Reserva Suprimida no catálogo fixo.
    pendente = reconhecer("SUPRESSAO_RL_ANTES2019")
    assert not pendente.get("arquivo"), f"Destino inexistente foi inventado: {pendente}"

    amaralina = reconhecer("amaralina")
    assert amaralina.get("referencia") and not amaralina.get("arquivo"), amaralina


def testar_catalogo():
    assert len(ENTRADAS) == 42  # v0.7.0: 37 + 5 do grupo SEMAD - SIGA (murundus foram para a camada Murundus do Uso do Solo)
    assert len(catalogo.MUNICIPIOS_GOIAS_NOMES) == 246
    assert not AMBIGUOS, f"Apelidos ambíguos: {AMBIGUOS}"
    assert not catalogo.camadas_sem_nome_planilha(), catalogo.camadas_sem_nome_planilha()

    auditoria = catalogo.verificar_catalogo(None, catalogo._estado_vazio())
    assert auditoria["problemas"] == [], auditoria
    assert auditoria["invalidos"] == set(), auditoria

    nomes = [e["nome"] for e in ENTRADAS]
    pastas = [catalogo.limpar_nome_pasta(x) for x in nomes]
    assert len({rec.normalizar_chave(x) for x in nomes}) == len(nomes), "Nome de exibição repetido"
    assert len({rec.normalizar_chave(x) for x in pastas}) == len(pastas), "Pasta da camada repetida"
    assert catalogo.ARQUIVOS_LOGICA <= set(INDICE), catalogo.ARQUIVOS_LOGICA - set(INDICE)
    cfg = catalogo.configuracao_geometrica(catalogo._estado_vazio())
    assert cfg["fechamento"] == catalogo.FECHAMENTO_PADRAO, cfg
    assert set(cfg["fechamento"]) <= set(INDICE), set(cfg["fechamento"]) - set(INDICE)
    assert cfg["fechamento_inclui_hidrografia"] is False
    assert cfg["nao_recortar"] == []

    faltantes = catalogo.itens_planilha_sem_camada(catalogo._estado_vazio())
    assert faltantes == [
        "Área de Reserva Legal Suprimida antes de 2019",
        "Área de Reserva Legal Suprimida depois de 2019",
    ], faltantes


def main():
    testar_catalogo()
    testar_catalogo_inteiro()
    testar_tokens_criticos()
    testar_totais_e_familias()
    testar_casos_reais()
    total_alias = sum(len(v) for v in APELIDOS.values())
    print(
        f"OK - {len(ENTRADAS)} camadas, {total_alias} apelidos, "
        f"{len(MUNICIPIOS)} municípios, {len(AMBIGUOS)} ambiguidades, catálogo consistente."
    )


if __name__ == "__main__":
    main()
