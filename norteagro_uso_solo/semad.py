# -*- coding: utf-8 -*-
"""v0.5.0: camadas da SEMAD-GO (SIGA - Sistema de Informações Geográficas Ambientais de Goiás) no imóvel.

As camadas ficam no CATÁLOGO (grupo "SEMAD - SIGA" de Criar / gerenciar camadas) e também na tela "Camadas da SEMAD".
Ao criar (ou atualizar) uma delas, o plugin se conecta ao GeoServer do SIGA - toda vez, nada fica guardado - e:

* Campos de Murundus, APP de Declividade, APP de Borda de Chapada e APP de Topo de Morro: grava só a parte DENTRO do
  imóvel (o resto é descartado). Precisa da camada Área Total do Imóvel com o limite desenhado.
* Unidades de Conservação (estaduais, federais, municipais e RPPN): grava as UC INTEIRAS - todas as que sobrepõem o
  imóvel ou estão perto dele (raio configurável, 10 km de fábrica) - com nome, descrição, se SOBREPÕE o imóvel e
  quanto. Também precisa do imóvel (para saber o que sobrepõe e o que está perto), mas a UC não é recortada.
* Se não existe nada no imóvel, a camada não é criada (e a de uma consulta anterior é retirada).

Essas camadas são referência: não entram no cálculo de áreas nem na correção.

v0.7.0 (pedido do escritório): os MURUNDUS não viram mais uma camada à parte. A parte deles dentro do imóvel vai para a
camada "Murundus" do grupo Uso do Solo (catálogo do escritório, ARQUIVO MURUNDUS), que é criada sozinha quando o
imóvel tem murundus - e entra no Quadro de Áreas como as outras camadas do Uso do Solo. Desenho feito à mão nessa
camada nunca é substituído: só a camada vazia, ou só com dados do SIGA, recebe a consulta nova (com cópia de segurança).
O "mapeamento original de 2020" fica só no catálogo (grupo SEMAD - SIGA), para quem quiser criar à mão.
"""
import json
import os
import tempfile
from datetime import datetime

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea, QgsFeature, QgsField, QgsGeometry,
    QgsPalLayerSettings, QgsProject, QgsRectangle, QgsSettings, QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer,
    QgsVectorLayerSimpleLabeling, QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor

from . import compat
from . import topologia as topo

SIGA_WFS = "https://siga.meioambiente.go.gov.br/geoserver/ows"
GRUPO = "SEMAD - SIGA"
PROPRIEDADE = "norteagro/semad"
CHAVE_CONFIG_AUTO = "norteagro/semad_auto"
CHAVE_CONFIG_RAIO = "norteagro/semad_raio_uc_km"
RAIO_UC_PADRAO_KM = 10.0
PASTA = GRUPO  # nome da pasta dentro de shapefiles (vem do grupo do catálogo)

FONTE_SIGA = "SEMAD-GO / SIGA"
# v0.7.0: murundus vão para a camada Murundus do Uso do Solo (catálogo do escritório)
MURUNDUS = "MURUNDUS"
MURUNDUS_ANTIGA = "SEMAD_MURUNDUS"   # camada à parte das versões 0.5/0.6 (grupo SEMAD - SIGA): sai quando a nova é gravada
PROPRIEDADE_DADOS = "norteagro/semad_dados"  # marca (só informativa) da camada do Uso do Solo preenchida pelo SIGA

# camadas do catálogo (ARQUIVO) -> camadas do SIGA
# "uso_do_solo": grava na camada do grupo Uso do Solo (entra no cálculo); "manual": só no catálogo, fora da
# consulta automática e da tela Camadas da SEMAD.
CAMADAS = [
    {"arquivo": MURUNDUS, "recortar": True, "cor": "#8E6C3A", "uso_do_solo": True,
     "fontes": ["geonode:murundus_final_2020_convalidacao"]},
    {"arquivo": "SEMAD_MURUNDUS_2020", "recortar": True, "cor": "#C49A55", "manual": True,
     "fontes": ["geonode:Murundus_final_2020"]},
    {"arquivo": "SEMAD_APP_DECLIVIDADE", "recortar": True, "cor": "#C0392B", "fontes": ["geonode:rel_app_declividade"]},
    {"arquivo": "SEMAD_APP_BORDA_CHAPADA", "recortar": True, "cor": "#8E44AD", "fontes": ["geonode:rel_app_b_chapada"]},
    {"arquivo": "SEMAD_APP_TOPO_MORRO", "recortar": True, "cor": "#D35400", "fontes": ["geonode:rel_app_topo_morro"]},
    {"arquivo": "SEMAD_UC", "recortar": False, "cor": "#1E8449",
     "fontes": ["geonode:ceuc_estadual", "geonode:uc_federal", "geonode:vw_uc_municipal", "geonode:vw_rppn_estadual"]},
]
ARQUIVOS = [c["arquivo"] for c in CAMADAS]
AUTOMATICAS = [c["arquivo"] for c in CAMADAS if not c.get("manual")]   # consulta automática e tela da SEMAD
NOMES = {
    MURUNDUS: "Murundus",
    "SEMAD_MURUNDUS_2020": "Campos de Murundus 2020 - mapeamento original (SEMAD)",
    "SEMAD_APP_DECLIVIDADE": "APP de Declividade (SEMAD)",
    "SEMAD_APP_BORDA_CHAPADA": "APP de Borda de Chapada (SEMAD)",
    "SEMAD_APP_TOPO_MORRO": "APP de Topo de Morro (SEMAD)",
    "SEMAD_UC": "Unidades de Conservação (SEMAD)",
}
EXPLICACAO = {
    MURUNDUS: "Campos de murundus mapeados pela SEMAD (2020, versão convalidada), só a parte dentro do imóvel. Vão para a "
              "camada Murundus do grupo Uso do Solo, criada sozinha quando o imóvel tem murundus.",
    "SEMAD_MURUNDUS_2020": "Mapeamento original de murundus de 2020 (antes da convalidação). Só a parte dentro do imóvel.",
    "SEMAD_APP_DECLIVIDADE": "APP de encostas com declividade acima de 45°. Só a parte dentro do imóvel.",
    "SEMAD_APP_BORDA_CHAPADA": "APP de borda de tabuleiro ou chapada. Só a parte dentro do imóvel.",
    "SEMAD_APP_TOPO_MORRO": "APP de topo de morro, monte, montanha e serra. Só a parte dentro do imóvel.",
    "SEMAD_UC": "Unidades de Conservação estaduais, federais, municipais e RPPN que sobrepõem o imóvel ou estão perto dele. "
                "Entram inteiras, com nome e descrição.",
}
GRUPOS_UC = {"US": "Uso Sustentável - US", "PI": "Proteção Integral - PI"}
SIGLAS_UC = {
    "APA": "Área de Proteção Ambiental - APA", "ARIE": "Área de Relevante Interesse Ecológico - ARIE",
    "ESEC": "Estação Ecológica - ESEC", "FLONA": "Floresta Nacional - FLONA", "MONA": "Monumento Natural - MONA",
    "PARNA": "Parque Nacional - PARNA", "REBIO": "Reserva Biológica - REBIO", "RESEX": "Reserva Extrativista - RESEX",
    "RDS": "Reserva de Desenvolvimento Sustentável - RDS", "REVIS": "Refúgio de Vida Silvestre - REVIS",
    "RPPN": "Reserva Particular do Patrimônio Natural - RPPN",
}


