# -*- coding: utf-8 -*-
"""Modo "Modelo Norte Agro" (Fase 6): modelos de fábrica, biblioteca de QPTs e geração da planta sem IA.

Modelos de fábrica (desenhados a partir das plantas reais do escritório):
  - uso_solo  : Planta de Uso e Ocupação do Solo (plantas reais de clientes)
  - passivos  : Planta de Passivos e Regularização Ambiental (2019 x atual)

Os modelos são descritos em milímetros de uma folha A3 paisagem e escalados para A4, A2 ou A1
(as folhas A têm a mesma proporção). Fontes escalam junto.

Biblioteca: pasta configurável (padrão: <perfil do QGIS>/norteagro_modelos) com uma subpasta
por modelo: modelo.qpt + modelo.json + miniatura.png + recursos/. Pode apontar para uma pasta
de rede ou do Drive compartilhado.
"""

from .core import compat
import copy
import json
import os
import re
import shutil
import time
import unicodedata

from qgis.core import QgsApplication, QgsMapLayer, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap, \
    QgsLayoutItemPicture, QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsSettings

from . import builder
from .core import carto, log, planilha_areas
from .core.correspondencia import Correspondencia

CHAVE_CFG = "norteagro_layout_ia"
FOLHAS = {"A4": 297.0, "A3": 420.0, "A2": 594.0, "A1": 841.0}

# ---------------------------------------------------------------- textos com variáveis
TXT_PARAMETROS = ("[% @na_projecao %]\nDatum Horizontal: [% @na_datum %]\n"
                  "Meridiano Central: [% @na_mc %]\nFuso: [% @na_fuso %]")
TXT_DADOS = ("Fonte: [% @na_fonte %]\nElaboração: [% @na_elaboracao %]\nData: [% @na_data %]\n"
             "Escala: 1:[% format_number(map_get(item_variables('{mapa}'), 'map_scale'), 0) %]\n"
             "Folha: [% @na_folha %]")
TXT_IMOVEL = ("Propriedade: [% @na_imovel %]\nProprietário: [% @na_proprietario %]\nCAR: [% @na_car %]"
              "[% if(coalesce(@na_matricula, '') <> '', '\\nMatrícula: ' || @na_matricula, '') %]\n"
              "Município: [% @na_municipio %] - [% @na_uf %]")
TXT_RT = "[% @na_responsavel %]\n[% @na_rt_titulo %]\n[% @na_crea %]"


def _caixa_texto(itens, prefixo, x, y, w, h, titulo, corpo, tam_titulo, tam_corpo, assinatura=False):
    itens.append({"t": "caixa", "id": f"caixa_{prefixo}", "x": x, "y": y, "w": w, "h": h})
    itens.append({"t": "rotulo", "id": f"titulo_{prefixo}", "x": x, "y": y + 1, "w": w, "h": 4.5,
                  "texto": titulo, "tam": tam_titulo, "negrito": True})
    if assinatura:
        itens.append({"t": "assinatura", "id": "assinatura_rt", "x": x + w * 0.22, "y": y + 5.5, "w": w * 0.56,
                      "h": h * 0.30})
        yl = y + 5.5 + h * 0.31
        itens.append({"t": "linha", "id": "linha_assinatura", "x1": x + w * 0.12, "y1": yl, "x2": x + w * 0.88,
                      "y2": yl})
        itens.append({"t": "rotulo", "id": f"texto_{prefixo}", "x": x, "y": yl + 0.4, "w": w,
                      "h": y + h - yl - 0.8, "texto": corpo, "tam": tam_corpo})
    else:
        itens.append({"t": "rotulo", "id": f"texto_{prefixo}", "x": x, "y": y + 6, "w": w, "h": h - 7,
                      "texto": corpo, "tam": tam_corpo})


def _spec_uso_solo():
    itens = [
        {"t": "mapa", "id": "mapa_principal", "papel": "principal", "x": 5, "y": 5, "w": 322, "h": 287,
         "moldura": 0.4, "grade": ["left", "right", "top", "bottom"]},
        {"t": "norte", "id": "norte", "mapa": "mapa_principal", "x": 10, "y": 10, "w": 14, "h": 14,
         "svg": "norte_uso_solo.svg"},
        {"t": "escala", "id": "escala_grafica", "mapa": "mapa_principal", "x": 222, "y": 276, "w": 100, "h": 11,
         "canto": 1.5},  # presa no canto inferior direito do mapa
        {"t": "logo", "id": "logo", "x": 345.5, "y": 6, "w": 68.7, "h": 42.5},
        {"t": "mapa", "id": "mapa_localizacao", "papel": "localizacao", "x": 331.5, "y": 51, "w": 85.8,
         "h": 62, "moldura": 0.3},
        {"t": "rotulo", "id": "rotulo_localizacao", "x": 331.5, "y": 113.5, "w": 85.8, "h": 4.5,
         "texto": "Localização: [% @na_municipio %] - [% @na_uf %]", "tam": 6.5},
        {"t": "legenda", "id": "legenda", "mapa": "mapa_principal", "x": 331.5, "y": 119, "w": 85.8, "h": 61,
         "colunas": 1, "tam": 8, "limite_y": 180.5, "quebra": 30},  # nome longo desce para a linha de baixo
    ]
    _caixa_texto(itens, "parametros", 331.5, 182.5, 85.8, 27, "PARÂMETROS CARTOGRÁFICOS", TXT_PARAMETROS, 9, 7.5)
    _caixa_texto(itens, "dados", 331.5, 211.5, 85.8, 29, "DADOS DE PROJETO",
                 TXT_DADOS.format(mapa="mapa_principal"), 9, 7.5)
    _caixa_texto(itens, "imovel", 331.5, 242.5, 85.8, 25.5, "PLANTA DE USO E OCUPAÇÃO DO SOLO", TXT_IMOVEL, 9, 7)
    _caixa_texto(itens, "rt", 331.5, 270, 85.8, 24, "RESPONSÁVEL TÉCNICO", TXT_RT, 9, 6.5, assinatura=True)
    meta = {
        "id": "uso_solo",
        "nome": "Planta de Uso do Solo",
        "descricao": "Mapa principal com coordenadas, quadros de áreas dentro do mapa e coluna à direita "
                     "(logo, localização do município, legenda, parâmetros, dados, imóvel e RT).",
        "mapas": {
            "mapa_principal": {"role": "principal", "extent_mode": "camada", "crs": "auto", "margin": 0.04,
                               "grid": True},
            "mapa_localizacao": {"role": "localizacao", "extent_mode": "municipio", "crs": "EPSG:4674"},
        },
        # imagem de satélite do mapa principal: a mais recente do ano, com a melhor qualidade disponível
        "imagens": {"mapa_principal": {"tipo": "recente"}},
        # legenda: todas as camadas do grupo "Uso do Solo" do painel de camadas (escolhível na tela),
        # na ordem e com os nomes do padrão do escritório; camadas a mais entram entre Reserva legal e APP total
        "legendas": [{"id": "legenda", "mapa": "mapa_principal", "nome": "Legenda do mapa",
                      "grupo": ["USO DO SOLO"], "ordem": LEGENDA_USO_SOLO, "extras_apos": "RESERVA_LEGAL",
                      "filtrar": True}],
        # tabelas no canto superior direito do mapa; diminuem até não cobrirem o imóvel (o mapa só afasta
        # para a próxima escala redonda se nem no menor tamanho couberem)
        "tabelas": {"ancora": [270, 10, 56], "largura": 56, "espaco": 3.5, "fonte": 6.8,
                    "blocos": [{"chave": "remanescentes", "total": True, "mapa": "mapa_principal"},
                               {"chave": "app", "total": True, "mapa": "mapa_principal"},
                               {"chave": "hidrografica", "total": True, "mapa": "mapa_principal"},
                               {"chave": "totais", "total": True, "mapa": "mapa_principal"}]},
        "variaveis_extras": [],
    }
    return {"meta": meta, "itens": itens}


