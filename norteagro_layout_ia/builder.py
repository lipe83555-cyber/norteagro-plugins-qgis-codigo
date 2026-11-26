# -*- coding: utf-8 -*-
"""Construção dos itens nativos do layout QGIS e exportação.

Usado pelos dois fluxos:
  - Modelo Norte Agro (sem IA): modelos.py monta o layout e chama as funções daqui;
  - Referência por IA: construir_de_proposta() transforma a proposta JSON revisada em itens.

Regras gerais:
  - nunca altera a simbologia das camadas do projeto (camadas de apoio da
    localização são camadas novas, num grupo próprio, desligadas no painel);
  - cada mapa tem camadas, SRC e extensão próprios (Fase 1);
  - legenda, escala e norte sempre ligados ao mapa certo;
  - textos variáveis são expressões [% @na_... %] (Fase 3);
  - figuras (logo, norte, assinatura) vão embutidas no QPT (base64) e também em recursos/.
"""

from .core import compat
import base64
import json
import math
import os
import re
import shutil

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsExpressionContextUtils, QgsFeatureRequest,
    QgsFillSymbol, QgsGradientFillSymbolLayer, QgsLayerTree, QgsLayerTreeLayer, QgsLayoutExporter,
    QgsLayoutItem, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemManualTable, QgsLayoutItemMap,
    QgsLayoutItemMapGrid, QgsLayoutItemPicture, QgsLayoutItemPolyline, QgsLayoutItemScaleBar, QgsLayoutItemShape,
    QgsLayoutFrame, QgsLayoutMeasurement, QgsLayoutPoint, QgsLayoutSize, QgsLayoutTableColumn, QgsLegendStyle,
    QgsLineSymbol, QgsMapLayer, QgsMapLayerLegendUtils, QgsMapLayerStyle, QgsPalLayerSettings,
    QgsRuleBasedRenderer, QgsPrintLayout, QgsProject, QgsReadWriteContext,
    QgsRectangle, QgsScaleBarSettings, QgsSingleSymbolRenderer, QgsTableCell, QgsTextBufferSettings, QgsTextFormat, QgsUnitTypes,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsLayoutItemPage,
)
from qgis.PyQt.QtCore import QPointF, Qt

ALINHA_ESQ = Qt.AlignmentFlag.AlignLeft
ALINHA_DIR = Qt.AlignmentFlag.AlignRight
ALINHA_VMEIO = Qt.AlignmentFlag.AlignVCenter
from qgis.PyQt.QtGui import QColor, QFont, QPolygonF
from qgis.PyQt.QtXml import QDomDocument

from .core import carto, ibge, identidade, log, planilha_areas
from .core.correspondencia import Correspondencia, chave as chave_nome

PASTA = os.path.dirname(__file__)
ASSETS = os.path.join(PASTA, "assets")
FONTE_PADRAO = "Arial"
MM = compat.UNID_LAYOUT_MM
GRUPO_APOIO = "NorteAgro Layout - apoio"
BRASIL_4674 = QgsRectangle(-74.1, -33.9, -34.7, 5.4)


# ------------------------------------------------------------------ utilidades
def formato_texto(tamanho, negrito=False, cor="#000000", familia=FONTE_PADRAO, italico=False):
    tf = QgsTextFormat()
    f = QFont(familia)
    f.setBold(negrito)
    f.setItalic(italico)
    tf.setFont(f)
    tf.setSize(float(tamanho))
    try:
        tf.setSizeUnit(compat.UNID_RENDER_PONTOS)
    except AttributeError:  # QGIS < 3.30
        tf.setSizeUnit(compat.UNID_RENDER_PONTOS)
    tf.setColor(QColor(cor))
    return tf



# ------------------------------------------------------------------ compatibilidade com QGIS antigos (3.22+)
def _fonte_de(fmt):
    f = fmt.font()
    try:
        f.setPointSizeF(float(fmt.size()))
    except Exception:
        pass
    return f


def formato_rotulo(lab, fmt):
    """QgsLayoutItemLabel.setTextFormat existe a partir do QGIS 3.24; antes, fonte e cor separadas."""
    try:
        lab.setTextFormat(fmt)
    except AttributeError:
        lab.setFont(_fonte_de(fmt))
        try:
            lab.setFontColor(fmt.color())
        except Exception:
            pass


def formato_estilo_legenda(estilo, fmt):
    """QgsLegendStyle.setTextFormat existe a partir do QGIS 3.30; antes, só a fonte."""
    try:
        estilo.setTextFormat(fmt)
    except AttributeError:
        estilo.setFont(_fonte_de(fmt))


def quebrar_legenda(leg, mm):
    """Quebra automática do texto da legenda (QGIS 3.32+). Nos anteriores a legenda fica sem quebra."""
    try:
        leg.setAutoWrapLinesAfter(float(mm))
    except AttributeError:
        pass

def posicionar(item, x, y, w, h):
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))


def adicionar(layout, item, ident, x, y, w, h, z=None):
    layout.addLayoutItem(item)
    item.setId(ident)
    posicionar(item, x, y, w, h)
    if z is not None:
        item.setZValue(z)
    return item


def rotulo(layout, ident, texto, x, y, w, h, tamanho=8, negrito=False, alinhamento="center", valinhamento="center",
           moldura=False, fundo=None):
    lab = QgsLayoutItemLabel(layout)
    lab.setText(texto)
    formato_rotulo(lab, formato_texto(tamanho, negrito))
    lab.setHAlign({"left": Qt.AlignmentFlag.AlignLeft, "right": Qt.AlignmentFlag.AlignRight}.get(alinhamento, Qt.AlignmentFlag.AlignHCenter))
    lab.setVAlign({"top": Qt.AlignmentFlag.AlignTop, "bottom": Qt.AlignmentFlag.AlignBottom}.get(valinhamento, Qt.AlignmentFlag.AlignVCenter))
    lab.setMarginX(0.8)
    lab.setMarginY(0.4)
    lab.setFrameEnabled(bool(moldura))
    if moldura:
        lab.setFrameStrokeWidth(QgsLayoutMeasurement(0.25, MM))
    if fundo:
        lab.setBackgroundEnabled(True)
        lab.setBackgroundColor(QColor(fundo))
    else:
        lab.setBackgroundEnabled(False)
    return adicionar(layout, lab, ident, x, y, w, h)


def caixa(layout, ident, x, y, w, h, contorno=0.3, preenchimento=None):
    s = QgsLayoutItemShape(layout)
    s.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    cor = preenchimento or "255,255,255,0"
    s.setSymbol(QgsFillSymbol.createSimple({"color": cor, "outline_color": "0,0,0,255",
                                            "outline_width": str(contorno), "outline_width_unit": "MM",
                                            "outline_style": "solid" if contorno > 0 else "no"}))
    return adicionar(layout, s, ident, x, y, w, h)


def linha(layout, ident, x1, y1, x2, y2, largura=0.25):
    pl = QgsLayoutItemPolyline(QPolygonF([QPointF(x1, y1), QPointF(x2, y2)]), layout)
    pl.setSymbol(QgsLineSymbol.createSimple({"color": "0,0,0,255", "width": str(largura), "width_unit": "MM"}))
    layout.addLayoutItem(pl)
    pl.setId(ident)
    return pl


def caminho_base64(caminho):
    """'base64:...' para embutir a figura no QPT (portável entre computadores)."""
    with open(caminho, "rb") as fh:
        return "base64:" + base64.b64encode(fh.read()).decode("ascii")