def eh_semad(arquivo):
    """Camada que é preenchida consultando o SIGA (inclui a Murundus do Uso do Solo)."""
    return str(arquivo or "").upper() in ARQUIVOS


def vai_para_uso_do_solo(arquivo):
    """v0.7.0: camada do grupo Uso do Solo preenchida pelo SIGA (Murundus). Ela entra no cálculo de áreas."""
    cfg = config_camada(arquivo)
    return bool(cfg and cfg.get("uso_do_solo"))


def config_camada(arquivo):
    return next((c for c in CAMADAS if c["arquivo"] == str(arquivo or "").upper()), None)


def nome_camada(plugin, arquivo):
    """Nome que aparece para a pessoa (o do catálogo, se houver)."""
    try:
        e = plugin.entrada(arquivo) if plugin is not None else None
    except Exception:
        e = None
    return str((e or {}).get("nome") or NOMES.get(str(arquivo).upper(), arquivo))


def raio_uc_km():
    try:
        return max(0.0, float(QgsSettings().value(CHAVE_CONFIG_RAIO, RAIO_UC_PADRAO_KM)))
    except Exception:
        return RAIO_UC_PADRAO_KM


def definir_raio_uc_km(valor):
    QgsSettings().setValue(CHAVE_CONFIG_RAIO, float(valor))


# ---------------------------------------------------------------- imóvel
def imovel_do_projeto(indice, srid=""):
    """(camada, geometria unida no SRC da camada) da Área do Imóvel do projeto; (camada, None) se ela está sem
    desenho; (None, None) se não há a camada."""
    from .areas import contar_feicoes, prever_reconhecimentos
    camadas = [c for c in QgsProject.instance().mapLayers().values()
               if isinstance(c, QgsVectorLayer) and c.isValid() and c.geometryType() == compat.GEOM_POLIGONO
               and not str(c.customProperty(PROPRIEDADE, "") or "")]
    if not camadas:
        return None, None
    try:
        prev, _ = prever_reconhecimentos(camadas, srid or "EPSG:31982", indice)
    except Exception:
        prev = {}
    imoveis = [c for c in camadas if (prev.get(c.id()) or {}).get("arquivo") == "AREA_DO_IMOVEL"]
    if not imoveis:
        return None, None
    # a com desenho primeiro; empate: a criada pelo plugin
    cam = max(imoveis, key=lambda c: (contar_feicoes(c) > 0,
                                      str(c.customProperty("norteagro/arquivo", "") or "") == "AREA_DO_IMOVEL",
                                      contar_feicoes(c)))
    gs = [QgsGeometry(f.geometry()) for f in cam.getFeatures() if f.hasGeometry() and not f.geometry().isEmpty()]
    if not gs:
        return cam, None
    g = topo.uniao(gs)
    if g is None or g.isEmpty() or g.area() <= 0:
        return cam, None
    return cam, g


# ---------------------------------------------------------------- rede
def baixar(url, timeout_s=60):
    """Baixa `url` pela rede do QGIS (usa o proxy configurado no QGIS). Devolve (bytes, erro)."""
    try:
        from qgis.core import QgsBlockingNetworkRequest
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest
        req = QgsBlockingNetworkRequest()
        try:
            req.setTimeout(int(timeout_s * 1000))
        except Exception:
            pass
        r = QNetworkRequest(QUrl(url))
        r.setRawHeader(b"User-Agent", b"QGIS NorteAgro")
        codigo = req.get(r, True)
        if codigo != QgsBlockingNetworkRequest.ErrorCode.NoError:
            return b"", (req.errorMessage() or "falha de rede")
        return bytes(req.reply().content()), ""
    except Exception as exc:  # fora do QGIS (testes) ou API diferente
        try:
            import urllib.request
            dados = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "QGIS NorteAgro"}),
                                           timeout=timeout_s).read()
            return dados, ""
        except Exception as exc2:
            return b"", str(exc2 or exc)


def consultar(tipo, caixa_4674, timeout_s=90):
    """Feições da camada `tipo` do SIGA na caixa (SIRGAS 2000). Devolve (lista de (QgsGeometry 4674, atributos), erro)."""
    url = (f"{SIGA_WFS}?service=WFS&version=1.0.0&request=GetFeature&typeName={tipo}"
           f"&outputFormat=application/json&srsName=EPSG:4674"
           f"&bbox={caixa_4674.xMinimum():.7f},{caixa_4674.yMinimum():.7f},"
           f"{caixa_4674.xMaximum():.7f},{caixa_4674.yMaximum():.7f}")
    dados, erro = baixar(url, timeout_s)
    if erro:
        return [], erro
    texto = dados.decode("utf-8", "replace").strip()
    if not texto.startswith("{"):
        return [], "o SIGA respondeu fora do padrão (serviço fora do ar?)"
    try:
        js = json.loads(texto)
    except Exception as exc:
        return [], f"resposta inválida do SIGA ({exc})"
    if not js.get("features"):
        return [], ""
    tmp = os.path.join(tempfile.gettempdir(), "norteagro_semad_" + tipo.split(":")[-1] + ".geojson")
    with open(tmp, "w", encoding="utf-8") as fp:
        fp.write(texto)
    lay = QgsVectorLayer(tmp, "semad", "ogr")
    if not lay.isValid():
        return [], "não foi possível ler a resposta do SIGA"
    nomes = lay.fields().names()
    saida = [(QgsGeometry(f.geometry()), {n: f[n] for n in nomes}) for f in lay.getFeatures()
             if f.hasGeometry() and not f.geometry().isEmpty()]
    del lay
    return saida, ""