LEGENDA_USO_SOLO = [["Área do imóvel", "AREA_DO_IMOVEL"], ["Área consolidada", "AREA_CONSOLIDADA"],
                    ["Remanescente de vegetação nativa", "AREA_DE_VEGETACAO"], ["Reserva legal", "RESERVA_LEGAL"],
                    ["Servidão administrativa", "SERVIDAO_ADMINISTRATIVA"], ["APP total", "APP_TOTAL"],
                    ["Hidrografia", "HIDROGRAFIA"], ["Nascentes", "NASCENTE"], ["Área suprimida", "AREA_SUPRIMIDA"]]

LEGENDA_PASSIVOS = [["Imóvel", "AREA_DO_IMOVEL"], ["Hidrografia", "HIDROGRAFIA"], ["Barramentos", "BARRAGEM"],
                    ["Cacimba", "CACIMBA"], ["Nascente", "NASCENTE"],
                    ["Área suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019"],
                    ["Área suprimida depois de 2019", "AREA_SUPRIMIDA_DEPOIS_2019"]]


def _spec_passivos():
    itens = [
        {"t": "mapa", "id": "mapa_esquerdo", "papel": "principal", "x": 6, "y": 6, "w": 202, "h": 245,
         "moldura": 0.4, "grade": ["left", "top", "bottom"]},
        {"t": "mapa", "id": "mapa_direito", "papel": "detalhe", "x": 213, "y": 6, "w": 202, "h": 245,
         "moldura": 0.4, "grade": ["right", "top", "bottom"]},
        {"t": "rotulo", "id": "data_imagem_1", "x": 72, "y": 9, "w": 70, "h": 6.5,
         "texto": "[% @na_data_imagem_1 %]", "tam": 11, "negrito": True, "fundo": "#ffffff", "moldura": True},
        {"t": "rotulo", "id": "data_imagem_2", "x": 279, "y": 9, "w": 70, "h": 6.5,
         "texto": "[% @na_data_imagem_2 %]", "tam": 11, "negrito": True, "fundo": "#ffffff", "moldura": True},
        # uma legenda em cada mapa, no canto inferior esquerdo (cresce para cima até "topo")
        {"t": "legenda", "id": "legenda_esquerda", "mapa": "mapa_esquerdo", "x": 9, "y": 192, "w": 64, "h": 56,
         "colunas": 1, "tam": 7.5, "limite_y": 249, "topo": 110, "quebra": 34},
        {"t": "legenda", "id": "legenda", "mapa": "mapa_direito", "x": 216, "y": 192, "w": 64, "h": 56,
         "colunas": 1, "tam": 7.5, "limite_y": 249, "topo": 110, "quebra": 34},
        # barra de escala de cada mapa (padrão do QGIS), presa no canto inferior direito do mapa ("canto" = folga)
        {"t": "escala", "id": "escala_grafica", "mapa": "mapa_esquerdo", "x": 132, "y": 236, "w": 72, "h": 9,
         "canto": 1.5},
        {"t": "escala", "id": "escala_grafica_direita", "mapa": "mapa_direito", "x": 339, "y": 236, "w": 72,
         "h": 9, "canto": 1.5},
        {"t": "norte", "id": "norte", "mapa": "mapa_direito", "x": 378, "y": 261, "w": 14, "h": 27,
         "svg": "norte_passivos.svg"},
        {"t": "logo", "id": "logo", "x": 393, "y": 259, "w": 24, "h": 31},
    ]
    _caixa_texto(itens, "parametros", 8, 258, 94, 34, "PARÂMETROS CARTOGRÁFICOS", TXT_PARAMETROS, 8, 7)
    _caixa_texto(itens, "dados", 102, 258, 94, 34, "DADOS DE PROJETO",
                 TXT_DADOS.format(mapa="mapa_esquerdo"), 8, 7)
    _caixa_texto(itens, "imovel", 196, 258, 85, 34, "PLANTA DE PASSIVOS E REGULARIZAÇÃO AMBIENTAL",
                 TXT_IMOVEL, 7.5, 6.5)
    _caixa_texto(itens, "rt", 281, 258, 94, 34, "RESPONSÁVEL TÉCNICO", TXT_RT, 8, 7, assinatura=True)
    meta = {
        "id": "passivos",
        "nome": "Planta de Passivos",
        "descricao": "Dois mapas lado a lado com a mesma extensão (imagem antiga x atual), quadros de passivos "
                     "no mapa da direita e faixa inferior com parâmetros, dados, imóvel, RT, norte e logo.",
        "mapas": {
            "mapa_esquerdo": {"role": "principal", "extent_mode": "camada", "crs": "auto", "margin": 0.04,
                              "grid": True},
            "mapa_direito": {"role": "detalhe", "extent_mode": "igual:mapa_esquerdo", "crs": "igual:mapa_esquerdo",
                             "grid": True},
        },
        # tabelas: mapa da esquerda = Uso do Solo, mapa da direita = Passivos; cada pilha fica no canto superior
        # direito do seu mapa (legenda no inferior esquerdo) e diminui até não cobrir o imóvel
        "tabelas": {"ancora": [366, 60, 50], "largura": 50, "espaco": 3, "fonte": 6.2,
                    "blocos": [{"chave": "remanescentes", "total": True, "mapa": "mapa_esquerdo"},
                               {"chave": "app", "total": True, "mapa": "mapa_esquerdo"},
                               {"chave": "hidrografica", "total": True, "mapa": "mapa_esquerdo"},
                               {"chave": "totais", "total": True, "mapa": "mapa_esquerdo"},
                               {"chave": "passivos", "total": True, "mapa": "mapa_direito"},
                               {"chave": "antes_2019", "total": False, "mapa": "mapa_direito"},
                               {"chave": "apos_2019", "total": False, "mapa": "mapa_direito"}]},
        "variaveis_extras": [["na_data_imagem_1", "Data da imagem do mapa esquerdo", ""],
                             ["na_data_imagem_2", "Data da imagem do mapa direito", ""]],
        # imagem de satélite de cada mapa (busca automática) e a data que vai no quadro branco do mapa
        "imagens": {"mapa_esquerdo": {"tipo": "antiga", "variavel": "na_data_imagem_1"},
                    "mapa_direito": {"tipo": "recente", "variavel": "na_data_imagem_2"}},
        # mapa da esquerda: camadas do grupo "Uso do Solo" (mesmo padrão da planta de Uso do Solo);
        # mapa da direita: camadas do grupo "Passivos" (itens padrão + camadas do grupo).
        # A pessoa marca, desmarca, troca a camada, renomeia ou acrescenta itens na tela.
        # "travar_mapa": o mapa mostra só as camadas da sua legenda (e a imagem de satélite).
        # "excluir": camadas do grupo que não entram (a área suprimida antes/depois de 2019 fica só à direita).
        "legendas": [{"id": "legenda_esquerda", "mapa": "mapa_esquerdo", "nome": "Mapa da esquerda (Uso do Solo)",
                      "grupo": ["USO DO SOLO"], "ordem": LEGENDA_USO_SOLO, "extras_apos": "RESERVA_LEGAL",
                      "excluir": ["AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"],
                      "filtrar": False, "travar_mapa": True},
                     {"id": "legenda", "mapa": "mapa_direito", "nome": "Mapa da direita (Passivos)",
                      "grupo": ["PASSIVO"], "padrao": LEGENDA_PASSIVOS, "ordem": LEGENDA_PASSIVOS,
                      "extras_apos": "NASCENTE", "filtrar": False, "travar_mapa": True}],
    }
    return {"meta": meta, "itens": itens}


