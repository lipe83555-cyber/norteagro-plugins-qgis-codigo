# -*- coding: utf-8 -*-
"""Proteção de identidade e marcadores dinâmicos (Fase 3) - parte sem QGIS.

Todo texto que vem da referência e contém nomes, registros profissionais,
documentos, matrículas ou datas é trocado por um marcador de variável de
projeto. O texto original nunca vai para o QPT: fica só na memória da tela de
revisão, onde o usuário confirma item a item. A exportação fica bloqueada
enquanto houver item pendente.

Variáveis usadas nos rótulos do layout (expressões QGIS):
  [% @na_imovel %] [% @na_municipio %] [% @na_proprietario %] [% @na_matricula %]
  [% @na_car %] [% @na_responsavel %] [% @na_rt_titulo %] [% @na_crea %]
  [% @na_empresa %] [% @na_elaboracao %] [% @na_data %] [% @na_documento %]
"""

import re
import unicodedata

VARIAVEIS_IMOVEL = [
    ("na_imovel", "Imóvel / propriedade", ""),
    ("na_proprietario", "Proprietário", ""),
    ("na_documento", "CPF/CNPJ do proprietário", ""),
    ("na_matricula", "Matrícula", ""),
    ("na_car", "CAR", ""),
    ("na_municipio", "Município", ""),
    ("na_uf", "Estado", "Goiás"),
    ("na_fonte", "Fonte", "Google Earth, SICAR"),
    ("na_elaboracao", "Elaboração", ""),
    ("na_data", "Data", ""),
]

VARIAVEIS_RT = [
    ("na_responsavel", "Nome", ""),   # cada escritório preenche em Configurações
    ("na_rt_titulo", "Título", "Engenheiro Agrônomo"),
    ("na_crea", "Registro", ""),
    ("na_empresa", "Empresa", "Norte Agro Projetos e Planejamentos Agroambientais Ltda"),
]

NOMES_VARIAVEIS = [v[0] for v in VARIAVEIS_IMOVEL + VARIAVEIS_RT]


def marcador(var):
    return f"[% @{var} %]"


# Padrões (ordem importa: os mais específicos primeiro)
_RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}\s*-?\s*\d{2}\b")
_RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}\b")
_RE_DATA = re.compile(
    r"\b(\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+de\s+(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|"
    r"novembro|dezembro)(\s+de\s+\d{4})?|(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)\s*(de\s*)?\d{4})\b", re.I)
_RE_CREA = re.compile(r"\b(CREA|CAU|CFTA|CRBIO|CRT)\b[^\n]*", re.I)
_RE_CAR = re.compile(r"\b[A-Z]{2}-\d{7}-[0-9A-F.]{8,}\b", re.I)
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_RE_FONE = re.compile(r"(\(?\b\d{2}\)?\s*)?\b9?\d{4}[-\s]?\d{4}\b")
# rótulo sozinho (sem valor na mesma linha): o valor vem na linha (ou célula) seguinte
_ROTULOS_SOZINHOS = [
    (re.compile(r"^\s*propriet[aá]ri[oa]s?\s*:?\s*$", re.I), "na_proprietario", "Proprietário"),
    (re.compile(r"^\s*(elabora[cç][aã]o|elaborado\s+por|desenho|desenhista)\s*:?\s*$", re.I), "na_elaboracao",
     "Elaboração"),
    (re.compile(r"^\s*matr[ií]culas?\s*(n[º°o.]*)?\s*:?\s*$", re.I), "na_matricula", "Matrícula"),
    (re.compile(r"^\s*(propriedade|im[oó]vel|fazenda)\s*:?\s*$", re.I), "na_imovel", "Imóvel"),
    (re.compile(r"^\s*munic[ií]pio\s*:?\s*$", re.I), "na_municipio", "Município"),
    (re.compile(r"^\s*(car|n[º°o.]?\s*do\s*car|registro\s+no\s+car)\s*:?\s*$", re.I), "na_car", "CAR"),
    (re.compile(r"^\s*(cpf|cnpj|cpf\s*/\s*cnpj)\s*:?\s*$", re.I), "na_documento", "CPF/CNPJ"),
    (re.compile(r"^\s*data\s*:?\s*$", re.I), "na_data", "Data"),
]


