# -*- coding: utf-8 -*-
"""Reconhecimento textual de camadas, sem dependências do QGIS.

Este módulo é propositalmente puro: a mesma normalização é usada no cálculo,
nas buscas das telas e nos testes executados fora do QGIS.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from itertools import product

LIGACOES = {"DE", "DA", "DO", "DAS", "DOS", "EM", "E", "NA", "NO", "POR"}
CRITICOS = {
    "ANTES", "DEPOIS", "2008", "2019", "APP", "RESERVA", "RESERVA_LEGAL",
    "SUPRIMIDA", "TOTAL", "CONSOLIDADA", "PRESERVADA", "PASSIVEL", "VEGETACAO",
    "IMOVEL", "GLEBAS", "ENCRAVADA", "SERVIDAO", "RECOMPOSICAO", "COMPENSACAO",
    "DANOS", "FLORESTAL", "LICENCIADA", "EMBARGADA",
}
REFERENCIA_TOKENS = {
    "MUNICIPIO", "MUNICIPAL", "LIMITE", "ESTADO", "UF", "SICAR", "SIGEF",
    "SNCI", "INCRA", "IBGE", "GEONODE",
}


def _sem_acento(texto):
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")


def _corrigir_anos(texto):
    """Separa qualificadores do ano e corrige dígito final repetido."""
    texto = re.sub(r"(?<![A-Z0-9])(ANTES|APOS|DEPOIS|POS)(20\d{2,3})(?![A-Z0-9])", r"\1_\2", texto)

    def corrigir(m):
        base, extra = m.group(1), m.group(2)
        return base if base[-1] == extra else m.group(0)

    return re.sub(r"(?<![A-Z0-9])(20\d{2})(\d)(?![A-Z0-9])", corrigir, texto)


def _colapsar_token(token):
    """Colapsa repetições típicas de digitação; a canonicalização seguinte repara termos legítimos."""
    if re.fullmatch(r"AP{2,}", token):
        return "APP"
    return re.sub(r"([A-Z])\1+", r"\1", token)


def normalizar_chave(texto):
    """Normalização forte e simétrica usada em nomes, pastas, aliases e ARQUIVOs."""
    s = _sem_acento(texto).upper().strip()
    s = re.sub(r"^00[_\s-]+", "", s)
    anterior = None
    while anterior != s:
        anterior = s
        s = re.sub(r"(?:\s+(?:COPIAR|COPY)|[_\s]*\(\d+\)|_\d{1,2})\s*$", "", s).strip()
    s = _corrigir_anos(s)
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    tokens = [_colapsar_token(x) for x in s.split("_") if x]
    tokens = [x for x in tokens if x not in LIGACOES]

    sinonimos = {
        "ANTROPIZADA": "SUPRIMIDA", "ANTROPIZADO": "SUPRIMIDA",
        "SUPRESSAO": "SUPRIMIDA", "SUPRESAO": "SUPRIMIDA",
        "SUPRESSO": "SUPRIMIDA", "SUPRESO": "SUPRIMIDA",
        "SUPRIMIDO": "SUPRIMIDA", "SUPRIMIDA": "SUPRIMIDA",
        "APOS": "DEPOIS", "POS": "DEPOIS", "DEPOIS": "DEPOIS",
        "PASSIVEL": "PASSIVEL", "PASIVEL": "PASSIVEL", "PASSIVEIS": "PASSIVEL", "PASIVEIS": "PASSIVEL",
        "PERIMETRO": "IMOVEL",
        "BARAGEM": "BARRAMENTO", "BARAMENTO": "BARRAMENTO", "BARAMENTOS": "BARRAMENTO",
        "BARRAGEM": "BARRAMENTO", "BARRAMENTO": "BARRAMENTO", "BARRAMENTOS": "BARRAMENTO",
        "NASCENTE": "NASCENTE", "NASCENTES": "NASCENTE",
        # v3.9.4: nomes que perderam as letras acentuadas ao passar por e-mail/ZIP/DAI
        # (ex.: "supresso_em_rea_passvel_aps_2019"). Tokens já com letras repetidas colapsadas.
        "REA": "AREA", "PASVEL": "PASSIVEL", "APS": "DEPOIS", "VEGETAO": "VEGETACAO",
        "PRESERVAO": "PRESERVACAO", "IMVEL": "IMOVEL", "COMPENSAO": "COMPENSACAO",
        "RECOMPOSIO": "RECOMPOSICAO", "SERVIDO": "SERVIDAO", "HIDROGRAFA": "HIDROGRAFIA",
    }
    tokens = [sinonimos.get(x, x) for x in tokens]

    # RL isolado equivale à expressão Reserva Legal.
    expandidos = []
    for tok in tokens:
        if tok == "RL":
            expandidos.extend(["RESERVA", "LEGAL"])
        else:
            expandidos.append(tok)
    tokens = expandidos

    # VEGETAÇÃO NATIVA / REMANESCENTE DE VEGETAÇÃO NATIVA -> VEGETACAO.
    if "VEGETACAO" in tokens and ("NATIVA" in tokens or "REMANESCENTE" in tokens):
        tokens = [x for x in tokens if x not in {"NATIVA", "REMANESCENTE"}]

    # AREA IMOVEL / AREA TOTAL IMOVEL / PERIMETRO -> IMOVEL.
    if "IMOVEL" in tokens:
        tokens = [x for x in tokens if x not in {"AREA", "TOTAL"}]

    # "Supressão em Área Passível" e o ARQUIVO SUPRESSAO_PASSIVEL_* precisam da mesma chave.
    if "PASSIVEL" in tokens:
        tokens = [x for x in tokens if x != "AREA"]

    # TOTAL implícito dentro da mesma família. Reserva suprimida é a variante sem período
    # do catálogo e, por isso, não recebe o token TOTAL.
    tem_periodo = any(x in tokens for x in ("ANTES", "DEPOIS", "2008", "2019"))
    if "SUPRIMIDA" in tokens and not tem_periodo and "TOTAL" not in tokens:
        if "RESERVA" not in tokens:
            tokens.append("TOTAL")

    return "_".join(tokens)


def chaves_texto(texto):
    """Chave do texto inteiro e, havendo rótulo/arquivo, também das partes separadas."""
    bruto = str(texto or "")
    partes = [bruto]
    if "\u2014" in bruto or "\u2013" in bruto or re.search(r"\s-\s", bruto):
        partes.extend(re.split(r"\s*(?:\u2014|\u2013)\s*|\s+-\s+", bruto))
    saida = []
    for parte in partes:
        chave = normalizar_chave(parte)
        if chave and chave not in saida:
            saida.append(chave)
    return saida


def _variantes_sinonimos(chave):
    if not chave:
        return set()
    opcoes = []
    for tok in chave.split("_"):
        if tok == "SUPRIMIDA":
            opcoes.append(["SUPRIMIDA", "SUPRESSAO", "ANTROPIZADA"])
        elif tok == "DEPOIS":
            opcoes.append(["DEPOIS", "APOS", "POS"])
        elif tok == "BARRAMENTO":
            opcoes.append(["BARRAMENTO", "BARRAGEM"])
        else:
            opcoes.append([tok])
    return {"_".join(p) for p in product(*opcoes)}


def _singular_plural(chave):
    if not chave:
        return set()
    partes = chave.split("_")
    ultimo = partes[-1]
    out = {chave}
    if len(ultimo) > 3 and not ultimo.isdigit():
        if ultimo.endswith("S"):
            out.add("_".join(partes[:-1] + [ultimo[:-1]]))
        else:
            out.add("_".join(partes[:-1] + [ultimo + "S"]))
    return out


def gerar_apelidos_para(arquivo, nome):
    """Gera apelidos por regras a partir do ARQUIVO e do nome de exibição."""
    canon_arq = normalizar_chave(arquivo)
    canon_nome = normalizar_chave(nome)
    sementes = {canon_arq, canon_nome}

    for base in list(sementes):
        if base.startswith("AREA_"):
            sementes.add(base[5:])
        elif base and not base.startswith(("APP_", "RESERVA_", "SUPRIMIDA_")):
            sementes.add("AREA_" + base)

    if arquivo == "APP_TOTAL":
        sementes.update({"APP", "PRESERVACAO_PERMANENTE", "AREA_PRESERVACAO_PERMANENTE"})
    if arquivo.startswith("APP_"):
        restante = canon_arq[4:] if canon_arq.startswith("APP_") else canon_arq
        sementes.update({f"PRESERVACAO_PERMANENTE_{restante}", f"AREA_PRESERVACAO_PERMANENTE_{restante}"})

    if arquivo == "RESERVA_LEGAL":
        sementes.update({"RL", "AREA_RESERVA_LEGAL", "RESERVA_LEGAL"})
    if arquivo == "RESERVA_SUPRIMIDA":
        # Sem período. As variantes temporais NÃO apontam para esta camada.
        sementes.update({"SUPRIMIDA_RESERVA_LEGAL", "SUPRESSAO_RESERVA_LEGAL", "SUPRESSAO_RL", "SUPRIMIDA_RL"})

    if arquivo == "AREA_DE_VEGETACAO":
        sementes.update({
            "VEGETACAO", "VEGETACAO_NATIVA", "REMANESCENTE", "REMANESCENTE_VEGETACAO_NATIVA",
            "AREA_VEGETACAO_NATIVA", "AREA_REMANESCENTE_VEGETACAO_NATIVA",
        })
    if arquivo == "BARRAGEM":
        sementes.update({"BARRAGEM", "BARRAMENTO", "BARRAMENTOS", "AREA_BARRAGEM", "AREA_BARRAMENTO"})
    if arquivo == "NASCENTE":
        sementes.update({"NASCENTE", "NASCENTES", "AREA_NASCENTE", "AREA_NASCENTES"})
    if arquivo == "AREA_DO_IMOVEL":
        sementes.update({"IMOVEL", "AREA_IMOVEL", "AREA_TOTAL_IMOVEL", "PERIMETRO", "PERIMETRO_IMOVEL"})

    if arquivo == "AREA_SUPRIMIDA":
        sementes.update({"AREA_SUPRIMIDA", "SUPRIMIDA", "SUPRESSAO", "ANTROPIZADA", "AREA_ANTROPIZADA",
                         "AREA_SUPRIMIDA_TOTAL", "SUPRIMIDA_TOTAL", "SUPRESSAO_TOTAL", "ANTROPIZADA_TOTAL"})
    if arquivo == "APP_SUPRIMIDA":
        sementes.update({"APP_SUPRIMIDA", "APP_SUPRESSAO", "APP_ANTROPIZADA",
                         "APP_SUPRIMIDA_TOTAL", "APP_SUPRESSAO_TOTAL", "APP_ANTROPIZADA_TOTAL"})
    if arquivo == "SUPRESSAO_PASSIVEL_TOTAL":
        sementes.update({"SUPRESSAO_AREA_PASSIVEL", "SUPRIMIDA_AREA_PASSIVEL", "SUPRESSAO_PASSIVEL",
                         "SUPRESSAO_AREA_PASSIVEL_TOTAL", "SUPRESSAO_PASSIVEL_TOTAL"})
    if arquivo == "SUPRESSAO_PASSIVEL_ANTES_2019":
        sementes.update({"SUPRESSAO_AREA_PASSIVEL_ANTES_2019", "SUPRIMIDA_AREA_PASSIVEL_ANTES_2019"})
    if arquivo == "SUPRESSAO_PASSIVEL_DEPOIS_2019":
        sementes.update({"SUPRESSAO_AREA_PASSIVEL_APOS_2019", "SUPRESSAO_AREA_PASSIVEL_DEPOIS_2019",
                         "SUPRIMIDA_AREA_PASSIVEL_APOS_2019", "SUPRIMIDA_AREA_PASSIVEL_DEPOIS_2019"})

    expandidos = set()
    for semente in sementes:
        for var in _variantes_sinonimos(normalizar_chave(semente)):
            expandidos.update(_singular_plural(normalizar_chave(var)))

    # ARQUIVO e nome de exibição ficam na etapa "nome"; aliases são só alternativas.
    expandidos.discard(canon_arq)
    expandidos.discard(canon_nome)
    return sorted(x for x in expandidos if x)


def gerar_apelidos_padrao(entradas):
    return {e["arquivo"]: gerar_apelidos_para(e["arquivo"], e.get("nome", e["arquivo"])) for e in entradas}


def indice_apelidos(apelidos_por_arquivo, apelidos_escritorio=None, arquivos_validos=None):
    """Cria apelido normalizado -> ARQUIVO e remove automaticamente qualquer colisão."""
    destinos = {}
    for arquivo, apelidos in (apelidos_por_arquivo or {}).items():
        if arquivos_validos is not None and arquivo not in arquivos_validos:
            continue
        for apelido in apelidos:
            for chave in chaves_texto(apelido):
                destinos.setdefault(chave, set()).add(arquivo)
    for apelido, arquivo in (apelidos_escritorio or {}).items():
        if arquivos_validos is not None and arquivo not in arquivos_validos:
            continue
        for chave in chaves_texto(apelido):
            destinos.setdefault(chave, set()).add(arquivo)
    ambiguos = {k: sorted(v) for k, v in destinos.items() if len(v) > 1}
    indice = {k: next(iter(v)) for k, v in destinos.items() if len(v) == 1}
    return indice, ambiguos


def assinatura_critica(chave):
    partes = set((chave or "").split("_"))
    sig = {x for x in CRITICOS if x in partes}
    if "RESERVA" in partes and "LEGAL" in partes:
        sig.add("RESERVA_LEGAL")
    return sig


def melhor_semelhanca(chaves, entradas, apelidos_por_arquivo=None):
    """Último recurso: razão >=0,88, margem >=0,05 e assinatura crítica idêntica."""
    candidatos = []
    for arquivo, entrada in entradas.items():
        variantes = set(chaves_texto(arquivo)) | set(chaves_texto(entrada.get("nome", "")))
        variantes.update((apelidos_por_arquivo or {}).get(arquivo, []))
        melhor = 0.0
        for origem in chaves:
            sig_o = assinatura_critica(origem)
            for cand in variantes:
                cand = normalizar_chave(cand)
                if assinatura_critica(cand) != sig_o:
                    continue
                melhor = max(melhor, SequenceMatcher(None, origem, cand).ratio())
        candidatos.append((melhor, arquivo))
    candidatos.sort(reverse=True)
    if not candidatos:
        return None, 0.0, 0.0
    r1, a1 = candidatos[0]
    r2 = candidatos[1][0] if len(candidatos) > 1 else 0.0
    if r1 >= 0.88 and (r1 - r2) >= 0.05:
        return a1, r1, r2
    return None, r1, r2


def nome_parece_referencia(texto, municipios_normalizados=None):
    """Filtro textual de município/base externa; município é comparação exata da chave inteira."""
    chaves = chaves_texto(texto)
    municipios = municipios_normalizados or set()
    for chave in chaves:
        if chave in municipios:
            return True
        tokens = set(chave.split("_"))
        if tokens & REFERENCIA_TOKENS:
            return True
        if "CAR_" in chave or chave.startswith("CAR_") or "_CAR_" in f"_{chave}_":
            return True
        if "BASE_" in chave or chave.startswith("BASE_") or "_BASE_" in f"_{chave}_":
            return True
    return False


def eh_pendente_area_passivel(chave):
    """Mantida só por compatibilidade: Área Passível tem destinos definidos na v3.7 atual."""
    return False


def reconhecer_texto(textos, entradas, alias_indice, apelidos_por_arquivo, municipios=None):
    """Reconhecimento puro usado nos testes e como núcleo lógico do fluxo QGIS."""
    chaves = []
    for texto in textos:
        for chave in chaves_texto(texto):
            if chave not in chaves:
                chaves.append(chave)
    if any(nome_parece_referencia(c, municipios) for c in chaves):
        return {"arquivo": "", "via": "referência", "razao": 0.0, "referencia": True}
    for chave in chaves:
        if chave in alias_indice:
            return {"arquivo": alias_indice[chave], "via": "apelido", "razao": 1.0, "referencia": False}
    canon = {}
    for arq, entrada in entradas.items():
        for chave in chaves_texto(arq) + chaves_texto(entrada.get("nome", "")):
            canon.setdefault(chave, arq)
    for chave in chaves:
        if chave in canon:
            return {"arquivo": canon[chave], "via": "nome", "razao": 1.0, "referencia": False}
    arq, r1, _ = melhor_semelhanca(chaves, entradas, apelidos_por_arquivo)
    return {"arquivo": arq or "", "via": "semelhança" if arq else "não reconhecida", "razao": r1, "referencia": False}
