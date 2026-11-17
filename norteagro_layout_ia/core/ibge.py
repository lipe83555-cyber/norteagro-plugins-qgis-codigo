# -*- coding: utf-8 -*-
"""Malha municipal do IBGE para o mapa de localização.

Acha o município onde o imóvel está pela posição (não pelo nome digitado):
1) camadas de municípios do projeto e a malha de Goiás que acompanha o plugin;
2) se o imóvel estiver fora delas, baixa a malha do IBGE (API de malhas, servicodados.ibge.gov.br) do estado
   do imóvel e dos estados vizinhos que aparecem no mapa, com nome e UF de cada município.

O que é baixado fica guardado (pasta do perfil do QGIS / norteagro_modelos / ibge) e é reaproveitado, então
na segunda vez funciona sem internet.
"""

from . import compat
import gzip
import json
import os

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
                       QgsFeatureRequest, QgsField, QgsFields, QgsGeometry, QgsJsonUtils, QgsProject,
                       QgsRectangle, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)

API = "https://servicodados.ibge.gov.br/api"
SIRGAS = QgsCoordinateReferenceSystem("EPSG:4674")
NOME_CAMADA = "Municípios (IBGE)"


def pasta_cache():
    p = os.path.join(QgsApplication.qgisSettingsDirPath(), "norteagro_modelos", "ibge")
    os.makedirs(p, exist_ok=True)
    return p


def _baixar_json(url, arquivo=None):
    """JSON da API do IBGE (vem compactado em gzip), guardado em disco quando 'arquivo' é dado."""
    if arquivo and os.path.isfile(arquivo):
        with open(arquivo, encoding="utf-8") as f:
            return json.load(f)
    from . import imagens
    bruto = imagens._requisitar(url)
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)
    dados = json.loads(bruto.decode("utf-8"))
    if arquivo:
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f)
    return dados


def _geometrias(geojson):
    """[(codarea, QgsGeometry em SIRGAS 2000)] de um GeoJSON da API de malhas."""
    saida = []
    for feat in geojson.get("features", []):
        g = QgsJsonUtils.geometryFromGeoJson(json.dumps(feat.get("geometry")))
        if g is None or g.isEmpty():
            continue
        saida.append((str(feat.get("properties", {}).get("codarea", "")), g))
    return saida


def _ufs():
    """[(codigo, sigla, nome, geometria)] dos estados."""
    cache = pasta_cache()
    malha = _baixar_json(f"{API}/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima"
                         f"&intrarregiao=UF", os.path.join(cache, "ufs.geojson"))
    nomes = {str(e["id"]): (e["sigla"], e["nome"])
             for e in _baixar_json(f"{API}/v1/localidades/estados", os.path.join(cache, "ufs_nomes.json"))}
    return [(cod, nomes.get(cod, ("", ""))[0], nomes.get(cod, ("", ""))[1], g) for cod, g in _geometrias(malha)]


def _municipios_da_uf(cod_uf):
    """[(cd_mun, nome, geometria)] dos municípios de um estado."""
    cache = pasta_cache()
    malha = _baixar_json(f"{API}/v3/malhas/estados/{cod_uf}?formato=application/vnd.geo+json"
                         f"&qualidade=intermediaria&intrarregiao=municipio",
                         os.path.join(cache, f"municipios_{cod_uf}.geojson"))
    nomes = {str(m["id"]): m["nome"] for m in _baixar_json(f"{API}/v1/localidades/estados/{cod_uf}/municipios",
                                                           os.path.join(cache, f"municipios_{cod_uf}_nomes.json"))}
    return [(cod, nomes.get(cod, cod), g) for cod, g in _geometrias(malha)]


def geometria_imovel(camada):
    """Geometria do imóvel (união das feições) em SIRGAS 2000."""
    partes = [f.geometry() for f in camada.getFeatures() if f.hasGeometry()]
    if not partes:
        return None
    g = QgsGeometry.unaryUnion(partes)
    if camada.crs() != SIRGAS:
        g.transform(QgsCoordinateTransform(camada.crs(), SIRGAS, QgsProject.instance().transformContext()))
    return g


