# -*- coding: utf-8 -*-
"""Leitura dos documentos do imóvel para preencher os "Dados do imóvel".

Documentos reconhecidos:
  - Recibo de inscrição no CAR do SIGCAR (Goiás) e do SICAR (federal)
  - Certidão de inteiro teor da matrícula (cartório, PDF com texto)

Campos: propriedade, proprietário, CAR, município (+ UF) e matrícula.

Tudo o que é encontrado vem como SUGESTÃO, com o trecho de origem, e só vai
para o layout depois que o usuário confere na tela. PDF digitalizado (só
imagem) não tem texto: o plugin avisa e o usuário digita (ou usa o OCR do
ambiente de suporte).
"""

import csv
import os
import re
import unicodedata

from . import pdf_texto

_PASTA_DADOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dados")
UF_POR_CODIGO = {
    "11": ("RO", "Rondônia"), "12": ("AC", "Acre"), "13": ("AM", "Amazonas"), "14": ("RR", "Roraima"),
    "15": ("PA", "Pará"), "16": ("AP", "Amapá"), "17": ("TO", "Tocantins"), "21": ("MA", "Maranhão"),
    "22": ("PI", "Piauí"), "23": ("CE", "Ceará"), "24": ("RN", "Rio Grande do Norte"), "25": ("PB", "Paraíba"),
    "26": ("PE", "Pernambuco"), "27": ("AL", "Alagoas"), "28": ("SE", "Sergipe"), "29": ("BA", "Bahia"),
    "31": ("MG", "Minas Gerais"), "32": ("ES", "Espírito Santo"), "33": ("RJ", "Rio de Janeiro"),
    "35": ("SP", "São Paulo"), "41": ("PR", "Paraná"), "42": ("SC", "Santa Catarina"),
    "43": ("RS", "Rio Grande do Sul"), "50": ("MS", "Mato Grosso do Sul"), "51": ("MT", "Mato Grosso"),
    "52": ("GO", "Goiás"), "53": ("DF", "Distrito Federal"),
}
UF_POR_SIGLA = {s: n for s, n in UF_POR_CODIGO.values()}

_PARTICULAS = {"de", "da", "das", "do", "dos", "e", "em", "na", "no", "ou", "a", "o", "outros", "outras"}
_SIGLAS = {"ltda", "me", "epp", "eireli", "s/a", "sa", "s.a.", "cia"}


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", _sem_acento(s).lower()).strip()


def titulo(s):
    """'WILIAM BATISTA ROSA' -> 'Wiliam Batista Rosa'; 'IRMÃOS OLIVEIRA LTDA' -> 'Irmãos Oliveira Ltda'."""
    palavras = re.split(r"(\s+)", str(s or "").strip())
    out = []
    primeira = True
    for p in palavras:
        if not p.strip():
            out.append(p)
            continue
        low = p.lower()
        if not primeira and low in _PARTICULAS:
            out.append(low)
        elif low in _SIGLAS:
            out.append({"ltda": "Ltda", "me": "ME", "epp": "EPP", "eireli": "EIRELI", "s/a": "S/A",
                        "sa": "S.A.", "s.a.": "S.A.", "cia": "Cia"}[low])
        elif re.fullmatch(r"[ivx]+", low) and len(low) <= 4:
            out.append(p.upper())
        else:
            out.append("-".join(x[:1].upper() + x[1:] for x in low.split("-")))
        primeira = False
    return "".join(out)


def carregar_municipios():
    caminho = os.path.join(_PASTA_DADOS, "municipios_ibge_go.csv")
    mun = {}
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as fh:
            for linha in csv.DictReader(fh, delimiter=";"):
                mun[linha["codigo_ibge"]] = linha["municipio"]
    return mun


_MUNICIPIOS = None


def municipios():
    global _MUNICIPIOS
    if _MUNICIPIOS is None:
        _MUNICIPIOS = carregar_municipios()
    return _MUNICIPIOS