FABRICA = {"uso_solo": _spec_uso_solo, "passivos": _spec_passivos}


def modelos_fabrica():
    return [(k, f()["meta"]) for k, f in FABRICA.items()]


# ---------------------------------------------------------------- construção a partir da especificação
def construir_fabrica(projeto, chave, folha="A3", corr=None, assinatura=None, logo=None, nome=None):
    """Monta o layout vazio (sem dados) de um modelo de fábrica. Retorna (layout, meta)."""
    spec = FABRICA[chave]()
    meta = copy.deepcopy(spec["meta"])
    largura = FOLHAS.get(folha, 420.0)
    s = largura / 420.0
    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    layout.setName(nome or f"{meta['nome']} - {folha}")
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(largura, largura / (2 ** 0.5),
                                                              builder.MM))
    corr = corr or Correspondencia.carregar()
    criados = {}
    for it in spec["itens"]:
        t = it["t"]
        g = {k: (v * s if k in ("x", "y", "w", "h", "x1", "y1", "x2", "y2") else v) for k, v in it.items()}
        if t == "mapa":
            criados[it["id"]] = builder.mapa(layout, it["id"], g["x"], g["y"], g["w"], g["h"], papel=it["papel"],
                                             moldura=it.get("moldura", 0.4) * max(1.0, s ** 0.5))
            criados[it["id"]].setCustomProperty("na_grade", json.dumps(it.get("grade") or []))
        elif t == "caixa":
            builder.caixa(layout, it["id"], g["x"], g["y"], g["w"], g["h"], contorno=0.3 * max(1.0, s ** 0.5))
        elif t == "rotulo":
            builder.rotulo(layout, it["id"], it["texto"], g["x"], g["y"], g["w"], g["h"], tamanho=it["tam"] * s,
                           negrito=it.get("negrito", False), moldura=it.get("moldura", False),
                           fundo=it.get("fundo"))
        elif t == "linha":
            builder.linha(layout, it["id"], g["x1"], g["y1"], g["x2"], g["y2"], 0.25 * max(1.0, s ** 0.5))
        elif t == "logo":
            builder.figura(layout, it["id"], logo or os.path.join(builder.ASSETS, "logo_norteagro.png"),
                           g["x"], g["y"], g["w"], g["h"])
        elif t == "assinatura":
            p = builder.figura(layout, it["id"], assinatura if assinatura and os.path.isfile(assinatura) else None,
                               g["x"], g["y"], g["w"], g["h"])
            p.setCustomProperty("na_papel", "assinatura")
    # itens ligados a mapas depois dos mapas
    for it in spec["itens"]:
        t = it["t"]
        if t not in ("norte", "escala", "legenda"):
            continue
        g = {k: (v * s if k in ("x", "y", "w", "h") else v) for k, v in it.items()}
        alvo = criados[it["mapa"]]
        if t == "norte":
            builder.norte(layout, it["id"], alvo, g["x"], g["y"], g["w"], g["h"], arquivo=it.get("svg"))
        elif t == "escala":
            sb = builder.escala_grafica(layout, it["id"], alvo, g["x"], g["y"], g["w"], g["h"], tamanho=7 * s)
            if it.get("canto") is not None:  # presa no canto inferior direito do mapa
                sb.setCustomProperty("na_canto", it["canto"] * s)
                builder.ajustar_escala(sb)
        elif t == "legenda":
            leg = builder.legenda(layout, it["id"], alvo, g["x"], g["y"], g["w"], g["h"], corr,
                                  colunas=it.get("colunas", 2), tamanho=it.get("tam", 7) * s, camadas=[],
                                  quebra=(it.get("quebra") or 0) * s or None)
            leg.setCustomProperty("na_limite_y", (it.get("limite_y") or 0) * s)
            if it.get("quebra"):
                leg.setCustomProperty("na_quebra", it["quebra"] * s)  # largura do texto no tamanho normal
            leg.setCustomProperty("na_tam", it.get("tam", 7) * s)
            leg.setCustomProperty("na_largura", g["w"])
            leg.setCustomProperty("na_area", json.dumps([g["x"], g["y"], g["w"]]))
            if it.get("topo"):
                leg.setCustomProperty("na_topo", it["topo"] * s)
    meta["folha"] = folha
    meta["escala_folha"] = s
    layout.setCustomProperty("na_meta", json.dumps(meta, ensure_ascii=False))
    return layout, meta


def meta_do_layout(layout):
    bruto = layout.customProperty("na_meta", "")
    if bruto:
        try:
            return json.loads(bruto)
        except ValueError:
            pass
    # QPT sem meta: deduz pelos ids
    mapas = {}
    for it in layout.items():
        if isinstance(it, QgsLayoutItemMap) and it.id():
            papel = it.customProperty("na_papel", "principal" if not mapas else "localizacao")
            mapas[it.id()] = {"role": papel}
    return {"id": "personalizado", "nome": layout.name(), "mapas": mapas,
            "legenda": {"id": "legenda", "mapas": [next(iter(mapas), "")], "filtrar": True},
            "tabelas": {"ancora": [270, 10, 52], "blocos": []}, "variaveis_extras": [], "escala_folha": 1.0}


# ---------------------------------------------------------------- geração
def legendas_do_meta(meta):
    """Legendas do modelo: [{id, mapa, mapas, nome, grupo, padrao, ordem, extras_apos, filtrar}].
    Aceita o formato antigo (uma legenda: chaves legenda, legenda_grupo, legenda_padrao...)."""
    if meta.get("legendas"):
        saida = []
        for cfg in meta["legendas"]:
            cfg = dict(cfg)
            cfg.setdefault("mapas", [cfg.get("mapa")] if cfg.get("mapa") else [])
            saida.append(cfg)
        return saida
    antiga = meta.get("legenda") or {}
    if not antiga and not (meta.get("legenda_grupo") or meta.get("legenda_padrao")):
        return []
    mapas = antiga.get("mapas") or []
    return [{"id": antiga.get("id", "legenda"), "mapa": (mapas or [""])[0], "mapas": mapas, "nome": "Legenda",
             "grupo": meta.get("legenda_grupo") or [], "padrao": meta.get("legenda_padrao") or [],
             "ordem": meta.get("legenda_ordem") or [], "extras_apos": meta.get("legenda_extras_apos"),
             "filtrar": antiga.get("filtrar", True)}]


