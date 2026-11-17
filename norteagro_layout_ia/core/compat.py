# -*- coding: utf-8 -*-
"""Compatibilidade entre versões do QGIS: 3.22 (LTR mais antiga em uso) até 3.44, e QGIS 4 (Qt6).

O QGIS foi mudando onde ficam os enums (QgsWkbTypes.PolygonGeometry -> Qgis.GeometryType.Polygon na 3.30,
QgsMapLayerProxyModel.PolygonLayer -> Qgis.LayerFilter.PolygonLayer na 3.34...) e o Qt6 tirou QVariant.String,
mudou QAction de lugar etc. Aqui cada valor é procurado do jeito novo e, se não existir, do jeito antigo.
O plugin usa só os nomes deste módulo para essas coisas.
"""
from qgis.core import Qgis, QgsField, QgsMapLayer, QgsUnitTypes, QgsVectorFileWriter, QgsWkbTypes

try:
    from qgis.core import QgsVectorDataProvider
except ImportError:  # pragma: no cover
    QgsVectorDataProvider = None
try:
    from qgis.core import QgsMapLayerProxyModel
except ImportError:  # pragma: no cover
    QgsMapLayerProxyModel = None
try:
    from qgis.core import QgsPalLayerSettings
except ImportError:  # pragma: no cover
    QgsPalLayerSettings = None

VERSAO = int(getattr(Qgis, "QGIS_VERSION_INT", 0) or 0)


def _primeiro(*opcoes):
    for f in opcoes:
        try:
            v = f()
        except Exception:
            continue
        if v is not None:
            return v
    return None


# --------------------------------------------------------------- tipos de geometria
GEOM_PONTO = _primeiro(lambda: Qgis.GeometryType.Point, lambda: QgsWkbTypes.PointGeometry)
GEOM_LINHA = _primeiro(lambda: Qgis.GeometryType.Line, lambda: QgsWkbTypes.LineGeometry)
GEOM_POLIGONO = _primeiro(lambda: Qgis.GeometryType.Polygon, lambda: QgsWkbTypes.PolygonGeometry)

WKB_PONTO = _primeiro(lambda: Qgis.WkbType.Point, lambda: QgsWkbTypes.Point)
WKB_POLIGONO = _primeiro(lambda: Qgis.WkbType.Polygon, lambda: QgsWkbTypes.Polygon)
WKB_MULTIPONTO = _primeiro(lambda: Qgis.WkbType.MultiPoint, lambda: QgsWkbTypes.MultiPoint)
WKB_MULTILINHA = _primeiro(lambda: Qgis.WkbType.MultiLineString, lambda: QgsWkbTypes.MultiLineString)
WKB_MULTIPOLIGONO = _primeiro(lambda: Qgis.WkbType.MultiPolygon, lambda: QgsWkbTypes.MultiPolygon)
WKB_COLECAO = _primeiro(lambda: Qgis.WkbType.GeometryCollection, lambda: QgsWkbTypes.GeometryCollection)

# --------------------------------------------------------------- unidades
UNID_METROS = _primeiro(lambda: Qgis.DistanceUnit.Meters, lambda: QgsUnitTypes.DistanceMeters)
UNID_HECTARES = _primeiro(lambda: Qgis.AreaUnit.Hectares, lambda: QgsUnitTypes.AreaHectares)
UNID_LAYOUT_MM = _primeiro(lambda: Qgis.LayoutUnit.Millimeters, lambda: QgsUnitTypes.LayoutMillimeters)
UNID_RENDER_PONTOS = _primeiro(lambda: Qgis.RenderUnit.Points, lambda: QgsUnitTypes.RenderPoints)

# --------------------------------------------------------------- camadas
CAMADA_VETOR = _primeiro(lambda: Qgis.LayerType.Vector, lambda: QgsMapLayer.VectorLayer)
CAMADA_RASTER = _primeiro(lambda: Qgis.LayerType.Raster, lambda: QgsMapLayer.RasterLayer)

FILTRO_PONTO = _primeiro(lambda: Qgis.LayerFilter.PointLayer, lambda: QgsMapLayerProxyModel.Filter.PointLayer,
                         lambda: QgsMapLayerProxyModel.PointLayer)
FILTRO_LINHA = _primeiro(lambda: Qgis.LayerFilter.LineLayer, lambda: QgsMapLayerProxyModel.Filter.LineLayer,
                         lambda: QgsMapLayerProxyModel.LineLayer)
FILTRO_POLIGONO = _primeiro(lambda: Qgis.LayerFilter.PolygonLayer, lambda: QgsMapLayerProxyModel.Filter.PolygonLayer,
                            lambda: QgsMapLayerProxyModel.PolygonLayer)
FILTRO_VETOR = _primeiro(lambda: Qgis.LayerFilter.VectorLayer, lambda: QgsMapLayerProxyModel.Filter.VectorLayer,
                         lambda: QgsMapLayerProxyModel.VectorLayer)

