# -*- coding: utf-8 -*-
"""Geração da planilha Excel. Este módulo não depende do QGIS.

v3.9.0: o quadro usa os valores resolvidos e arredondados (``valores_quadro``),
de modo que as linhas exibidas somam exatamente o Total; quadros reordenados;
caixa de observações dimensionada sem distorcer a linha do título; abas
"Todas as camadas" e "Conferências" organizadas.
"""
import base64
import io
import itertools
import math
import struct
from datetime import datetime

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

TOL_HA = 0.0001
ORDEM_SITUACAO = {"ALERTA": 0, "VERIFICAR": 1, "CONFERIR": 2, "AJUSTADO": 3, "SEM DADOS": 4, "OK": 5}
SECOES_CONFERENCIA = [
    "Fechamento e regras de consistência (R1-R9)",
    "Ajustes topológicos feitos no quadro (T1-T4)",
    "Regras de posição (P1-P6)",
    "Geometria e hidrografia (G1-G3)",
    "Reconhecimento, duplicidade e camadas",
]


def _numero(valor):
    try:
        return float(valor or 0.0)
    except Exception:
        return 0.0


def _r4(valor):
    return round(_numero(valor), 4)


def validar_unicidade_quadros(dados):
    """Valida que uma fonte reconhecida pertence a no máximo um quadro direto."""
    aparicoes = {}

    def add(arquivo, quadro):
        if arquivo:
            aparicoes.setdefault(arquivo, set()).add(quadro)
    diretas = {
        "RESERVA_LEGAL": "Áreas Remanescentes",
        "APP_PRESERVADA": "Área de Preservação Permanente", "APP_CONSOLIDADA": "Área de Preservação Permanente",
        "HIDROGRAFIA": "Área Hidrográfica",
        "AREA_CONSOLIDADA": "Áreas Totais do Imóvel", "AREA_DE_VEGETACAO": "Áreas Totais do Imóvel", "AREA_DO_IMOVEL": "Áreas Totais do Imóvel",
        "AREA_SUPRIMIDA_ANTES_2019": "Passivos ambientais", "AREA_SUPRIMIDA_DEPOIS_2019": "Passivos ambientais",
        "APP_ANTROPIZADA_APOS_2019": "Área antropizada após 2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019": "Área antropizada após 2019",
        "APP_ANTROPIZADA_ANTES_2019": "Área antropizada antes de 2019", "SUPRESSAO_PASSIVEL_ANTES_2019": "Área antropizada antes de 2019",
        "COMPENSACAO_DANOS": "Área Total de Compensação", "COMPENSACAO_FLORESTAL": "Área Total de Compensação", "AREA_RECOMPOSICAO": "Área Total de Compensação",
    }
    for a, q in diretas.items():
        add(a, q)
    for item in dados.get("hidro", []):
        add(item.get("arquivo"), "Área Hidrográfica")
    for item in dados.get("outras", []):
        add(item.get("arquivo"), "Outras camadas")
    fechamento = list(dados.get("fechamento_classes") or [])
    if len(fechamento) != len(set(fechamento)):
        raise ValueError("FECHAMENTO contém ARQUIVO repetido.")
    conflitos = {a: sorted(qs) for a, qs in aparicoes.items() if len(qs) > 1}
    if conflitos:
        raise ValueError("Uma camada seria exibida em mais de um quadro: " + "; ".join(f"{a}: {', '.join(qs)}" for a, qs in conflitos.items()))
    return True


def _problemas_quadro(dados, titulo):
    return list((dados.get("problemas_por_quadro") or {}).get(titulo, []) or [])


def _obs_texto(problemas):
    if not problemas:
        return ""
    ordenados = sorted(problemas, key=lambda x: abs(_numero(x.get("area_ha"))) if x.get("area_ha") is not None else float(x.get("quantidade") or 0), reverse=True)
    linhas = []
    for i, item in enumerate(ordenados[:4], 1):
        desc = str(item.get("descricao") or item.get("tipo") or "Problema").strip()
        tamanho = str(item.get("tamanho") or "").strip()
        onde = str(item.get("onde") or "").strip()
        resolver = str(item.get("como_resolver") or "").strip()
        l = f"({i}) {desc}" + (f" - {tamanho}" if tamanho and tamanho not in desc else "")
        if onde:
            l += f"\nOnde: {onde}"
        linhas.append(l)
    if len(ordenados) > 4:
        linhas.append(f"+ {len(ordenados)-4} outros")
    # v3.9: o "Como resolver" de cada item fica na aba Conferências (caixa mais compacta).
    return "Observações\n" + "\n".join(linhas) + "\nComo resolver: ver aba Conferências."


