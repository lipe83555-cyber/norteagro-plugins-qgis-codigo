# -*- coding: utf-8 -*-
"""Operações reutilizáveis de conteúdo, backup e remoção segura de camadas."""
from . import compat
import glob
import os
from datetime import datetime

from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
    QgsGeometry, QgsProject, QgsVectorLayer, QgsWkbTypes,
)


def fonte_camada(camada):
    """Caminho real do provider, compatível com fontes OGR com sufixos |... ."""
    try:
        bruto = str(camada.dataProvider().dataSourceUri() or "") if camada and camada.dataProvider() else ""
        if not bruto and camada:
            bruto = str(camada.source() or "")
        # v0.7.0: camada aberta pela PASTA ("pasta|layername=X") -> o arquivo X.shp de dentro dela
        return os.path.abspath(compat.arquivo_da_fonte(bruto)) if bruto else ""
    except Exception:
        return ""


def codigo_tipo_geometria(camada):
    """Retorna P/L/Pt para a família geométrica da camada."""
    if not isinstance(camada, QgsVectorLayer):
        return ""
    geom = camada.geometryType()
    if geom == compat.GEOM_POLIGONO:
        return "P"
    if geom == compat.GEOM_LINHA:
        return "L"
    if geom == compat.GEOM_PONTO:
        return "Pt"
    return ""


def tipos_compativeis(camada, tipo_destino):
    return codigo_tipo_geometria(camada) == str(tipo_destino or "")


def metricas_camada(camada, srid):
    """Número de feições e área plana em ha no SRC informado, como no fluxo Substituir."""
    if not isinstance(camada, QgsVectorLayer):
        return 0, 0.0
    quantidade = int(camada.featureCount())
    if quantidade < 0:  # v3.9.4: KML e alguns provedores devolvem -2 (desconhecido)
        quantidade = sum(1 for _ in camada.getFeatures())
    if camada.geometryType() != compat.GEOM_POLIGONO:
        return quantidade, 0.0
    alvo = QgsCoordinateReferenceSystem(srid)
    if not alvo.isValid():
        return quantidade, 0.0
    transformacao = QgsCoordinateTransform(camada.crs(), alvo, QgsProject.instance().transformContext())
    area = 0.0
    for feat in camada.getFeatures():
        if not feat.hasGeometry():
            continue
        geom = QgsGeometry(feat.geometry())
        try:
            if camada.crs() != alvo:
                geom.transform(transformacao)
            area += geom.area()
        except Exception:
            continue
    return quantidade, area / 10000.0


def backup_shapefile(camada):
    """Copia todos os sidecars do SHP para _backup/AAAA-MM-DD_HHMMSS/."""
    if not isinstance(camada, QgsVectorLayer):
        raise RuntimeError("Camada de destino inválida para backup.")
    shp = fonte_camada(camada)
    if not shp or not os.path.isfile(shp):
        raise RuntimeError("O arquivo de destino não foi encontrado para o backup.")
    pasta = os.path.dirname(shp)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino = os.path.join(pasta, "_backup", carimbo)
    n = 2
    while os.path.exists(destino):  # v3.9.4: dois backups no mesmo segundo não se sobrescrevem
        destino = os.path.join(pasta, "_backup", f"{carimbo}_{n}"); n += 1
    os.makedirs(destino, exist_ok=True)
    base = os.path.splitext(shp)[0]
    copiados = 0
    for origem in glob.glob(base + ".*"):
        if os.path.isfile(origem):
            import shutil
            shutil.copy2(origem, os.path.join(destino, os.path.basename(origem)))
            copiados += 1
    if not copiados:
        raise RuntimeError("Nenhum arquivo do Shapefile foi encontrado para o backup.")
    return destino


def substituir_conteudo(destino, origem, corrigir=True, criar_backup=True, ignorar_sem_geometria=False):
    """Substitui feições na MESMA camada de destino, com rollback e backup opcional.

    ``ignorar_sem_geometria`` é usado pela padronização: registros nulos/vazios não
    são copiados para a nova camada padrão. O fluxo tradicional de Substituir mantém
    o comportamento anterior por padrão.
    """
    if not isinstance(destino, QgsVectorLayer) or not isinstance(origem, QgsVectorLayer):
        raise RuntimeError("Origem e destino precisam ser camadas vetoriais.")
    if codigo_tipo_geometria(destino) != codigo_tipo_geometria(origem):
        raise RuntimeError("O tipo de geometria da origem é incompatível com o destino.")
    if destino.id() == origem.id():
        raise RuntimeError("A camada de origem não pode ser a própria camada de destino.")
    if destino.isEditable():
        if destino.isModified():
            raise RuntimeError("A camada de destino possui edições não salvas. Salve ou reverta antes de continuar.")
        destino.rollBack()

    backup = backup_shapefile(destino) if criar_backup else ""
    iniciou = False
    try:
        fonte = origem
        if corrigir and origem.geometryType() != compat.GEOM_PONTO:
            from qgis import processing
            fonte = processing.run(
                "native:fixgeometries",
                {"INPUT": origem, "METHOD": 1, "OUTPUT": "TEMPORARY_OUTPUT"},
            )["OUTPUT"]
        transformacao = QgsCoordinateTransform(fonte.crs(), destino.crs(), QgsProject.instance().transformContext())
        if not destino.startEditing():
            raise RuntimeError("Não foi possível iniciar a edição da camada de destino.")
        iniciou = True
        ids = [f.id() for f in destino.getFeatures()]
        if ids and not destino.deleteFeatures(ids):
            raise RuntimeError("Falha ao apagar as feições antigas.")
        indice_id = destino.fields().indexOf("id")
        sequencia = 1
        ignoradas_sem_geometria = 0
        for feat in fonte.getFeatures():
            tem_geom = feat.hasGeometry()
            if tem_geom:
                try:
                    tem_geom = not feat.geometry().isNull() and not feat.geometry().isEmpty()
                except Exception:
                    tem_geom = False
            if ignorar_sem_geometria and not tem_geom:
                ignoradas_sem_geometria += 1
                continue
            novo = QgsFeature(destino.fields())
            if tem_geom:
                geom = QgsGeometry(feat.geometry())
                if fonte.crs() != destino.crs():
                    geom.transform(transformacao)
                if QgsWkbTypes.isMultiType(destino.wkbType()) and not geom.isMultipart():
                    geom.convertToMultiType()
                novo.setGeometry(geom)
            if indice_id >= 0:
                novo.setAttribute(indice_id, sequencia)
            if not destino.addFeature(novo):
                raise RuntimeError(f"Falha ao adicionar a feição {sequencia}.")
            sequencia += 1
        if not destino.commitChanges():
            erros = "; ".join(destino.commitErrors())
            destino.rollBack(); iniciou = False
            raise RuntimeError("Falha no commit: " + erros)
        iniciou = False
        return {"backup": backup, "feicoes": int(destino.featureCount()), "sem_geometria_ignoradas": ignoradas_sem_geometria}
    except Exception:
        if iniciou and destino.isEditable():
            destino.rollBack()
        raise