def figura(layout, ident, caminho, x, y, w, h, embutir=True):
    p = QgsLayoutItemPicture(layout)
    adicionar(layout, p, ident, x, y, w, h)
    if caminho and os.path.isfile(caminho):
        svg = caminho.lower().endswith(".svg")
        origem = caminho_base64(caminho) if embutir else caminho
        try:
            p.setPicturePath(origem, QgsLayoutItemPicture.FormatSVG if svg else QgsLayoutItemPicture.FormatRaster)
        except TypeError:
            p.setPicturePath(origem)
        p.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
        p.setCustomProperty("na_origem", os.path.basename(caminho))
    return p


# ------------------------------------------------------------------ camadas
def camadas_projeto(projeto):
    """Camadas na ordem do painel (de cima para baixo), com visibilidade."""
    raiz = projeto.layerTreeRoot()
    saida = []
    for no in raiz.findLayers():
        if no.layer() is not None:
            saida.append((no.layer(), no.isVisible()))
    return saida


def achar_camada(projeto, nome, corr=None):
    """Acha camada pelo id, nome exato, nome normalizado ou correspondência (AREA_DO_IMOVEL ~ Área do Imóvel)."""
    if not nome:
        return None
    if isinstance(nome, QgsMapLayer):
        return nome
    cam = projeto.mapLayer(nome)
    if cam:
        return cam
    por_nome = projeto.mapLayersByName(nome)
    if por_nome:
        return por_nome[0]
    alvo = chave_nome(nome)
    for c, _ in camadas_projeto(projeto):
        if chave_nome(c.name()) == alvo:
            return c
    if corr:
        item = corr.procurar(nome)
        if item:
            for c, _ in camadas_projeto(projeto):
                if corr.procurar(c.name()) is item:
                    return c
    return None


def ordenar_como_painel(projeto, camadas):
    """Ordem de desenho do mapa = ordem do painel de camadas (de cima para baixo), com imagens e mapas
    de fundo sempre por último (embaixo), não importa a ordem em que foram marcadas."""
    ordem = {c.id(): i for i, (c, _v) in enumerate(camadas_projeto(projeto))}
    vistos, unicas = set(), []
    for c in camadas:
        if c is not None and c.id() not in vistos:
            vistos.add(c.id())
            unicas.append(c)
    return sorted(unicas, key=lambda c: (1 if c.type() == compat.CAMADA_RASTER else 0,
                                         ordem.get(c.id(), 10 ** 6)))


def _eh_mapa_base(camada):
    if camada.type() != compat.CAMADA_RASTER:
        return False
    prov = camada.providerType().lower()
    return prov in ("wms", "xyz", "arcgismapserver", "wcs", "vectortile") or "type=xyz" in camada.source()


def papel_camada(camada, corr):
    p = corr.papel(camada.name()) if corr else None
    if p:
        return p
    if _eh_mapa_base(camada) or camada.type() == compat.CAMADA_RASTER:
        return "base"
    return None


def camadas_padrao(projeto, papel_mapa, corr):
    """Camadas sugeridas para um mapa conforme o papel (principal, localizacao...)."""
    todas = camadas_projeto(projeto)
    apoio = {c.id() for c in _camadas_do_grupo_apoio(projeto)}
    if papel_mapa == "localizacao":
        return [c for c, _ in todas if papel_camada(c, corr) == "municipio"][:1]
    imovel = camada_imovel(projeto, corr)
    limite = None
    if imovel is not None and not imovel.extent().isEmpty() and extensao_valida(imovel.extent()):
        e = transformar(imovel.extent(), imovel.crs(), QgsCoordinateReferenceSystem("EPSG:4674"), projeto)
        limite = max(e.width() * e.height(), 1e-8) * 400  # 20 x 20 vezes o imóvel
    saida = []
    for c, vis in todas:
        if not vis or c.id() in apoio or papel_camada(c, corr) in ("municipio", "estado", "brasil"):
            continue
        if limite and c.type() == compat.CAMADA_VETOR and c is not imovel and extensao_valida(c.extent()):
            e = transformar(c.extent(), c.crs(), QgsCoordinateReferenceSystem("EPSG:4674"), projeto)
            if e.width() * e.height() > limite:
                continue  # camada regional (estado, país, malha municipal): não entra no mapa do imóvel
        saida.append(c)
    return saida


def _camadas_do_grupo_apoio(projeto):
    g = projeto.layerTreeRoot().findGroup(GRUPO_APOIO)
    return [n.layer() for n in g.findLayers() if n.layer()] if g else []


def camada_imovel(projeto, corr):
    for c, _ in camadas_projeto(projeto):
        if c.type() == compat.CAMADA_VETOR and corr.papel(c.name()) == "imovel":
            return c
    return None


# ------------------------------------------------------------------ extensões
def extensao_valida(r):
    """False para a extensão de camada vazia (nula/infinita): ela não pode ser transformada de SRC.
    Um ponto só (extensão de tamanho zero) continua válido."""
    return not r.isNull() and all(math.isfinite(v) and abs(v) < 1e15 for v in
                                  (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()))


def transformar(retangulo, crs_origem, crs_destino, projeto):
    if not crs_origem.isValid() or not crs_destino.isValid() or crs_origem == crs_destino:
        return QgsRectangle(retangulo)
    ct = QgsCoordinateTransform(crs_origem, crs_destino, projeto.transformContext())
    try:
        ct.setBallparkTransformsAreAppropriate(True)
    except AttributeError:
        pass
    return ct.transformBoundingBox(retangulo)


def com_margem(r, margem):
    r = QgsRectangle(r)
    if r.isEmpty():
        r.grow(100)
        return r
    dx, dy = r.width() * margem, r.height() * margem
    return QgsRectangle(r.xMinimum() - dx, r.yMinimum() - dy, r.xMaximum() + dx, r.yMaximum() + dy)


def utm_sugerido(camada, projeto):
    """EPSG SIRGAS 2000 / UTM do fuso do centro da camada (hemisfério sul: 31960 + fuso)."""
    if camada is None or not extensao_valida(camada.extent()):
        return None
    geo = transformar(camada.extent(), camada.crs(), QgsCoordinateReferenceSystem("EPSG:4674"), projeto)
    lon, lat = geo.center().x(), geo.center().y()
    if not (-180 <= lon <= 180):
        return None
    fuso = int(math.floor((lon + 180) / 6) + 1)
    if lat < 0 and 18 <= fuso <= 25:
        return QgsCoordinateReferenceSystem(f"EPSG:{31960 + fuso}")
    if lat >= 0 and 11 <= fuso <= 22:
        return QgsCoordinateReferenceSystem(f"EPSG:{31954 + fuso}")
    return None


def _campo_nome(camada):
    nomes = [f.name() for f in camada.fields()]
    for cand in ("NM_MUN", "NM_MUNICIP", "NOME_MUN", "MUNICIPIO", "NM_MUNICIPIO", "NOME", "NAME", "NM_UF", "NOME_UF"):
        for n in nomes:
            if n.upper() == cand:
                return n
    for n in nomes:
        if "NOM" in n.upper() or "NAME" in n.upper():
            return n
    return nomes[0] if nomes else None


def _sem_acento_baixo(s):
    return chave_nome(s)


def feicao_municipio(camada, nome, campo=None):
    campo = campo or _campo_nome(camada)
    if not campo or not nome:
        return None, campo
    alvo = _sem_acento_baixo(nome)
    for f in camada.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoFlags)):
        if _sem_acento_baixo(f[campo]) == alvo:
            return f, campo
    return None, campo