def legenda_escolhivel(cfg):
    """A legenda tem itens escolhidos na tela (grupo de camadas ou itens padrão)?"""
    return bool(cfg.get("grupo") or cfg.get("padrao"))


def _item(layout, ident):
    return layout.itemById(ident) if ident else None


def gerar_planta(projeto, layout, meta, dados, cfg_mapas=None, blocos=None, casas=4, corr=None, assinatura=None,
                 progresso=lambda t: None, imagens=None, legenda_itens=None, logo=None):
    """Preenche um layout (de fábrica ou carregado de QPT) com os dados do projeto.

    dados: variáveis na_* (imóvel, RT, elaboração, data, fonte...)
    cfg_mapas: {id_mapa: cfg} escolhida na tela (camadas, SRC, enquadramento), sobrepõe a do modelo.
    blocos: resultado de planilha_areas.importar() ou None (tabelas para preencher à mão).
    imagens: {id_mapa: camada raster} - imagem de satélite de cada mapa (substitui as outras imagens do mapa).
    legenda_itens: [(camada, nome)] - itens da legenda escolhidos na tela, nessa ordem (None = automático).
    Retorna a lista de avisos.
    """
    t0 = time.time()
    corr = corr or Correspondencia.carregar()
    avisos = []
    cfg_mapas = cfg_mapas or {}
    s = float(meta.get("escala_folha", 1.0))
    progresso("Gravando os dados do imóvel nas variáveis do projeto...")
    builder.definir_variaveis_projeto(projeto, dados)

    # mapas: primeiro os independentes, depois os que copiam outro ("igual:<id>")
    ordem = sorted(meta.get("mapas", {}).items(),
                   key=lambda kv: 1 if str(kv[1].get("extent_mode", "")).startswith("igual:") else 0)
    for ident, base in ordem:
        m = _item(layout, ident)
        if not isinstance(m, QgsLayoutItemMap):
            avisos.append(f"O modelo não tem o mapa '{ident}'.")
            continue
        cfg = dict(base)
        cfg.update({k: v for k, v in (cfg_mapas.get(ident) or {}).items() if v not in (None, "")})
        progresso(f"Configurando o mapa '{ident}'...")
        modo = str(cfg.get("extent_mode", ""))
        if modo.startswith("igual:"):
            ref = _item(layout, modo.split(":", 1)[1])
            cfg_ref = dict(cfg)
            cfg_ref["extent_mode"] = "projeto"
            if str(cfg.get("crs", "")).startswith("igual:") and isinstance(ref, QgsLayoutItemMap):
                cfg_ref["crs"] = ref.crs().authid() or "auto"
            builder.configurar_mapa(m, cfg_ref, projeto, corr, dados, avisos)
            if isinstance(ref, QgsLayoutItemMap):
                m.setCrs(ref.crs())
                m.setExtent(ref.extent())
                m.setScale(ref.scale())
        else:
            builder.configurar_mapa(m, cfg, projeto, corr, dados, avisos)
        if imagens and imagens.get(ident) is not None:
            _trocar_imagem(projeto, m, imagens[ident])
        if cfg.get("grid", base.get("grid")):
            lados = json.loads(m.customProperty("na_grade", "[]") or "[]") or ["left", "right", "top", "bottom"]
            while m.grids().size():
                m.grids().removeGrid(m.grids().grid(0).id())
            builder.grade(m, lados=lados, tamanho=6 * s)

    # legendas (uma por mapa quando o modelo tem mais de uma)
    cfgs_leg = legendas_do_meta(meta)
    if isinstance(legenda_itens, list):  # formato antigo: itens da primeira legenda
        legenda_itens = {cfgs_leg[0]["id"]: legenda_itens} if cfgs_leg else None
    for leg_cfg in cfgs_leg:
        leg = _item(layout, leg_cfg.get("id", "legenda"))
        if not isinstance(leg, QgsLayoutItemLegend):
            continue
        escolhidos = (legenda_itens or {}).get(leg.id()) if legenda_itens is not None else None
        camadas = []
        for mid in leg_cfg.get("mapas", []):
            m = _item(layout, mid)
            if isinstance(m, QgsLayoutItemMap):
                for c in m.layers():
                    if c not in camadas:
                        camadas.append(c)
        # legenda escolhida na tela: sem filtro pelo mapa (o filtro é calculado depois, em segundo plano, e
        # impede de medir a legenda para encaixá-la no espaço reservado)
        leg.setLegendFilterByMapEnabled(bool(leg_cfg.get("filtrar", True)) and escolhidos is None)
        if escolhidos is not None:
            itens_ok = [(c, n) for c, n in escolhidos if c is not None]
            # camada escolhida para a legenda precisa estar desenhada no mapa ligado à legenda
            ligado = leg.linkedMap() or _item(layout, (leg_cfg.get("mapas") or [""])[0])
            if isinstance(ligado, QgsLayoutItemMap) and leg_cfg.get("travar_mapa"):
                # mapa travado: só as camadas desta legenda (e as imagens de satélite/fundo que já estavam)
                imagens_mapa = [c for c in ligado.layers() if c.type() == compat.CAMADA_RASTER]
                ligado.setLayers(builder.ordenar_como_painel(projeto, [c for c, _n in itens_ok] + imagens_mapa))
                ligado.setKeepLayerSet(True)
                ligado.storeCurrentLayerStyles()
            elif isinstance(ligado, QgsLayoutItemMap):
                faltam = [c for c, _n in itens_ok if c not in ligado.layers()]
                if faltam:
                    ligado.setLayers(builder.ordenar_como_painel(projeto, ligado.layers() + faltam))
                    ligado.storeCurrentLayerStyles()
                    avisos.append(f"Acrescentadas ao mapa '{ligado.id()}' (legenda): " +
                                  ", ".join(c.name() for c in faltam) + ".")
            builder.montar_legenda(leg, [c for c, _n in itens_ok], corr,
                                   nomes={c.id(): n for c, n in itens_ok if n})
        else:
            builder.montar_legenda(leg, camadas, corr)
        _ajustar_legenda(leg, avisos)

    # legendas dentro dos mapas (Passivos): mesma caixa nos dois mapas, presas embaixo, como espelho
    dentro = [it for it in layout.items() if isinstance(it, QgsLayoutItemLegend)
              and it.customProperty("na_topo") not in (None, "")]
    if len(dentro) > 1:
        w = max(l.sizeWithUnits().width() for l in dentro)
        h = max(l.sizeWithUnits().height() for l in dentro)
        for l in dentro:
            l.setResizeToContents(False)
            l.attemptResize(QgsLayoutSize(w, h, builder.MM))
            limite = float(l.customProperty("na_limite_y", 0) or 0) or (l.positionWithUnits().y() + h)
            l.attemptMove(QgsLayoutPoint(l.positionWithUnits().x(), limite - h, builder.MM))

    # escala gráfica: tamanho padrão do QGIS para a escala final do mapa (como o botão do compositor)
    for it in layout.items():
        if isinstance(it, QgsLayoutItemScaleBar) and it.linkedMap() is not None:
            builder.ajustar_escala(it)

    # tabelas
    progresso("Montando os quadros de áreas...")
    cfg_tab = meta.get("tabelas") or {}
    if cfg_tab.get("blocos"):
        chaves = [b["chave"] for b in cfg_tab["blocos"]]
        if blocos is None:
            blocos = planilha_areas.blocos_vazios(chaves)
            avisos.append("Sem planilha de áreas: as tabelas ficaram com os campos para preenchimento manual.")
        builder.preencher_tabelas_areas(layout, meta, blocos, escala=s, casas=casas)

        def refazer_tabelas(fator):
            builder.preencher_tabelas_areas(layout, meta, blocos, escala=s, casas=casas, fator=fator)
    else:
        refazer_tabelas = None

    # imóvel no centro; barra de escala do canto, tabelas e legenda sem ficar em cima dele
    _arrumar_dentro_dos_mapas(projeto, layout, meta, corr, s, avisos, refazer_tabelas)

    # logo do escritório (configurações) no lugar da logo, também em modelos da biblioteca
    if logo and os.path.isfile(logo):
        for it in layout.items():
            if isinstance(it, QgsLayoutItemPicture) and (it.id() == "logo" or it.customProperty("na_papel") == "logo"):
                it.setPicturePath(builder.caminho_base64(logo))
                it.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
                it.setCustomProperty("na_origem", os.path.basename(logo))
    # assinatura do RT (sempre do perfil, nunca da imagem)
    for it in layout.items():
        if isinstance(it, QgsLayoutItemPicture) and it.customProperty("na_papel") == "assinatura":
            if assinatura and os.path.isfile(assinatura):
                it.setPicturePath(builder.caminho_base64(assinatura))
                it.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
                it.setCustomProperty("na_origem", os.path.basename(assinatura))
            else:
                it.setPicturePath("")

    principal = next((_item(layout, i) for i, c in meta.get("mapas", {}).items() if c.get("role") == "principal"),
                     None)
    if isinstance(principal, QgsLayoutItemMap):
        vals = builder.definir_variaveis_layout(layout, principal)
        if principal.crs().isGeographic():
            avisos.append("O mapa principal está em coordenadas geográficas; para planta técnica use SIRGAS 2000 "
                          "/ UTM (deixe o SRC em 'automático').")
        log.info(f"Parâmetros cartográficos: {vals}")
    layout.refresh()
    progresso(f"Planta montada em {time.time() - t0:.1f} s.")
    return avisos