def municipio_na_camada(camada, geom_imovel_4674):
    """Feição da camada de municípios com a maior parte do imóvel (ou None se o imóvel estiver fora)."""
    g = QgsGeometry(geom_imovel_4674)
    if camada.crs() != SIRGAS:
        g.transform(QgsCoordinateTransform(SIRGAS, camada.crs(), QgsProject.instance().transformContext()))
    melhor, area = None, 0.0
    req = QgsFeatureRequest().setFilterRect(g.boundingBox())
    for f in camada.getFeatures(req):
        if not f.hasGeometry():
            continue
        inter = f.geometry().intersection(g)
        a = inter.area() if inter is not None and not inter.isEmpty() else 0.0
        if a <= 0 and f.geometry().contains(g.centroid()):
            a = 1e-12
        if a > area:
            melhor, area = f, a
    return melhor


def malha_para_imovel(geom_imovel_4674, margem=0.39):
    """Baixa (ou lê do disco) a malha municipal do estado do imóvel e dos estados vizinhos que entram no
    enquadramento do mapa de localização. Retorna a camada (GeoPackage guardado) já no projeto, no grupo de
    apoio, ou None se o imóvel não estiver no Brasil."""
    centro = geom_imovel_4674.centroid()
    ufs = _ufs()
    uf_imovel = next((u for u in ufs if u[3].contains(centro) or u[3].intersects(geom_imovel_4674)), None)
    if uf_imovel is None:
        return None
    municipios = {u[0]: _municipios_da_uf(u[0]) for u in [uf_imovel]}
    # município do imóvel -> área do mapa -> estados vizinhos que aparecem nela
    mun = max(((c, n, g) for c, n, g in municipios[uf_imovel[0]] if g.intersects(geom_imovel_4674)),
              key=lambda t: t[2].intersection(geom_imovel_4674).area(), default=None)
    if mun is not None:
        caixa = QgsRectangle(mun[2].boundingBox())
        caixa.grow(max(caixa.width(), caixa.height()) * margem)
        area_mapa = QgsGeometry.fromRect(caixa)
        for u in ufs:
            if u[0] not in municipios and u[3].intersects(area_mapa):
                municipios[u[0]] = _municipios_da_uf(u[0])
    siglas = {u[0]: u[1] for u in ufs}
    codigos = "_".join(sorted(municipios))
    arquivo = os.path.join(pasta_cache(), f"municipios_ibge_{codigos}.gpkg")
    if not os.path.isfile(arquivo):
        campos = QgsFields()
        campos.append(QgsField("CD_MUN", compat.CAMPO_TEXTO))
        campos.append(QgsField("NM_MUN", compat.CAMPO_TEXTO))
        campos.append(QgsField("SIGLA_UF", compat.CAMPO_TEXTO))
        mem = QgsVectorLayer("MultiPolygon?crs=EPSG:4674", "municipios", "memory")
        mem.dataProvider().addAttributes(campos)
        mem.updateFields()
        feicoes = []
        for cod_uf, lista in municipios.items():
            for cod, nome, g in lista:
                f = QgsFeature(mem.fields())
                g = QgsGeometry(g)
                g.convertToMultiType()
                f.setGeometry(g)
                f.setAttributes([cod, nome, siglas.get(cod_uf, "")])
                feicoes.append(f)
        mem.dataProvider().addFeatures(feicoes)
        op = QgsVectorFileWriter.SaveVectorOptions()
        op.driverName = "GPKG"
        op.layerName = "municipios"
        QgsVectorFileWriter.writeAsVectorFormatV3(mem, arquivo, QgsProject.instance().transformContext(), op)
    return _no_projeto(arquivo)


def _no_projeto(arquivo):
    from .. import builder
    projeto = QgsProject.instance()
    fonte = arquivo + "|layername=municipios"
    for c in builder._camadas_do_grupo_apoio(projeto):
        if os.path.normcase(c.source()) == os.path.normcase(fonte):
            return c
    cam = QgsVectorLayer(fonte, NOME_CAMADA, "ogr")
    if not cam.isValid():
        return None
    projeto.addMapLayer(cam, False)
    no = builder._grupo_apoio(projeto).addLayer(cam)
    no.setItemVisibilityChecked(False)
    return cam


def tipo_poligono(camada):
    return isinstance(camada, QgsVectorLayer) and camada.geometryType() == compat.GEOM_POLIGONO