# ---------------------------------------------------------------- busca
def _medidor(crs):
    d = QgsDistanceArea()
    d.setSourceCrs(crs, QgsProject.instance().transformContext())
    d.setEllipsoid("GRS80")
    return d


def _t(v):
    if v is None:
        return ""
    if hasattr(v, "toString") and hasattr(v, "isValid"):  # QDateTime / QDate do OGR
        try:
            if not v.isValid():
                return ""
            return v.toString("dd/MM/yyyy")
        except Exception:
            return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s in ("NULL", "None", "nan"):
        return ""
    s = s.replace("Sutententável", "Sustentável").replace("Sustententável", "Sustentável")
    if s.startswith("Area "):
        s = "Á" + s[1:]
    return s


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if x == x else None
    except Exception:
        return None


def _ha_br(v, casas=2):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _criacao_curta(texto):
    """Só o primeiro ato de criação (a UC federal lista todos os decretos) + o ano entre parênteses, se houver."""
    texto = str(texto or "").strip()
    ano = ""
    if texto.endswith(")") and "(" in texto:
        ano = texto[texto.rindex("("):]
        texto = texto[:texto.rindex("(")].strip()
    primeiro = texto.split(";")[0].strip().rstrip(".")
    if primeiro != texto.rstrip("."):
        primeiro += " e alterações"
    return (primeiro + (" " + ano if ano else "")).strip()


def descrever_uc(attrs, tipo, area_calculada_ha=None):
    """Nome, categoria, grupo... e uma descrição legível da UC (cada camada do SIGA tem campos diferentes)."""
    if tipo.endswith("uc_federal"):
        sigla = _t(attrs.get("siglacateg"))
        d = {"nome": _t(attrs.get("nomeuc")), "categoria": SIGLAS_UC.get(sigla.upper(), sigla),
             "grupo": GRUPOS_UC.get(_t(attrs.get("grupouc")).upper(), _t(attrs.get("grupouc"))),
             "esfera": _t(attrs.get("esferaadm")) or "Federal",
             "criacao": " ".join(x for x in (_t(attrs.get("criacaoato")),
                                             ("(" + _t(attrs.get("criacaoano")) + ")") if _t(attrs.get("criacaoano")) else "")
                                 if x),
             "area_uc_ha": _num(attrs.get("areahaalb")), "gestor": _t(attrs.get("ngi")),
             "codigo": ("CNUC " + _t(attrs.get("cnuc"))) if _t(attrs.get("cnuc")) else "", "municipio": ""}
    else:
        registro = _t(attrs.get("dataregistro"))
        d = {"nome": _t(attrs.get("nomeunidade")), "categoria": _t(attrs.get("categoria")),
             "grupo": _t(attrs.get("grupo")), "esfera": _t(attrs.get("esferaadministrativa")),
             "criacao": _t(attrs.get("cria_ato")) or (("registro em " + registro) if registro else ""),
             "area_uc_ha": _num(attrs.get("area_ha") if attrs.get("area_ha") is not None else attrs.get("area_ha_alb")),
             "gestor": "", "codigo": "", "municipio": _t(attrs.get("municipio") or attrs.get("municipioibge"))}
        if tipo.endswith("rppn_estadual"):
            d["categoria"] = d["categoria"] or SIGLAS_UC["RPPN"]
            d["esfera"] = d["esfera"] or "Estadual"
        elif tipo.endswith("uc_municipal"):
            d["esfera"] = d["esfera"] or "Municipal"
        else:
            d["esfera"] = d["esfera"] or "Estadual"
    sigla = d["categoria"].strip().upper()
    if sigla in SIGLAS_UC:
        d["categoria"] = SIGLAS_UC[sigla]
    if d["grupo"].strip().upper() in GRUPOS_UC:
        d["grupo"] = GRUPOS_UC[d["grupo"].strip().upper()]
    if not d["nome"]:
        d["nome"] = d["categoria"] or "Unidade de Conservação (sem nome no SIGA)"
    partes = [x for x in (d["categoria"], d["grupo"], ("esfera " + d["esfera"].lower()) if d["esfera"] else "") if x]
    if d["criacao"]:
        partes.append("criação: " + _criacao_curta(d["criacao"]))
    if d["area_uc_ha"]:
        partes.append(f"área oficial {_ha_br(d['area_uc_ha'])} ha")
    elif area_calculada_ha:
        partes.append(f"área {_ha_br(area_calculada_ha)} ha (calculada)")
    if d["gestor"]:
        partes.append("gestão: " + d["gestor"])
    if d["codigo"]:
        partes.append(d["codigo"])
    if d["municipio"] and not d["municipio"].isdigit():
        partes.append("município: " + d["municipio"])
    d["descricao"] = " - ".join(partes)
    return d