def _arrumar_dentro_dos_mapas(projeto, layout, meta, corr, s=1.0, avisos=None, refazer_tabelas=None):
    """Nada em cima do imóvel: a barra de escala presa no canto e as pilhas de tabelas de cada mapa
    (procuram um canto livre do imóvel e dos outros itens). Se não houver lugar, o mapa afasta para a
    próxima escala redonda, sempre com o imóvel no centro, e tenta de novo."""
    from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsLayoutItemPage, QgsRectangle
    avisos = avisos if avisos is not None else []
    cfg_mapas = meta.get("mapas") or {}
    imovel = builder.camada_imovel(projeto, corr) if corr else None
    geom = None
    if imovel is not None:
        partes = [f.geometry() for f in imovel.getFeatures() if f.hasGeometry()]
        geom = QgsGeometry.unaryUnion(partes) if partes else None
    em_crs = {}

    def geom_no_mapa(mapa):
        chave = mapa.crs().authid()
        if chave not in em_crs:
            g = QgsGeometry(geom)
            if imovel.crs() != mapa.crs():
                g.transform(QgsCoordinateTransform(imovel.crs(), mapa.crs(), projeto.transformContext()))
            em_crs[chave] = g
        return em_crs[chave]

    def ret_mm(it):
        p, t = it.positionWithUnits(), it.sizeWithUnits()
        return p.x(), p.y(), p.x() + t.width(), p.y() + t.height()

    def cobre_imovel(mapa, r, folga=1.5):
        """O retângulo r (mm na folha) cobre o desenho do imóvel neste mapa?"""
        if geom is None:
            return False
        ext = mapa.extent()
        mx0, my0, mx1, my1 = ret_mm(mapa)
        lw, lh = mx1 - mx0, my1 - my0
        x0, y0, x1, y1 = r[0] - folga, r[1] - folga, r[2] + folga, r[3] + folga
        q = QgsRectangle(ext.xMinimum() + (x0 - mx0) / lw * ext.width(), ext.yMaximum() - (y1 - my0) / lh * ext.height(),
                         ext.xMinimum() + (x1 - mx0) / lw * ext.width(), ext.yMaximum() - (y0 - my0) / lh * ext.height())
        return geom_no_mapa(mapa).intersects(QgsGeometry.fromRect(q))

    def base(mapa):
        modo = str((cfg_mapas.get(mapa.id()) or {}).get("extent_mode", ""))
        ref = _item(layout, modo.split(":", 1)[1]) if modo.startswith("igual:") else None
        return ref if isinstance(ref, QgsLayoutItemMap) else mapa

    mexidos = set()

    def afastar(mapas):
        """Próxima escala redonda nos mapas (e nos que copiam a extensão deles); barras de escala de novo."""
        bases = {base(m_).id(): base(m_) for m_ in mapas}
        for mapa in bases.values():
            mapa.setScale(carto.escala_arredondada(mapa.scale() * 1.001 + 1))
            mexidos.add(mapa.id())
        for ident, cfg in cfg_mapas.items():
            modo = str(cfg.get("extent_mode", ""))
            m_ = _item(layout, ident)
            ref = _item(layout, modo.split(":", 1)[1]) if modo.startswith("igual:") else None
            if isinstance(m_, QgsLayoutItemMap) and isinstance(ref, QgsLayoutItemMap) and ref.id() in mexidos:
                m_.setExtent(ref.extent())
                m_.setScale(ref.scale())
                mexidos.add(ident)
        for b in layout.items():
            if isinstance(b, QgsLayoutItemScaleBar) and b.linkedMap() is not None:
                builder.ajustar_escala(b)

    # 1) barras de escala presas no canto
    barras = [b for b in layout.items() if isinstance(b, QgsLayoutItemScaleBar) and b.linkedMap() is not None
              and b.customProperty("na_canto") not in (None, "")]
    for _ in range(12):
        cobrindo = [b.linkedMap() for b in barras if cobre_imovel(b.linkedMap(), ret_mm(b))]
        if not cobrindo:
            break
        afastar(cobrindo)

    # 2) pilhas de tabelas de cada mapa
    pilhas = {}
    for it in layout.items():
        g = it.customProperty("na_grupo_tab", "") if hasattr(it, "customProperty") else ""
        if g and isinstance(_item(layout, g), QgsLayoutItemMap):
            pilhas.setdefault(g, []).append(it)

    def obstaculos(mapa, proprios):
        mx0, my0, mx1, my1 = ret_mm(mapa)
        saida = []
        for it in layout.items():
            if it in proprios or isinstance(it, (QgsLayoutItemMap, QgsLayoutItemPage)) or not it.isVisible():
                continue
            if not hasattr(it, "positionWithUnits"):
                continue
            r = ret_mm(it)
            if r[2] > mx0 and r[0] < mx1 and r[3] > my0 and r[1] < my1:
                saida.append(r)
        return saida

    motores = []

    def preparar(mapa):
        """Imóvel no mapa já preparado para testes rápidos de interseção."""
        if geom is None:
            return None
        g = geom_no_mapa(mapa)
        motor = QgsGeometry.createGeometryEngine(g.constGet())
        motor.prepareGeometry()
        motores.append((g, motor))  # mantém a geometria viva enquanto o motor é usado
        return motor

    def livre_em(mapa, motor, obs, r):
        mx0, my0, mx1, my1 = ret_mm(mapa)
        borda, folga = 2.5 * s, 1.5 * s
        if r[0] < mx0 + borda - 0.01 or r[2] > mx1 - borda + 0.01 or r[1] < my0 + borda - 0.01 \
                or r[3] > my1 - borda + 0.01:
            return False
        if any(r[0] < o[2] + folga and r[2] > o[0] - folga and r[1] < o[3] + folga and r[3] > o[1] - folga
               for o in obs):
            return False
        if motor is None:
            return True
        ext = mapa.extent()
        lw, lh = mx1 - mx0, my1 - my0
        x0, y0, x1, y1 = r[0] - folga, r[1] - folga, r[2] + folga, r[3] + folga
        q = QgsRectangle(ext.xMinimum() + (x0 - mx0) / lw * ext.width(), ext.yMaximum() - (y1 - my0) / lh * ext.height(),
                         ext.xMinimum() + (x1 - mx0) / lw * ext.width(), ext.yMaximum() - (y0 - my0) / lh * ext.height())
        caixa_geo = QgsGeometry.fromRect(q)  # guardada numa variável: o motor só recebe a referência
        return not motor.intersects(caixa_geo.constGet())

    # 2) padrão fixo e espelhado: tabelas no canto superior direito de cada mapa e legenda no canto inferior
    #    esquerdo. Se cobrirem o imóvel, diminuem (letra e largura) até ficarem livres; o mapa só afasta
    #    (próxima escala redonda) se nem no menor tamanho couberem: o mapa é o que mais importa.
    from qgis.core import QgsLegendStyle
    # sempre o MAIOR tamanho que cabe: do maior (180%) ao menor (65%); fica o primeiro que não cobre nada
    FATORES = [round(1.8 - 0.05 * i, 2) for i in range(24)]  # 1,80 ... 0,65
    LARGURA_MAX_TABELA = 0.45  # a pilha de tabelas ocupa no máximo 45% da largura do mapa
    FATORES_LEGENDA = [f for f in FATORES if f <= 1.0]  # legenda não passa do tamanho do modelo (só diminui)
    legendas = sorted([l for l in layout.items() if isinstance(l, QgsLayoutItemLegend) and l.linkedMap() is not None
                       and l.customProperty("na_topo") not in (None, "")], key=lambda l: l.linkedMap().id())
    motores_mapa = {}

    def motor_de(mapa):
        if mapa.id() not in motores_mapa:
            motores_mapa[mapa.id()] = preparar(mapa)
        return motores_mapa[mapa.id()]

    def pilhas_atuais():
        saida = {}
        for it in layout.items():
            g = it.customProperty("na_grupo_tab", "") if hasattr(it, "customProperty") else ""
            if g and isinstance(_item(layout, g), QgsLayoutItemMap):
                saida.setdefault(g, []).append(it)
        return saida

    def caixa(itens):
        rs = [ret_mm(i) for i in itens]
        return min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)

    def tabelas_livres():
        atuais = pilhas_atuais()
        todas = [it for its in atuais.values() for it in its] + legendas
        for g, itens in atuais.items():
            mp = _item(layout, g)
            if not livre_em(mp, motor_de(mp), obstaculos(mp, todas), caixa(itens)):
                return False
        return True

    def legenda_no_tamanho(fator):
        """Letra da legenda * fator, caixas iguais nos mapas, presas no canto inferior esquerdo."""
        tams = []
        for l in legendas:
            t = float(l.customProperty("na_tam", 7) or 7) * fator
            for estilo in (QgsLegendStyle.Style.SymbolLabel, QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.Group):
                builder.formato_estilo_legenda(l.rstyle(estilo), builder.formato_texto(t))
            builder.formato_estilo_legenda(l.rstyle(QgsLegendStyle.Style.Title), builder.formato_texto(t * 1.15, negrito=True))
            l.setSymbolWidth(7 * t / 8)
            l.setSymbolHeight(4 * t / 8)
            if l.customProperty("na_quebra"):
                builder.quebrar_legenda(l, float(l.customProperty("na_quebra")) * fator)
            tams.append(_medir_legenda(l))
        w, h = max(t[0] for t in tams), max(t[1] for t in tams)
        for l in legendas:
            mx0, _my0, _mx1, my1 = ret_mm(l.linkedMap())
            l.setResizeToContents(False)
            l.attemptResize(QgsLayoutSize(w, h, builder.MM))
            l.attemptMove(QgsLayoutPoint(mx0 + 2.5 * s, my1 - 2.5 * s - h, builder.MM))

    def legendas_livres():
        tabs = [it for its in pilhas_atuais().values() for it in its]
        for l in legendas:
            mp = l.linkedMap()
            if not livre_em(mp, motor_de(mp), obstaculos(mp, legendas + tabs), ret_mm(l)):
                return False
        return True

    if pilhas or legendas:
        mapas_moveis = []
        for mp in [_item(layout, g) for g in sorted(pilhas)] + [l.linkedMap() for l in legendas]:
            if mp not in mapas_moveis:
                mapas_moveis.append(mp)
        # Rápido: mede legenda e tabelas uma vez no tamanho normal e testa os tamanhos menores só com
        # retângulos (o tamanho é proporcional ao fator); refaz os itens de verdade uma única vez no fator
        # escolhido e confere. Assim cada escala custa milissegundos em vez de refazer as tabelas 8 vezes.
        if pilhas and refazer_tabelas is not None:
            refazer_tabelas(1.0)
            base_tab = {g: caixa(its) for g, its in pilhas_atuais().items()}
        else:
            base_tab = {}
        if legendas:
            legenda_no_tamanho(1.0)
            base_leg = {l: ret_mm(l) for l in legendas}
        else:
            base_leg = {}
        fixos_por_mapa = {}

        def fixos(mapa):
            if mapa.id() not in fixos_por_mapa:
                moveis = [it for its in pilhas_atuais().values() for it in its] + legendas
                fixos_por_mapa[mapa.id()] = obstaculos(mapa, moveis)
            return fixos_por_mapa[mapa.id()]

        def tab_no_fator(f):
            """Retângulos das pilhas no fator f (presas no canto superior direito)."""
            saida = {}
            for g, (x0, y0, x1, y1) in base_tab.items():
                saida[g] = (x1 - (x1 - x0) * f, y0, x1, y0 + (y1 - y0) * f)
            return saida

        def leg_no_fator(f):
            saida = {}
            for l, (x0, y0, x1, y1) in base_leg.items():
                saida[l] = (x0, y1 - (y1 - y0) * f, x0 + (x1 - x0) * f, y1)  # presa no canto inferior esquerdo
            return saida

        def fator_livre(retangulos_no_fator, mapa_de, extras=lambda f: [], largura_max=None, fatores=FATORES):
            for f in fatores:
                rets = retangulos_no_fator(f)
                if largura_max is not None and any(
                        r[2] - r[0] > largura_max * (ret_mm(mapa_de(k))[2] - ret_mm(mapa_de(k))[0]) for k, r in rets.items()):
                    continue
                if all(livre_em(mapa_de(k), motor_de(mapa_de(k)), fixos(mapa_de(k)) + extras(f), r)
                       for k, r in rets.items()):
                    return f
            return None

        for _ in range(15):
            f_tab = fator_livre(tab_no_fator, lambda g: _item(layout, g), largura_max=LARGURA_MAX_TABELA) \
                if base_tab else 1.0
            f_leg = None
            if f_tab is not None:
                f_leg = fator_livre(leg_no_fator, lambda l: l.linkedMap(),
                                    lambda f: list(tab_no_fator(f_tab).values()),
                                    fatores=FATORES_LEGENDA) if base_leg else 1.0
            if f_tab is not None and f_leg is not None:
                if base_tab:
                    refazer_tabelas(f_tab)
                if base_leg:
                    legenda_no_tamanho(f_leg)
                # confere com os itens de verdade; se a estimativa falhou, desce um passo de cada vez
                ok = (not base_tab or tabelas_livres()) and (not base_leg or legendas_livres())
                if not ok:
                    for f in [x for x in FATORES if base_tab and x < f_tab]:
                        refazer_tabelas(f)
                        if tabelas_livres():
                            break
                    for f in [x for x in FATORES if base_leg and x < f_leg]:
                        legenda_no_tamanho(f)
                        if legendas_livres():
                            break
                    ok = (not base_tab or tabelas_livres()) and (not base_leg or legendas_livres())
                if ok:
                    break
                if base_tab:
                    refazer_tabelas(1.0)
                if base_leg:
                    legenda_no_tamanho(1.0)
            afastar(mapas_moveis)
        else:
            avisos.append("Não achei tamanho para a legenda e as tabelas sem cobrir o imóvel; confira a planta.")

    # coordenadas da moldura de novo para a nova escala
    for ident in mexidos:
        m_ = _item(layout, ident)
        if isinstance(m_, QgsLayoutItemMap) and m_.grids().size():
            lados = json.loads(m_.customProperty("na_grade", "[]") or "[]") or ["left", "right", "top", "bottom"]
            while m_.grids().size():
                m_.grids().removeGrid(m_.grids().grid(0).id())
            builder.grade(m_, lados=lados, tamanho=6 * s)
        if isinstance(m_, QgsLayoutItemMap):
            m_.refresh()