def rotulo_sozinho(texto):
    for regex, var, nome in _ROTULOS_SOZINHOS:
        if regex.match(str(texto or "")):
            return var, nome
    return None, None

# Palavras-chave de linha (rótulo: valor)
_CHAVES = [
    (re.compile(r"respons[aá]vel\s+t[eé]cnic", re.I), "na_responsavel", "Responsável Técnico"),
    (re.compile(r"\belabora[cç][aã]o\b|\belaborado\s+por\b|\bdesenho\b|\bdesenhista\b", re.I),
     "na_elaboracao", "Elaboração"),
    (re.compile(r"\bpropriet[aá]ri", re.I), "na_proprietario", "Proprietário"),
    (re.compile(r"\bmatr[ií]cula\b", re.I), "na_matricula", "Matrícula"),
    (re.compile(r"\bengenheir|\beng\.|\bagr[oô]nom|\bge[oó]log|\bbi[oó]log|\barquitet|\bt[eé]cnico\s+em\b",
                re.I), "na_rt_titulo", "Título profissional"),
    (re.compile(r"\bcpf\b", re.I), "na_documento", "CPF"),
    (re.compile(r"\bcnpj\b", re.I), "na_documento", "CNPJ"),
    (re.compile(r"\bdata\b", re.I), "na_data", "Data"),
    (re.compile(r"\b(propriedade|im[oó]vel|fazenda|s[ií]tio|ch[aá]cara)\b\s*:", re.I), "na_imovel", "Imóvel"),
    (re.compile(r"\bmunic[ií]pio\b\s*:", re.I), "na_municipio", "Município"),
    (re.compile(r"\bcar\b\s*:", re.I), "na_car", "CAR"),
]


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def mascarar(texto):
    """Versão parcialmente oculta para registros (nunca o texto inteiro)."""
    s = str(texto or "").strip()
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


class Achado:
    def __init__(self, elemento, linha, original, substituto, motivo, variavel):
        self.elemento = elemento
        self.linha = linha
        self.original = original
        self.substituto = substituto
        self.motivo = motivo
        self.variavel = variavel
        self.decisao = None  # None (pendente) | "marcador" | "manter"

    def como_dict(self, com_original=False):
        d = {"elemento": self.elemento, "linha": self.linha, "substituto": self.substituto,
             "motivo": self.motivo, "variavel": self.variavel, "decisao": self.decisao,
             "original_mascarado": mascarar(self.original)}
        if com_original:
            d["original"] = self.original
        return d


def _substituir_linha(linha, contexto_rt=False):
    """Retorna (linha_nova, motivo, variavel) ou (None, None, None) se a linha é segura."""
    texto = linha.strip()
    if not texto:
        return None, None, None
    # já é marcador
    if re.fullmatch(r"(\[%.*?%\]|\{\{\w+\}\})", texto):
        return None, None, None

    # rótulo: valor com palavra-chave
    for regex, var, nome in _CHAVES:
        if regex.search(texto):
            if ":" in texto:
                rotulo = texto.split(":", 1)[0].strip()
                # Título do bloco RT ("RESPONSÁVEL TÉCNICO:") sem valor
                valor = texto.split(":", 1)[1].strip()
                if not valor:
                    return None, None, None
                if var == "na_responsavel":
                    return f"{rotulo}: {marcador('na_responsavel')}", f"{nome} na referência", var
                return f"{rotulo}: {marcador(var)}", f"{nome} na referência", var
            if var == "na_responsavel" and len(texto) <= 25:
                # é só o título do bloco ("RESPONSÁVEL TÉCNICO")
                return None, None, None
            if var == "na_rt_titulo":
                return marcador("na_rt_titulo"), "Título profissional na referência", var
            if var in ("na_data",):
                break  # tratado pelos padrões de data abaixo
            if var in ("na_imovel", "na_municipio", "na_car", "na_documento"):
                break
            return marcador(var), f"{nome} na referência", var

    if _RE_CREA.search(texto):
        return _RE_CREA.sub(marcador("na_crea"), texto).strip(), "Registro profissional (CREA/CAU) na referência", \
            "na_crea"
    if _RE_CNPJ.search(texto):
        return _RE_CNPJ.sub(marcador("na_documento"), texto), "CNPJ na referência", "na_documento"
    if _RE_CPF.search(texto):
        return _RE_CPF.sub(marcador("na_documento"), texto), "CPF na referência", "na_documento"
    if _RE_CAR.search(texto):
        return _RE_CAR.sub(marcador("na_car"), texto), "Número de CAR na referência", "na_car"
    if _RE_DATA.search(texto):
        return _RE_DATA.sub(marcador("na_data"), texto), "Data na referência", "na_data"
    if _RE_EMAIL.search(texto):
        return _RE_EMAIL.sub("", texto).strip(" -:|"), "E-mail na referência", None
    if _RE_FONE.search(texto) and re.search(r"(fone|tel|cel|whats|contato|\(\d{2}\))", texto, re.I):
        return _RE_FONE.sub("", texto).strip(" -:|"), "Telefone na referência", None
    if contexto_rt:
        # linhas soltas dentro do bloco de responsável técnico (nome, assinatura)
        if re.search(r"[A-Za-zÀ-ú]{2,}", texto) and not re.fullmatch(r"[_\-\s.]+", texto):
            return marcador("na_responsavel"), "Nome no bloco de responsável técnico", "na_responsavel"
    return None, None, None