def municipio_por_nome(texto):
    """Acha o município de Goiás citado no texto (maior nome que casar)."""
    alvo = " " + _norm(texto) + " "
    melhor = None
    for cod, nome in municipios().items():
        n = " " + _norm(nome) + " "
        if n in alvo and (melhor is None or len(nome) > len(melhor[1])):
            melhor = (cod, nome)
    return melhor


# ---------------------------------------------------------------- CAR
_RE_CAR = re.compile(r"\b([A-Z]{2})\s*-\s*(\d{7})\s*-\s*((?:[0-9A-F]{4}\.?){7}[0-9A-F]{4})\b", re.I)


def formatar_car(uf, cod, hexa):
    h = re.sub(r"[^0-9A-F]", "", hexa.upper())
    return f"{uf.upper()}-{cod}-" + ".".join(h[i:i + 4] for i in range(0, len(h), 4))


def achar_car(texto):
    m = _RE_CAR.search(texto or "")
    if not m:
        return None
    return formatar_car(m.group(1), m.group(2), m.group(3)), m.group(2)


class Campo:
    def __init__(self, valor, documento, trecho="", confianca="alta", alternativas=None):
        self.valor = valor
        self.documento = documento
        self.trecho = trecho
        self.confianca = confianca
        self.alternativas = list(alternativas or [])

    def como_dict(self):
        return {"valor": self.valor, "documento": self.documento, "trecho": self.trecho,
                "confianca": self.confianca, "alternativas": self.alternativas}


def _linha_apos(linhas, rotulo_regex, salto=1):
    for i, l in enumerate(linhas):
        if re.search(rotulo_regex, l, re.I):
            for j in range(i + salto, min(i + salto + 3, len(linhas))):
                if linhas[j].strip():
                    return linhas[j].strip(), l.strip()
    return None, None


def _tipo(texto):
    t = _norm(texto[:4000])
    if "recibo de inscricao" in t and "car" in t:
        return "recibo_sigcar" if "sigcar" in _norm(texto) or "nome razao social" in t else "recibo_sicar"
    if "demonstrativo" in t and "car" in t:
        return "demonstrativo_car"
    if "matricula" in t and ("certid" in t or "registro de imoveis" in t or "cartorio" in t or "imovel" in t):
        return "matricula"
    return "desconhecido"


def _ler_recibo_sigcar(texto, nome_doc):
    campos = {}
    linhas = [l for l in texto.splitlines()]
    # proprietários: entre o cabeçalho "Nome/Razão Social CPF/CNPJ" e "Dados Gerais"
    nomes = []
    dentro = False
    for l in linhas:
        if re.search(r"Nome\s*/\s*Raz[aã]o\s+Social", l, re.I):
            dentro = True
            continue
        if dentro:
            if re.search(r"Dados\s+Gerais|Dados\s+do\s+Im[oó]vel", l, re.I):
                break
            nome = re.sub(r"\s*(\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\s*$", "", l).strip()
            if nome and re.search(r"[A-Za-zÀ-ú]{2}", nome):
                nomes.append(nome)
    if nomes:
        valor = nomes[0] if len(nomes) == 1 else f"{nomes[0]} e outros"
        campos["proprietario"] = Campo(valor, nome_doc, "Proprietário/Possuidor: " + "; ".join(nomes[:3]),
                                       "alta" if len(nomes) == 1 else "média",
                                       alternativas=nomes + ([", ".join(nomes)] if len(nomes) > 1 else []))
    car = achar_car(texto)
    if car:
        campos["car"] = Campo(car[0], nome_doc, "Nº Recibo Federal")
    imovel, rot = _linha_apos(linhas, r"^\s*Nome\s+do\s+Im[oó]vel\s*$")
    if imovel:
        campos["imovel"] = Campo(re.sub(r"\s{2,}", " ", imovel), nome_doc, "Nome do Imóvel")
    mun_linha, _ = _linha_apos(linhas, r"^\s*Munic[ií]pio\s+UF\s*$")
    _municipio(campos, mun_linha, car, nome_doc)
    mat = re.search(r"Matr[ií]cula\s+[\d.,]+\s+Certid[aã]o\s+de\s+registro\s*([\d.,\s/-]+)", texto, re.I)
    if mat:
        nums = [n.strip() for n in re.split(r"[,;]", mat.group(1)) if n.strip()]
        if nums:
            campos["matricula"] = Campo(", ".join(nums), nome_doc, "Documentação das Áreas do Imóvel",
                                        "média")
    return campos


