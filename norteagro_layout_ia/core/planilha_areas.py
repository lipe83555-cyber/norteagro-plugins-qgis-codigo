# -*- coding: utf-8 -*-
"""Leitura da planilha de áreas gerada pelo plugin "Norte Agro - Uso do Solo" (Fase 4).

Este plugin não calcula área. Ele só lê os quadros já calculados e monta as
tabelas da planta no padrão de 4 blocos da Norte Agro:

  1. Áreas Remanescentes
  2. Área de Preservação Permanente
  3. Área Hidrográfica (Área Curso D'Água + uma linha por cacimba/barramento)
  4. Áreas Totais do Imóvel

O leitor de .xlsx usa só a biblioteca padrão do Python (zipfile + xml), para
não depender de openpyxl no Python do QGIS. Também aceita .csv
(Bloco;Descrição;Hectares) para preenchimento manual ou planilhas antigas.

Na planilha, cada quadro é: título numa célula, a linha seguinte com
"Descrição | Hectares", as linhas de itens e uma linha "Total". O total é
sempre recalculado pela soma dos itens (fórmulas sem valor salvo não
quebram a leitura); se o valor gravado no Excel divergir, gera alerta.
"""

import csv
import io
import os
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

BLOCOS = [
    ("remanescentes", "Áreas Remanescentes"),
    ("app", "Área de Preservação Permanente"),
    ("hidrografica", "Área Hidrográfica"),
    ("totais", "Áreas Totais do Imóvel"),
]
# quadros usados na Planta de Passivos e Regularização Ambiental
BLOCOS_PASSIVOS = [
    ("passivos", "Passivos ambientais"),
    ("antes_2019", "Área suprimida antes de 2019"),
    ("apos_2019", "Área suprimida após 2019"),
]
BLOCOS_EXTRAS = [("compensacao", "Área Total de Compensação")]
TITULO_BLOCO = dict(BLOCOS + BLOCOS_PASSIVOS + BLOCOS_EXTRAS)

# títulos aceitos (normalizados) para cada bloco
_SINONIMOS_BLOCO = {
    "remanescentes": ["areas remanescentes", "area remanescente", "remanescentes"],
    "app": ["area de preservacao permanente", "areas de preservacao permanente", "app",
            "preservacao permanente"],
    "hidrografica": ["area hidrografica", "areas hidrograficas", "hidrografia", "area hidrica"],
    "totais": ["areas totais do imovel", "area total do imovel", "areas totais", "imovel",
               "fechamento do imovel", "quadro do imovel"],
    "passivos": ["passivos ambientais", "passivos", "passivo ambiental"],
    "antes_2019": ["area antropizada antes de 2019", "area suprimida antes de 2019", "antropizada antes de 2019",
                   "supressao antes de 2019"],
    "apos_2019": ["area antropizada apos 2019", "area antropizada depois de 2019", "area suprimida apos 2019",
                  "area suprimida depois de 2019", "antropizada apos 2019", "supressao apos 2019"],
    "compensacao": ["area total de compensacao", "compensacao", "areas de compensacao"],
}

# nomes que a planilha usa e o nome que a planta mostra
RENOMEAR_LINHA = {
    "hidrografia": "Área Curso D'Água",
    "area curso d agua": "Área Curso D'Água",
    "curso d agua": "Área Curso D'Água",
}

ABA_PREFERIDA = "quadro de areas"
TOLERANCIA_HA = 0.0001


class ErroPlanilha(Exception):
    pass