def _grupo_apoio(projeto):
    raiz = projeto.layerTreeRoot()
    g = raiz.findGroup(GRUPO_APOIO)
    if g is None:
        g = raiz.insertGroup(len(raiz.children()), GRUPO_APOIO)
        g.setItemVisibilityChecked(False)
        g.setExpanded(False)
    return g


def estilo_localizacao(camada_mun, nome_municipio, campo=None, expressao=None):
    """Estilo (XML) para o mapa de localização: municípios em cinza com nome e o município do imóvel em
    destaque verde. Vai como 'estilo do item' (layer style override) do mapa: a camada do projeto não muda
    e o estilo fica gravado no QPT."""
    campo = campo or _campo_nome(camada_mun)
    clone = camada_mun.clone()
    raiz = QgsRuleBasedRenderer.Rule(None)
    cinza = QgsFillSymbol.createSimple({"color": "211,211,211,255", "outline_color": "40,40,40,255",
                                        "outline_width": "0.2", "outline_width_unit": "MM"})
    r_outros = QgsRuleBasedRenderer.Rule(cinza, 0, 0, "", "Municípios")
    r_outros.setIsElse(True)
    raiz.appendChild(r_outros)
    if campo and nome_municipio:
        grad = QgsGradientFillSymbolLayer(QColor(11, 158, 27), QColor(200, 207, 200))
        grad.setReferencePoint1(QPointF(0.5, 0.0))
        grad.setReferencePoint2(QPointF(0.5, 1.0))
        simb = QgsFillSymbol()
        simb.changeSymbolLayer(0, grad)
        contorno = QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "0,0,0,255",
                                               "outline_width": "0.35", "outline_width_unit": "MM"})
        simb.appendSymbolLayer(contorno.symbolLayer(0).clone())
        valor = str(nome_municipio).replace("'", "''")
        # expressao: escolhe a feição certa (ex.: "$id = 12"), sem confundir municípios de mesmo nome
        r_dest = QgsRuleBasedRenderer.Rule(simb, 0, 0, expressao or f"\"{campo}\" = '{valor}'",
                                           str(nome_municipio))
        raiz.appendChild(r_dest)
    clone.setRenderer(QgsRuleBasedRenderer(raiz))
    if campo:
        pal = QgsPalLayerSettings()
        pal.fieldName = campo
        tf = formato_texto(6.5, cor="#333333")
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(0.6)
        buf.setColor(QColor(255, 255, 255, 200))
        tf.setBuffer(buf)
        pal.setFormat(tf)
        try:
            pal.placement = compat.ROTULO_SOBRE_PONTO
        except AttributeError:
            pal.placement = compat.ROTULO_SOBRE_PONTO
        clone.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        clone.setLabelsEnabled(True)
    estilo = QgsMapLayerStyle()
    estilo.readFromLayer(clone)
    return estilo.xmlData()


# ------------------------------------------------------------------ mapas (Fase 1)
def configurar_mapa(mapa, cfg, projeto, corr, dados=None, avisos=None):
    """Aplica camadas, SRC, extensão e tema próprios ao item de mapa.

    cfg: {"layers": [...], "crs": "EPSG:..."|"auto", "extent_mode": ..., "extent_layer": ..., "margin": 0.1,
          "theme": ..., "municipio": {"layer", "field", "value"}, "manual_extent": [...],
          "round_scale": True, "grid": True}
    """
    avisos = avisos if avisos is not None else []
    dados = dados or {}
    cfg = dict(cfg or {})
    papel = cfg.get("role") or mapa.customProperty("na_papel", "principal")
    modo = cfg.get("extent_mode") or ("municipio" if papel == "localizacao" else "camada")
    margem = float(cfg.get("margin", 0.10 if papel != "localizacao" else 0.04))
    mapa.setCustomProperty("na_papel", papel)

    # --- camadas
    nomes = cfg.get("layers")
    camadas = []
    if nomes:
        for n in nomes:
            c = achar_camada(projeto, n, corr)
            if c:
                camadas.append(c)
            else:
                avisos.append(f"Mapa '{mapa.id()}': camada '{n}' não encontrada no projeto.")
    else:
        camadas = camadas_padrao(projeto, papel, corr)

    # --- SRC
    crs_txt = cfg.get("crs") or ("EPSG:4674" if papel == "localizacao" else "auto")
    if crs_txt == "auto":
        crs = utm_sugerido(achar_camada(projeto, cfg.get("extent_layer"), corr) or camada_imovel(projeto, corr),
                           projeto) or projeto.crs()
    else:
        crs = QgsCoordinateReferenceSystem(crs_txt)
        if not crs.isValid():
            avisos.append(f"Mapa '{mapa.id()}': SRC '{crs_txt}' inválido; usado o SRC do projeto.")
            crs = projeto.crs()
    mapa.setCrs(crs)

    # --- extensão
    ext = None
    estilo_mapa = {}
    if modo == "municipio":
        info = cfg.get("municipio") or {}
        nome_mun = info.get("value") or dados.get("na_municipio")
        cam_mun, f, campo_mun = None, None, None
        # 1) pela posição do imóvel: camadas de municípios do projeto, malha de Goiás do plugin e, se o imóvel
        #    estiver fora delas, a malha do IBGE do estado do imóvel (baixada uma vez e guardada)
        imovel = camada_imovel(projeto, corr) if corr else None
        g_im = ibge.geometria_imovel(imovel) if imovel is not None and not info.get("value") else None
        if g_im is not None:
            vistas = set()

            def candidatas():
                yield achar_camada(projeto, info.get("layer"), corr)
                for c_, _v in camadas_projeto(projeto):
                    if papel_camada(c_, corr) == "municipio":
                        yield c_
                yield municipios_embutidos(projeto)

            for c_ in candidatas():
                if c_ is None or c_.id() in vistas or not ibge.tipo_poligono(c_):
                    continue
                vistas.add(c_.id())
                f = ibge.municipio_na_camada(c_, g_im)
                if f is not None:
                    cam_mun = c_
                    break
            if f is None:
                try:
                    cam_mun = ibge.malha_para_imovel(g_im)
                    f = ibge.municipio_na_camada(cam_mun, g_im) if cam_mun is not None else None
                except Exception as e:  # sem internet e sem cópia guardada
                    avisos.append(f"Não consegui baixar a malha de municípios do IBGE ({e}); o mapa de "
                                  f"localização usou o nome do município digitado.")
                    cam_mun, f = None, None
            if f is not None:
                campo_mun = _campo_nome(cam_mun)
                _municipio_do_imovel(projeto, f, cam_mun, campo_mun, dados, avisos)
        # 2) pelo nome digitado (sem camada do imóvel ou imóvel fora das malhas)
        if f is None:
            cam_mun = achar_camada(projeto, info.get("layer"), corr) or next(
                (c_ for c_, _ in camadas_projeto(projeto) if papel_camada(c_, corr) == "municipio"), None)
            if cam_mun is None:
                cam_mun = municipios_embutidos(projeto)
            if cam_mun is not None and nome_mun:
                f, campo_mun = feicao_municipio(cam_mun, nome_mun, info.get("field"))
                if f is None:
                    avisos.append(f"Município '{nome_mun}' não encontrado na camada '{cam_mun.name()}' (campo "
                                  f"{campo_mun}). Confira o nome em Dados do imóvel.")
        if f is None:
            if cam_mun is None or not nome_mun:
                avisos.append(f"Mapa '{mapa.id()}': sem camada de municípios ou sem município informado; usado o "
                              f"enquadramento do projeto.")
            modo = "projeto"
            if cam_mun is not None:
                camadas = [cam_mun]
        else:
            ext = transformar(f.geometry().boundingBox(), cam_mun.crs(), crs, projeto)
            ext = com_margem(ext, margem + 0.35)  # mostra os vizinhos
            # localização: só a malha municipal (com estilo próprio do mapa); nunca a camada do imóvel
            camadas = [cam_mun]
            estilo_mapa = {cam_mun.id(): estilo_localizacao(cam_mun, f[campo_mun], campo_mun,
                                                            expressao=f"$id = {f.id()}")}
    if modo in ("estado", "brasil"):
        info = cfg.get("municipio") or {}
        cam = achar_camada(projeto, cfg.get("extent_layer"), corr)
        if cam is None and modo == "estado":
            cam = achar_camada(projeto, info.get("layer"), corr) or municipios_embutidos(projeto)
        if cam is not None:
            ext = com_margem(transformar(cam.extent(), cam.crs(), crs, projeto), margem)
            if not camadas or nomes is None:
                camadas = [cam]
        elif modo == "brasil":
            ext = com_margem(transformar(BRASIL_4674, QgsCoordinateReferenceSystem("EPSG:4674"), crs, projeto),
                             margem)
            avisos.append(f"Mapa '{mapa.id()}': sem camada do Brasil no projeto; enquadrado só pela extensão.")
    if modo == "manual" and cfg.get("manual_extent"):
        x0, y0, x1, y1 = cfg["manual_extent"]
        ext = QgsRectangle(x0, y0, x1, y1)
        if cfg.get("manual_crs"):
            ext = transformar(ext, QgsCoordinateReferenceSystem(cfg["manual_crs"]), crs, projeto)
    if modo == "camada":
        cam = achar_camada(projeto, cfg.get("extent_layer"), corr) or camada_imovel(projeto, corr)
        if cam is None and camadas:
            cam = next((c for c in camadas if c.type() == compat.CAMADA_VETOR), camadas[0])
        if cam is not None:
            ext = com_margem(transformar(cam.extent(), cam.crs(), crs, projeto), margem)
        else:
            modo = "projeto"
    if modo == "tema" or cfg.get("theme"):
        tema = cfg.get("theme")
        if tema and tema in projeto.mapThemeCollection().mapThemes():
            mapa.setFollowVisibilityPreset(True)
            mapa.setFollowVisibilityPresetName(tema)
        elif tema:
            avisos.append(f"Mapa '{mapa.id()}': tema '{tema}' não existe no projeto.")
    else:
        mapa.setFollowVisibilityPreset(False)
    if ext is None or modo == "projeto":
        todas = [c for c in camadas if c.type() == compat.CAMADA_VETOR] or camadas
        r = QgsRectangle()
        for c in todas:
            ce = c.extent()
            # camadas vazias têm extensão nula/infinita: não entram no enquadramento
            if ce.isNull() or ce.isEmpty() or not all(math.isfinite(v) and abs(v) < 1e15 for v in
                                                      (ce.xMinimum(), ce.yMinimum(), ce.xMaximum(), ce.yMaximum())):
                continue
            try:
                e = transformar(ce, c.crs(), crs, projeto)
            except Exception:
                continue
            if r.isEmpty():
                r = e
            else:
                r.combineExtentWith(e)
        ext = com_margem(r, margem) if not r.isEmpty() else None

    camadas = ordenar_como_painel(projeto, camadas)
    mapa.setLayers(camadas)
    mapa.setKeepLayerSet(True)
    mapa.setKeepLayerStyles(True)
    mapa.storeCurrentLayerStyles()
    if estilo_mapa:
        sobrepor = dict(mapa.layerStyleOverrides())
        sobrepor.update(estilo_mapa)
        mapa.setLayerStyleOverrides(sobrepor)
    if ext is not None and not ext.isEmpty():
        mapa.zoomToExtent(ext)
        if cfg.get("round_scale", papel == "principal") and mapa.scale() > 0:
            mapa.setScale(carto.escala_arredondada(mapa.scale()))
    mapa.setCustomProperty("na_cfg", json.dumps({k: v for k, v in cfg.items() if k != "_origem_usuario"},
                                                ensure_ascii=False))
    mapa.refresh()
    return camadas