def _ler_recibo_sicar(texto, nome_doc):
    """Recibo federal (SICAR): rótulos 'Nome do Imóvel Rural:', 'Município:', 'Registro no CAR:' ..."""
    campos = {}
    m = re.search(r"Nome\s+do\s+Im[oó]vel(?:\s+Rural)?\s*:?\s*\n?\s*(.+)", texto, re.I)
    if m and m.group(1).strip():
        campos["imovel"] = Campo(m.group(1).strip(), nome_doc, "Nome do Imóvel Rural")
    car = achar_car(texto)
    if car:
        campos["car"] = Campo(car[0], nome_doc, "Registro no CAR")
    m = re.search(r"(?:Nome|Propriet[aá]rio[^:\n]*)\s*:\s*([A-ZÀ-Ú][A-ZÀ-Ú .'-]{3,})", texto)
    if m:
        campos["proprietario"] = Campo(m.group(1).strip(), nome_doc, "Proprietário/Possuidor", "média")
    m = re.search(r"Munic[ií]pio\s*:\s*(.+)", texto, re.I)
    _municipio(campos, m.group(1) if m else None, car, nome_doc)
    return campos


def _municipio(campos, linha_mun, car, nome_doc):
    cod = car[1] if car else None
    nome_cod = municipios().get(cod) if cod else None
    uf = UF_POR_CODIGO.get(cod[:2]) if cod else None
    if nome_cod:
        trecho = f"código IBGE {cod} do número do CAR"
        if linha_mun and _norm(nome_cod) not in _norm(linha_mun):
            campos["municipio"] = Campo(nome_cod, nome_doc, trecho + f" (o documento diz '{linha_mun}')", "média",
                                        alternativas=[titulo(linha_mun)])
        else:
            campos["municipio"] = Campo(nome_cod, nome_doc, trecho)
    elif linha_mun:
        achado = municipio_por_nome(linha_mun)
        valor = achado[1] if achado else titulo(re.sub(r"\s+(Goi[aá]s|GO)\s*$", "", linha_mun.strip(), flags=re.I))
        campos["municipio"] = Campo(valor, nome_doc, f"Município: {linha_mun}", "média")
    if uf:
        campos["uf"] = Campo(uf[1], nome_doc, "código do CAR")
    elif linha_mun and re.search(r"Goi[aá]s|\bGO\b", linha_mun):
        campos["uf"] = Campo("Goiás", nome_doc, f"Município: {linha_mun}")