def buscar(arquivo, imovel_geom, imovel_crs, srid_trabalho="EPSG:31982", raio_km=None):
    """Consulta UMA camada do catálogo SEMAD. Devolve {arquivo, situacao: tem|nao_tem|erro, erro, feicoes:
    [(geometria no SRC de trabalho, atributos prontos)], ha_dentro, nomes (UC que sobrepõem), perto (UC perto)}.
    Nada é gravado aqui."""
    cfg = config_camada(arquivo)
    ctx = QgsProject.instance().transformContext()
    sirgas = QgsCoordinateReferenceSystem("EPSG:4674")
    trab = QgsCoordinateReferenceSystem(srid_trabalho or "EPSG:31982")
    if not trab.isValid() or trab.isGeographic():
        trab = QgsCoordinateReferenceSystem("EPSG:31982")
    im_trab = QgsGeometry(imovel_geom)
    if imovel_crs != trab:
        im_trab.transform(QgsCoordinateTransform(imovel_crs, trab, ctx))
    im_trab = topo.so_poligonos(im_trab)
    im_s = QgsGeometry(imovel_geom)
    if imovel_crs != sirgas:
        im_s.transform(QgsCoordinateTransform(imovel_crs, sirgas, ctx))
    raio_km = raio_uc_km() if raio_km is None else max(0.0, float(raio_km))
    caixa = QgsRectangle(im_s.boundingBox())
    caixa.grow(0.002 if cfg["recortar"] else max(0.002, raio_km / 100.0))  # ~200 m; UC: o raio (1° ~ 105-111 km)
    para_trab = QgsCoordinateTransform(sirgas, trab, ctx)
    motor = QgsGeometry.createGeometryEngine(im_trab.constGet())
    motor.prepareGeometry()
    d = _medidor(trab)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    res = {"arquivo": cfg["arquivo"], "situacao": "nao_tem", "erro": "", "feicoes": [], "ha_dentro": 0.0, "nomes": [],
           "perto": 0, "srid": trab.authid(), "raio_km": raio_km}
    vistos = set()
    for tipo in cfg["fontes"]:
        feicoes, erro = consultar(tipo, caixa)
        if erro:
            res["situacao"], res["erro"] = "erro", erro
            return res
        for g, attrs in feicoes:
            try:
                g.transform(para_trab)
            except Exception:
                continue
            g = topo.so_poligonos(g)
            if g is None or g.isEmpty():
                continue
            dentro = None
            if motor.intersects(g.constGet()):
                try:
                    dentro = topo.intersecao(g, im_trab)
                except Exception:
                    dentro = None
            ha = d.measureArea(dentro) / 10000.0 if not topo.vazia(dentro) else 0.0
            if cfg["recortar"]:
                if ha < 0.0001:
                    continue  # fora do imóvel ou só encostando na divisa: descartado
                a = {"fonte": FONTE_SIGA, "area_ha": round(ha, 4), "consulta": agora}
                if "murundu" in tipo.lower():
                    a["id_semad"] = _t(attrs.get("id_murundu") if attrs.get("id_murundu") is not None
                                       else attrs.get("ID_Murundu"))
                    a["municipio"] = _t(attrs.get("municipio") or attrs.get("Municipio"))
                res["feicoes"].append((dentro, a))
                res["ha_dentro"] += ha
                continue
            # UC: inteira, se sobrepõe o imóvel ou está a até `raio_km` dele
            sobrepoe = ha >= 0.0001
            dist_km = 0.0 if sobrepoe else g.distance(im_trab) / 1000.0
            if dist_km > raio_km:
                continue
            u = descrever_uc(attrs, tipo, d.measureArea(g) / 10000.0)
            chave = (u["nome"].lower(), int(round(g.area() / 1000.0)))
            if chave in vistos:
                continue  # a mesma UC em duas camadas do SIGA
            vistos.add(chave)
            area_uc = u["area_uc_ha"] or d.measureArea(g) / 10000.0
            a = {"nome": u["nome"][:254], "categoria": u["categoria"][:254], "grupo": u["grupo"][:254],
                 "esfera": u["esfera"][:254], "criacao": u["criacao"][:254], "area_uc_ha": round(area_uc, 2),
                 "sobrepoe": "Sim" if sobrepoe else "Não", "dentro_ha": round(ha, 4), "dist_km": round(dist_km, 2),
                 "descricao": u["descricao"][:254], "fonte": FONTE_SIGA, "consulta": agora}
            res["feicoes"].append((g, a))
            if sobrepoe:
                res["ha_dentro"] += ha
                res["nomes"].append(u["nome"])
            else:
                res["perto"] += 1
    if not cfg["recortar"]:
        # as que sobrepõem primeiro, depois as mais perto
        res["feicoes"].sort(key=lambda x: (x[1]["sobrepoe"] != "Sim", x[1]["dist_km"], x[1]["nome"]))
    if res["feicoes"]:
        res["situacao"] = "tem"
    return res


# ---------------------------------------------------------------- gravação na camada do catálogo
CAMPOS_RECORTE = [("fonte", "t", 60), ("area_ha", "r", 0), ("id_semad", "t", 30), ("municipio", "t", 80),
                  ("consulta", "t", 20)]
CAMPOS_UC = [("nome", "t", 254), ("categoria", "t", 120), ("grupo", "t", 60), ("esfera", "t", 30),
             ("criacao", "t", 254), ("area_uc_ha", "r", 0), ("sobrepoe", "t", 3), ("dentro_ha", "r", 0),
             ("dist_km", "r", 0), ("descricao", "t", 254), ("fonte", "t", 60), ("consulta", "t", 20)]


def _campo(nome, tipo, tamanho):
    if tipo == "t":
        return QgsField(nome, compat.CAMPO_TEXTO, "String", tamanho or 254)
    return QgsField(nome, compat.CAMPO_REAL, "Real", 18, 4)


def _garantir_campos(camada, campos):
    existentes = set(camada.fields().names())
    novos = [_campo(n, t, tam) for n, t, tam in campos if n not in existentes]
    if novos:
        camada.dataProvider().addAttributes(novos)
        camada.updateFields()


def _rotulos_uc(camada, cor):
    try:
        pal = QgsPalLayerSettings()
        pal.fieldName = "nome"
        fmt = QgsTextFormat(); fmt.setSize(9); fmt.setColor(QColor(cor))
        buf = QgsTextBufferSettings(); buf.setEnabled(True); buf.setSize(0.8); buf.setColor(QColor("white"))
        fmt.setBuffer(buf)
        pal.setFormat(fmt)
        camada.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        camada.setLabelsEnabled(True)
    except Exception:
        pass
    try:
        camada.setMapTipTemplate(
            "<b>[% \"nome\" %]</b><br>[% \"descricao\" %]<br>Sobrepõe o imóvel: <b>[% \"sobrepoe\" %]</b>"
            " ([% \"dentro_ha\" %] ha) - distância do imóvel: [% \"dist_km\" %] km")
        camada.setDisplayExpression("\"nome\"")
    except Exception:
        pass