_CACHE_MUN = {}

UFS = {"AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
       "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
       "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
       "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
       "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
       "SE": "Sergipe", "TO": "Tocantins"}


def _municipio_do_imovel(projeto, feicao, camada, campo, dados, avisos):
    """Município achado pela posição do imóvel: preenche município/estado da planta quando estão vazios e
    avisa quando o que foi digitado é outro."""
    nome = str(feicao[campo] or "").strip() if campo else ""
    sigla = ""
    for n in ("SIGLA_UF", "UF", "SG_UF"):
        if camada.fields().indexOf(n) >= 0:
            sigla = str(feicao[n] or "").strip().upper()
            break
    if not nome:
        return
    uf = UFS.get(sigla, sigla)
    digitado = (dados or {}).get("na_municipio", "") or ""
    if not digitado.strip():
        QgsExpressionContextUtils.setProjectVariable(projeto, "na_municipio", nome)
        if uf:
            QgsExpressionContextUtils.setProjectVariable(projeto, "na_uf", uf)
        avisos.append(f"Município achado pela posição do imóvel: {nome}" + (f" - {uf}" if uf else "") + ".")
    elif _sem_acento_baixo(digitado) != _sem_acento_baixo(nome):
        avisos.append(f"Pela posição do imóvel ele fica em {nome}" + (f" - {uf}" if uf else "") +
                      f", mas em Dados do imóvel está '{digitado}'. O mapa de localização destaca {nome}; "
                      f"confira o município digitado.")


def municipio_pelo_imovel(projeto, corr, baixar=False):
    """v0.29.0: (município, estado) onde fica a maior parte da camada do imóvel, sem precisar digitar.
    Procura nas camadas de municípios do projeto e na malha de Goiás que acompanha o plugin (sem colocá-la no
    projeto); com baixar=True, também na malha do IBGE do estado do imóvel. ("", "") se não achar."""
    try:
        imovel = camada_imovel(projeto, corr) if corr else None
        g_im = ibge.geometria_imovel(imovel) if imovel is not None else None
    except Exception:
        g_im = None
    if g_im is None or g_im.isEmpty():
        return "", ""
    candidatas = [c for c, _v in camadas_projeto(projeto) if papel_camada(c, corr) == "municipio"]
    gpkg = os.path.join(PASTA, "dados", "go_municipios_ibge_simplificado.gpkg")
    if os.path.isfile(gpkg):
        cam = QgsVectorLayer(gpkg + "|layername=municipios", "Municípios de Goiás (IBGE)", "ogr")
        if cam.isValid():
            candidatas.append(cam)
    if baixar:
        try:
            candidatas.append(ibge.malha_para_imovel(g_im))
        except Exception:
            pass
    for cam in candidatas:
        try:
            if cam is None or not ibge.tipo_poligono(cam):
                continue
            f = ibge.municipio_na_camada(cam, g_im)
            if f is None:
                continue
            campo = _campo_nome(cam)
            nome = str(f[campo] or "").strip() if campo else ""
            if not nome:
                continue
            sigla = ""
            for n in ("SIGLA_UF", "UF", "SG_UF"):
                if cam.fields().indexOf(n) >= 0:
                    sigla = str(f[n] or "").strip().upper()
                    break
            return nome, UFS.get(sigla, sigla)
        except Exception:
            continue
    return "", ""