def remover_camada_segura(plugin, camada, mover_interna=True, instante=None):
    """Remove do projeto; move apenas dados pertencentes à pasta do mapa para _apagados."""
    if not isinstance(camada, QgsVectorLayer):
        return {"movida": False, "removida": False, "falha": "Camada vetorial inválida.", "destino": ""}
    projeto = QgsProject.instance()
    pasta_mapa, _ = plugin.memoria_basica()
    raiz_shp = os.path.join(pasta_mapa, "shapefiles") if pasta_mapa else ""
    fonte = plugin._fonte(camada)
    arquivo = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
    if not arquivo and fonte.lower().endswith(".shp"):
        arquivo = os.path.splitext(os.path.basename(fonte))[0].upper()
    interno = bool(fonte and raiz_shp and plugin._dentro(fonte, raiz_shp))
    pasta_fonte = os.path.dirname(fonte) if fonte else ""
    pasta_camada = os.path.basename(pasta_fonte) if pasta_fonte else (arquivo or "CAMADA")
    kml_raiz = plugin.kml.diretorio_kml(camada) if hasattr(plugin, "kml") else ""
    kml_novo = plugin.kml.caminho_kml(camada) if hasattr(plugin, "kml") else ""
    kml_subpasta = os.path.join(kml_raiz, pasta_camada) if kml_raiz and pasta_camada else ""
    kml_solto = os.path.join(kml_raiz, arquivo + ".kml") if kml_raiz and arquivo else ""

    try:
        plugin.kml.desconectar(camada.id())
        if camada.isEditable():
            camada.rollBack()
        projeto.removeMapLayer(camada.id())
        QApplication.processEvents()
    except Exception as exc:
        return {"movida": False, "removida": False, "falha": str(exc), "destino": ""}

    if not (interno and mover_interna):
        return {"movida": False, "removida": True, "falha": "", "destino": "", "externa": True}

    instante = instante or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino_raiz = os.path.join(pasta_mapa, "_apagados", instante)
    destino_shp = os.path.join(destino_raiz, "shapefiles", pasta_camada)
    destino_kml = os.path.join(destino_raiz, "kml", pasta_camada)
    try:
        os.makedirs(os.path.dirname(destino_shp), exist_ok=True)
        # Pasta normal da camada: move inteira, preservando QML e _backup.
        if pasta_fonte and os.path.normcase(os.path.abspath(pasta_fonte)) != os.path.normcase(os.path.abspath(raiz_shp)):
            ok, erro = plugin._mover_com_retry(pasta_fonte, destino_shp)
            if not ok:
                raise RuntimeError(erro)
        else:
            # Compatibilidade defensiva para SHP antigo colocado diretamente em shapefiles/.
            os.makedirs(destino_shp, exist_ok=True)
            base = os.path.splitext(fonte)[0]
            for origem in [p for p in glob.glob(base + ".*") if os.path.isfile(p)]:
                ok, erro = plugin._mover_com_retry(origem, os.path.join(destino_shp, os.path.basename(origem)))
                if not ok:
                    raise RuntimeError(erro)

        # Move a subpasta KML correspondente ao mesmo carimbo. KML legado solto também é preservado.
        if kml_subpasta and os.path.isdir(kml_subpasta):
            os.makedirs(os.path.dirname(destino_kml), exist_ok=True)
            ok, erro = plugin._mover_com_retry(kml_subpasta, destino_kml)
            if not ok:
                raise RuntimeError("KML: " + erro)
        elif kml_novo and os.path.isfile(kml_novo):
            os.makedirs(destino_kml, exist_ok=True)
            ok, erro = plugin._mover_com_retry(kml_novo, os.path.join(destino_kml, os.path.basename(kml_novo)))
            if not ok:
                raise RuntimeError("KML: " + erro)
        elif kml_solto and os.path.isfile(kml_solto):
            os.makedirs(destino_kml, exist_ok=True)
            ok, erro = plugin._mover_com_retry(kml_solto, os.path.join(destino_kml, os.path.basename(kml_solto)))
            if not ok:
                raise RuntimeError("KML legado: " + erro)
        return {"movida": True, "removida": True, "falha": "", "destino": destino_raiz, "externa": False}
    except Exception as exc:
        plugin.log(f"Falha ao mover camada para _apagados: {exc}")
        return {"movida": False, "removida": True, "falha": str(exc), "destino": destino_raiz, "externa": False}