def _linhas_visuais(texto, largura=64):
    return sum(max(1, int(math.ceil(len(l) / float(largura)))) for l in str(texto).split("\n"))


def _secao(item):
    regra = str(item.get("regra") or "").upper()
    texto = str(item.get("verificacao") or "")
    if regra.startswith("R") or texto.startswith(("Fechamento do imóvel", "Total ")):
        return 0
    if regra.startswith("T"):
        return 1
    if regra.startswith("P"):
        return 2
    if regra.startswith("G"):
        return 3
    return 4


def _situacao(item):
    fixa = item.get("situacao")
    if fixa:
        return fixa
    if not item.get("tem_dados", True):
        return "SEM DADOS"
    a, b = item.get("a"), item.get("b")
    if a is not None and b is not None:
        tol = _numero(item.get("tolerancia")) or TOL_HA
        return "OK" if abs(_numero(a) - _numero(b)) < tol else "ALERTA"
    return "ALERTA"


class _Campos(dict):
    def __missing__(self, chave):
        return "{" + chave + "}"


def _titulo_planilha(texto, imovel, data, metodo, src):
    """Título do modelo de tabela: aceita {imovel}, {data}, {metodo} e {src}."""
    try:
        return str(texto).format_map(_Campos(imovel=imovel, data=data, metodo=metodo, src=src))
    except Exception:
        return str(texto)