def _trocar_imagem(projeto, mapa, imagem):
    """Deixa no mapa só esta imagem de fundo (tira outras imagens/mapas de fundo marcados)."""
    from qgis.core import QgsMapLayer
    vetores = [c for c in mapa.layers() if c.type() != compat.CAMADA_RASTER]
    mapa.setLayers(builder.ordenar_como_painel(projeto, vetores + [imagem]))
    mapa.setKeepLayerSet(True)
    mapa.storeCurrentLayerStyles()
    mapa.refresh()


def _ajustar_legenda(leg, avisos):
    """Faz a legenda caber no espaço reservado (sem invadir os quadros abaixo):
    1) aproxima os itens; 2) diminui a letra até 75%; 3) passa para duas colunas, se couber na largura."""
    limite = float(leg.customProperty("na_limite_y", 0) or 0)
    if not limite:
        return
    tam0 = float(leg.customProperty("na_tam", 7) or 7)
    largura_max = leg.sizeWithUnits().width() if not leg.customProperty("na_largura") else \
        float(leg.customProperty("na_largura"))
    leg.setCustomProperty("na_largura", largura_max)

    leg.setResizeToContents(True)  # a caixa acompanha o conteúdo (senão os últimos itens ficam cortados)
    topo = float(leg.customProperty("na_topo", 0) or 0)
    if topo:
        # legenda dentro do mapa, presa embaixo: mede a partir do topo permitido e depois desce até o limite
        pos = leg.positionWithUnits()
        leg.attemptMove(QgsLayoutPoint(pos.x(), topo, builder.MM))
        try:
            _encaixar_legenda(leg, avisos, limite, tam0, largura_max)
        finally:
            leg.attemptMove(QgsLayoutPoint(pos.x(), limite - leg.sizeWithUnits().height(), builder.MM))
        return
    _encaixar_legenda(leg, avisos, limite, tam0, largura_max)
    # centraliza a legenda no espaço reservado (na largura e na altura)
    try:
        x0, y0, w0 = [float(v) for v in json.loads(leg.customProperty("na_area", "") or "null")]
    except (TypeError, ValueError):
        return
    tam = leg.sizeWithUnits()
    x = x0 + max(0.0, (w0 - tam.width()) / 2)
    y = y0 + max(0.0, (limite - y0 - tam.height()) / 2)
    leg.attemptMove(QgsLayoutPoint(x, y, builder.MM))