def _ler_matricula(texto, nome_doc):
    campos = {}
    plano = re.sub(r"[ \t]+", " ", texto.replace("\n", " "))
    # número da matrícula
    m = re.search(r"MATR[IÍ]CULA\s*(?:N\s*[º°o.]?|n\s*[º°.])\s*:?\s*(\d[\d.]*)", plano, re.I)
    if not m:
        m = re.search(r"Matr[ií]cula[^\d]{0,15}(\d[\d.]{1,10})", plano, re.I)
    if m:
        num = m.group(1).rstrip(".")
        num = num.lstrip("0") or num
        campos["matricula"] = Campo(num, nome_doc, plano[max(0, m.start() - 10):m.end() + 5].strip())
    # imóvel: trecho após "IMÓVEL:"
    m = re.search(r"IM[OÓ]VEL\s*:\s*(.{0,900})", plano, re.I)
    if m:
        trecho = m.group(1)
        f = re.search(r"(?:fazenda|denominad[ao]s?|lugar\s+denominado|im[oó]vel\s+denominado)\s+"
                      r"((?:[“\"'][^”\"']{2,60}[”\"'](?:\s+ou\s+[“\"'][^”\"']{2,60}[”\"'])?)|"
                      r"(?:[A-ZÀ-Ú][A-ZÀ-Úa-zà-ú0-9]*(?:\s+(?:d[aeo]s?|[A-ZÀ-Ú][A-ZÀ-Úa-zà-ú0-9]*))*))",
                      trecho, re.I)
        if f:
            nome = f.group(1).strip().strip(",;")
            nome = nome.replace("“", '"').replace("”", '"')
            prefixo = "" if re.match(r"fazenda", nome, re.I) else "Fazenda "
            if re.search(r"fazenda", f.group(0)[:8], re.I) and not nome.lower().startswith("fazenda"):
                valor = prefixo + nome
            else:
                valor = nome if nome.lower().startswith("fazenda") else prefixo + nome
            campos["imovel"] = Campo(re.sub(r"\s{2,}", " ", valor).strip(), nome_doc,
                                     "IMÓVEL: ..." + f.group(0)[:80], "média")
        mun = re.search(r"munic[ií]pio\s+(?:de|da|do)\s+([A-ZÀ-Úa-zà-ú' ]{3,40}?)(?:\s*[-/,]|\s+Estado|\s+com\b|\s*\.)",
                        trecho, re.I)
        achado = municipio_por_nome(mun.group(1)) if mun else municipio_por_nome(trecho[:400])
        if achado:
            campos["municipio"] = Campo(achado[1], nome_doc, "IMÓVEL: ... município de " + achado[1], "média")
            campos["uf"] = Campo("Goiás", nome_doc, "município de Goiás")
    # proprietário: "PROPRIETÁRIO(S): NOME, brasileiro..." e adquirentes em registros posteriores
    donos = []
    for m in re.finditer(r"PROPRIET[AÁ]RI[OA]S?\s*:\s*([A-ZÀ-Ú][A-ZÀ-Ú .'&-]{3,90}?)\s*[,;(]", plano):
        donos.append(("proprietário", m.group(1).strip(), m.start()))
    for m in re.finditer(r"(?:ADQUIRENTES?|OUTORGAD[OA]S?\s+COMPRADOR(?:ES|A)?|COMPRADOR(?:ES|A)?)\s*:\s*"
                         r"([A-ZÀ-Ú][A-ZÀ-Ú .'&-]{3,90}?)\s*[,;(]", plano):
        donos.append(("adquirente", m.group(1).strip(), m.start()))
    donos.sort(key=lambda x: x[2])
    if donos:
        atual = donos[-1]
        alternativas = []
        for _, n, _ in donos:
            if n not in alternativas:
                alternativas.append(n)
        conf = "alta" if len(alternativas) == 1 else "média"
        trecho = (f"{atual[0].upper()}: {atual[1]}" +
                  (" (último registro de transmissão; confira se houve averbações depois)" if len(donos) > 1 else ""))
        campos["proprietario"] = Campo(atual[1], nome_doc, trecho, conf, alternativas=alternativas)
    return campos