def _tamanho_png(dados):
    try:
        if dados[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", dados[16:24])
    except Exception:
        pass
    return None


def gerar_planilha(caminho, dados, modelo=None):
    validar_unicidade_quadros(dados)
    # v3.9.6: modelo de tabela do escritório (quadros, títulos, linhas, cores, fonte, logo, colunas).
    from .modelos import TITULO_PADRAO_QUADRO, modelo_tabela_padrao, normalizar_modelo_tabela
    mt = normalizar_modelo_tabela(modelo) if modelo else modelo_tabela_padrao()
    cores = mt["cores"]; ren = mt["linhas"]
    wb = xlsxwriter.Workbook(caminho)
    # Identidade visual da Norte Agro - fonte Calibri 10.
    base = {"font_name": mt["fonte"], "font_size": mt["tamanho"]}
    fmt_num = wb.add_format({**base, "num_format": "0.0000", "border": 1, "align": "right"})
    fmt_num_nb = wb.add_format({**base, "num_format": "0.0000", "align": "right"})
    fmt_num2_nb = wb.add_format({**base, "num_format": "0.00", "align": "right"})
    fmt_int = wb.add_format({**base, "num_format": "0"})
    fmt_int_b = wb.add_format({**base, "num_format": "0", "border": 1, "align": "right"})
    fmt_num2_b = wb.add_format({**base, "num_format": "0.00", "border": 1, "align": "right"})
    fmt_titulo = wb.add_format({**base, "bold": True, "align": "left", "valign": "vcenter", "border": 1, "bg_color": "#E4EDD8", "font_color": "#262621"})
    fmt_cab = wb.add_format({**base, "bold": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": cores["cabecalho_fundo"], "font_color": cores["cabecalho_texto"], "text_wrap": True})
    fmt_txt = wb.add_format({**base, "border": 1, "valign": "top"})
    fmt_txt_wrap = wb.add_format({**base, "border": 1, "valign": "top", "text_wrap": True})
    fmt_total_desc = wb.add_format({**base, "bold": True, "border": 1, "top": 2})
    fmt_total_num = wb.add_format({**base, "bold": True, "border": 1, "top": 2, "num_format": "0.0000", "align": "right"})
    fmt_ital = wb.add_format({**base, "italic": True, "font_color": "#6E5E4E", "text_wrap": True})
    fmt_alerta = wb.add_format({**base, "bold": True, "font_color": "#9C0006", "bg_color": "#FFC7CE", "num_format": "0.0000", "border": 1})
    fmt_banner = wb.add_format({**base, "bold": True, "font_color": "#9C0006", "bg_color": "#FBE4E2", "align": "center", "valign": "vcenter", "text_wrap": True, "border": 1})
    fmt_banner_aj = wb.add_format({**base, "bold": True, "font_color": "#1F4E79", "bg_color": "#DDEBF7", "align": "center", "valign": "vcenter", "text_wrap": True, "border": 1})
    fmt_recorte = wb.add_format({**base, "italic": True, "font_color": "#9C6500", "bg_color": "#FFF2D6", "text_wrap": True})
    fmt_obs = wb.add_format({**base, "font_size": 9, "bg_color": "#FFF6D8", "border": 1, "text_wrap": True, "valign": "top", "font_color": "#262621"})
    fmt_ok = wb.add_format({**base, "font_color": "#315B16", "bg_color": "#E7F2DE", "bold": True, "border": 1})
    fmt_bad = wb.add_format({**base, "font_color": "#8F1D17", "bg_color": "#FBE4E2", "bold": True, "border": 1})
    fmt_conf = wb.add_format({**base, "font_color": "#865400", "bg_color": "#FFF2D6", "bold": True, "border": 1})
    fmt_ver = wb.add_format({**base, "font_color": "#5A3A83", "bg_color": "#EEE7F8", "bold": True, "border": 1})
    fmt_sem = wb.add_format({**base, "font_color": "#5F5D57", "bg_color": "#ECEBE7", "bold": True, "border": 1})
    fmt_aj = wb.add_format({**base, "font_color": "#1F4E79", "bg_color": "#DDEBF7", "bold": True, "border": 1})
    fmt_secao = wb.add_format({**base, "bold": True, "font_color": "#262621", "bg_color": "#E4EDD8", "border": 1})
    fmt_head = wb.add_format({**base, "bold": True, "font_size": mt["tamanho"] + 2, "font_color": cores["planilha_texto"], "bg_color": cores["planilha_fundo"], "align": "left", "valign": "vcenter"})
    formatos_situacao = {"OK": fmt_ok, "ALERTA": fmt_bad, "CONFERIR": fmt_conf, "VERIFICAR": fmt_ver, "SEM DADOS": fmt_sem, "AJUSTADO": fmt_aj}

    valores = dados.get("valores", {}) or {}
    vq = dados.get("valores_quadro") or {}
    esp = dados.get("especiais", {}) or {}
    nomes = dados.get("nomes_catalogo", {}) or {}
    fechamento = dados.get("fechamento", {}) or {}

    def val(k):
        return _numero(vq[k]) if k in vq else _r4(valores.get(k, 0))

    def val_esp(chave_vq, chave_esp):
        return _numero(vq[chave_vq]) if chave_vq in vq else _r4(esp.get(chave_esp))

    def nome(k, padrao):
        return str(nomes.get(k) or padrao)

    gerado = dados.get("gerado_em") or datetime.now()
    dt = gerado if isinstance(gerado, str) else gerado.strftime("%d/%m/%Y %H:%M")
    metodo_original = str(dados.get("metodo", "") or "")
    if metodo_original.startswith("Elipsoidal") and _numero(dados.get("densificacao_m")) > 0:
        metodo = "Elipsoidal (GRS80, vértices a cada 10 m)"
    elif metodo_original.startswith(("Plana", "Plano")):
        metodo = "Plano UTM"
    else:
        metodo = metodo_original
    imovel_nome = str(dados.get("imovel_nome") or "PROJETO")
    cabecalho = f"Gerado em {dt} | Método: {metodo} | SRC: {dados.get('srid','')}"

    # ------------------------------------------------------------ Quadro de Áreas
    # v3.9: quadros em duas colunas alinhadas (B:C e E:F, coluna D de respiro),
    # cada par começando na mesma linha; observações numa seção própria abaixo.
    ws = wb.add_worksheet("Quadro de Áreas")
    ws.hide_gridlines(2); ws.set_landscape(); ws.set_paper(9); ws.fit_to_pages(1, 0)
    ws.set_margins(0.25, 0.25, 0.35, 0.35); ws.set_footer('&L&10Norte Agro - Uso do Solo&C&P/&N')
    extras_col = [c for c in ("m2", "pct") if mt["colunas"].get(c)]
    LARG = 2 + len(extras_col)              # colunas de cada quadro
    COL_E, COL_D = 1, 1 + LARG + 1          # início dos quadros da esquerda e da direita
    ULT = COL_D + LARG - 1
    larg_extra = {"m2": 16, "pct": 13}
    ws.set_column(0, 0, 2); ws.set_column(COL_E + LARG, COL_E + LARG, 4)
    for inicio in (COL_E, COL_D):
        ws.set_column(inicio, inicio, 46); ws.set_column(inicio + 1, inicio + 1, 14)
        for k, nome_c in enumerate(extras_col):
            ws.set_column(inicio + 2 + k, inicio + 2 + k, larg_extra[nome_c])
    fmt_tit_q = wb.add_format({**base, "bold": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": cores["titulo_fundo"], "font_color": cores["titulo_texto"]})
    fmt_obs_sec = wb.add_format({**base, "bold": True, "align": "left", "valign": "vcenter", "border": 1, "bg_color": "#F0F0EB", "font_color": "#262621"})
    fmt_obs_item = wb.add_format({**base, "border": 1, "text_wrap": True, "valign": "top", "bg_color": "#FFFBEF", "font_color": "#262621"})
    fmt_m2 = wb.add_format({**base, "num_format": "#,##0.00", "border": 1, "align": "right"})
    fmt_pct = wb.add_format({**base, "num_format": "0.00%", "border": 1, "align": "right"})
    fmt_total_m2 = wb.add_format({**base, "bold": True, "border": 1, "top": 2, "num_format": "#,##0.00", "align": "right"})
    fmt_total_pct = wb.add_format({**base, "bold": True, "border": 1, "top": 2, "num_format": "0.00%", "align": "right"})
    titulo_q = _titulo_planilha(mt["titulo_planilha"], imovel_nome, dt, metodo, dados.get("srid", ""))
    ws.merge_range(0, 1, 0, ULT, titulo_q, fmt_head); ws.set_row(0, 24)
    if mt.get("logo_png"):
        try:
            bruto = base64.b64decode(mt["logo_png"]); tam = _tamanho_png(bruto)
            if tam and tam[1] > 0:
                alt_px = 48.0; esc = alt_px / tam[1]; larg_px = tam[0] * esc
                ws.set_row(0, 40)
                ult_px = (larg_extra.get(extras_col[-1], 14) if extras_col else 14) * 7 + 5
                ws.insert_image(0, ULT, "logo.png", {"image_data": io.BytesIO(bruto), "x_scale": esc, "y_scale": esc,
                                                     "x_offset": max(0, int(ult_px - larg_px - 2)), "y_offset": 3, "object_position": 3})
        except Exception:
            pass
    ws.merge_range(1, 1, 1, ULT, cabecalho, fmt_ital)
    ws.freeze_panes(2, 0)
    linha = 2  # v3.9: só resultados nesta aba; avisos e problemas ficam na aba Observações
    topo = linha + 1

    area_imovel_ref = val("AREA_DO_IMOVEL") if ("AREA_DO_IMOVEL" in vq or "AREA_DO_IMOVEL" in valores) else 0.0

    def desenhar(col, linha, titulo, linhas, total=True, conferir=None, cab_valor="Hectares"):
        """Desenha um quadro a partir de (linha, col) e devolve a última linha usada.

        linhas: [(descrição, valor)] ou [(descrição, valor, formato)].
        conferir: (rótulo, valor) - só aparece, com a Diferença, se o Total não bater.
        v3.9.6: nomes das linhas e colunas extras (m², % do imóvel) vêm do modelo de tabela.
        """
        c_desc, c_val = col, col + 1
        c_fim = col + LARG - 1
        col_l = xl_col_to_name(c_val)
        ws.merge_range(linha, c_desc, linha, c_fim, titulo, fmt_tit_q)
        ws.write(linha + 1, c_desc, ren.get("Descrição", "Descrição"), fmt_cab); ws.write(linha + 1, c_val, ren.get(cab_valor, cab_valor), fmt_cab)
        for k, nome_c in enumerate(extras_col):
            ws.write(linha + 1, c_val + 1 + k, "m²" if nome_c == "m2" else "% do imóvel", fmt_cab)

        def extras(r, v, e_total=False):
            for k, nome_c in enumerate(extras_col):
                c = c_val + 1 + k; ref = f"{col_l}{r + 1}"
                if nome_c == "m2":
                    ws.write_formula(r, c, f"=ROUND({ref}*10000,2)", fmt_total_m2 if e_total else fmt_m2, round(float(v) * 10000.0, 2))
                elif area_imovel_ref > 0:
                    ws.write_formula(r, c, f"={ref}/{area_imovel_ref}", fmt_total_pct if e_total else fmt_pct, float(v) / area_imovel_ref)
                else:
                    ws.write_blank(r, c, None, fmt_total_pct if e_total else fmt_pct)

        def vazias(r, fmt):
            for k in range(len(extras_col)):
                ws.write_blank(r, c_val + 1 + k, None, fmt)

        first = linha + 2
        for off, item in enumerate(linhas):
            desc, v = item[0], item[1]
            fmt_v = item[2] if len(item) > 2 else fmt_num
            numero = _r4(v) if fmt_v is fmt_num else _numero(v)
            ws.write(first + off, c_desc, ren.get(desc, desc), fmt_txt)
            ws.write_number(first + off, c_val, numero, fmt_v)
            extras(first + off, numero)
        bottom = first + len(linhas) - 1
        if total:
            total_row = bottom + 1
            ws.write(total_row, c_desc, ren.get("Total", "Total"), fmt_total_desc)
            if isinstance(total, (int, float)) and not isinstance(total, bool):
                # v0.4.0: Total vindo da própria camada (ex.: APP Total), não da soma das linhas
                cache = _r4(total)
                ws.write_number(total_row, c_val, cache, fmt_total_num)
            else:
                cache = round(sum(_r4(x[1]) for x in linhas), 4)
                ws.write_formula(total_row, c_val, f"=ROUND(SUM({col_l}{first+1}:{col_l}{bottom+1}),4)", fmt_total_num, cache)
            extras(total_row, cache, True)
            bottom = total_row
            if conferir is not None and abs(round(cache - _r4(conferir[1]), 4)) >= TOL_HA:
                ref_row = bottom + 1
                ws.write(ref_row, c_desc, conferir[0], fmt_txt); ws.write_number(ref_row, c_val, _r4(conferir[1]), fmt_num); vazias(ref_row, fmt_txt)
                bottom = ref_row + 1
                ws.write(bottom, c_desc, "Diferença", fmt_alerta)
                ws.write_formula(bottom, c_val, f"=ROUND({col_l}{total_row+1}-{col_l}{ref_row+1},4)", fmt_alerta, round(cache - _r4(conferir[1]), 4)); vazias(bottom, fmt_alerta)
        return bottom

    # Conteúdo dos quadros.
    linhas_f = []
    for x in dados.get("fechamento_linhas") or []:
        arqs = list(x.get("arquivos") or [])
        v = sum(val(a) for a in arqs) if arqs else _r4(x.get("area"))
        linhas_f.append((str(x.get("descricao") or ""), v))
    if not linhas_f:
        linhas_f = [("Área Antropizada não Consolidada", val("AREA_SUPRIMIDA_ANTES_2019") + val("AREA_SUPRIMIDA_DEPOIS_2019")),
                    (nome("AREA_CONSOLIDADA", "Área Consolidada"), val("AREA_CONSOLIDADA")),
                    (nome("AREA_DE_VEGETACAO", "Área de Vegetação Nativa"), val("AREA_DE_VEGETACAO"))]
    area_sem = val("__SEM_FECHAMENTO__") if "__SEM_FECHAMENTO__" in vq else _r4(fechamento.get("area_sem_classificacao"))
    if area_sem >= TOL_HA:
        linhas_f.append(("Área sem classificação", area_sem))

    # v0.4.0: cada linha é a área da própria camada (APP Suprimida = a camada APP Suprimida, que é antes + depois
    # juntas; só se ela não existir a linha soma as duas). O Total é a camada APP Total.
    app_sup = val("APP_SUPRIMIDA") if ("APP_SUPRIMIDA" in vq or "APP_SUPRIMIDA" in valores) else \
        val("APP_ANTROPIZADA_ANTES_2019") + val("APP_ANTROPIZADA_APOS_2019")
    linhas_app = [
        (nome("APP_PRESERVADA", "APP Preservada"), val("APP_PRESERVADA")),
        (nome("APP_CONSOLIDADA", "APP Consolidada"), val("APP_CONSOLIDADA")),
        (nome("APP_SUPRIMIDA", "APP Suprimida"), app_sup),
    ]
    if val("__SEM_APP__") >= TOL_HA:
        linhas_app.append(("Área sem classificação", val("__SEM_APP__")))
    total_app = val("APP_TOTAL") if ("APP_TOTAL" in vq or "APP_TOTAL" in valores) else True

    def linhas_antropizada(app_arq, app_padrao, rl_vq, rl_esp, rl_nome, pas_arq, pas_padrao, chave_sem):
        r_ = [(nome(app_arq, app_padrao), val(app_arq)), (rl_nome, val_esp(rl_vq, rl_esp)), (nome(pas_arq, pas_padrao), val(pas_arq))]
        if val(chave_sem) >= TOL_HA:
            r_.append(("Área sem classificação", val(chave_sem)))
        return r_

    hidro = [(nome("HIDROGRAFIA", "Hidrografia"), val("HIDROGRAFIA"))] + [
        (x.get("descricao", ""), _r4(x.get("area"))) for x in dados.get("hidro", [])]
    outras = [(x.get("nome", ""), val(x.get("arquivo")) if x.get("arquivo") in vq else _r4(x.get("area"))) for x in dados.get("outras", [])]
    pers = dados.get("linhas_personalizadas") or {}

    def mais(quadro_nome):
        """v3.9.6: linhas de camadas personalizadas que a usuária colocou neste quadro."""
        return [(x.get("nome", ""), val(x.get("arquivo")) if x.get("arquivo") in vq else _r4(x.get("area")))
                for x in pers.get(quadro_nome, [])]
    hidro += mais("Área Hidrográfica")
    conteudo = {
        "IMOVEL": (linhas_f, True, (nome("AREA_DO_IMOVEL", "Área Total do Imóvel") + " (camada)", val("AREA_DO_IMOVEL"))),
        "PASSIVOS": ([
            (nome("AREA_SUPRIMIDA_ANTES_2019", "Área Suprimida antes de 2019"), val("AREA_SUPRIMIDA_ANTES_2019")),
            (nome("AREA_SUPRIMIDA_DEPOIS_2019", "Área Suprimida depois de 2019"), val("AREA_SUPRIMIDA_DEPOIS_2019"))] + mais("Passivos ambientais"), True, None),
        "REMANESCENTES": ([
            (nome("RESERVA_LEGAL", "Área de Reserva Legal"), val("RESERVA_LEGAL")),
            ("Área Fora da RL e APP", val_esp("FORA_RL_APP", "area_fora_rl_app"))], True, None),
        "ANTES": (linhas_antropizada(
            "APP_ANTROPIZADA_ANTES_2019", "APP Suprimida antes de 2019", "RL_SUP_ANTES", "reserva_suprimida_antes",
            "Área de Reserva Legal Suprimida antes de 2019", "SUPRESSAO_PASSIVEL_ANTES_2019",
            "Supressão em Área Passível antes de 2019", "__SEM_ANTES__"), True, None),
        "APP": (linhas_app, total_app, None),
        "APOS": (linhas_antropizada(
            "APP_ANTROPIZADA_APOS_2019", "APP Suprimida depois de 2019", "RL_SUP_APOS", "reserva_suprimida_apos",
            "Área de Reserva Legal Suprimida depois de 2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019",
            "Supressão em Área Passível após 2019", "__SEM_APOS__"), True, None),
        "HIDRO": (hidro, True, None),
        "COMPENSACAO": ([
            (nome("COMPENSACAO_DANOS", "Área de Compensação por Danos"), val("COMPENSACAO_DANOS")),
            (nome("COMPENSACAO_FLORESTAL", "Área de Compensação Florestal"), val("COMPENSACAO_FLORESTAL")),
            (nome("AREA_RECOMPOSICAO", "Área de Recomposição"), val("AREA_RECOMPOSICAO"))] + mais("Área Total de Compensação"), True, None),
        "OUTRAS": (outras, False, None),
    }
    # v3.9.6: quadros, ordem, lado e títulos vêm do modelo de tabela (padrão = layout de sempre).
    esquerda, direita = [], []
    for q in mt["quadros"]:
        if not q["visivel"] or q["id"] not in conteudo or (q["id"] == "OUTRAS" and not outras):
            continue
        linhas_q, tot_q, conf_q = conteudo[q["id"]]
        (direita if q["lado"] == "D" else esquerda).append((q["titulo"], linhas_q, tot_q, conf_q))
    linha = topo
    for esq, dir_ in itertools.zip_longest(esquerda, direita):
        fim_e = desenhar(COL_E, linha, *esq) if esq else linha
        fim_d = desenhar(COL_D, linha, *dir_) if dir_ else linha
        linha = max(fim_e, fim_d) + 3

    # ------------------------------------------------------------ Observações (aba própria)
    wo = wb.add_worksheet("Observações")
    wo.hide_gridlines(2); wo.set_landscape(); wo.set_paper(9); wo.fit_to_pages(1, 0)
    wo.set_margins(0.25, 0.25, 0.35, 0.35); wo.set_footer('&L&10Norte Agro - Uso do Solo&C&P/&N')
    cab_o = ["Quadro", "Nº", "Situação", "Observação", "Tamanho", "Onde (E / N)", "Como resolver"]
    for col_o, larg in enumerate([30, 5, 12, 62, 14, 46, 62]):
        wo.set_column(col_o, col_o, larg)
    wo.merge_range(0, 0, 0, 6, f"{imovel_nome} - Observações", fmt_head); wo.set_row(0, 24)
    wo.merge_range(1, 0, 1, 6, cabecalho, fmt_ital)
    lo = 2
    avisos_topo = []
    if dados.get("tem_problemas_geometricos"):
        avisos_topo.append(("Há problemas de desenho nas camadas. O cálculo não alterou nenhuma camada: corrija o desenho antes de entregar os arquivos.", fmt_banner))
    if dados.get("tem_ajustes"):
        avisos_topo.append(("Valores do quadro com ajuste topológico em memória (sobreposições, lascas e partes fora resolvidas) - detalhes na aba Conferências, regras T1-T4.", fmt_banner_aj))
    if dados.get("houve_recorte"):
        avisos_topo.append(("Valores recortados no limite do imóvel - detalhes na aba Conferências.", fmt_recorte))
    for texto_av, fmt_av in avisos_topo:
        wo.merge_range(lo, 0, lo, 6, texto_av, fmt_av); wo.set_row(lo, 20); lo += 1
    lo += 1
    hdr_o = lo
    wo.write_row(hdr_o, 0, cab_o, fmt_cab)
    wo.freeze_panes(hdr_o + 1, 0)
    ordem_quadros = ["Áreas Totais do Imóvel", "Passivos ambientais", "Áreas Remanescentes", "Área antropizada antes de 2019",
                     "Área de Preservação Permanente", "Área antropizada após 2019", "Área Hidrográfica",
                     "Área Total de Compensação", "Outras camadas"]
    por_quadro = {}
    titulos_modelo = {TITULO_PADRAO_QUADRO[q["id"]]: q["titulo"] for q in mt["quadros"]}
    for item in dados.get("problemas_detalhados") or []:
        por_quadro.setdefault(str(item.get("quadro") or "").strip() or "Geral", []).append(item)
    ordem_quadros += [q for q in por_quadro if q not in ordem_quadros]
    for quadro_nome in ordem_quadros:
        probs = sorted(por_quadro.get(quadro_nome) or [], key=lambda x: (
            ORDEM_SITUACAO.get(str(x.get("situacao") or ""), 9),
            -(abs(_numero(x.get("area_ha"))) if x.get("area_ha") is not None else float(x.get("quantidade") or 0))))
        for i, item in enumerate(probs, 1):
            lo += 1
            sit = str(item.get("situacao") or "")
            wo.write(lo, 0, titulos_modelo.get(quadro_nome, quadro_nome), fmt_txt_wrap)
            wo.write_number(lo, 1, i, fmt_int_b)
            wo.write(lo, 2, sit, formatos_situacao.get(sit, fmt_txt))
            wo.write(lo, 3, str(item.get("descricao") or item.get("tipo") or ""), fmt_txt_wrap)
            wo.write(lo, 4, str(item.get("tamanho") or ""), fmt_txt_wrap)
            wo.write(lo, 5, str(item.get("onde") or ""), fmt_txt_wrap)
            wo.write(lo, 6, str(item.get("como_resolver") or ""), fmt_txt_wrap)
    if lo == hdr_o:
        lo += 1
        wo.merge_range(lo, 0, lo, 6, "Nenhum problema de desenho encontrado.", fmt_ok)
    else:
        wo.autofilter(hdr_o, 0, lo, 6)

    # ------------------------------------------------------------ Todas as camadas
    wt = wb.add_worksheet("Todas as camadas")
    wt.hide_gridlines(2); wt.freeze_panes(3, 2); wt.set_landscape(); wt.set_paper(9); wt.fit_to_pages(1, 0)
    wt.set_margins(0.25, 0.25, 0.35, 0.35); wt.set_footer('&L&10Norte Agro - Uso do Solo&C&P/&N')
    colunas = [
        ("Grupo", "grupo", "txt", 22), ("Nome no QGIS", "nome", "txt", 30), ("Arquivo de origem", "arquivo_origem", "txt", 48),
        ("Tipo", "tipo", "txt", 10), ("Feições", "feicoes", "int", 9),
        ("Área bruta (ha)", "area_bruta", "ha", 15), ("Fora do imóvel (ha)", "fora_imovel", "ha", 15),
        ("Área considerada (ha)", "area_considerada", "ha", 17), ("Ajuste topológico (ha)", "ajuste_topologico", "ha", 17),
        ("Área no quadro (ha)", "area_quadro", "ha", 16), ("Área no quadro (m²)", "_m2", "m2", 17),
        ("Comprimento (m)", "comprimento", "m2", 15), ("Registros sem geometria", "registros_sem_geometria", "int", 14),
        ("SRC original", "srid_original", "txt", 14), ("Reconhecida como", "_rec", "txt", 48),
    ]
    wt.merge_range(0, 0, 0, len(colunas) - 1, f"{imovel_nome} - Todas as camadas", fmt_head)
    wt.merge_range(1, 0, 1, len(colunas) - 1, cabecalho + " | Área no quadro = área considerada depois da resolução topológica (ver Conferências T1-T4)", fmt_ital)
    header_row = 2
    wt.write_row(header_row, 0, [c[0] for c in colunas], fmt_cab); wt.set_row(header_row, 30)
    linhas_todas = dados.get("todas", [])
    for rr, item in enumerate(linhas_todas, header_row + 1):
        for c, (_, chave, tipo, _) in enumerate(colunas):
            if chave == "_rec":
                wt.write(rr, c, item.get("reconhecida_texto") or item.get("reconhecida", "") or "", fmt_txt); continue
            if chave == "_m2":
                v = item.get("area_quadro")
                if v is None: wt.write_blank(rr, c, None)
                else: wt.write_number(rr, c, round(_numero(v) * 10000.0, 2), fmt_num2_nb)
                continue
            v = item.get(chave)
            if tipo == "txt":
                wt.write(rr, c, v or "", fmt_txt)
            elif tipo == "int":
                wt.write_number(rr, c, int(v or 0), fmt_int)
            elif v is None:
                wt.write_blank(rr, c, None)
            elif tipo == "ha":
                wt.write_number(rr, c, _r4(v), fmt_num_nb)
            else:
                wt.write_number(rr, c, round(_numero(v), 2), fmt_num2_nb)
    wt.autofilter(header_row, 0, max(header_row + 1, header_row + len(linhas_todas)), len(colunas) - 1)
    for c, col in enumerate(colunas):
        wt.set_column(c, c, col[3])

    # ------------------------------------------------------------ Conferências
    wc = wb.add_worksheet("Conferências")
    wc.hide_gridlines(2); wc.freeze_panes(3, 0); wc.set_landscape(); wc.set_paper(9); wc.fit_to_pages(1, 0)
    wc.set_margins(0.25, 0.25, 0.35, 0.35); wc.set_footer('&L&10Norte Agro - Uso do Solo&C&P/&N')
    cab = ["Regra", "Verificação", "Valor A", "Valor B", "Diferença", "Situação", "Como resolver"]
    wc.merge_range(0, 0, 0, len(cab) - 1, f"{imovel_nome} - Conferências", fmt_head)
    wc.merge_range(1, 0, 1, len(cab) - 1, cabecalho, fmt_ital)
    header_conf = 2
    wc.write_row(header_conf, 0, cab, fmt_cab)
    wc.set_column("A:A", 8); wc.set_column("B:B", 80); wc.set_column("C:E", 13); wc.set_column("F:F", 13); wc.set_column("G:G", 70)
    confs = list(dados.get("conferencias", []) or [])
    ordenadas = sorted(enumerate(confs), key=lambda par: (_secao(par[1]), ORDEM_SITUACAO.get(_situacao(par[1]), 9), par[0]))
    rr = header_conf
    secao_atual = None
    for _, item in ordenadas:
        sec = _secao(item)
        if sec != secao_atual:
            rr += 1; secao_atual = sec
            wc.merge_range(rr, 0, rr, len(cab) - 1, SECOES_CONFERENCIA[sec], fmt_secao)
        rr += 1
        wc.write(rr, 0, item.get("regra", "") or "", fmt_txt)
        wc.write(rr, 1, item.get("verificacao", "") or "", fmt_txt_wrap)
        a, b = item.get("a"), item.get("b")
        wc.write_blank(rr, 2, None, fmt_num) if a is None else wc.write_number(rr, 2, _numero(a), fmt_num)
        wc.write_blank(rr, 3, None, fmt_num) if b is None else wc.write_number(rr, 3, _numero(b), fmt_num)
        if a is not None and b is not None:
            dif = abs(_numero(a) - _numero(b)); tol = item.get("tolerancia")
            if tol is not None and dif < float(tol):
                dif = 0.0
            wc.write_number(rr, 4, dif, fmt_num)
        else:
            wc.write_blank(rr, 4, None, fmt_num)
        sit = _situacao(item)
        wc.write(rr, 5, sit, formatos_situacao.get(sit, fmt_txt))
        wc.write(rr, 6, item.get("como_resolver", "") or "", fmt_txt_wrap)
    if confs:
        wc.autofilter(header_conf, 0, rr, len(cab) - 1)
    row = rr + 3
    wc.write(row, 0, "Avisos", fmt_cab)
    for aviso in dados.get("avisos", []):
        row += 1
        wc.merge_range(row, 0, row, 6, str(aviso), fmt_ital)
    row += 2
    wc.merge_range(row, 0, row, 6, f"Data/hora: {dt} | Usuário: {dados.get('usuario','')} | Método: {metodo} | Elipsoide: {dados.get('elipsoide','')} | SRC: {dados.get('srid','')}", fmt_ital)

    try:
        wb.close()
    except xlsxwriter.exceptions.FileCreateError as exc:
        causa = getattr(exc, "__cause__", None)
        if isinstance(causa, PermissionError) or "Permission" in str(exc) or "Errno 13" in str(exc):
            raise PermissionError(caminho) from exc
        raise
    return caminho