def _medir_legenda(leg):
    """Mede a legenda com o desenhador do QGIS (pintor a 300 dpi) e ajusta a caixa. Retorna (largura, altura)."""
    from qgis.core import QgsLayoutUtils, QgsLegendRenderer
    from qgis.PyQt.QtGui import QImage, QPainter
    leg.refresh()
    imagem = QImage(4, 4, QImage.Format.Format_ARGB32)
    pintor = QPainter(imagem)
    try:
        ctx = QgsLayoutUtils.createRenderContextForLayout(leg.layout(), pintor, 300)
        tam = QgsLegendRenderer(leg.model(), leg.legendSettings()).minimumSize(ctx)
    finally:
        pintor.end()
    if tam.width() > 0 and tam.height() > 0:
        leg.attemptResize(QgsLayoutSize(tam.width(), tam.height(), builder.MM))
    return leg.sizeWithUnits().width(), leg.sizeWithUnits().height()


def _encaixar_legenda(leg, avisos, limite, tam0, largura_max):
    from qgis.core import QgsLegendStyle

    def fim():
        # mede com o próprio desenhador de legendas (o adjustBoxSize do QGIS 3.44 não redimensiona aqui)
        # (com um pintor a 300 dpi: sem pintor o QGIS mede o texto em 88 dpi e a legenda sai mais larga)
        from qgis.core import QgsLayoutUtils, QgsLegendRenderer
        from qgis.PyQt.QtGui import QImage, QPainter
        leg.refresh()
        imagem = QImage(4, 4, QImage.Format.Format_ARGB32)
        pintor = QPainter(imagem)
        try:
            ctx = QgsLayoutUtils.createRenderContextForLayout(leg.layout(), pintor, 300)
            tam = QgsLegendRenderer(leg.model(), leg.legendSettings()).minimumSize(ctx)
        finally:
            pintor.end()
        if tam.width() > 0 and tam.height() > 0:
            leg.attemptResize(QgsLayoutSize(tam.width(), tam.height(), builder.MM))
        return leg.positionWithUnits().y() + leg.sizeWithUnits().height()

    def fonte(fator):
        tam = tam0 * fator
        for estilo in (QgsLegendStyle.Style.SymbolLabel, QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.Group):
            builder.formato_estilo_legenda(leg.rstyle(estilo), builder.formato_texto(tam))
        builder.formato_estilo_legenda(leg.rstyle(QgsLegendStyle.Style.Title), builder.formato_texto(tam * 1.15, negrito=True))
        leg.setSymbolWidth(7 * tam / 8)
        leg.setSymbolHeight(4 * tam / 8)
        quebra = leg.customProperty("na_quebra")
        if quebra:  # a quebra acompanha a letra: só nome realmente longo desce para a linha de baixo
            builder.quebrar_legenda(leg, float(quebra) * fator)

    def cabe():
        # folga de 4 mm na largura: o texto impresso sai um pouco mais largo que o medido e a legenda
        # fica centralizada com uma pequena margem dos dois lados
        return fim() <= limite + 0.01 and leg.sizeWithUnits().width() <= largura_max - 4

    leg.setEqualColumnWidth(False)
    # 1) uma coluna, letra normal
    leg.setColumnCount(1)
    if cabe():
        return
    # 2) pouco espaço: duas colunas, diminuindo a letra só o necessário para caber na largura
    leg.setColumnCount(2)
    leg.setEqualColumnWidth(False)
    fator = 1.0
    while True:
        if cabe():
            return
        if fator <= 0.71:
            break
        fator -= 0.05
        fonte(fator)
    for margem in (1.6, 1.0, 0.6):  # itens mais próximos
        leg.rstyle(QgsLegendStyle.Style.Symbol).setMargin(QgsLegendStyle.Side.Top, margem)
        leg.rstyle(QgsLegendStyle.Style.SymbolLabel).setMargin(QgsLegendStyle.Side.Top, margem)
        if cabe():
            return
    # 3) nem em duas colunas coube: uma coluna com itens próximos e letra menor
    leg.setColumnCount(1)
    fonte(1.0)
    if cabe():
        return
    fator = 1.0
    while fator > 0.71:
        fator -= 0.05
        fonte(fator)
        if cabe():
            return
    avisos.append("A legenda ficou maior que o espaço reservado; confira se ela cobre outros quadros.")