def municipios_embutidos(projeto):
    """Malha municipal de Goiás simplificada que acompanha o plugin (IBGE), usada quando o
    projeto não tem camada de municípios. Entra no grupo de apoio."""
    caminho = os.path.join(PASTA, "dados", "go_municipios_ibge_simplificado.gpkg")
    if not os.path.isfile(caminho):
        return None
    for c in _camadas_do_grupo_apoio(projeto):
        if c.name() == "Municípios de Goiás (IBGE)":
            return c
    cam = QgsVectorLayer(caminho + "|layername=municipios", "Municípios de Goiás (IBGE)", "ogr")
    if not cam.isValid():
        return None
    projeto.addMapLayer(cam, False)
    no = _grupo_apoio(projeto).addLayer(cam)
    no.setItemVisibilityChecked(False)
    return cam


def grade(mapa, papel="principal", lados=("left", "right", "top", "bottom"), tamanho=6.0):
    """Coordenadas na moldura do mapa (UTM em metros ou graus, conforme o SRC do mapa)."""
    g = QgsLayoutItemMapGrid("Coordenadas", mapa)
    mapa.grids().addGrid(g)
    crs = mapa.crs()
    g.setCrs(crs)
    g.setStyle(QgsLayoutItemMapGrid.GridStyle.FrameAnnotationsOnly)
    ext = mapa.extent()
    if crs.isGeographic():
        intervalo = carto.intervalo_grade(min(ext.width(), ext.height()), 4)
        g.setAnnotationFormat(QgsLayoutItemMapGrid.DegreeMinuteSecondSuffix)
        g.setAnnotationPrecision(1)
    else:
        # 3 a 5 marcas por lado: maior intervalo "redondo" que caiba ao menos 3 vezes no lado menor
        bruto = min(ext.width(), ext.height()) / 3.2
        passos = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000]
        intervalo = max([p for p in passos if p <= bruto] or [passos[0]])
        g.setAnnotationFormat(QgsLayoutItemMapGrid.AnnotationFormat.DecimalWithSuffix)
        g.setAnnotationPrecision(0)
    g.setIntervalX(intervalo)
    g.setIntervalY(intervalo)
    g.setAnnotationEnabled(True)
    g.setAnnotationTextFormat(formato_texto(tamanho))
    g.setFrameStyle(QgsLayoutItemMapGrid.FrameStyle.ExteriorTicks)
    g.setFrameWidth(1.5)
    g.setFramePenSize(0.25)
    lados_qgis = {"left": QgsLayoutItemMapGrid.BorderSide.Left, "right": QgsLayoutItemMapGrid.BorderSide.Right,
                  "top": QgsLayoutItemMapGrid.BorderSide.Top, "bottom": QgsLayoutItemMapGrid.BorderSide.Bottom}
    for nome, lado in lados_qgis.items():
        g.setAnnotationPosition(QgsLayoutItemMapGrid.AnnotationPosition.OutsideMapFrame, lado)
        if nome in ("left", "right"):
            g.setAnnotationDirection(QgsLayoutItemMapGrid.AnnotationDirection.Vertical if nome == "left"
                                     else QgsLayoutItemMapGrid.AnnotationDirection.VerticalDescending, lado)
        else:
            g.setAnnotationDirection(QgsLayoutItemMapGrid.AnnotationDirection.Horizontal, lado)
        g.setAnnotationDisplay(QgsLayoutItemMapGrid.DisplayMode.ShowAll if nome in lados else QgsLayoutItemMapGrid.DisplayMode.HideAll,
                               lado)
    flags = QgsLayoutItemMapGrid.FrameSideFlags()
    for nome in lados:
        flags |= {"left": QgsLayoutItemMapGrid.FrameSideFlag.FrameLeft, "right": QgsLayoutItemMapGrid.FrameSideFlag.FrameRight,
                  "top": QgsLayoutItemMapGrid.FrameSideFlag.FrameTop, "bottom": QgsLayoutItemMapGrid.FrameSideFlag.FrameBottom}[nome]
    g.setFrameSideFlags(flags)
    g.setAnnotationFrameDistance(0.8)
    return g


def mapa(layout, ident, x, y, w, h, papel="principal", moldura=0.4):
    m = QgsLayoutItemMap(layout)
    m.setFrameEnabled(moldura > 0)
    m.setFrameStrokeWidth(QgsLayoutMeasurement(moldura, MM))
    m.setBackgroundColor(QColor(255, 255, 255))
    adicionar(layout, m, ident, x, y, w, h)
    m.setCustomProperty("na_papel", papel)
    return m


# ------------------------------------------------------------------ legenda, escala, norte
def legenda(layout, ident, mapa_ligado, x, y, w, h, corr, titulo="Legenda", colunas=2, tamanho=8,
            filtrar=True, camadas=None, quebra=None):
    """quebra: largura máxima do texto de cada item (mm); nome maior continua na linha de baixo."""
    leg = QgsLayoutItemLegend(layout)
    adicionar(layout, leg, ident, x, y, w, h)
    if quebra:
        quebrar_legenda(leg, quebra)
    leg.setTitle(titulo)
    leg.setLinkedMap(mapa_ligado)
    leg.setLegendFilterByMapEnabled(bool(filtrar))
    leg.setColumnCount(int(colunas))
    leg.setSplitLayer(False)
    leg.setEqualColumnWidth(False)
    leg.setSymbolWidth(7 * tamanho / 8)
    leg.setSymbolHeight(4 * tamanho / 8)
    leg.setWrapString("")
    for estilo in (QgsLegendStyle.Style.SymbolLabel, QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.Group):
        formato_estilo_legenda(leg.rstyle(estilo), formato_texto(tamanho))
    formato_estilo_legenda(leg.rstyle(QgsLegendStyle.Style.Title), formato_texto(tamanho * 1.15, negrito=True))
    leg.setTitleAlignment(Qt.AlignmentFlag.AlignHCenter)
    leg.setBackgroundEnabled(True)
    leg.setBackgroundColor(QColor(255, 255, 255))
    montar_legenda(leg, camadas if camadas is not None else mapa_ligado.layers(), corr)
    return leg


def montar_legenda(leg, camadas, corr, nomes=None):
    """Só as camadas do mapa (sem mapas de fundo e camadas de apoio), com os nomes do padrão do escritório.
    nomes = {id_camada: nome} escolhidos na tela (têm prioridade sobre a tabela de correspondência)."""
    nomes = nomes or {}
    leg.setAutoUpdateModel(False)
    raiz = leg.model().rootGroup()
    raiz.removeAllChildren()
    for c in camadas:
        if c is None or _eh_mapa_base(c) or c.type() == compat.CAMADA_RASTER:
            continue
        if corr and corr.papel(c.name()) in ("municipio", "estado", "brasil"):
            continue
        no = raiz.addLayer(c)
        nome = nomes.get(c.id()) or (corr.nome_legenda(c.name()) if corr else None)
        if nome:
            no.setUseLayerName(False)
            no.setName(nome)
            no.setCustomProperty("legend/title-label", nome)
            # camada de símbolo único: o texto desenhado é o rótulo do símbolo
            if c.type() == compat.CAMADA_VETOR and c.renderer() is not None and \
                    c.renderer().type() == "singleSymbol":
                QgsMapLayerLegendUtils.setLegendNodeUserLabel(no, 0, nome)
            leg.model().refreshLayerLegend(no)
    leg.adjustBoxSize()
    leg.refresh()