def _camada_memoria(arquivo, srid):
    """Sem pasta do mapa: a camada fica temporária no projeto (some ao fechar)."""
    proj = QgsProject.instance()
    for c in proj.mapLayers().values():
        if str(c.customProperty(PROPRIEDADE, "") or "") == arquivo and c.providerType() == "memory":
            return c
    camada = QgsVectorLayer(f"MultiPolygon?crs={srid}&field=id:integer", NOMES.get(arquivo, arquivo), "memory")
    camada.setCustomProperty(PROPRIEDADE, arquivo)
    proj.addMapLayer(camada, False)
    raiz = proj.layerTreeRoot()
    grupo = raiz.findGroup(GRUPO) or raiz.insertGroup(0, GRUPO)
    grupo.addLayer(camada)
    from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer
    cfg = config_camada(arquivo)
    cor = QColor(cfg["cor"])
    if cfg["recortar"]:
        simb = QgsFillSymbol.createSimple({"color": f"{cor.red()},{cor.green()},{cor.blue()},110",
                                           "outline_color": cor.name(), "outline_width": "0.4"})
    else:
        simb = QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": cor.name(), "outline_width": "0.8"})
    camada.setRenderer(QgsSingleSymbolRenderer(simb))
    return camada


def gravar(plugin, res):
    """Cria (ou carrega) a camada do catálogo e TROCA o conteúdo dela pelo resultado da consulta.
    Devolve (camada, acao): acao "criada" ou "atualizada" (Murundus do Uso do Solo: também "mantida" e "sem_mudanca",
    ver gravar_uso_do_solo)."""
    arquivo = res["arquivo"]
    cfg = config_camada(arquivo)
    if cfg.get("uso_do_solo"):
        return gravar_uso_do_solo(plugin, res)
    pasta, _ = plugin.memoria_basica()
    acao = "atualizada"
    camada = None
    if pasta and os.path.isdir(pasta):
        antes = plugin.camada_plugin(arquivo)
        ok, acao_c, erro = plugin.criar_ou_carregar(arquivo, _semad_interno=True)
        if not ok and _limpar_restos(plugin, arquivo):
            ok, acao_c, erro = plugin.criar_ou_carregar(arquivo, _semad_interno=True)
        if not ok:
            raise RuntimeError(erro or "não foi possível criar a camada")
        camada = plugin.camada_plugin(arquivo)
        acao = "criada" if (acao_c == "criada" or antes is None) else "atualizada"
    if camada is None:
        camada = _camada_memoria(arquivo, res.get("srid") or "EPSG:31982")
    if camada.isEditable():
        camada.rollBack()
    _garantir_campos(camada, CAMPOS_RECORTE if cfg["recortar"] else CAMPOS_UC)
    prov = camada.dataProvider()
    ids = [f.id() for f in camada.getFeatures()]
    if ids:
        prov.deleteFeatures(ids)
    trab_crs = QgsCoordinateReferenceSystem(res.get("srid") or "EPSG:31982")
    tr = QgsCoordinateTransform(trab_crs, camada.crs(), QgsProject.instance()) if camada.crs() != trab_crs else None
    multi = QgsWkbTypes.isMultiType(camada.wkbType())
    nomes = camada.fields().names()
    novas = []
    for i, (g, a) in enumerate(res["feicoes"], 1):
        g = QgsGeometry(g)
        if tr is not None:
            g.transform(tr)
        partes = [g] if (multi or not g.isMultipart()) else [QgsGeometry(p) for p in g.asGeometryCollection()]
        for p in partes:
            if multi:
                p.convertToMultiType()
            f = QgsFeature(camada.fields())
            f.setGeometry(p)
            dados = dict(a)
            dados["id"] = i
            f.setAttributes([dados.get(n) for n in nomes])
            novas.append(f)
    ok_add, _ = prov.addFeatures(novas)
    if not ok_add:
        raise RuntimeError("o arquivo da camada não aceitou as feições (está aberto em outro programa?)")
    camada.updateExtents()
    camada.setCustomProperty(PROPRIEDADE, arquivo)
    if not cfg["recortar"]:
        _rotulos_uc(camada, cfg["cor"])
        _salvar_estilo(camada)
    camada.reload()
    camada.triggerRepaint()
    return camada, acao


# ---------------------------------------------------------------- v0.7.0: Murundus no grupo Uso do Solo
def _entrada_padrao_murundus():
    """Definição de fábrica da camada Murundus (padrao/catalogo_extra.json), para quando o catálogo do escritório
    não tem mais a camada (alguém removeu): ela entra só neste projeto, no Uso do Solo, em "Outras camadas"."""
    item = {}
    try:
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "padrao", "catalogo_extra.json")
        with open(caminho, encoding="utf-8") as fp:
            dados = json.load(fp)
        item = next((x for x in dados.get("extras", []) if str(x.get("arquivo", "")).upper() == MURUNDUS), {}) or {}
    except Exception:
        item = {}
    return {"arquivo": MURUNDUS, "nome": str(item.get("nome") or "Murundus"), "tipo": "P", "grupo": "Uso do Solo",
            "quadro": str(item.get("quadro") or "OUTRAS"), "estilo_xml": str(item.get("estilo") or ""),
            "personalizada": True, "origem": "projeto"}


def entrada_uso_do_solo(plugin, arquivo):
    """Entrada do catálogo da camada do Uso do Solo; sem ela no catálogo, grava a de fábrica só neste projeto."""
    e = plugin.entrada(arquivo)
    if e:
        return e
    if str(arquivo).upper() == MURUNDUS:
        try:
            plugin.salvar_extra_projeto(_entrada_padrao_murundus())
        except Exception:
            pass
        e = plugin.entrada(arquivo)
    return e