SIMBOLOGIA_POR_FEICAO = _primeiro(lambda: Qgis.FeatureSymbologyExport.PerFeature,
                                  lambda: QgsVectorFileWriter.SymbologyExport.FeatureSymbology,
                                  lambda: QgsVectorFileWriter.FeatureSymbology)
ROTULO_SOBRE_PONTO = _primeiro(lambda: Qgis.LabelPlacement.OverPoint,
                               lambda: QgsPalLayerSettings.Placement.OverPoint,
                               lambda: QgsPalLayerSettings.OverPoint)

CAP_MUDAR_GEOMETRIA = _primeiro(lambda: Qgis.VectorProviderCapability.ChangeGeometries,
                                lambda: QgsVectorDataProvider.Capability.ChangeGeometries,
                                lambda: QgsVectorDataProvider.ChangeGeometries)
CAP_APAGAR_FEICOES = _primeiro(lambda: Qgis.VectorProviderCapability.DeleteFeatures,
                               lambda: QgsVectorDataProvider.Capability.DeleteFeatures,
                               lambda: QgsVectorDataProvider.DeleteFeatures)

# --------------------------------------------------------------- mensagens
MSG_INFO = _primeiro(lambda: Qgis.MessageLevel.Info, lambda: Qgis.Info)
MSG_AVISO = _primeiro(lambda: Qgis.MessageLevel.Warning, lambda: Qgis.Warning)
MSG_CRITICO = _primeiro(lambda: Qgis.MessageLevel.Critical, lambda: Qgis.Critical)
MSG_SUCESSO = _primeiro(lambda: Qgis.MessageLevel.Success, lambda: Qgis.Success)


def tem_capacidade(capacidades, capacidade):
    try:
        return bool(capacidades & capacidade)
    except Exception:
        try:
            return bool(int(capacidades) & int(capacidade))
        except Exception:
            return False


# --------------------------------------------------------------- geometria
def tornar_valida(geom):
    """makeValid pelo método Structure (3.28+), que não abre buracos; nas versões antigas, o makeValid simples."""
    try:
        return geom.makeValid(Qgis.MakeValidMethod.Structure, False)
    except Exception:
        pass
    try:
        return geom.makeValid()
    except Exception:
        return geom.buffer(0, 5)


def parametros_grade(tamanho):
    """QgsGeometryParameters com snap-rounding (3.28+). Nas versões antigas devolve None e as operações
    rodam sem grade (o plugin já trata None)."""
    try:
        from qgis.core import QgsGeometryParameters
        p = QgsGeometryParameters()
        p.setGridSize(float(tamanho))
        return p
    except Exception:
        return None


# --------------------------------------------------------------- campos (Qt6 tirou QVariant.String)
def _tipo_campo(nome):
    if VERSAO >= 33800:
        try:
            from qgis.PyQt.QtCore import QMetaType
            return {"texto": QMetaType.Type.QString, "inteiro": QMetaType.Type.Int,
                    "real": QMetaType.Type.Double}[nome]
        except Exception:
            pass
    from qgis.PyQt.QtCore import QVariant
    return {"texto": QVariant.String, "inteiro": QVariant.Int, "real": QVariant.Double}[nome]


CAMPO_TEXTO = _tipo_campo("texto")
CAMPO_INTEIRO = _tipo_campo("inteiro")
CAMPO_REAL = _tipo_campo("real")


def campo(nome, tipo):
    return QgsField(nome, tipo)


# --------------------------------------------------------------- Qt (QAction e QShortcut foram para o QtGui no Qt6)
try:
    from qgis.PyQt.QtGui import QAction, QShortcut  # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction, QShortcut  # Qt5


def executar_dialogo(dialogo):
    """exec() existe nos dois; exec_() só no Qt5."""
    return dialogo.exec()


def categorias_sem_propriedades():
    """Todas as categorias de estilo menos as propriedades personalizadas (para salvar o .qml)."""
    from qgis.core import QgsMapLayer
    try:
        return QgsMapLayer.StyleCategories(int(QgsMapLayer.StyleCategory.AllStyleCategories) &
                                           ~int(QgsMapLayer.StyleCategory.CustomProperties))
    except Exception:
        pass
    try:  # Qt6: flags são enum.Flag
        return QgsMapLayer.StyleCategory.AllStyleCategories & ~QgsMapLayer.StyleCategory.CustomProperties
    except Exception:
        return QgsMapLayer.StyleCategory.AllStyleCategories


def aceito(resultado):
    """True se o diálogo foi aceito. No Qt6 exec() devolve int e QDialog.DialogCode.Accepted é enum."""
    try:
        return int(resultado) == 1
    except Exception:
        return getattr(resultado, "value", resultado) == 1