def escala_grafica(layout, ident, mapa_ligado, x, y, w=None, h=None, tamanho=None, fundo=None):
    """Barra de escala exatamente como o botão "Adicionar barra de escala" do compositor do QGIS:
    configurações padrão do QGIS, ligada ao mapa maior e colocada no lugar reservado no modelo, com um
    fundo branco discreto. Tamanho, segmentos e unidades são os do QGIS (w, h, tamanho e fundo são ignorados)."""
    sb = QgsLayoutItemScaleBar(layout)
    sb.applyDefaultSettings()
    layout.addLayoutItem(sb)
    sb.setId(ident)
    sb.attemptMove(QgsLayoutPoint(x, y, MM))
    sb.setLinkedMap(mapa_ligado)
    # fundo branco com pouca transparência, só para destacar a barra da imagem
    sb.setBackgroundEnabled(True)
    sb.setBackgroundColor(QColor(255, 255, 255, 225))
    ajustar_escala(sb)
    return sb


def ajustar_escala(sb):
    """O mesmo que o QGIS faz ao inserir a barra pelo botão: tamanho padrão para a escala atual do mapa
    ligado (chamado de novo depois que o mapa recebe a extensão final)."""
    sb.applyDefaultSize(sb.guessUnits())
    sb.update()
    folga = sb.customProperty("na_canto")
    mapa = sb.linkedMap()
    if folga not in (None, "") and mapa is not None:
        # presa no canto inferior direito do mapa, com uma folga pequena da moldura
        folga = float(folga)
        pm, tm, t = mapa.positionWithUnits(), mapa.sizeWithUnits(), sb.sizeWithUnits()
        sb.attemptMove(QgsLayoutPoint(pm.x() + tm.width() - folga - t.width(),
                                      pm.y() + tm.height() - folga - t.height(), MM))

def escala_numerica(layout, ident, mapa_ligado, x, y, w, h, tamanho=8):
    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Numeric")
    adicionar(layout, sb, ident, x, y, w, h)
    sb.setLinkedMap(mapa_ligado)
    sb.setTextFormat(formato_texto(tamanho))
    sb.update()
    return sb


def norte(layout, ident, mapa_ligado, x, y, w, h, modo="true", arquivo=None):
    """Seta do norte ligada ao mapa. arquivo: SVG da pasta assets (cada modelo tem a sua)."""
    caminho = os.path.join(ASSETS, arquivo) if arquivo else ""
    if not os.path.isfile(caminho):
        caminho = os.path.join(ASSETS, "norte.svg")
    p = figura(layout, ident, caminho, x, y, w, h)
    p.setLinkedMap(mapa_ligado)
    p.setNorthMode(QgsLayoutItemPicture.NorthMode.GridNorth if modo == "grid" else QgsLayoutItemPicture.NorthMode.TrueNorth)
    p.setCustomProperty("na_norte", modo)
    return p


# ------------------------------------------------------------------ tabelas de áreas (Fase 4)
ALTURA_LINHA = {420: 3.6}


MARGEM_CELULA = 0.8
GRADE_TABELA = 0.2


def altura_linha_tabela(tamanho):
    """Altura útil de cada linha (mm) para a fonte em pontos; a linha total soma margens e grade."""
    return round(tamanho * 0.3528 * 1.45, 2)


def tabela_manual(layout, ident, linhas, x, y, w, cabecalho=("Descrição", "Hectares"), tamanho=6.5,
                  total_negrito=True, larguras=(0.72, 0.28)):
    """QgsLayoutItemManualTable no padrão das plantas: a linha "Descrição | Hectares" é a primeira linha
    da tabela (como nas plantas do escritório) e a linha Total vai em negrito.

    O QGIS calcula a altura da tabela pela moldura; por isso as alturas das linhas são fixadas e a
    moldura recebe exatamente a soma. Retorna (tabela, moldura, altura_mm)."""
    # v0.29.0 (otimização): cada "set" da tabela refaz o desenho dela inteira. Agora tudo é configurado com a
    # tabela ainda vazia e fora da folha, o conteúdo entra por último e o QGIS refaz uma vez só.
    t = QgsLayoutItemManualTable.create(layout)
    ncol = len(cabecalho) if cabecalho else (len(linhas[0]) if linhas else 2)
    fmt_n = formato_texto(tamanho)
    fmt_b = formato_texto(tamanho, negrito=True)
    todas = ([list(cabecalho)] if cabecalho else []) + [list(l) for l in linhas]
    conteudo = []
    for i_lin, linha_ in enumerate(todas):
        total = str(linha_[0]).strip().lower() == "total"
        lin = []
        for i in range(ncol):
            v = linha_[i] if i < len(linha_) else ""
            cel = QgsTableCell(str(v))
            try:
                cel.setTextFormat(fmt_b if (total and total_negrito) else fmt_n)
                cel.setHorizontalAlignment(ALINHA_ESQ if i == 0 else ALINHA_DIR)
                cel.setVerticalAlignment(ALINHA_VMEIO)
            except AttributeError:
                pass
            lin.append(cel)
        conteudo.append(lin)
    t.setIncludeTableHeader(False)
    t.setContentTextFormat(fmt_n)
    t.setShowGrid(True)
    t.setGridStrokeWidth(GRADE_TABELA)
    t.setCellMargin(MARGEM_CELULA)
    larg_util = w - ncol * (2 * MARGEM_CELULA + GRADE_TABELA) - GRADE_TABELA
    if len(larguras) != ncol:
        larguras = [1.0 / ncol] * ncol
    t.setColumnWidths([max(5.0, larg_util * f) for f in larguras])
    h_util = altura_linha_tabela(tamanho)
    t.setRowHeights([h_util] * len(conteudo))
    t.setBackgroundColor(QColor(255, 255, 255))
    t.setCustomProperty("na_tabela", ident)
    t.setTableContents(conteudo)
    layout.addMultiFrame(t)
    # o QGIS só desenha a linha que cabe inteira; a folga evita perder a linha Total por arredondamento
    altura = len(conteudo) * (h_util + 2 * MARGEM_CELULA + GRADE_TABELA + 0.05) + GRADE_TABELA + 0.6
    fr = QgsLayoutFrame(layout, t)
    fr.attemptMove(QgsLayoutPoint(x, y, MM))
    fr.attemptResize(QgsLayoutSize(w, altura, MM))
    fr.setId(ident)
    fr.setFrameEnabled(False)
    fr.setBackgroundEnabled(False)
    fr.setCustomProperty("na_tabela", ident)
    t.addFrame(fr)
    return t, fr, altura


def remover_tabelas_areas(layout):
    """Remove as tabelas de áreas anteriores (tabelas primeiro, depois os títulos)."""
    for mf in list(layout.multiFrames()):
        if str(mf.customProperty("na_tabela", "")).startswith("tab_"):
            # as molduras (frames) ficam na folha se não forem tiradas antes da tabela
            for fr in list(mf.frames()):
                layout.removeLayoutItem(fr)
            if mf in layout.multiFrames():
                layout.removeMultiFrame(mf)
    titulos = [it for it in layout.items()
               if isinstance(it, QgsLayoutItemLabel) and it.id().startswith("tab_")]
    for it in titulos:
        layout.removeLayoutItem(it)