_RE_TITULO_RT = re.compile(r"respons[aá]vel\s+t[eé]cnic|\bassinatura\b|\bresp\.\s*t[eé]c", re.I)


def _caixa(el):
    return (el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"])


def _dentro(a, b, tol=0.9):
    ia = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return ia / area >= tol


def rotulos_no_bloco_rt(proposta):
    """Ids de rótulos que pertencem ao bloco de Responsável Técnico, mesmo em caixas de texto separadas:
    dentro da mesma moldura que o título do bloco, ou logo abaixo dele (até 15% da altura da página),
    com sobreposição horizontal."""
    els = proposta.get("elements", [])
    titulos = [e for e in els if e["type"] == "label" and _RE_TITULO_RT.search(e.get("text", "") or "")]
    molduras = [e for e in els if e["type"] == "shape"]
    ids = set()
    for t in titulos:
        ct = _caixa(t)
        caixas_rt = [_caixa(m) for m in molduras if _dentro(ct, _caixa(m))]
        for e in els:
            if e is t or e["type"] != "label":
                continue
            ce = _caixa(e)
            if any(_dentro(ce, cm) for cm in caixas_rt):
                ids.add(e["id"])
                continue
            sobrep_h = min(ce[2], ct[2]) - max(ce[0], ct[0])
            if sobrep_h > 0.5 * min(ce[2] - ce[0], ct[2] - ct[0]) and ct[1] <= ce[1] <= ct[3] + 0.15:
                ids.add(e["id"])
    return ids


def proteger_texto(texto, elemento="?", contexto_rt_inicial=False):
    """Processa um texto de rótulo. Retorna (texto_protegido, [Achado])."""
    achados = []
    linhas = str(texto or "").split("\n")
    contexto_rt = bool(contexto_rt_inicial)
    saida = []
    valor_de = None  # rótulo sozinho na linha anterior
    for i, linha in enumerate(linhas):
        sem = _sem_acento(linha).lower()
        if re.search(r"responsavel\s+tecnic", sem):
            contexto_rt = True
        if valor_de and linha.strip():
            var_ant, nome_ant = valor_de
            valor_de = None
            if not re.fullmatch(r"\s*\[%.*%\]\s*", linha):
                nova = marcador(var_ant)
                achados.append(Achado(elemento, i, linha, nova, f"{nome_ant} na referência (linha abaixo do rótulo)",
                                      var_ant))
                saida.append(nova)
                continue
        var_s, nome_s = rotulo_sozinho(linha)
        if var_s:
            valor_de = (var_s, nome_s)
            saida.append(linha)
            continue
        nova, motivo, var = _substituir_linha(linha, contexto_rt)
        if nova is not None and nova != linha:
            achados.append(Achado(elemento, i, linha, nova, motivo, var))
            saida.append(nova)
        else:
            saida.append(linha)
    return "\n".join(saida), achados


def proteger_proposta(proposta):
    """Aplica a proteção a todos os rótulos e tabelas de uma proposta (alterando-a).

    Retorna a lista de achados (com o texto original apenas em memória).
    """
    achados = []
    bloco_rt = rotulos_no_bloco_rt(proposta)
    for el in proposta.get("elements", []):
        if el["type"] == "label":
            novo, a = proteger_texto(el.get("text", ""), el["id"], el["id"] in bloco_rt)
            if a:
                el["text"] = novo
                el.setdefault("review", []).append("Texto com dados pessoais substituído por marcador")
                achados.extend(a)
        elif el["type"] == "table":
            for r, linha in enumerate(el.get("rows") or []):
                valor_de = None
                for c, cel in enumerate(linha):
                    ident = f"{el['id']}[{r},{c}]"
                    if valor_de and str(cel).strip():
                        var_ant, nome_ant = valor_de
                        valor_de = None
                        novo = marcador(var_ant)
                        achados.append(Achado(ident, 0, str(cel), novo, f"{nome_ant} na referência (célula ao lado)",
                                              var_ant))
                        linha[c] = novo
                        continue
                    var_s, nome_s = rotulo_sozinho(cel)
                    if var_s:
                        valor_de = (var_s, nome_s)
                        continue
                    novo, a = proteger_texto(cel, ident)
                    if a:
                        linha[c] = novo
                        achados.extend(a)
            if el.get("text"):
                novo, a = proteger_texto(el["text"], el["id"])
                el["text"] = novo
                achados.extend(a)
        elif el["type"] == "picture" and el.get("role") not in ("logo", "assinatura"):
            # recorte da referência pode ser assinatura, carimbo ou logo de terceiro: sai por padrão
            el["sem_recorte"] = True
            achados.append(Achado(el["id"], -1, "(recorte da imagem de referência)", "(imagem vazia no modelo)",
                                  "Imagem recortada da referência (pode ser assinatura, carimbo ou logo de terceiro)",
                                  None))
    return achados


def pendentes(achados):
    return [a for a in achados if a.decisao is None]


def pode_exportar(achados):
    return not pendentes(achados)


def aplicar_decisao(proposta, achado, decisao):
    """decisao='marcador' mantém o marcador; decisao='manter' devolve o texto original
    (somente com confirmação explícita do usuário na interface)."""
    if decisao not in ("marcador", "manter"):
        raise ValueError("Decisão inválida")
    achado.decisao = decisao
    alvo = achado.elemento
    texto_linha = achado.original if decisao == "manter" else achado.substituto
    if achado.linha == -1:  # imagem recortada
        for el in proposta.get("elements", []):
            if el["id"] == alvo:
                el["sem_recorte"] = decisao != "manter"
        return
    for el in proposta.get("elements", []):
        if el["type"] == "label" and el["id"] == alvo:
            linhas = el.get("text", "").split("\n")
            if 0 <= achado.linha < len(linhas):
                linhas[achado.linha] = texto_linha
                el["text"] = "\n".join(linhas)
            return
        if el["type"] == "table" and alvo.startswith(el["id"] + "["):
            m = re.match(r".*\[(\d+),(\d+)\]$", alvo)
            if m:
                r, c = int(m.group(1)), int(m.group(2))
                linhas = el["rows"][r][c].split("\n")
                if 0 <= achado.linha < len(linhas):
                    linhas[achado.linha] = texto_linha
                    el["rows"][r][c] = "\n".join(linhas)
            return


def textos_suspeitos_restantes(textos):
    """Varredura final de segurança antes de gravar o QPT: retorna textos que ainda
    parecem conter CPF, CNPJ ou CREA literais (sem marcador)."""
    restantes = []
    for t in textos:
        s = re.sub(r"\[%.*?%\]", "", str(t or ""), flags=re.S)
        if _RE_CPF.search(s) or _RE_CNPJ.search(s) or _RE_EMAIL.search(s) or \
                re.search(r"\b(CREA|CAU|CFTA|CRBIO|CRT)\b[\s\-/:.A-Za-z]{0,10}\d", s, re.I):
            restantes.append(t)
    return restantes