def _camada_uso_memoria(plugin, arquivo, srid):
    """Sem pasta do mapa: camada temporária no grupo Uso do Solo (some ao fechar o projeto)."""
    proj = QgsProject.instance()
    for c in proj.mapLayers().values():
        if str(c.customProperty(PROPRIEDADE_DADOS, "") or "") == arquivo and c.providerType() == "memory":
            return c
    entrada = plugin.entrada(arquivo) or _entrada_padrao_murundus()
    camada = QgsVectorLayer(f"MultiPolygon?crs={srid}&field=id:integer", entrada.get("nome") or arquivo, "memory")
    camada.setCustomProperty("norteagro/arquivo", arquivo)
    camada.setCustomProperty("norteagro/nome", entrada.get("nome") or arquivo)
    camada.setCustomProperty(PROPRIEDADE_DADOS, arquivo)
    proj.addMapLayer(camada, False)
    raiz = proj.layerTreeRoot()
    grupo = raiz.findGroup(entrada.get("grupo") or "Uso do Solo") or raiz.insertGroup(0, entrada.get("grupo") or "Uso do Solo")
    grupo.addLayer(camada)
    try:
        from qgis.core import QgsSingleSymbolRenderer
        from .catalogo import simbolo_entrada
        camada.setRenderer(QgsSingleSymbolRenderer(simbolo_entrada(entrada)))
    except Exception:
        pass
    return camada


def camada_uso_do_solo(plugin, arquivo):
    """A camada do Uso do Solo já carregada no projeto (da pasta do mapa ou temporária), ou None."""
    camada = None
    try:
        camada = plugin.camada_plugin(arquivo)
    except Exception:
        camada = None
    if camada is not None:
        return camada
    for c in QgsProject.instance().mapLayers().values():
        if isinstance(c, QgsVectorLayer) and str(c.customProperty(PROPRIEDADE_DADOS, "") or "") == arquivo:
            return c
    return None


def feicoes_feitas_a_mao(camada):
    """Feições com desenho que NÃO vieram do SIGA (campo fonte diferente de SEMAD-GO / SIGA ou sem o campo)."""
    if camada is None:
        return 0
    tem_fonte = "fonte" in camada.fields().names()
    n = 0
    for f in camada.getFeatures():
        if not f.hasGeometry() or f.geometry().isEmpty():
            continue
        if not tem_fonte or str(f["fonte"] or "").strip() != FONTE_SIGA:
            n += 1
    return n


def _mesmo_conteudo(camada, res, tolerancia_m2=1.0):
    """True se a camada já tem exatamente o que o SIGA devolveu (diferença menor que 1 m²): não regrava à toa
    (a consulta roda toda vez que Criar / gerenciar abre)."""
    try:
        trab = QgsCoordinateReferenceSystem(res.get("srid") or "EPSG:31982")
        tr = QgsCoordinateTransform(camada.crs(), trab, QgsProject.instance()) if camada.crs() != trab else None
        atuais = []
        for f in camada.getFeatures():
            if f.hasGeometry() and not f.geometry().isEmpty():
                g = QgsGeometry(f.geometry())
                if tr is not None:
                    g.transform(tr)
                atuais.append(g)
        novas = [QgsGeometry(g) for g, _ in res["feicoes"]]
        if not atuais or not novas:
            return False
        a, b = topo.uniao(atuais), topo.uniao(novas)
        if a is None or b is None:
            return False
        dif = a.symDifference(b)
        return dif is None or dif.isEmpty() or dif.area() < tolerancia_m2
    except Exception:
        return False


def gravar_uso_do_solo(plugin, res):
    """v0.7.0: grava os murundus do SIGA na camada Murundus do grupo Uso do Solo.

    * Não existe: cria (no grupo Uso do Solo, com o estilo do catálogo) e grava.
    * Existe vazia, ou só com dados do SIGA: troca pelo resultado da consulta (cópia de segurança em _backup antes);
      se já é igual, não mexe.
    * Tem desenho feito à mão: NÃO mexe (acao "mantida").
    Devolve (camada, acao): "criada", "atualizada", "sem_mudanca" ou "mantida"."""
    arquivo = res["arquivo"]
    pasta, _ = plugin.memoria_basica()
    camada = camada_uso_do_solo(plugin, arquivo)
    existia = camada is not None
    if pasta and os.path.isdir(pasta):
        entrada = entrada_uso_do_solo(plugin, arquivo)
        if not entrada:
            raise RuntimeError("a camada Murundus não está no catálogo")
        try:
            existia = existia or os.path.isfile(plugin.caminho_shp(arquivo))
        except Exception:
            pass
        ok, acao_c, erro = plugin.criar_ou_carregar(arquivo, _semad_interno=True)
        if not ok and _limpar_restos(plugin, arquivo):
            ok, acao_c, erro = plugin.criar_ou_carregar(arquivo, _semad_interno=True)
        if not ok:
            raise RuntimeError(erro or "não foi possível criar a camada")
        camada = plugin.camada_plugin(arquivo)
        if camada is None:
            raise RuntimeError("a camada foi criada, mas não foi carregada no projeto")
    elif camada is None:
        camada = _camada_uso_memoria(plugin, arquivo, res.get("srid") or "EPSG:31982")
    if camada.isEditable():
        if camada.isModified():
            return camada, "mantida"  # alguém está editando a camada agora: não mexe
        camada.rollBack()
    if feicoes_feitas_a_mao(camada):
        return camada, "mantida"
    if existia and _mesmo_conteudo(camada, res):
        return camada, "sem_mudanca"
    if existia and str(camada.providerType() or "").lower() == "ogr" and any(True for _ in camada.getFeatures()):
        try:
            from .operacoes import backup_shapefile
            backup_shapefile(camada)
        except Exception as exc:
            raise RuntimeError(f"não foi possível guardar a cópia de segurança ({exc}); a camada não foi alterada")
    _garantir_campos(camada, CAMPOS_RECORTE)
    trab_crs = QgsCoordinateReferenceSystem(res.get("srid") or "EPSG:31982")
    tr = QgsCoordinateTransform(trab_crs, camada.crs(), QgsProject.instance()) if camada.crs() != trab_crs else None
    multi = QgsWkbTypes.isMultiType(camada.wkbType())
    nomes = camada.fields().names()
    novas = []
    for i, (g, a) in enumerate(res["feicoes"], 1):
        g = QgsGeometry(g)
        if tr is not None:
            g.transform(tr)
        partes = [g] if (multi or not g.isMultipart()) else [QgsGeometry(p) for p in g.asGeometryCollection()]
        for p in partes:
            if multi:
                p.convertToMultiType()
            f = QgsFeature(camada.fields())
            f.setGeometry(p)
            dados = dict(a)
            dados["id"] = i
            f.setAttributes([dados.get(n) for n in nomes])
            novas.append(f)
    prov = camada.dataProvider()
    ids = [f.id() for f in camada.getFeatures()]
    if ids and not prov.deleteFeatures(ids):
        raise RuntimeError("o arquivo da camada não deixou apagar o conteúdo antigo (está aberto em outro programa?)")
    ok_add, _ = prov.addFeatures(novas)
    if not ok_add:
        raise RuntimeError("o arquivo da camada não aceitou as feições (está aberto em outro programa?)")
    camada.updateExtents()
    camada.setCustomProperty(PROPRIEDADE_DADOS, arquivo)
    camada.reload()
    camada.triggerRepaint()
    try:
        plugin.kml.exportar_automatico(camada)  # espelho KML (a gravação direta não passa pelo "salvar edição")
    except Exception:
        pass
    _retirar_murundus_antiga(plugin)
    QgsProject.instance().setDirty(True)
    return camada, ("atualizada" if existia else "criada")