def normalizar(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def bloco_do_titulo(titulo):
    n = normalizar(titulo)
    if not n:
        return None
    for chave, sinonimos in _SINONIMOS_BLOCO.items():
        if n in sinonimos:
            return chave
    # títulos personalizados pelo modelo de tabela do outro plugin
    if "remanescente" in n:
        return "remanescentes"
    if "preservacao permanente" in n or re.fullmatch(r"app( .*)?", n) and "suprimida" not in n:
        return "app"
    if "hidrograf" in n:
        return "hidrografica"
    if "totais" in n and "imovel" in n:
        return "totais"
    if "2019" in n and ("antes" in n):
        return "antes_2019"
    if "2019" in n and ("apos" in n or "depois" in n):
        return "apos_2019"
    if "passivo" in n:
        return "passivos"
    if "compensacao" in n:
        return "compensacao"
    return None


def para_numero(v):
    """Converte '1.234,5678', '1234.5678', 1234.5 e '' para float (ou None)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    s = re.sub(r"(?i)\s*(ha|hectares?)$", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def formatar_ha(valor, casas=4):
    """Hectares com vírgula decimal e sem separador de milhar (padrão das plantas)."""
    if valor is None:
        return ""
    return f"{float(valor):.{int(casas)}f}".replace(".", ",")


# ---------------------------------------------------------------- leitor .xlsx sem dependências
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _col_para_indice(letras):
    n = 0
    for ch in letras:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n


def _ref(ref):
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return int(m.group(2)), _col_para_indice(m.group(1))


def ler_xlsx(caminho):
    """Lê todas as abas: {nome_aba: {(linha, coluna): {"v": valor, "f": formula}}}.

    Valores numéricos vêm como float, textos como str. Linhas e colunas começam em 1.
    """
    try:
        z = zipfile.ZipFile(caminho)
    except (zipfile.BadZipFile, OSError) as e:
        raise ErroPlanilha(f"Não foi possível abrir a planilha '{os.path.basename(caminho)}': {e}. "
                           f"Confira se o arquivo é .xlsx e não está aberto/bloqueado no Excel.") from e
    with z:
        nomes = set(z.namelist())
        compartilhadas = []
        if "xl/sharedStrings.xml" in nomes:
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", _NS):
                compartilhadas.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        alvo_rel = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", _NS)}
        abas = {}
        for sh in wb.findall("m:sheets/m:sheet", _NS):
            nome = sh.get("name")
            rid = sh.get(f"{{{_NS['r']}}}id")
            alvo = alvo_rel.get(rid, "")
            alvo = alvo.lstrip("/")
            caminho_aba = alvo if alvo.startswith("xl/") else "xl/" + alvo
            if caminho_aba not in nomes:
                continue
            celulas = {}
            raiz = ET.fromstring(z.read(caminho_aba))
            for c in raiz.iter(f"{{{_NS['m']}}}c"):
                ref = c.get("r")
                if not ref:
                    continue
                tipo = c.get("t")
                v = c.find("m:v", _NS)
                f = c.find("m:f", _NS)
                valor = None
                if tipo == "s" and v is not None:
                    try:
                        valor = compartilhadas[int(v.text)]
                    except (ValueError, IndexError):
                        valor = None
                elif tipo == "inlineStr":
                    valor = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
                elif tipo in ("str", "e"):
                    valor = v.text if v is not None else None
                elif tipo == "b":
                    valor = (v.text == "1") if v is not None else None
                elif v is not None and v.text is not None:
                    try:
                        valor = float(v.text)
                    except ValueError:
                        valor = v.text
                celulas[_ref(ref)] = {"v": valor, "f": f.text if f is not None else None}
            abas[nome] = celulas
        return abas


def ler_csv(caminho):
    """CSV com colunas Bloco;Descrição;Hectares (separador ; ou ,). Retorna estrutura de quadros."""
    with open(caminho, "rb") as fh:
        bruto = fh.read()
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = bruto.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    amostra = texto[:2000]
    sep = ";" if amostra.count(";") >= amostra.count(",") else ","
    leitor = csv.reader(io.StringIO(texto), delimiter=sep)
    linhas = [r for r in leitor if any(x.strip() for x in r)]
    if not linhas:
        raise ErroPlanilha("CSV vazio.")
    cab = [normalizar(x) for x in linhas[0]]
    if "bloco" not in cab[0] and "quadro" not in cab[0]:
        raise ErroPlanilha("O CSV precisa das colunas: Bloco;Descrição;Hectares.")
    quadros = {}
    ordem = []
    for r in linhas[1:]:
        r = (r + ["", "", ""])[:3]
        titulo, desc, val = r[0].strip(), r[1].strip(), r[2].strip()
        if not titulo or not desc:
            continue
        q = quadros.get(titulo)
        if q is None:
            q = {"titulo": titulo, "itens": [], "total_planilha": None, "extras": [], "origem": "csv"}
            quadros[titulo] = q
            ordem.append(titulo)
        if normalizar(desc) == "total":
            q["total_planilha"] = para_numero(val)
        else:
            q["itens"].append((desc, para_numero(val)))
    return [quadros[t] for t in ordem]


def _texto_celula(cel):
    if not cel:
        return ""
    v = cel.get("v")
    if v is None:
        return ""
    if isinstance(v, float):
        return ""
    return str(v).strip()


def extrair_quadros(celulas):
    """Acha os quadros "Título / Descrição | Hectares / itens / Total" numa aba."""
    quadros = []
    if not celulas:
        return quadros
    max_linha = max(r for r, _ in celulas)
    for (r, c), cel in sorted(celulas.items()):
        if normalizar(_texto_celula(cel)) != "descricao":
            continue
        if normalizar(_texto_celula(celulas.get((r, c + 1)))) not in ("hectares", "area ha", "ha", "area"):
            continue
        titulo = _texto_celula(celulas.get((r - 1, c)))
        if not titulo:
            continue
        itens, extras, total, formulas = [], [], None, []
        achou_total = False
        linha = r + 1
        while linha <= max_linha:
            desc = _texto_celula(celulas.get((linha, c)))
            cel_val = celulas.get((linha, c + 1)) or {}
            if not desc and cel_val.get("v") is None:
                break
            if normalizar(desc) == "descricao":
                break
            # o título de outro quadro logo abaixo (sem linha em branco) encerra este
            prox = _texto_celula(celulas.get((linha + 1, c)))
            if normalizar(prox) == "descricao":
                break
            valor = cel_val.get("v")
            num = valor if isinstance(valor, float) else para_numero(valor)
            if normalizar(desc) == "total":
                total = num
                achou_total = True
            elif achou_total:
                extras.append((desc, num, cel_val.get("f")))
            else:
                itens.append((desc, num if num is not None else (0.0 if cel_val.get("f") else None)))
                if cel_val.get("f") and not num:
                    formulas.append(desc)
            linha += 1
        quadros.append({"titulo": titulo, "itens": itens, "total_planilha": total, "extras": extras,
                        "origem": f"linha {r - 1}", "formulas_sem_valor": formulas})
    return quadros


def encurtar_linha(chave, desc):
    """Nos quadros 'antes/após 2019' a planta não repete o período em cada linha."""
    if chave in ("antes_2019", "apos_2019"):
        return re.sub(r"\s+(antes\s+de|depois\s+de|ap[oó]s)\s+2019\s*$", "", desc, flags=re.I).strip() or desc
    return desc


def importar(caminho, casas=4, chaves=None):
    """Lê a planilha e devolve (blocos, avisos, aba).

    chaves: blocos que o modelo usa (padrão: os 4 da Planta de Uso do Solo).
    blocos = {"remanescentes": {"titulo", "linhas": [(desc, valor_float)], "total": float}, ...}
    Sempre traz os blocos pedidos; os não encontrados vêm vazios e geram aviso.
    """
    chaves = list(chaves or [k for k, _ in BLOCOS])
    avisos = []
    ext = os.path.splitext(caminho)[1].lower()
    if ext == ".csv":
        quadros = ler_csv(caminho)
        nome_aba = "CSV"
    elif ext in (".xlsx", ".xlsm"):
        abas = ler_xlsx(caminho)
        if not abas:
            raise ErroPlanilha("A planilha não tem abas legíveis.")
        nome_aba = None
        for nome in abas:
            if normalizar(nome) == ABA_PREFERIDA:
                nome_aba = nome
                break
        candidatas = [nome_aba] if nome_aba else list(abas)
        quadros = []
        for nome in candidatas:
            q = extrair_quadros(abas[nome])
            if any(bloco_do_titulo(x["titulo"]) for x in q):
                quadros = q
                nome_aba = nome
                break
        if not quadros:
            raise ErroPlanilha("Não encontrei os quadros de áreas (título, 'Descrição | Hectares' e 'Total'). "
                               "Use a planilha gerada pelo plugin 'Norte Agro - Uso do Solo' (aba 'Quadro de Áreas').")
    elif ext == ".xls":
        raise ErroPlanilha("Formato .xls antigo não é lido. Abra no Excel e salve como .xlsx.")
    else:
        raise ErroPlanilha("Escolha um arquivo .xlsx ou .csv.")

    blocos = {}
    ignorados = []
    for q in quadros:
        chave = bloco_do_titulo(q["titulo"])
        if not chave or chave not in chaves:
            ignorados.append(q["titulo"])
            continue
        if chave in blocos:
            avisos.append(f"Quadro '{q['titulo']}' repetido na planilha; usado o primeiro.")
            continue
        linhas = []
        for desc, val in q["itens"]:
            nome = RENOMEAR_LINHA.get(normalizar(desc), desc) if chave == "hidrografica" else encurtar_linha(chave, desc)
            if val is None:
                avisos.append(f"{TITULO_BLOCO[chave]}: linha '{desc}' sem valor numérico; considerada 0.")
                val = 0.0
            linhas.append((nome, float(val)))
        total = sum(v for _, v in linhas)
        for desc in q.get("formulas_sem_valor") or []:
            avisos.append(f"{TITULO_BLOCO[chave]}: a linha '{desc}' é uma fórmula sem resultado salvo (vale 0 na "
                          f"leitura). Abra a planilha no Excel, salve e importe de novo.")
        tp = q.get("total_planilha")
        if tp is not None and abs(round(total, casas) - round(tp, casas)) >= TOLERANCIA_HA:
            avisos.append(f"{TITULO_BLOCO[chave]}: total da planilha ({formatar_ha(tp, casas)}) difere da soma "
                          f"das linhas ({formatar_ha(total, casas)}). Usada a soma das linhas.")
        for desc, num, _f in q.get("extras", []):
            if normalizar(desc).startswith("area total do imovel") and num is not None \
                    and abs(round(num, casas) - round(total, casas)) >= TOLERANCIA_HA and num > 0:
                avisos.append(f"Áreas Totais do Imóvel: soma ({formatar_ha(total, casas)}) difere da "
                              f"Área Total do Imóvel da camada ({formatar_ha(num, casas)}). Confira o fechamento.")
            elif normalizar(desc).startswith("diferenca"):
                avisos.append(f"{TITULO_BLOCO[chave]}: a planilha marca diferença de fechamento.")
        blocos[chave] = {"titulo": TITULO_BLOCO[chave], "linhas": linhas, "total": total,
                         "titulo_planilha": q["titulo"]}

    for chave in chaves:
        titulo = TITULO_BLOCO.get(chave, chave)
        if chave not in blocos:
            avisos.append(f"Quadro '{titulo}' não encontrado na planilha: a tabela fica para preenchimento manual.")
            blocos[chave] = {"titulo": titulo, "linhas": [], "total": 0.0, "titulo_planilha": None,
                             "manual": True}
    blocos = {k: blocos[k] for k in chaves}
    if ignorados:
        avisos.append("Quadros da planilha que não entram neste modelo de planta: " + ", ".join(ignorados) + ".")
    return blocos, avisos, nome_aba


def blocos_vazios(chaves=None):
    """Estrutura para preenchimento manual (sem planilha)."""
    chaves = list(chaves or [k for k, _ in BLOCOS])
    padrao = {
        "passivos": ["Área Suprimida antes de 2019", "Área Suprimida depois de 2019"],
        "antes_2019": ["APP Suprimida", "Área de Reserva Legal Suprimida", "Supressão em Área Passível"],
        "apos_2019": ["APP Suprimida", "Área de Reserva Legal Suprimida", "Supressão em Área Passível"],
        "compensacao": ["Área de Compensação por Danos", "Área de Compensação Florestal", "Área de Recomposição"],
        "remanescentes": ["Área da Reserva Legal Proposta", "APP Preservada", "Área Fora da RL e APP"],
        "app": ["APP Preservada", "APP Consolidada", "APP Suprimida"],
        "hidrografica": ["Área Curso D'Água"],
        "totais": ["Área Suprimida", "Área Consolidada", "Área Remanescente", "Servidão Administrativa"],
    }
    return {k: {"titulo": TITULO_BLOCO[k], "linhas": [(d, None) for d in padrao.get(k, [])], "total": None,
                "manual": True} for k in chaves}


def linhas_tabela(bloco, casas=4, com_total=True):
    """Linhas de texto da tabela (sem cabeçalho de colunas): [[desc, valor], ..., ["Total", soma]]."""
    linhas = [[d, formatar_ha(v, casas) if v is not None else ""] for d, v in bloco["linhas"]]
    if com_total:
        total = bloco.get("total")
        linhas.append(["Total", formatar_ha(total, casas) if total is not None else ""])
    return linhas