def preencher_tabelas_areas(layout, meta, blocos, escala=1.0, casas=4, fator=1.0):
    """Monta as tabelas do modelo (uma por quadro), empilhadas a partir da âncora do modelo.

    meta["tabelas"] = {"ancora": [x, y, largura], "espaco": mm, "blocos": [{"chave", "titulo", "total"}]}
    Bloco com "mapa": a pilha fica dentro daquele mapa (posição provisória no canto superior direito; o
    lugar final, livre do imóvel e dos outros itens, é escolhido depois) e "largura" vale para a pilha.
    fator: encolhe as tabelas que ficam dentro dos mapas (letra, largura e espaço), para não cobrirem o imóvel.
    Retorna a lista de ids criados.
    """
    cfg = meta.get("tabelas") or {}
    x, y, w = [float(v) * escala for v in cfg.get("ancora", [270, 10, 50])]
    largura_grupo = float(cfg.get("largura", w / escala)) * escala * fator
    espaco = float(cfg.get("espaco", 4)) * escala
    tam = float(cfg.get("fonte", 6.5)) * escala ** 0.5
    em_grupo = any(bl.get("mapa") for bl in cfg.get("blocos", []))
    if em_grupo:
        tam *= fator
        espaco *= fator
    alt_titulo = altura_linha_tabela(tam) + 2 * MARGEM_CELULA + GRADE_TABELA
    remover_tabelas_areas(layout)
    criados = []
    pilhas = {}  # id do mapa -> [x, y] da próxima tabela
    for b in cfg.get("blocos", []):
        chave = b["chave"]
        grupo = b.get("mapa") or ""
        mapa = layout.itemById(grupo) if grupo else None
        if mapa is not None:
            if grupo not in pilhas:
                pm, tm = mapa.positionWithUnits(), mapa.sizeWithUnits()
                borda = 2.5 * escala
                pilhas[grupo] = [pm.x() + tm.width() - largura_grupo - borda, pm.y() + borda]
            bx, by, bw = pilhas[grupo][0], pilhas[grupo][1], largura_grupo
        else:
            grupo = ""
            bx, by, bw = x, y, w
        bloco = blocos.get(chave) or planilha_areas.blocos_vazios([chave])[chave]
        titulo = b.get("titulo") or bloco.get("titulo") or planilha_areas.TITULO_BLOCO.get(chave, chave)
        linhas = planilha_areas.linhas_tabela(bloco, casas, com_total=b.get("total", True))
        lab = rotulo(layout, f"tab_{chave}_titulo", titulo, bx, by, bw, alt_titulo, tamanho=tam, moldura=True,
                     fundo="#ffffff")
        lab.setFrameStrokeWidth(QgsLayoutMeasurement(0.2, MM))
        _, fr, altura = tabela_manual(layout, f"tab_{chave}", linhas, bx, by + alt_titulo, bw, tamanho=tam)
        criados += [lab.id(), fr.id()]
        if bloco.get("manual"):
            fr.setCustomProperty("na_manual", True)
        if grupo:
            for it in (lab, fr):
                it.setCustomProperty("na_grupo_tab", grupo)
                it.setCustomProperty("na_bloco_tab", f"{len(criados) // 2:02d}_{chave}")
            pilhas[grupo][1] += alt_titulo + altura + espaco
        else:
            y += alt_titulo + altura + espaco
    return criados


# ------------------------------------------------------------------ variáveis (Fase 3)
def definir_variaveis_projeto(projeto, dados):
    """dados = {"na_imovel": "...", ...}. Só chaves na_* conhecidas ou extras do modelo."""
    for k, v in dados.items():
        if k.startswith("na_"):
            QgsExpressionContextUtils.setProjectVariable(projeto, k, "" if v is None else str(v))


def ler_variaveis_projeto(projeto):
    escopo = QgsExpressionContextUtils.projectScope(projeto)
    return {n: escopo.variable(n) for n in escopo.variableNames() if n.startswith("na_")}


def definir_variaveis_layout(layout, mapa_principal):
    """Parâmetros cartográficos calculados do SRC do mapa principal e a folha."""
    crs = mapa_principal.crs()
    p = carto.parametros_src(crs.authid(), crs.toProj(), crs.description(), crs.isGeographic())
    pg = layout.pageCollection().page(0)
    folha = carto.nome_folha(pg.pageSize().width(), pg.pageSize().height())
    valores = {"na_projecao": p["projecao"], "na_datum": p["datum"], "na_mc": p["meridiano"],
               "na_fuso": p["fuso"], "na_folha": folha, "na_src": crs.authid()}
    for k, v in valores.items():
        QgsExpressionContextUtils.setLayoutVariable(layout, k, v)
    return valores


TEXTO_ESCALA = "[% format_number(map_get(item_variables('{mapa}'), 'map_scale'), 0) %]"


def texto_escala(id_mapa="mapa_principal"):
    return "1:" + TEXTO_ESCALA.format(mapa=id_mapa)


# ------------------------------------------------------------------ verificação de identidade
def textos_do_layout(layout):
    textos = []
    for it in layout.items():
        if isinstance(it, QgsLayoutItemLabel):
            textos.append((it.id(), it.text()))
        elif isinstance(it, QgsLayoutItemLegend):
            textos.append((it.id(), it.title()))
    for mf in layout.multiFrames():
        if isinstance(mf, QgsLayoutItemManualTable):
            for r in mf.tableContents():
                for c in r:
                    textos.append((mf.customProperty("na_tabela", "tabela"), str(c.content())))
    return textos


def verificar_identidade(layout, permitidos=()):
    """Retorna textos que ainda parecem conter CPF/CNPJ/CREA literais (a exportação deve ser bloqueada)."""
    permitidos = set(permitidos or ())
    suspeitos = []
    for ident, t in textos_do_layout(layout):
        if t in permitidos:
            continue
        if identidade.textos_suspeitos_restantes([t]):
            suspeitos.append((ident, identidade.mascarar(t)))
    return suspeitos