def _retirar_murundus_antiga(plugin):
    """A camada "Campos de Murundus (SEMAD)" das versões 0.5/0.6 (grupo SEMAD - SIGA) agora é a Murundus do Uso do
    Solo: a antiga sai do mapa e o arquivo dela (só dado do SIGA, nunca desenho) é apagado."""
    proj = QgsProject.instance()
    arquivos = set()
    for c in list(proj.mapLayers().values()):
        if str(c.customProperty(PROPRIEDADE, "") or "") != MURUNDUS_ANTIGA and \
                str(c.customProperty("norteagro/arquivo", "") or "").upper() != MURUNDUS_ANTIGA:
            continue
        try:
            fonte = str(c.dataProvider().dataSourceUri()).split("|", 1)[0]
            if fonte.lower().endswith(".shp"):
                arquivos.add(fonte)
        except Exception:
            pass
        _soltar_arquivo(c)
        proj.removeMapLayer(c.id())
    pasta, _ = plugin.memoria_basica()
    if pasta and os.path.isdir(pasta):
        for raiz, _dirs, nomes in os.walk(os.path.join(pasta, "shapefiles")):
            if "_backup" in raiz:
                continue
            for n in nomes:
                if n.upper() == MURUNDUS_ANTIGA + ".SHP":
                    arquivos.add(os.path.join(raiz, n))
    for shp in arquivos:
        if os.path.isfile(shp) and _apagar_shp(shp):
            try:
                d = os.path.dirname(shp)
                if os.path.isdir(d) and not [x for x in os.listdir(d) if not x.lower().endswith(".qml")]:
                    for x in os.listdir(d):
                        os.remove(os.path.join(d, x))
                    os.rmdir(d)
            except Exception:
                pass
    g = proj.layerTreeRoot().findGroup(GRUPO)
    if g is not None and not g.children():
        g.parent().removeChildNode(g)


def _salvar_estilo(camada):
    """Guarda o rótulo da UC no QML da camada (vale para os próximos projetos)."""
    try:
        fonte = str(camada.dataProvider().dataSourceUri()).split("|", 1)[0]
        if fonte.lower().endswith(".shp"):
            camada.saveNamedStyle(os.path.splitext(fonte)[0] + ".qml", categories=compat.categorias_sem_propriedades())
    except Exception:
        pass


_EXTS_SHP = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".qmd")


def _soltar_arquivo(camada):
    """Fecha o arquivo da camada no QGIS (o Windows não deixa apagar arquivo aberto)."""
    try:
        fonte = str(camada.dataProvider().dataSourceUri()).split("|", 1)[0]
        camada.dataProvider().invalidateConnections(fonte)
    except Exception:
        pass


def _apagar_shp(shp):
    """Apaga o shapefile começando pelo .shp: se ele estiver preso, não mexe nos outros (o arquivo continua inteiro).
    Devolve True se apagou."""
    base = os.path.splitext(shp)[0]
    try:
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()
    except Exception:
        pass
    try:
        if os.path.exists(base + ".shp"):
            os.remove(base + ".shp")
    except Exception:
        return False
    for ext in _EXTS_SHP[1:]:
        try:
            if os.path.exists(base + ext):
                os.remove(base + ext)
        except Exception:
            pass
    return True


def retirar(plugin, arquivo):
    """Sem nada no imóvel: tira a camada do projeto e apaga o arquivo (é dado da SEMAD, não desenho do técnico).
    Se o Windows não deixar apagar, o arquivo fica vazio (sem feições) e fora do mapa. Devolve True se havia algo.
    v0.7.0: a Murundus do Uso do Solo NUNCA é apagada aqui (pode ter desenho do técnico); devolve False."""
    if vai_para_uso_do_solo(arquivo):
        return False
    proj = QgsProject.instance()
    havia = False
    try:
        shp = plugin.caminho_shp(arquivo)
    except Exception:
        shp = ""
    for c in list(proj.mapLayers().values()):
        if str(c.customProperty(PROPRIEDADE, "") or "") == arquivo or plugin.camada_plugin(arquivo) is c:
            try:
                if c.isEditable():
                    c.rollBack()
                ids = [f.id() for f in c.getFeatures()]
                if ids:
                    c.dataProvider().deleteFeatures(ids)  # se o arquivo não puder ser apagado, fica vazio
            except Exception:
                pass
            _soltar_arquivo(c)
            proj.removeMapLayer(c.id())
            havia = True
    if shp and os.path.isfile(shp):
        havia = True
        if _apagar_shp(shp):
            try:
                pasta = os.path.dirname(shp)
                if os.path.isdir(pasta) and not [x for x in os.listdir(pasta) if not x.lower().endswith(".qml")]:
                    for x in os.listdir(pasta):
                        os.remove(os.path.join(pasta, x))
                    os.rmdir(pasta)
            except Exception:
                pass
    g = proj.layerTreeRoot().findGroup(GRUPO)
    if g is not None and not g.children():
        g.parent().removeChildNode(g)
    return havia