def ler_documento(caminho, max_paginas=8):
    """Lê um PDF e retorna (tipo, {campo: Campo}, avisos)."""
    nome_doc = os.path.basename(caminho)
    avisos = []
    if not caminho.lower().endswith(".pdf"):
        return "desconhecido", {}, ["Escolha um arquivo PDF (recibo do CAR ou certidão de matrícula)."]
    try:
        paginas, metodo = pdf_texto.extrair(caminho, max_paginas)
    except Exception as e:
        return "desconhecido", {}, [f"Não foi possível ler o PDF '{nome_doc}': {e}"]
    texto = "\n".join(paginas)
    # carimbos de assinatura digital não contam como texto do documento
    util = "\n".join(l for l in texto.splitlines()
                     if not re.search(r"assinad|dados:\s*20\d\d|:\d{8,}|^\s*-?\d{2}'\d{2}'\s*$|^\s*\d{2,}\s*$", l, re.I))
    if len(re.sub(r"\s", "", util)) < 150:
        return "digitalizado", {}, [f"'{nome_doc}' parece digitalizado (só imagem, sem texto). Digite os dados ou "
                                    f"use o OCR do ambiente de suporte (support/Instalar_OCR_Windows.cmd)."]
    tipo = _tipo(texto)
    if tipo == "recibo_sigcar":
        campos = _ler_recibo_sigcar(texto, nome_doc)
    elif tipo in ("recibo_sicar", "demonstrativo_car"):
        campos = _ler_recibo_sicar(texto, nome_doc)
    elif tipo == "matricula":
        campos = _ler_matricula(texto, nome_doc)
    else:
        campos = {}
        car = achar_car(texto)
        if car:
            campos["car"] = Campo(car[0], nome_doc, "número de CAR encontrado no texto", "média")
            _municipio(campos, None, car, nome_doc)
        avisos.append(f"'{nome_doc}': tipo de documento não reconhecido; só o que tem formato próprio (CAR) foi "
                      f"procurado.")
    if not campos:
        avisos.append(f"'{nome_doc}': nenhum dado do imóvel encontrado.")
    avisos.append(f"'{nome_doc}' lido como {tipo.replace('_', ' ')} ({metodo}).")
    return tipo, campos, avisos


PRIORIDADE = {
    "car": ["recibo_sigcar", "recibo_sicar", "demonstrativo_car", "matricula", "desconhecido"],
    "imovel": ["recibo_sigcar", "recibo_sicar", "demonstrativo_car", "matricula"],
    "municipio": ["recibo_sigcar", "recibo_sicar", "demonstrativo_car", "matricula", "desconhecido"],
    "uf": ["recibo_sigcar", "recibo_sicar", "demonstrativo_car", "matricula", "desconhecido"],
    "proprietario": ["recibo_sigcar", "recibo_sicar", "demonstrativo_car", "matricula"],
    "matricula": ["matricula", "recibo_sigcar", "recibo_sicar"],
}


def combinar(leituras, maiusculas="titulo"):
    """Junta as leituras de vários documentos. leituras = [(tipo, campos, avisos)].

    Retorna ({campo: Campo}, avisos). Quando documentos discordam, o valor vem do
    documento de maior prioridade e os outros ficam como alternativas, com aviso.
    maiusculas: "titulo" (Wiliam Batista Rosa) ou "documento" (como está no PDF) - vale para
    proprietário e município.
    """
    final = {}
    avisos = []
    for tipo, campos, av in leituras:
        avisos.extend(av)
    for chave, ordem in PRIORIDADE.items():
        candidatos = []
        for tipo, campos, _ in leituras:
            if chave in campos:
                candidatos.append((ordem.index(tipo) if tipo in ordem else 99, tipo, campos[chave]))
        if not candidatos:
            continue
        candidatos.sort(key=lambda x: x[0])
        escolhido = candidatos[0][2]
        outros = [c[2] for c in candidatos[1:]]
        if chave == "matricula":
            # matrículas de vários documentos se somam
            nums = []
            for _, _, c in candidatos:
                for n in re.split(r"\s*,\s*", c.valor):
                    n2 = n.lstrip("0") or n
                    if n2 and n2 not in nums:
                        nums.append(n2)
            escolhido = Campo(", ".join(nums), escolhido.documento, escolhido.trecho, escolhido.confianca)
        else:
            for o in outros:
                if _norm(o.valor) != _norm(escolhido.valor) and not (
                        chave == "proprietario" and _norm(escolhido.valor).startswith(_norm(o.valor))):
                    avisos.append(f"{chave.capitalize()}: '{escolhido.documento}' diz '{escolhido.valor}' e "
                                  f"'{o.documento}' diz '{o.valor}'. Confira.")
                if o.valor != escolhido.valor and o.valor not in escolhido.alternativas:
                    escolhido.alternativas.append(o.valor)
        if maiusculas == "titulo" and chave in ("proprietario",):
            escolhido.alternativas = [escolhido.valor] + [a for a in escolhido.alternativas if a != escolhido.valor]
            escolhido.valor = titulo(escolhido.valor)
        final[chave] = escolhido
    return final, avisos