# ------------------------------------------------------------------ proposta JSON -> layout (fluxo IA)
def construir_de_proposta(projeto, proposta, nome_layout, corr=None, dados=None, blocos=None,
                          imagem_referencia=None, pasta_recursos=None, casas=4, logo=None, assinatura=None):
    """Cria um QgsPrintLayout a partir da proposta revisada. Retorna (layout, avisos)."""
    corr = corr or Correspondencia.carregar()
    avisos = []
    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    layout.setName(nome_layout)
    W, H = proposta["page"]["width_mm"], proposta["page"]["height_mm"]
    pg = layout.pageCollection().page(0)
    pg.setPageSize(QgsLayoutSize(W, H, MM))
    mapas = {}
    pendentes = []
    elementos = sorted(proposta["elements"], key=lambda e: 0 if e["type"] in ("shape",) else
                       1 if e["type"] == "map" else 2)
    for z, el in enumerate(elementos):
        x, y, w, h = el["x"] * W, el["y"] * H, el["w"] * W, el["h"] * H
        t = el["type"]
        if t == "map":
            m = mapa(layout, el["id"], x, y, w, h, papel=el.get("role", "principal"))
            configurar_mapa(m, dict(el.get("map") or {}, role=el.get("role", "principal")), projeto, corr, dados,
                            avisos)
            if (el.get("map") or {}).get("grid"):
                grade(m)
            mapas[el["id"]] = m
        elif t == "label":
            rotulo(layout, el["id"], el.get("text", ""), x, y, w, h, tamanho=el.get("font_size", 8),
                   negrito=el.get("bold", False), alinhamento=el.get("align", "left"),
                   moldura=el.get("frame", False))
        elif t == "shape":
            caixa(layout, el["id"], x, y, w, h, preenchimento="255,255,255,255" if el.get("fill") else None)
        elif t == "line":
            if w >= h:
                linha(layout, el["id"], x, y + h / 2, x + w, y + h / 2)
            else:
                linha(layout, el["id"], x + w / 2, y, x + w / 2, y + h)
        elif t == "picture":
            papel = el.get("role")
            caminho = None
            if papel == "logo":
                caminho = logo if logo and os.path.isfile(logo) else None  # v0.32.7: sem logo de fábrica
            elif papel == "assinatura":
                caminho = assinatura
            elif imagem_referencia and pasta_recursos and not el.get("sem_recorte", True):
                # recorte só com confirmação explícita na revisão (pode ser assinatura/carimbo de terceiro)
                caminho = recortar_referencia(imagem_referencia, el, pasta_recursos)
            figura(layout, el["id"], caminho, x, y, w, h)
            if not caminho and papel != "logo":
                avisos.append(f"Imagem '{el['id']}' sem arquivo: escolha a figura no layout.")
        elif t == "table":
            if el.get("block") and blocos is not None and el["block"] in blocos:
                linhas = planilha_areas.linhas_tabela(blocos[el["block"]], casas)
                titulo = planilha_areas.TITULO_BLOCO[el["block"]]
                lab = rotulo(layout, f"tab_{el['block']}_titulo", titulo, x, y, w, 4, tamanho=7, moldura=True)
                tabela_manual(layout, f"tab_{el['block']}", linhas, x, y + lab.sizeWithUnits().height(), w)
            else:
                linhas = el.get("rows") or []
                cab = linhas[0] if linhas else ["Descrição", "Valor"]
                corpo = linhas[1:] if len(linhas) > 1 else []
                _, fr, _ = tabela_manual(layout, el["id"], corpo, x, y, w, cabecalho=tuple(cab[:4]) or ("",),
                                         larguras=tuple([1.0 / max(1, len(cab[:4]))] * max(1, len(cab[:4]))))
        else:
            pendentes.append((el, (x, y, w, h)))
    for el, (x, y, w, h) in pendentes:
        alvo = mapas.get(el.get("map_id")) or (next(iter(mapas.values())) if mapas else None)
        if alvo is None:
            avisos.append(f"'{el['id']}' ({el['type']}) sem mapa: não criado.")
            continue
        if el["type"] == "legend":
            legenda(layout, el["id"], alvo, x, y, w, h, corr, titulo=el.get("title", "Legenda"))
        elif el["type"] == "scale":
            if el.get("style") == "numeric":
                escala_numerica(layout, el["id"], alvo, x, y, w, h)
            else:
                escala_grafica(layout, el["id"], alvo, x, y, w, h)
        elif el["type"] == "north":
            norte(layout, el["id"], alvo, x, y, w, h, el.get("north_mode", "true"))
    principal = next((m for m in mapas.values() if m.customProperty("na_papel") == "principal"),
                     next(iter(mapas.values()), None))
    if principal is not None:
        definir_variaveis_layout(layout, principal)
    layout.setCustomProperty("na_origem", "ia")
    return layout, avisos


def recortar_referencia(imagem, el, pasta):
    from qgis.PyQt.QtGui import QImage
    img = QImage(imagem)
    if img.isNull():
        return None
    W, H = img.width(), img.height()
    rec = img.copy(int(el["x"] * W), int(el["y"] * H), max(1, int(el["w"] * W)), max(1, int(el["h"] * H)))
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"recorte_{el['id']}.png")
    rec.save(destino, "PNG")
    return destino


# ------------------------------------------------------------------ exportação
def salvar_qpt(layout, caminho):
    doc = QDomDocument()
    ok = layout.saveAsTemplate(caminho, QgsReadWriteContext())
    if not ok:
        raise RuntimeError(f"Não foi possível gravar o modelo em '{caminho}'. Confira se a pasta existe e se "
                           f"você tem permissão de escrita.")
    del doc
    return caminho


def carregar_qpt(projeto, caminho, nome=None):
    with open(caminho, "r", encoding="utf-8") as fh:
        conteudo = fh.read()
    doc = QDomDocument()
    doc.setContent(conteudo)
    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    _itens, ok = layout.loadFromTemplate(doc, QgsReadWriteContext(), True)
    if not ok:
        raise RuntimeError(f"O arquivo '{os.path.basename(caminho)}' não é um modelo (.qpt) válido do QGIS.")
    if nome:
        layout.setName(nome)
    return layout


def exportar_previa(layout, caminho_png, dpi=110):
    exp = QgsLayoutExporter(layout)
    cfg = QgsLayoutExporter.ImageExportSettings()
    cfg.dpi = dpi
    res = exp.exportToImage(caminho_png, cfg)
    if res != QgsLayoutExporter.ExportResult.Success:
        raise RuntimeError(f"Falha ao gerar a prévia ({res}).")
    return caminho_png


def exportar_pacote(layout, pasta, proposta_ia=None, proposta_automatica=None, proposta_revisada=None,
                    conferencia=None, permitidos=(), zipar=False):
    """Grava layout.qpt, recursos/, pre_visualizacao.png, propostas separadas (automática x revisada),
    conferencia.json e COMO_ABRIR.txt. Bloqueia se houver texto suspeito de identidade."""
    suspeitos = verificar_identidade(layout, permitidos)
    if suspeitos:
        raise PermissionError("Exportação bloqueada: há textos com CPF/CNPJ/CREA não confirmados: " +
                              "; ".join(f"{i}: {t}" for i, t in suspeitos[:5]))
    os.makedirs(pasta, exist_ok=True)
    rec = os.path.join(pasta, "recursos")
    os.makedirs(rec, exist_ok=True)
    for it in layout.items():
        if isinstance(it, QgsLayoutItemPicture):
            nome = it.customProperty("na_origem", "")
            for cand in (os.path.join(ASSETS, nome) if nome else "", it.picturePath()):
                if cand and os.path.isfile(cand):
                    shutil.copy2(cand, os.path.join(rec, os.path.basename(cand)))
                    break
    qpt = salvar_qpt(layout, os.path.join(pasta, "layout.qpt"))
    previa = exportar_previa(layout, os.path.join(pasta, "pre_visualizacao.png"))
    for nome, conteudo in (("proposta_ia.json", proposta_ia), ("proposta_automatica.json", proposta_automatica),
                           ("proposta_revisada.json", proposta_revisada), ("conferencia.json", conferencia)):
        if conteudo is not None:
            with open(os.path.join(pasta, nome), "w", encoding="utf-8") as fh:
                json.dump(conteudo, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(pasta, "COMO_ABRIR.txt"), "w", encoding="utf-8") as fh:
        fh.write(
            "Como abrir este modelo no QGIS\n\n"
            "1. Abra o projeto com as camadas do imóvel.\n"
            "2. Projeto > Novo layout de impressão > dê um nome.\n"
            "3. No layout: Layout > Adicionar itens do modelo... > escolha layout.qpt.\n"
            "   (ou, no plugin NorteAgro Layout, use 'Salvar layout como modelo' e depois 'Gerar planta').\n"
            "4. Os mapas guardam as camadas pelo nome e pela fonte. Se as camadas estiverem em outra pasta,\n"
            "   selecione cada mapa e marque as camadas em Propriedades do item > Camadas.\n"
            "5. Os textos usam variáveis do projeto (@na_imovel, @na_proprietario...). Preencha-as no plugin,\n"
            "   aba 'Planta (Modelo Norte Agro)', quadro 3 'Dados do imóvel', ou em Projeto > Propriedades >\n"
            "   Variáveis.\n"
            "6. Figuras (logo, norte, assinatura) estão embutidas no layout; cópias ficam em recursos/.\n")
    if zipar:
        shutil.make_archive(pasta.rstrip("\\/"), "zip", pasta)
    return {"qpt": qpt, "previa": previa, "pasta": pasta}


def adicionar_ao_projeto(projeto, layout):
    gerente = projeto.layoutManager()
    nome = layout.name() or "Layout"
    base = nome
    n = 2
    while gerente.layoutByName(nome) is not None:
        nome = f"{base} ({n})"
        n += 1
    layout.setName(nome)
    gerente.addLayout(layout)
    return layout