def _limpar_restos(plugin, arquivo):
    """Arquivos que sobraram pela metade (sem o .shp, ou .shp sem o .dbf) impedem criar a camada: tira o resto."""
    try:
        shp = plugin.caminho_shp(arquivo)
    except Exception:
        return False
    if not shp:
        return False
    base = os.path.splitext(shp)[0]
    inteiro = all(os.path.exists(base + e) for e in (".shp", ".shx", ".dbf"))
    restos = [base + e for e in _EXTS_SHP if os.path.exists(base + e)]
    if inteiro or not restos:
        return False
    for r in restos:
        try:
            os.remove(r)
        except Exception:
            pass
    return True


def problema_imovel(plugin):
    """"" se dá para consultar; senão "sem_imovel" ou "imovel_vazio"."""
    _, srid = plugin.memoria_basica()
    cam, geom = imovel_do_projeto(plugin.indice_atual(), srid)
    if cam is None:
        return "sem_imovel"
    if geom is None:
        return "imovel_vazio"
    return ""


def gerar(plugin, arquivos=None, progresso=None):
    """Consulta o SIGA e grava as camadas pedidas (todas as da SEMAD se None).
    Devolve (resultados, problema_do_imovel). Com problema no imóvel nada é consultado."""
    arquivos = [str(a).upper() for a in (arquivos or AUTOMATICAS) if eh_semad(a)]
    _, srid = plugin.memoria_basica()
    srid = srid or "EPSG:31982"
    cam, geom = imovel_do_projeto(plugin.indice_atual(), srid)
    if cam is None:
        return [], "sem_imovel"
    if geom is None:
        return [], "imovel_vazio"
    resultados = []
    for i, arq in enumerate(arquivos):
        if progresso:
            progresso(i, len(arquivos), f"Consultando o SIGA: {NOMES.get(arq, arq)}...")
        try:
            res = buscar(arq, geom, cam.crs(), srid)
        except Exception as exc:
            res = {"arquivo": arq, "situacao": "erro", "erro": str(exc), "feicoes": [], "ha_dentro": 0.0, "nomes": [],
                   "perto": 0}
        res["imovel"] = cam.name()
        if res["situacao"] == "tem":
            try:
                _, res["acao"] = gravar(plugin, res)
            except Exception as exc:
                res["situacao"], res["erro"] = "erro", f"não gravou: {exc}"
        elif res["situacao"] == "nao_tem":
            if vai_para_uso_do_solo(arq):
                # v0.7.0: a camada do Uso do Solo não é apagada; só avisa se ela ainda tem dados antigos do SIGA
                cam_uso = camada_uso_do_solo(plugin, arq)
                res["antiga"] = bool(cam_uso is not None and any(True for _ in cam_uso.getFeatures())
                                     and not feicoes_feitas_a_mao(cam_uso))
            else:
                res["retirada"] = retirar(plugin, arq)
        resultados.append(res)
    if progresso:
        progresso(len(arquivos), len(arquivos), "Consulta concluída")
    return resultados, ""


def texto_problema_imovel(problema):
    if problema == "sem_imovel":
        return ("As camadas da SEMAD são analisadas pelo limite do imóvel, e este projeto ainda não tem a camada "
                "Área Total do Imóvel. Gere primeiro a Área Total do Imóvel, desenhe (ou cole) o limite e salve; "
                "depois gere as camadas da SEMAD.")
    if problema == "imovel_vazio":
        return ("A camada Área Total do Imóvel está sem desenho. Desenhe (ou cole) o limite do imóvel e salve a "
                "edição; depois gere as camadas da SEMAD.")
    return ""


def linha_resultado(res):
    """Texto curto do resultado de uma camada (sem o nome dela)."""
    if res["situacao"] == "erro":
        return f"não consultada: {res['erro']}"
    cfg = config_camada(res["arquivo"])
    if cfg.get("uso_do_solo"):
        # v0.7.0: Murundus do grupo Uso do Solo
        if res["situacao"] == "nao_tem":
            if res.get("antiga"):
                return ("o SIGA não mostra murundus dentro do imóvel agora, mas a camada tem murundus de uma consulta "
                        "anterior (o limite do imóvel mudou?) - nada foi apagado, confira")
            return "não tem murundus no imóvel - camada não criada"
        qtd = f"{len(res['feicoes'])} polígono(s), {_ha_br(res['ha_dentro'], 4)} ha dentro do imóvel"
        acao = res.get("acao") or ""
        if acao == "mantida":
            return (f"{qtd} no SIGA, mas a camada Murundus já tem desenho feito à mão (ou está em edição) - "
                    "não foi substituída")
        if acao == "sem_mudanca":
            return f"{qtd} - camada Murundus (Uso do Solo) já estava atualizada"
        return f"{qtd} - gravados na camada Murundus (Uso do Solo)"
    if res["situacao"] == "nao_tem":
        if cfg["recortar"]:
            return "não tem no imóvel - camada não criada"
        return f"nenhuma UC no imóvel nem a até {_ha_br(res.get('raio_km', raio_uc_km()), 0)} km - camada não criada"
    if cfg["recortar"]:
        return (f"{len(res['feicoes'])} polígono(s), {_ha_br(res['ha_dentro'], 4)} ha dentro do imóvel "
                "(só a parte de dentro)")
    if res["nomes"]:
        sob = f"sobrepõe o imóvel: {'; '.join(res['nomes'])} ({_ha_br(res['ha_dentro'], 4)} ha)"
    else:
        sob = "nenhuma sobrepõe o imóvel"
    perto = f"; {res['perto']} perto (até {_ha_br(res.get('raio_km', raio_uc_km()), 0)} km)" if res["perto"] else ""
    return f"{len(res['feicoes'])} UC inteira(s) - {sob}{perto}"


def resumo(resultados):
    return [f"{NOMES.get(r['arquivo'], r['arquivo'])}: {linha_resultado(r)}" for r in resultados]


def mudou_algo(res):
    """A consulta criou ou trocou o conteúdo de alguma camada (para a mensagem automática não repetir o mesmo aviso)."""
    return res.get("situacao") == "tem" and res.get("acao") not in ("sem_mudanca",)


def camadas_semad_no_projeto():
    return [c for c in QgsProject.instance().mapLayers().values() if str(c.customProperty(PROPRIEDADE, "") or "")]