# ---------------------------------------------------------------- biblioteca
def pasta_biblioteca():
    s = QgsSettings()
    padrao = os.path.join(QgsApplication.qgisSettingsDirPath(), "norteagro_modelos")
    return s.value(f"{CHAVE_CFG}/biblioteca", padrao)


def definir_pasta_biblioteca(caminho):
    QgsSettings().setValue(f"{CHAVE_CFG}/biblioteca", caminho)


def _slug(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s or "modelo"


def listar_biblioteca(pasta=None):
    """[(caminho_pasta, meta)] dos modelos salvos na biblioteca."""
    pasta = pasta or pasta_biblioteca()
    saida = []
    if not os.path.isdir(pasta):
        return saida
    for nome in sorted(os.listdir(pasta)):
        d = os.path.join(pasta, nome)
        qpt = os.path.join(d, "modelo.qpt")
        if os.path.isdir(d) and os.path.isfile(qpt):
            meta = {"nome": nome}
            mj = os.path.join(d, "modelo.json")
            if os.path.isfile(mj):
                try:
                    with open(mj, encoding="utf-8") as fh:
                        meta = json.load(fh)
                except (OSError, ValueError):
                    pass
            saida.append((d, meta))
    return saida


def copia_sem_dados(layout):
    """Cópia do layout para a biblioteca: sem camadas/caminhos do cliente nos mapas e sem as tabelas de
    áreas preenchidas (o modelo é refeito com os dados de cada imóvel na geração)."""
    copia = layout.clone()
    for it in copia.items():
        if isinstance(it, QgsLayoutItemMap):
            it.setLayers([])
            it.setKeepLayerSet(False)
            it.setLayerStyleOverrides({})
            it.setKeepLayerStyles(False)
            it.setFollowVisibilityPreset(False)
        elif isinstance(it, QgsLayoutItemLegend):
            it.setAutoUpdateModel(False)
            it.model().rootGroup().removeAllChildren()
    builder.remover_tabelas_areas(copia)
    copia.setName(layout.name())
    return copia


def salvar_como_modelo(layout, nome, descricao="", pasta=None):
    """Grava QPT + recursos + miniatura + modelo.json numa subpasta da biblioteca.
    Bloqueia se houver CPF/CNPJ/CREA/e-mail literal nos textos."""
    suspeitos = builder.verificar_identidade(layout)
    if suspeitos:
        raise PermissionError("Modelo não salvo: há textos com dados pessoais não confirmados: " +
                              "; ".join(f"{i}: {t}" for i, t in suspeitos[:5]))
    pasta = pasta or pasta_biblioteca()
    destino = os.path.join(pasta, _slug(nome))
    if os.path.exists(destino):
        destino = f"{destino}_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(os.path.join(destino, "recursos"), exist_ok=True)
    meta = meta_do_layout(layout)
    meta["nome"] = nome
    meta["descricao"] = descricao or meta.get("descricao", "")
    meta["salvo_em"] = time.strftime("%d/%m/%Y %H:%M")
    modelo = copia_sem_dados(layout)
    modelo.setCustomProperty("na_meta", json.dumps(meta, ensure_ascii=False))
    builder.salvar_qpt(modelo, os.path.join(destino, "modelo.qpt"))
    try:
        builder.exportar_previa(modelo, os.path.join(destino, "miniatura.png"), dpi=30)
    except RuntimeError as e:
        log.aviso(f"Miniatura não gerada: {e}")
    for it in layout.items():
        if isinstance(it, QgsLayoutItemPicture):
            nome_rec = it.customProperty("na_origem", "")
            cand = os.path.join(builder.ASSETS, nome_rec) if nome_rec else ""
            if cand and os.path.isfile(cand):
                shutil.copy2(cand, os.path.join(destino, "recursos", nome_rec))
    with open(os.path.join(destino, "modelo.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return destino


def abrir_modelo(projeto, origem, folha="A3", corr=None, assinatura=None, logo=None, nome=None):
    """origem = "fabrica:uso_solo" | "fabrica:passivos" | caminho de pasta da biblioteca | caminho .qpt."""
    if origem.startswith("fabrica:"):
        return construir_fabrica(projeto, origem.split(":", 1)[1], folha, corr, assinatura, logo, nome)
    qpt = os.path.join(origem, "modelo.qpt") if os.path.isdir(origem) else origem
    layout = builder.carregar_qpt(projeto, qpt, nome)
    meta = meta_do_layout(layout)
    return layout, meta
