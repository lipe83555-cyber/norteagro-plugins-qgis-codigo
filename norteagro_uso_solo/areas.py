# -*- coding: utf-8 -*-
"""Cálculo de áreas, reconhecimento lógico e conferência geométrica.

Toda correção/recorte desta unidade ocorre apenas em camadas temporárias/memória.
Nenhum SHP, DBF, SHX, QML ou KML de entrada é alterado pelo cálculo.
"""
from . import compat
import getpass
import os
import re
from datetime import datetime

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    Qgis, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsDistanceArea, QgsFeature, QgsField, QgsFillSymbol, QgsGeometry, QgsPalLayerSettings,
    QgsProcessingContext, QgsProcessingFeedback, QgsProject, QgsRendererCategory,
    QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes,
)

from .catalogo import lugar_quadro, QUADRO_DO_LUGAR
from .catalogo import (
    FECHAMENTO_PADRAO, MUNICIPIOS_GOIAS, apelidos_para_indice, configuracao_geometrica,
    extras_projeto,
)
from .reconhecimento import (
    chaves_texto, melhor_semelhanca, nome_parece_referencia, normalizar_chave,
)
from . import topologia as topo

# Camadas usadas diretamente nos quadros e operações especiais.
# v3.9.6: linhas padrão dos quadros que só somam (base para descontar as personalizadas).
BASE_QUADROS_SOMADOS = {
    "Passivos ambientais": ("AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"),
    "Área Hidrográfica": ("HIDROGRAFIA", "BARRAGEM", "CACIMBA", "TANQUE", "LAGOA_NATURAL"),
    "Área Total de Compensação": ("COMPENSACAO_DANOS", "COMPENSACAO_FLORESTAL", "AREA_RECOMPOSICAO"),
}

USADAS_NOS_QUADROS = {
    "RESERVA_LEGAL", "APP_PRESERVADA", "APP_CONSOLIDADA",
    "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019", "HIDROGRAFIA",
    "BARRAGEM", "CACIMBA", "TANQUE", "LAGOA_NATURAL", "AREA_SUPRIMIDA_ANTES_2019",
    "AREA_SUPRIMIDA_DEPOIS_2019", "AREA_CONSOLIDADA", "AREA_DE_VEGETACAO",
    "AREA_DO_IMOVEL", "SUPRESSAO_PASSIVEL_ANTES_2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019",
    "COMPENSACAO_DANOS", "COMPENSACAO_FLORESTAL", "AREA_RECOMPOSICAO",
    "RESERVA_SUPRIMIDA", "RESERVA_SUPRIMIDA_ANTES_2019", "RESERVA_SUPRIMIDA_DEPOIS_2019",
}
REQUERIDAS = (USADAS_NOS_QUADROS - {"RESERVA_SUPRIMIDA_ANTES_2019", "RESERVA_SUPRIMIDA_DEPOIS_2019"}) | {"APP_TOTAL"}
HIDRO_FEICOES = {
    "BARRAGEM": "Barramento", "CACIMBA": "Cacimba",
    "TANQUE": "Tanque", "LAGOA_NATURAL": "Lagoa Natural",
}
# v0.3.0: a hidrografia é a única que pode passar do limite do imóvel (rio, nascente, barramento...). No quadro
# conta só a parte de dentro, mas o trecho de fora não é erro de desenho.
HIDRO_PODE_SAIR = {"HIDROGRAFIA", "NASCENTE", "BARRAGEM", "CACIMBA", "TANQUE", "LAGOA_NATURAL", "VEREDAS"}


# v0.3.0: água (rio, barramento, tanque, cacimba, lagoa) não é consolidada nem vegetação. Quando há água dentro do
# imóvel ela entra sozinha no quadro "Áreas Totais do Imóvel" (linha Hidrografia), com prioridade sobre as coberturas;
# assim, tirando o rio da Consolidada, o total continua fechando e não sobra "Área sem classificação".
# Ordem: a feição específica (barramento...) antes do rio, para não contar a mesma água duas vezes.
AGUA_FECHAMENTO = ["BARRAGEM", "TANQUE", "CACIMBA", "LAGOA_NATURAL", "HIDROGRAFIA"]
# v0.4.0: supressão é passivo (aconteceu no passado): se depois virou barragem/rio, continua suprimida.
# No fechamento ela vem antes da água; a água só ganha da Consolidada e da Vegetação.
SUPRESSAO_ANTES_DA_AGUA = ["AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"]
PREFIXO_FECH = "__FECH__"  # chave do valor da água DENTRO do fechamento (sem a parte que é suprimida)


def pode_sair_do_imovel(arquivo, indice=None):
    arquivo = str(arquivo or "").upper()
    if arquivo in HIDRO_PODE_SAIR:
        return True
    try:
        return lugar_quadro((indice or {}).get(arquivo)) == "HIDRO"
    except Exception:
        return False


VIA_PRIORIDADE = {"propriedade": 60, "manual": 50, "apelido": 40, "nome": 30, "semelhança": 20}
TOL_HA = 0.0001
TOL_PARTE_M2 = 1.0
# v0.4.0: nas conferências de cobertura (R1-R9), frestas menores que isto são ruído de arredondamento entre camadas
# (o quadro já soma à vizinha); só o que passa disso vira alerta.
MICRO_PARTE_M2 = 0.5


def _area_significativa(partes):
    """(ha, partes) só com as partes de pelo menos MICRO_PARTE_M2."""
    sig = [x for x in partes if float(x.get("area_m2") or 0.0) >= MICRO_PARTE_M2]
    return sum(float(x.get("area_m2") or 0.0) for x in sig) / 10000.0, sig
DENSIFICACAO_ELIPSOIDAL_M = 10.0
PROVEDORES_REFERENCIA = {
    "wfs", "wms", "xyz", "oapif", "arcgisfeatureserver", "vectortile", "memory",
}


def normalizar_nome_camada(nome):
    return normalizar_chave(nome)


def grupo_da_camada(camada):
    raiz = QgsProject.instance().layerTreeRoot()
    no = raiz.findLayer(camada.id())
    pai = no.parent() if no else None
    partes = []
    while pai is not None and pai is not raiz:
        if hasattr(pai, "name") and pai.name():
            partes.append(pai.name())
        pai = pai.parent() if hasattr(pai, "parent") else None
    return " / ".join(reversed(partes)) if partes else "Sem grupo"


def arquivo_fonte(camada):
    try:
        return str(camada.dataProvider().dataSourceUri()).split("|", 1)[0]
    except Exception:
        try:
            return str(camada.source()).split("|", 1)[0]
        except Exception:
            return ""


def chave_manual_camada(camada):
    fonte = arquivo_fonte(camada).strip()
    if fonte and (os.path.isabs(fonte) or re.match(r"^[A-Za-z]:[\\/]", fonte) or fonte.lower().endswith(".shp")):
        return os.path.normcase(os.path.normpath(fonte))
    return normalizar_chave(camada.name())


def _textos_camada(camada):
    textos = [camada.name()]
    fonte = arquivo_fonte(camada)
    if fonte:
        nome = os.path.splitext(os.path.basename(fonte))[0]
        pasta = os.path.basename(os.path.dirname(fonte))
        if nome:
            textos.append(nome)
        if pasta:
            textos.append(pasta)
    return textos


def contar_feicoes(camada):
    """featureCount() devolve -2 (desconhecido) em KML; conta de verdade nos arquivos locais."""
    try:
        if camada is None or not camada.isValid():
            return 0
        n = int(camada.featureCount())
        if n >= 0:
            return n
        if str(camada.providerType() or "").lower() not in ("ogr", "memory", "spatialite", "delimitedtext"):
            return n
        from qgis.core import QgsFeatureRequest
        req = QgsFeatureRequest().setNoAttributes()
        return sum(1 for _ in camada.getFeatures(req))
    except Exception:
        return 0


def _reconhecer_semantico(chaves, indice):
    """v3.9: supressão + (APP | RL | passível) + período, em qualquer ordem de palavras.

    Cobre "SUPRESSÃO APP APOS 2019" e os nomes longos dos KML do SIGA/SEMAD
    ("... PRESERVAÇÃO PERMANENTE ... ENTRE AS DATAS DE 22_07_2008 E 27_12_2019 ...").
    """
    for chave in chaves:
        tk = set(str(chave).upper().split("_"))
        if not (tk & {"SUPRIMIDA", "ANTROPIZADA"}):
            continue
        app = "APP" in tk or {"PRESERVACAO", "PERMANENTE"} <= tk
        rl = "RL" in tk or {"RESERVA", "LEGAL"} <= tk
        pas = "PASSIVEL" in tk
        if (app, rl, pas).count(True) != 1:
            continue
        depois = bool(tk & {"DEPOIS", "APOS"})
        antes = "ANTES" in tk or ("ENTRE" in tk and "2008" in tk)
        if depois and antes:
            continue
        if app:
            alvo = "APP_ANTROPIZADA_APOS_2019" if depois else "APP_ANTROPIZADA_ANTES_2019" if antes else "APP_SUPRIMIDA"
        elif pas:
            alvo = "SUPRESSAO_PASSIVEL_DEPOIS_2019" if depois else "SUPRESSAO_PASSIVEL_ANTES_2019" if antes else "SUPRESSAO_PASSIVEL_TOTAL"
        else:
            alvo = "RESERVA_SUPRIMIDA_DEPOIS_2019" if depois else "RESERVA_SUPRIMIDA_ANTES_2019" if antes else "RESERVA_SUPRIMIDA"
            if alvo not in indice:
                alvo = "RESERVA_SUPRIMIDA"
        if alvo in indice:
            return alvo
    return ""


def _tipo_geometria(camada):
    geom = camada.geometryType()
    if geom == compat.GEOM_POLIGONO:
        return "Polígono"
    if geom == compat.GEOM_LINHA:
        return "Linha"
    if geom == compat.GEOM_PONTO:
        return "Ponto"
    return "Outro"


def _dentro(caminho, pasta):
    try:
        if not caminho or not pasta:
            return False
        a = os.path.normcase(os.path.abspath(caminho))
        b = os.path.normcase(os.path.abspath(pasta))
        return os.path.commonpath([a, b]) == b
    except Exception:
        return False


def _palavras_referencias(refs):
    saida = []
    for item in refs or []:
        nome = item.get("nome") if isinstance(item, dict) else item
        tk = {x for x in normalizar_chave(nome).split("_") if x}
        if tk:
            saida.append((str(nome), tk))
    return saida


def _reconhecer_basico(camada, indice, alias_indice, tabela_apelidos, manuais, override=None, refs=None, explicitos=None):
    """v0.5.0: o reconhecimento de sempre; camada da SEMAD (grupo "SEMAD - SIGA" do catálogo: murundus, APP de relevo,
    UC) reconhecida por qualquer via vira referência - ela não entra no cálculo de áreas nem na correção."""
    r = _reconhecer_basico_0(camada, indice, alias_indice, tabela_apelidos, manuais, override, refs, explicitos)
    if str((r or {}).get("arquivo") or "").upper().startswith("SEMAD_"):
        return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False, "criterio":"SEMAD (SIGA)"}
    return r


def _reconhecer_basico_0(camada, indice, alias_indice, tabela_apelidos, manuais, override=None, refs=None, explicitos=None):
    """Ordem A1: referência textual > propriedade > manual > apelido > nome > semelhança.
    v0.1.1: nomes ensinados pelo usuário (apelidos do escritório e escolhas salvas no projeto)
    valem antes do filtro textual de referência - senão "Limite APP", "APP Município" etc. nunca calculariam."""
    if override:
        if override == "__REFERENCIA__":
            return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False}
        if override == "__IGNORAR__":
            return {"arquivo":"", "via":"ignorar", "razao":0.0, "referencia":False, "ignorar":True}
        if override in indice:
            return {"arquivo":override, "via":"manual", "razao":1.0, "referencia":False, "ignorar":False}

    try:
        if str(camada.customProperty("norteagro/conferencia", "") or "") == "1":
            return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False, "criterio":"conferência"}
        if str(camada.customProperty("norteagro/semad", "") or ""):
            # v0.5.0: camadas da SEMAD (SIGA) - murundus, APP de relevo, UC - são referência, não entram no cálculo
            return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False, "criterio":"SEMAD (SIGA)"}
    except Exception:
        pass

    textos = _textos_camada(camada)
    prop_cedo = str(camada.customProperty("norteagro/arquivo", "") or "").upper().strip()
    manual_cedo = str((manuais or {}).get(chave_manual_camada(camada), "") or "")
    if prop_cedo in indice:
        explicitos = None; manual_cedo = ""   # camada do plugin: a propriedade gravada decide (abaixo)
    if manual_cedo in indice:
        return {"arquivo":manual_cedo, "via":"manual", "razao":1.0, "referencia":False, "ignorar":False}
    if explicitos:
        for texto in textos:
            for chave in chaves_texto(texto):
                if chave in explicitos and explicitos[chave] in indice:
                    return {"arquivo":explicitos[chave], "via":"apelido", "razao":1.0, "referencia":False, "ignorar":False}
    if any(nome_parece_referencia(t, MUNICIPIOS_GOIAS) for t in textos):
        return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False, "criterio":"nome"}

    prop = str(camada.customProperty("norteagro/arquivo", "") or "").upper().strip()
    if prop in indice:
        return {"arquivo":prop, "via":"propriedade", "razao":1.0, "referencia":False, "ignorar":False}

    manual = str((manuais or {}).get(chave_manual_camada(camada), "") or "")
    if manual == "__REFERENCIA__":
        return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False, "criterio":"manual"}
    if manual == "__IGNORAR__":
        return {"arquivo":"", "via":"ignorar", "razao":0.0, "referencia":False, "ignorar":True}
    if manual in indice:
        return {"arquivo":manual, "via":"manual", "razao":1.0, "referencia":False, "ignorar":False}

    chaves = []
    for texto in textos:
        for chave in chaves_texto(texto):
            if chave not in chaves:
                chaves.append(chave)
    for chave in chaves:
        if chave in alias_indice:
            return {"arquivo":alias_indice[chave], "via":"apelido", "razao":1.0, "referencia":False, "ignorar":False}

    canon = {}
    for arq, entrada in indice.items():
        for chave in chaves_texto(arq) + chaves_texto(entrada.get("nome", "")):
            canon.setdefault(chave, arq)
    for chave in chaves:
        if chave in canon:
            return {"arquivo":canon[chave], "via":"nome", "razao":1.0, "referencia":False, "ignorar":False}

    # v3.9.5: lista de referências do escritório. Vem depois de propriedade, escolha
    # manual, apelido e nome exato do catálogo, e antes das regras aproximadas.
    if refs:
        palavras_camada = set()
        for chave in chaves:
            palavras_camada.update(x for x in chave.split("_") if x)
        for nome_ref, tk in refs:
            if tk <= palavras_camada:
                return {"arquivo":"", "via":"referência", "razao":0.0, "referencia":True, "ignorar":False,
                        "criterio":f"lista do escritório: {nome_ref}"}

    # v3.9.4: "Compensação por supressão em APP" é camada de COMPENSAÇÃO; as regras
    # aproximadas abaixo nunca podem levá-la para uma camada de supressão.
    palavras = set()
    for chave in chaves:
        palavras.update(str(chave).upper().split("_"))
    familia = {"COMPENSACAO", "RECOMPOSICAO"} & palavras
    def _compativel(arq_):
        return not familia or any(f in str(arq_).upper() for f in familia)

    arq = _reconhecer_semantico(chaves, indice) if not familia else ""
    if arq:
        return {"arquivo":arq, "via":"nome", "razao":1.0, "referencia":False, "ignorar":False}

    arq, r1, _ = melhor_semelhanca(chaves, indice, tabela_apelidos)
    if arq and _compativel(arq):
        return {"arquivo":arq, "via":"semelhança", "razao":r1, "referencia":False, "ignorar":False}
    arq = _reconhecer_por_palavras(chaves, canon, alias_indice)
    if arq and not _compativel(arq):
        arq = ""
    if arq:
        # Sugestão marcada como semelhança: aparece em amarelo para o técnico conferir.
        return {"arquivo":arq, "via":"semelhança", "razao":0.9, "referencia":False, "ignorar":False}
    return {"arquivo":"", "via":"não reconhecida", "razao":r1, "referencia":False, "ignorar":False}


def _reconhecer_por_palavras(chaves, canon, alias_indice):
    """v3.9.4: "hidrografia rio", "nascente gps" -> nome contém TODAS as palavras de uma
    camada do catálogo. Fica a candidata mais específica (mais palavras); empate entre
    camadas diferentes = ambíguo, não reconhece."""
    palavras = set()
    for chave in chaves:
        palavras.update(x for x in str(chave).upper().split("_") if x)
    if not palavras:
        return ""
    candidatos = {}
    for fonte in (canon, alias_indice or {}):
        for chave, arq in fonte.items():
            tk = {x for x in str(chave).upper().split("_") if x}
            if tk and tk <= palavras:
                candidatos[arq] = max(candidatos.get(arq, 0), len(tk))
    if not candidatos:
        return ""
    maior = max(candidatos.values())
    melhores = [a for a, n in candidatos.items() if n == maior]
    return melhores[0] if len(melhores) == 1 else ""


def _extensao_transformada(camada, alvo):
    try:
        ext = camada.extent()
        if not ext or ext.isEmpty():
            return None
        if camada.crs().isValid() and camada.crs() != alvo:
            tr = QgsCoordinateTransform(camada.crs(), alvo, QgsProject.instance().transformContext())
            ext = tr.transformBoundingBox(ext)
        return ext
    except Exception:
        return None


def _area_retangulo(ext):
    if not ext:
        return 0.0
    try:
        return max(0.0, float(ext.width())) * max(0.0, float(ext.height()))
    except Exception:
        return 0.0


def prever_reconhecimentos(camadas, srid, indice_catalogo, manuais=None, overrides=None):
    """Classifica sem Processing; catálogo reconhecido não vira referência por extensão/provedor."""
    tabela, alias_indice, ambiguos = apelidos_para_indice(indice_catalogo)
    overrides = overrides or {}
    try:
        from .catalogo import referencias_escritorio
        refs = _palavras_referencias(referencias_escritorio())
    except Exception:
        refs = []
    explicitos = {}
    try:
        from .catalogo import apelidos_escritorio
        for apelido in apelidos_escritorio():
            for chave in chaves_texto(apelido):
                if chave in alias_indice:
                    explicitos[chave] = alias_indice[chave]
    except Exception:
        explicitos = {}
    resultados = {}
    for camada in camadas:
        resultados[camada.id()] = _reconhecer_basico(
            camada, indice_catalogo, alias_indice, tabela, manuais or {}, overrides.get(camada.id()), refs, explicitos
        )

    alvo = QgsCoordinateReferenceSystem(srid) if srid else QgsCoordinateReferenceSystem()
    imoveis = [c for c in camadas if resultados[c.id()].get("arquivo") == "AREA_DO_IMOVEL"]
    area_imovel_bbox = 0.0
    if alvo.isValid() and imoveis:
        imovel = max(imoveis, key=lambda c: contar_feicoes(c))
        area_imovel_bbox = _area_retangulo(_extensao_transformada(imovel, alvo))

    for camada in camadas:
        r = resultados[camada.id()]
        # Itens A1 2-6 já reconhecidos não são referência pelos critérios espaciais/provedor.
        if r.get("arquivo") or r.get("referencia") or r.get("ignorar"):
            continue
        try:
            prov = str(camada.providerType() or "").lower()
        except Exception:
            prov = ""
        if prov in PROVEDORES_REFERENCIA:
            resultados[camada.id()] = {
                "arquivo":"", "via":"referência", "razao":0.0,
                "referencia":True, "ignorar":False, "criterio":"serviço/memória",
            }
            continue
        if alvo.isValid() and area_imovel_bbox > 0:
            ext = _extensao_transformada(camada, alvo)
            if _area_retangulo(ext) > 50.0 * area_imovel_bbox:
                resultados[camada.id()] = {
                    "arquivo":"", "via":"referência", "razao":0.0,
                    "referencia":True, "ignorar":False, "criterio":"extensão",
                }
    return resultados, ambiguos


def rotulo_reconhecimento(resultado, indice=None):
    if resultado.get("referencia"):
        return "referência - não calculada"
    if resultado.get("ignorar"):
        return "ignorada - não calculada"
    arquivo = resultado.get("arquivo", "")
    if arquivo:
        nome = str((indice or {}).get(arquivo, {}).get("nome") or arquivo)
        return f"{nome} ({arquivo}, via {resultado.get('via','nome')})"
    return "não reconhecida - não calculada"


def _medidor(srid, metodo, avisos):
    projeto = QgsProject.instance()
    d = QgsDistanceArea()
    d.setSourceCrs(QgsCoordinateReferenceSystem(srid), projeto.transformContext())
    if metodo.startswith("Elipsoidal"):
        ell = str(projeto.ellipsoid() or "")
        if not ell or ell.upper() == "NONE":
            ell = "EPSG:7019"
            avisos.append("Elipsoide padrão usado: EPSG:7019 (GRS80).")
        d.setEllipsoid(ell)
    else:
        ell = "NONE"
        d.setEllipsoid("NONE")
    return d, ell


def _partes_do_tipo(geom, tipo):
    """Mantém só as partes do tipo pedido (polígono ou linha).

    Interseções e diferenças entre polígonos vizinhos podem devolver coleções
    mistas (linhas e pontos onde os polígonos só se tocam). densifyByDistance
    do QGIS derruba o programa (access violation) com essas coleções, então
    pontos e linhas soltos são descartados antes de medir: não têm área.
    """
    if geom is None or geom.isNull() or geom.isEmpty():
        return None
    try:
        if QgsWkbTypes.geometryType(geom.wkbType()) == tipo and \
                QgsWkbTypes.flatType(geom.wkbType()) != compat.WKB_COLECAO:
            return QgsGeometry(geom)
        partes = []
        for parte in geom.asGeometryCollection():
            if parte is None or parte.isNull() or parte.isEmpty():
                continue
            if QgsWkbTypes.geometryType(parte.wkbType()) == tipo:
                partes.append(QgsGeometry(parte))
        if not partes:
            return None
        if len(partes) == 1:
            return partes[0]
        return QgsGeometry.collectGeometry(partes)
    except Exception:
        return None


def _densificar_geometria(geom, aplicar=False, tipo=None):
    """Densifica somente em memória. No método elipsoidal limita segmentos a 10 m."""
    if geom is None or geom.isNull() or geom.isEmpty():
        return QgsGeometry(geom) if geom is not None else geom
    if tipo is None:
        tipo = QgsWkbTypes.geometryType(geom.wkbType())
    copia = _partes_do_tipo(geom, tipo)
    if copia is None:
        return QgsGeometry()
    if not aplicar or tipo not in (compat.GEOM_POLIGONO, compat.GEOM_LINHA):
        return copia
    try:
        densa = copia.densifyByDistance(10)
        return densa if densa is not None and not densa.isNull() else copia
    except Exception:
        return copia


def _area_ha(d, geom, densificar=False):
    # v3.9: mede parte por parte, só polígonos válidos; densifica cada parte simples
    # (densificar coleções mistas derrubava o QGIS - ver _crash_log.txt).
    return topo.area_ha(d, geom, densificar)


def _comprimento_m(d, geom, densificar=False):
    if geom is None or geom.isNull() or geom.isEmpty():
        return 0.0
    medida = _densificar_geometria(geom, densificar, compat.GEOM_LINHA)
    if medida is None or medida.isNull() or medida.isEmpty():
        return 0.0
    return float(d.convertLengthMeasurement(d.measureLength(medida), compat.UNID_METROS))


def _reprojetar(camada, alvo, context, feedback):
    from qgis import processing
    return processing.run('native:reprojectlayer', {
        'INPUT': camada, 'TARGET_CRS': alvo, 'OUTPUT': 'TEMPORARY_OUTPUT'
    }, context=context, feedback=feedback)['OUTPUT']


def _corrigir(camada, context, feedback):
    from qgis import processing
    # v3.9: método Structure (1). O Linework (padrão) abre buracos onde o anel
    # se cruza e faz a área sumir sem aviso.
    try:
        return processing.run('native:fixgeometries', {
            'INPUT': camada, 'METHOD': 1, 'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']
    except Exception:
        return processing.run('native:fixgeometries', {
            'INPUT': camada, 'OUTPUT': 'TEMPORARY_OUTPUT'
        }, context=context, feedback=feedback)['OUTPUT']


def _dissolver(camada, context, feedback):
    # v3.9.12: uma feição só (já válida) dissolvida é ela mesma: não chama o Processamento.
    try:
        if camada is not None and camada.featureCount() == 1:
            f = next(camada.getFeatures())
            if f.hasGeometry() and f.geometry().isGeosValid():
                return camada
    except Exception:
        pass
    from qgis import processing
    return processing.run('native:dissolve', {
        'INPUT': camada, 'FIELD': [], 'OUTPUT': 'TEMPORARY_OUTPUT'
    }, context=context, feedback=feedback)['OUTPUT']


def _mesclar(camadas, alvo, context, feedback):
    from qgis import processing
    return processing.run('native:mergevectorlayers', {
        'LAYERS': camadas, 'CRS': alvo, 'OUTPUT': 'TEMPORARY_OUTPUT'
    }, context=context, feedback=feedback)['OUTPUT']


def _diferenca(entrada, sobreposicao, context, feedback):
    from qgis import processing
    return processing.run('native:difference', {
        'INPUT': entrada, 'OVERLAY': sobreposicao, 'OUTPUT': 'TEMPORARY_OUTPUT'
    }, context=context, feedback=feedback)['OUTPUT']


def _intersecao(entrada, sobreposicao, context, feedback):
    from qgis import processing
    return processing.run('native:intersection', {
        'INPUT': entrada, 'OVERLAY': sobreposicao, 'OUTPUT': 'TEMPORARY_OUTPUT'
    }, context=context, feedback=feedback)['OUTPUT']


def _src_assumido(camada, alvo_authid=""):
    """v3.9.4: camada sem SRC. Antes assumia EPSG:4326 e uma camada em UTM ia parar
    fora do lugar (área zerada). Agora deduz pela extensão: graus -> 4326; senão o
    SRC do cálculo."""
    try:
        ext = camada.extent()
        vazio = ext.isNull() or ext.isEmpty()
        graus = (not vazio) and abs(ext.xMinimum()) <= 180 and abs(ext.xMaximum()) <= 180 and abs(ext.yMinimum()) <= 90 and abs(ext.yMaximum()) <= 90
    except Exception:
        vazio, graus = True, False
    try:
        crs = camada.crs()
        if crs.isValid():
            # SRC geográfico declarado, mas coordenadas em metros (camada salva com SRC trocado).
            if crs.isGeographic() and not vazio and not graus and alvo_authid:
                return alvo_authid, True
            return (crs.authid() or crs.toWkt()), False
    except Exception:
        pass
    return ("EPSG:4326" if graus or not alvo_authid else alvo_authid), True


def _copia_sem_geometria(camada, alvo_authid=""):
    """Copia a camada para memória descartando somente geometrias nulas/vazias."""
    crs, assumido = _src_assumido(camada, alvo_authid)
    tipo = QgsWkbTypes.displayString(camada.wkbType())
    memoria = QgsVectorLayer(f"{tipo}" + (f"?crs={crs}" if crs.upper().startswith("EPSG:") else ""), "norteagro_limpa", "memory")
    if not assumido and camada.crs().isValid():
        memoria.setCrs(camada.crs())
    elif not crs.upper().startswith("EPSG:"):
        memoria.setCrs(QgsCoordinateReferenceSystem(crs))
    prov = memoria.dataProvider()
    prov.addAttributes([f for f in camada.fields()])
    memoria.updateFields()
    saida = []
    sem_geom = 0
    invalidas = 0
    poligono = camada.geometryType() == compat.GEOM_POLIGONO
    for feat in camada.getFeatures():
        try:
            geom = feat.geometry()
        except Exception:
            geom = None
        if geom is None or geom.isEmpty():
            sem_geom += 1
            continue
        if poligono:
            try:
                if not geom.isGeosValid():
                    invalidas += 1
            except Exception:
                pass
        nova = QgsFeature(memoria.fields())
        nova.setAttributes(feat.attributes())
        nova.setGeometry(QgsGeometry(geom))
        saida.append(nova)
    if saida:
        prov.addFeatures(saida)
        memoria.updateExtents()
    return memoria, sem_geom, invalidas


def _variacao_correcao(camada):
    """Área antes x depois da correção (Structure) das feições inválidas, no SRC do cálculo."""
    variacao = 0.0
    locais = []
    if not camada:
        return variacao, locais
    for feat in camada.getFeatures():
        g = feat.geometry()
        try:
            if not g or g.isEmpty() or g.isGeosValid():
                continue
            antes = abs(float(g.area()))
            depois = topo.area_plana(topo.so_poligonos(g))
            variacao += depois - antes
            e, n = topo.ponto_interno(g)
            locais.append((abs(depois - antes), e, n))
        except Exception:
            continue
    locais.sort(reverse=True)
    return variacao, locais


def _preparar_camada(camada, alvo, context, feedback, corrigir=False):
    limpa, sem_geom, invalidas = _copia_sem_geometria(camada, alvo.authid() if alvo is not None else "")
    if limpa.featureCount() <= 0:
        return None, None, sem_geom, invalidas, 0.0, []
    # v3.9.12: só reprojeta/corrige quando precisa (cada chamada ao Processamento custa ~10 ms).
    mesmo_src = alvo is not None and limpa.crs().isValid() and limpa.crs() == alvo
    reprojetada = limpa if mesmo_src else _reprojetar(limpa, alvo, context, feedback)
    variacao, locais = _variacao_correcao(reprojetada) if (corrigir and invalidas) else (0.0, [])
    ja_valida = (mesmo_src and invalidas == 0 and limpa.geometryType() == compat.GEOM_POLIGONO)
    corrigida = _corrigir(reprojetada, context, feedback) if (corrigir and not ja_valida) else reprojetada
    return reprojetada, corrigida, sem_geom, invalidas, variacao, locais


def _densificar_camada(camada, aplicar=False):
    """Retorna uma cópia em memória com todas as geometrias densificadas de modo uniforme."""
    if not camada or not aplicar:
        return camada
    crs = camada.crs().authid() or "EPSG:4326"
    tipo = QgsWkbTypes.displayString(camada.wkbType())
    memoria = QgsVectorLayer(f"{tipo}?crs={crs}", "norteagro_densificada", "memory")
    prov = memoria.dataProvider()
    prov.addAttributes([f for f in camada.fields()])
    memoria.updateFields()
    feats = []
    for feat in camada.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        nova = QgsFeature(memoria.fields())
        nova.setAttributes(feat.attributes())
        nova.setGeometry(_densificar_geometria(geom, True))
        feats.append(nova)
    if feats:
        prov.addFeatures(feats)
        memoria.updateExtents()
    return memoria


def _alerta_coordenadas(camada, nome):
    try:
        ext = camada.extent()
        xmin, xmax = float(ext.xMinimum()), float(ext.xMaximum())
        ymin, ymax = float(ext.yMinimum()), float(ext.yMaximum())
        if xmin >= 100000 and xmax <= 900000 and ymin >= 7000000 and ymax <= 10000000:
            return None
        faixa = f"X={xmin:.3f}..{xmax:.3f}; Y={ymin:.3f}..{ymax:.3f}"
        return (
            "Coordenadas fora da área de Goiás/Brasil - a camada foi desenhada fora do lugar "
            f"(projeto sem imagem de fundo ou SRC errado): {nome}. Extensão encontrada: {faixa}."
        )
    except Exception:
        return None


def _area_total_camada(camada, d, densificar=False):
    return sum(_area_ha(d, f.geometry(), densificar) for f in camada.getFeatures()) if camada else 0.0


def _geom_dissolvida(camada):
    if not camada:
        return None
    geoms = []
    for feat in camada.getFeatures():
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            geoms.append(QgsGeometry(geom))
    if not geoms:
        return None
    if len(geoms) == 1:
        return geoms[0]
    try:
        return QgsGeometry.unaryUnion(geoms)
    except Exception:
        g = geoms[0]
        for outro in geoms[1:]:
            try:
                g = g.combine(outro)
            except Exception:
                pass
        return g


def _partes_geom(geom, d, densificar=False):
    """Partes poligonais com área e centro; coordenadas só são usadas acima de 0,1 m²."""
    if geom is None or geom.isEmpty():
        return []
    try:
        geoms = geom.asGeometryCollection() if geom.isMultipart() else [QgsGeometry(geom)]
    except Exception:
        geoms = [QgsGeometry(geom)]
    saida = []
    for parte in geoms:
        if not parte or parte.isEmpty():
            continue
        if QgsWkbTypes.geometryType(parte.wkbType()) != compat.GEOM_POLIGONO:
            continue
        area_ha = _area_ha(d, parte, densificar)
        area_m2 = area_ha * 10000.0
        try:
            ponto = parte.centroid().asPoint()
            e, n = float(ponto.x()), float(ponto.y())
        except Exception:
            e = n = 0.0
        saida.append({"geom": QgsGeometry(parte), "area": area_ha, "area_m2": area_m2, "e": e, "n": n})
    saida.sort(key=lambda x: x["area_m2"], reverse=True)
    return saida


def _partes_camada(camada, d, densificar=False):
    saida = []
    if camada:
        for feat in camada.getFeatures():
            saida.extend(_partes_geom(feat.geometry(), d, densificar))
    saida.sort(key=lambda x: x["area_m2"], reverse=True)
    return saida


def _coords_partes(partes, limite=5):
    validas = [x for x in partes if x.get("area_m2", 0.0) > TOL_PARTE_M2][:limite]
    return "; ".join(
        f"{x['area_m2']:.1f} m² em E {x['e']:.1f} / N {x['n']:.1f}" for x in validas
    )


def _linhas_hidrograficas(arquivo, camada, d, densificar=False):
    if arquivo not in HIDRO_FEICOES or not camada:
        return []
    campos = camada.fields(); idx_id = campos.indexOf("id"); idx_nome = campos.indexOf("nome"); registros = []
    for pos, feat in enumerate(camada.getFeatures(), 1):
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue
        ident = feat[idx_id] if idx_id >= 0 else pos
        nome = str(feat[idx_nome]).strip() if idx_nome >= 0 and feat[idx_nome] not in (None, "") else ""
        try:
            chave = (0, float(ident))
        except Exception:
            chave = (1, str(ident))
        registros.append((chave, nome, _area_ha(d, geom, densificar)))
    registros.sort(key=lambda x: x[0]); base = HIDRO_FEICOES[arquivo]
    # v3.9.4: o campo "nome" vem como complemento ("Barramento 1 - PARTE 1"), para
    # que nomes repetidos ou genéricos não deixem linhas iguais no quadro.
    return [{"arquivo":arquivo, "descricao":f"{base} {n}" + (f" - {nome}" if nome and nome.casefold() != f"{base} {n}".casefold() else ""), "area":area}
            for n, (_, nome, area) in enumerate(registros, 1)]


def _tem_desenho(reg):
    """v0.7.0: a camada tem desenho (polígono com área; ponto/linha com feição)."""
    if reg.get("tipo") == "Polígono":
        return float(reg.get("area_bruta") or 0.0) > 0.0
    return int(reg.get("feicoes") or 0) > 0


def _prioridade_registro(reg):
    fonte = str(reg.get("arquivo_origem") or "").lower()
    nome_arquivo = os.path.splitext(os.path.basename(fonte))[0].upper()
    return (
        # v0.7.0: camada VAZIA nunca vale mais que uma desenhada. Antes a 00_AREA_DO_IMOVEL vazia criada pelo plugin na
        # pasta do mapa ganhava da "Área do imóvel" desenhada (caso real de cliente), e o imóvel saía 0 ha.
        1 if _tem_desenho(reg) else 0,
        1 if reg.get("local_mapa") else 0,
        1 if nome_arquivo and nome_arquivo == str(reg.get("reconhecida") or "").upper() else 0,  # v3.9.4: arquivo com o nome exato do padrão
        0 if fonte.endswith((".kml", ".kmz")) else 1,  # v3.9: SHP vale mais que o espelho KML
        VIA_PRIORIDADE.get(reg.get("via"), 0),
        int(reg.get("feicoes") or 0),
    )


def _chave_fonte(camada, rec):
    """Identidade de fonte; preserva subcamadas de containers e deduplica SHP realmente repetido."""
    try:
        bruto = str(camada.dataProvider().dataSourceUri() or camada.source() or "")
    except Exception:
        bruto = ""
    fonte = bruto.split("|", 1)[0].strip()
    if not fonte:
        return ""
    prov = str(camada.providerType() or "").lower()
    local = os.path.isabs(fonte) or re.match(r"^[A-Za-z]:[\\/]", fonte)
    if local:
        try:
            base = os.path.normcase(os.path.abspath(os.path.normpath(fonte)))
        except Exception:
            base = os.path.normcase(fonte)
        # SHP/KML/GeoJSON têm uma camada por arquivo. Em containers (ex. GPKG), o
        # sufixo |layername=... distingue subcamadas diferentes do mesmo arquivo.
        if os.path.splitext(fonte)[1].lower() in (".shp", ".kml", ".geojson", ".json"):
            return "file:" + base
        sufixo = bruto[len(fonte):]
        return "file:" + base + os.path.normcase(sufixo)
    if prov == "memory":
        return f"memory:{rec.get('arquivo','')}:{bruto}"
    return f"{prov}:{bruto}"


def _kml_espelho_ids(camadas, previsoes, pasta_mapa):
    """KML do próprio espelho é ignorado quando o SHP correspondente está no projeto."""
    shps = []
    for camada in QgsProject.instance().mapLayers().values():
        if not isinstance(camada, QgsVectorLayer):
            continue
        fonte = arquivo_fonte(camada)
        if not fonte.lower().endswith(".shp"):
            continue
        arq = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
        if not arq:
            arq = os.path.splitext(os.path.basename(fonte))[0].upper()
        raiz_kml = str(camada.customProperty("norteagro/kml_dir", "") or "").strip()
        if not raiz_kml and pasta_mapa:
            raiz_kml = os.path.join(pasta_mapa, "kml")
        if not raiz_kml:
            continue
        pasta_real = os.path.basename(os.path.dirname(fonte))
        shps.append((arq, os.path.normcase(os.path.abspath(os.path.join(raiz_kml, pasta_real, arq + ".kml"))),
                     os.path.normcase(os.path.abspath(os.path.join(raiz_kml, arq + ".kml")))))
    ids = set()
    for camada in camadas:
        fonte = arquivo_fonte(camada)
        if not fonte.lower().endswith(".kml"):
            continue
        atual = os.path.normcase(os.path.abspath(fonte))
        rec = previsoes.get(camada.id(), {})
        arq_rec = str(rec.get("arquivo", "") or "").upper()
        for arq, novo, legado in shps:
            if (not arq_rec or arq_rec == arq) and atual in (novo, legado):
                ids.add(camada.id())
                break
    return ids


def _operacoes_especiais(escolhidas, d, alvo, context, feedback, avisos, conferencias=None, densificar=False):
    """Operações derivadas sempre usam geometrias consideradas e chaves ARQUIVO."""
    conferencias = conferencias if conferencias is not None else []
    especiais = {"area_fora_rl_app":0.0, "reserva_suprimida_antes":0.0, "reserva_suprimida_apos":0.0}
    veg = escolhidas.get("AREA_DE_VEGETACAO")
    if veg and veg.get("corrigida"):
        overlays = [escolhidas[a]["corrigida"] for a in ("RESERVA_LEGAL", "APP_TOTAL")
                    if a in escolhidas and escolhidas[a].get("corrigida")]
        try:
            if not overlays:
                especiais["area_fora_rl_app"] = veg.get("area", 0.0)
            else:
                sobre = _mesclar(overlays, alvo, context, feedback) if len(overlays) > 1 else overlays[0]
                sobre = _dissolver(sobre, context, feedback)
                especiais["area_fora_rl_app"] = _area_total_camada(
                    _diferenca(veg["corrigida"], sobre, context, feedback), d, densificar
                )
        except Exception as exc:
            avisos.append(f"Falha de processing em Área Fora da RL e APP: {exc}")

    for sufixo, alvo_sup, direto_arq in (
        ("antes", "AREA_SUPRIMIDA_ANTES_2019", "RESERVA_SUPRIMIDA_ANTES_2019"),
        ("apos", "AREA_SUPRIMIDA_DEPOIS_2019", "RESERVA_SUPRIMIDA_DEPOIS_2019"),
    ):
        calculada = 0.0
        reserva, sup = escolhidas.get("RESERVA_SUPRIMIDA"), escolhidas.get(alvo_sup)
        if reserva and sup and reserva.get("corrigida") and sup.get("corrigida"):
            try:
                inter = _dissolver(
                    _intersecao(reserva["corrigida"], sup["corrigida"], context, feedback),
                    context, feedback
                )
                calculada = _area_total_camada(inter, d, densificar)
            except Exception as exc:
                avisos.append(f"Falha de processing na Reserva Suprimida {sufixo}: {exc}")
        direto = escolhidas.get(direto_arq)
        if direto and direto.get("area") is not None:
            valor_direto = float(direto.get("area") or 0.0)
            especiais[f"reserva_suprimida_{sufixo}"] = valor_direto
            if reserva and sup:
                diferenca = abs(valor_direto - calculada)
                conferencias.append({
                    "verificacao": f"{direto_arq}: camada própria x interseção calculada",
                    "a": valor_direto, "b": calculada,
                    "situacao": "OK" if diferenca <= TOL_HA else "ALERTA",
                })
        else:
            especiais[f"reserva_suprimida_{sufixo}"] = calculada
    return especiais


def _nome_catalogo(indice, arquivo):
    return str(indice.get(arquivo, {}).get("nome") or arquivo)


def _coberturas_parte(parte, escolhidas, fechamento, d, indice, densificar=False):
    """Descreve outras camadas do catálogo que cobrem uma parte sem classificação."""
    descricoes = []
    area_parte = float(parte.get("area") or 0.0)
    geom = parte.get("geom")
    if not geom or geom.isEmpty():
        return descricoes
    for arquivo, reg in escolhidas.items():
        if arquivo == "AREA_DO_IMOVEL" or arquivo in fechamento or reg.get("tipo") != "Polígono":
            continue
        outra = reg.get("geom_considerada")
        if not outra or outra.isEmpty():
            continue
        try:
            inter = geom.intersection(outra)
            a = _area_ha(d, inter, densificar)
        except Exception:
            continue
        if a * 10000.0 <= TOL_PARTE_M2:
            continue
        nome = _nome_catalogo(indice, arquivo)
        if area_parte > 0 and abs(a - area_parte) <= 0.00001:
            descricoes.append(f"dentro de {nome}")
        else:
            descricoes.append(f"{a*10000.0:.1f} m² sobre {nome}")
    return descricoes[:5]



QUADRO_POR_REGRA = {
    "R1": "Áreas Totais do Imóvel",
    "R2": "Área de Preservação Permanente",
    "R3": "Área de Preservação Permanente",
    "R4": "Área antropizada antes de 2019",
    "R5": "Área antropizada após 2019",
    "R6": "Passivos ambientais",
    "R7": "Áreas Remanescentes",
    "R8": "Áreas Remanescentes",
    "R9": "Passivos ambientais",
    "P1": "Área de Preservação Permanente",
    "P2": "Áreas Remanescentes",
    "P3": "Passivos ambientais",
    "P4": "Áreas Remanescentes",
    "P5": "Áreas Totais do Imóvel",
    "P6": "Áreas Remanescentes",
}


_QUADRO_PERSONALIZADO = {}  # v3.9.6: preenchido a cada cálculo {ARQUIVO: quadro}


def _quadro_arquivo(arquivo):
    if arquivo in _QUADRO_PERSONALIZADO:
        return _QUADRO_PERSONALIZADO[arquivo] or "Outras camadas"
    if arquivo in {"APP_TOTAL", "APP_PRESERVADA", "APP_CONSOLIDADA", "APP_SUPRIMIDA", "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019"}:
        return "Área de Preservação Permanente"
    if arquivo in {"RESERVA_LEGAL", "RESERVA_PRESERVADA", "RESERVA_CONSOLIDADA", "RESERVA_SUPRIMIDA"}:
        return "Áreas Remanescentes"
    if arquivo in {"AREA_SUPRIMIDA_ANTES_2019", "SUPRESSAO_PASSIVEL_ANTES_2019"}:
        return "Área antropizada antes de 2019"
    if arquivo in {"AREA_SUPRIMIDA_DEPOIS_2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019"}:
        return "Área antropizada após 2019"
    if arquivo in {"AREA_DO_IMOVEL", "AREA_CONSOLIDADA", "AREA_DE_VEGETACAO"}:
        return "Áreas Totais do Imóvel"
    return "Passivos ambientais"


def _texto_tamanho(area_ha=None, comprimento_m=None, quantidade=None):
    if quantidade is not None:
        return f"{int(quantidade)} registro(s)"
    if comprimento_m is not None:
        return f"{float(comprimento_m):.1f} m"
    area_ha = float(area_ha or 0.0)
    if area_ha <= 1.0:
        return f"{area_ha * 10000.0:.1f} m²"
    return f"{area_ha:.4f} ha"


def _local_partes(partes, limite=3):
    validas = [x for x in (partes or []) if float(x.get("area_m2") or 0.0) > TOL_PARTE_M2][:limite]
    return "; ".join(f"E {x['e']:.0f} / N {x['n']:.0f}" for x in validas)


def _como_resolver(tipo, parte="", todo="", a="", b=""):
    # v3.9: chamadas com a/b (nomes das camadas) também preenchem parte/todo.
    parte = parte or a
    todo = todo or b
    if tipo == "Sem cobertura":
        return "Desenhe ou estenda a camada correta sobre a área indicada, com aderência ligada às camadas vizinhas."
    if tipo in {"Fora do todo", "Fora do imóvel"}:
        return f"Recorte a camada {parte or 'parte'} pela camada {todo or 'todo'} (Vetor > Geoprocessamento > Recortar) e substitua o conteúdo."
    if tipo == "Sobreposição":
        return "Defina qual das duas classes vale na área indicada e retire a área da outra (Vetor > Geoprocessamento > Diferença)."
    if tipo == "Violação de posição":
        return f"A camada {a or parte} invade {b or todo} na área indicada. Ajuste os vértices ou recorte {a or parte} por {b or todo}."
    if tipo == "Registros sem geometria":
        return f"Abra a tabela de atributos de {parte}, selecione pela expressão is_empty_or_null($geometry) e apague os registros."
    if tipo == "Mesmo arquivo carregado mais de uma vez":
        return "Remova uma das cópias do projeto (botão direito > Remover camada; o arquivo não é apagado)."
    if tipo == "Geometria corrigida no cálculo":
        return f"Corrija a camada {parte} (Vetor > Geometria > Corrigir geometrias) e substitua o conteúdo."
    if tipo == "Lasca":
        return "Confira no mapa; se for resto de desenho, apague ou mescle com o polígono vizinho."
    if tipo == "VERIFICAR":
        return "Confirme se essa área da Reserva Legal é consolidada. Se for, crie a camada Área de Reserva Legal Consolidada; se não, corrija a posição da RL."
    return "Confira a geometria e corrija o desenho antes de entregar os arquivos."


def _registrar_problema(conferencias, problemas_texto, problemas_detalhados, geoms_conf,
                        regra, tipo, quadro, descricao, situacao="ALERTA", area_ha=None,
                        partes=None, como_resolver="", camadas=None, comprimento_m=None,
                        quantidade=None, detalhe_local=""):
    tamanho = _texto_tamanho(area_ha, comprimento_m, quantidade)
    onde = detalhe_local or _local_partes(partes)
    verificacao = str(descricao)
    if tamanho and tamanho not in verificacao:
        verificacao += f" - {tamanho}"
    if onde:
        verificacao += f" - {onde}"
    item = {
        "regra": regra or "", "verificacao": verificacao, "situacao": situacao,
        "como_resolver": como_resolver or _como_resolver(tipo),
    }
    if area_ha is not None:
        item["a"] = float(area_ha or 0.0)
    conferencias.append(item)
    if situacao in {"ALERTA", "CONFERIR", "VERIFICAR"}:
        detalhe = {
            "regra": regra or "", "tipo": tipo, "quadro": quadro or "",
            "descricao": str(descricao), "situacao": situacao,
            "area_ha": float(area_ha or 0.0) if area_ha is not None else None,
            "comprimento_m": float(comprimento_m or 0.0) if comprimento_m is not None else None,
            "quantidade": int(quantidade or 0) if quantidade is not None else None,
            "tamanho": tamanho, "onde": onde,
            "como_resolver": como_resolver or _como_resolver(tipo), "camadas": list(camadas or []),
        }
        problemas_detalhados.append(detalhe)
        problemas_texto.append(
            f"{regra + ' - ' if regra else ''}{descricao}: {tamanho}" +
            (f" ({onde})" if onde else "") + "."
        )
        for parte in (partes or []):
            if float(parte.get("area_m2") or 0.0) <= TOL_PARTE_M2:
                continue
            geoms_conf.append({
                "tipo": tipo, "regra": regra or "", "camada": " / ".join(camadas or []) or str(descricao),
                "area_m2": float(parte.get("area_m2") or 0.0), "e": float(parte.get("e") or 0.0),
                "n": float(parte.get("n") or 0.0), "geom": parte.get("geom"),
            })
    return item


def _geom_registro(escolhidas, arquivo):
    reg = escolhidas.get(arquivo)
    geom = reg.get("geom_considerada") if reg else None
    return QgsGeometry(geom) if geom and not geom.isEmpty() else None


def _geom_reserva_periodo(escolhidas, periodo):
    reserva = _geom_registro(escolhidas, "RESERVA_SUPRIMIDA")
    sup = _geom_registro(escolhidas, "AREA_SUPRIMIDA_ANTES_2019" if periodo == "antes" else "AREA_SUPRIMIDA_DEPOIS_2019")
    if not reserva or not sup:
        return None
    try:
        return reserva.intersection(sup)
    except Exception:
        return None


def _uniao_geometrias(geoms):
    geoms = [QgsGeometry(g) for g in geoms if g and not g.isEmpty()]
    if not geoms:
        return None
    try:
        return QgsGeometry.unaryUnion(geoms)
    except Exception:
        atual = geoms[0]
        for g in geoms[1:]:
            try:
                atual = atual.combine(g)
            except Exception:
                pass
        return atual


def _avaliar_regra_conjunto(regra, titulo, todo_arq, partes_specs, escolhidas, d, densificar,
                             indice, conferencias, problemas_texto, problemas_detalhados, geoms_conf):
    todo = _geom_registro(escolhidas, todo_arq)
    partes = []; faltantes = []; tipos = []
    for spec in partes_specs:
        if isinstance(spec, tuple) and spec[0] == "DERIVADA_RL":
            geom = _geom_reserva_periodo(escolhidas, spec[1])
            nome = "Área de Reserva Legal Suprimida " + ("antes de 2019" if spec[1] == "antes" else "depois de 2019")
            tipo = "RL"
        else:
            geom = _geom_registro(escolhidas, spec); nome = _nome_catalogo(indice, spec)
            tipo = "APP" if str(spec).startswith("APP_") else str(spec)
        if geom:
            partes.append((nome, geom)); tipos.append(tipo)
        else:
            faltantes.append(nome)
    quadro = QUADRO_POR_REGRA.get(regra, "")
    if not todo or faltantes:
        conferencias.append({"regra":regra,"verificacao":f"{regra}. {titulo} - dados ausentes" + (f": {', '.join(faltantes)}" if faltantes else ""),"situacao":"SEM DADOS","como_resolver":"Carregue as camadas necessárias para executar esta conferência."})
        return
    union = _uniao_geometrias([g for _,g in partes]); nome_todo = _nome_catalogo(indice,todo_arq); problemas_regra=0
    try:
        sem = todo.difference(union) if union else QgsGeometry(todo); area=_area_ha(d,sem,densificar)
        area, ps = _area_significativa(_partes_geom(sem,d,densificar)) if area >= TOL_HA else (area, [])
        if area >= TOL_HA:
            _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,regra,"Sem cobertura",quadro,f"{regra}. {nome_todo} possui área sem cobertura pelas partes","ALERTA",area,ps,_como_resolver("Sem cobertura"),[nome_todo]); problemas_regra+=1
        fora = union.difference(todo) if union else None; area_fora=_area_ha(d,fora,densificar) if fora else 0.0
        area_fora, ps = _area_significativa(_partes_geom(fora,d,densificar)) if area_fora >= TOL_HA else (area_fora, [])
        if area_fora >= TOL_HA:
            _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,regra,"Fora do todo",quadro,f"{regra}. Partes fora de {nome_todo}","ALERTA",area_fora,ps,_como_resolver("Fora do todo","partes",nome_todo),[x[0] for x in partes]+[nome_todo]); problemas_regra+=1
        for i in range(len(partes)):
            for j in range(i+1,len(partes)):
                inter=partes[i][1].intersection(partes[j][1]); ai=_area_ha(d,inter,densificar)
                if ai < TOL_HA: continue
                if regra in ("R4","R5") and {tipos[i], tipos[j]} == {"APP","RL"}:
                    # v0.5.0: a Reserva Legal pode conter APP (Código Florestal, art. 15): RL Suprimida dentro da APP
                    # Suprimida é desenho certo; no quadro a área conta uma vez só, na APP.
                    conferencias.append({"regra":regra,"verificacao":f"{regra}. {partes[j][0]} dentro de {partes[i][0]} - {_texto_tamanho(ai)} (permitido: a RL pode conter APP; no quadro conta na APP)","a":ai,"situacao":"OK","como_resolver":"Nada a fazer."})
                    continue
                ps=_partes_geom(inter,d,densificar)
                _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,regra,"Sobreposição",quadro,f"{regra}. Sobreposição entre {partes[i][0]} e {partes[j][0]}","ALERTA",ai,ps,_como_resolver("Sobreposição",a=partes[i][0],b=partes[j][0]),[partes[i][0],partes[j][0]]); problemas_regra+=1
    except Exception as exc:
        conferencias.append({"regra":regra,"verificacao":f"{regra}. Falha na conferência: {exc}","situacao":"ALERTA","como_resolver":"Revise as geometrias das camadas envolvidas."}); return
    if not problemas_regra:
        conferencias.append({"regra":regra,"verificacao":f"{regra}. {titulo}","situacao":"OK","como_resolver":"Nenhuma correção necessária."})


def _avaliar_regras_consistencia(escolhidas, d, densificar, indice, fechamento, inclui_hidrografia,
                                  conferencias, problemas_texto, problemas_detalhados, geoms_conf):
    regras = [
        ("R2","APP Total = soma das subclasses","APP_TOTAL",["APP_PRESERVADA","APP_CONSOLIDADA","APP_ANTROPIZADA_ANTES_2019","APP_ANTROPIZADA_APOS_2019"]),
        ("R3","APP Suprimida = antes + depois de 2019","APP_SUPRIMIDA",["APP_ANTROPIZADA_ANTES_2019","APP_ANTROPIZADA_APOS_2019"]),
        ("R4","Área Suprimida antes de 2019 = APP + RL + passível","AREA_SUPRIMIDA_ANTES_2019",["APP_ANTROPIZADA_ANTES_2019",("DERIVADA_RL","antes"),"SUPRESSAO_PASSIVEL_ANTES_2019"]),
        ("R5","Área Suprimida depois de 2019 = APP + RL + passível","AREA_SUPRIMIDA_DEPOIS_2019",["APP_ANTROPIZADA_APOS_2019",("DERIVADA_RL","depois"),"SUPRESSAO_PASSIVEL_DEPOIS_2019"]),
        ("R6","Área Suprimida = antes + depois de 2019","AREA_SUPRIMIDA",["AREA_SUPRIMIDA_ANTES_2019","AREA_SUPRIMIDA_DEPOIS_2019"]),
        ("R7","Área de Reserva Legal = preservada + consolidada + suprimida","RESERVA_LEGAL",["RESERVA_PRESERVADA","RESERVA_CONSOLIDADA","RESERVA_SUPRIMIDA"]),
        ("R8","Área de Reserva Legal Suprimida = antes + depois de 2019","RESERVA_SUPRIMIDA",[("DERIVADA_RL","antes"),("DERIVADA_RL","depois")]),
        ("R9","Supressão em Área Passível = antes + depois de 2019","SUPRESSAO_PASSIVEL_TOTAL",["SUPRESSAO_PASSIVEL_ANTES_2019","SUPRESSAO_PASSIVEL_DEPOIS_2019"]),
    ]
    for args in regras:
        _avaliar_regra_conjunto(*args,escolhidas,d,densificar,indice,conferencias,problemas_texto,problemas_detalhados,geoms_conf)

    def registrar_posicao(regra,a_arq,b_arq,tipo="Violação de posição",modo="fora"):
        ga,gb=_geom_registro(escolhidas,a_arq),_geom_registro(escolhidas,b_arq)
        if not ga or not gb: return False
        geom=ga.difference(gb) if modo=="fora" else ga.intersection(gb); area=_area_ha(d,geom,densificar)
        if area >= TOL_HA:
            na,nb=_nome_catalogo(indice,a_arq),_nome_catalogo(indice,b_arq); ps=_partes_geom(geom,d,densificar)
            _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,regra,tipo,QUADRO_POR_REGRA.get(regra,""),f"{regra}. {na} em posição incompatível com {nb}","ALERTA",area,ps,_como_resolver(tipo,a=na,b=nb),[na,nb]); return True
        return False

    p1_req=("APP_TOTAL","APP_PRESERVADA","APP_CONSOLIDADA","APP_ANTROPIZADA_ANTES_2019","APP_ANTROPIZADA_APOS_2019")
    if not all(_geom_registro(escolhidas,x) for x in p1_req):
        conferencias.append({"regra":"P1","verificacao":"P1. Subclasses de APP dentro da APP Total - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue APP Total, APP Preservada, APP Consolidada e as duas APP Suprimidas temporais."})
    else:
        erro=False
        for arq in p1_req[1:]: erro=registrar_posicao("P1",arq,"APP_TOTAL") or erro
        if not erro: conferencias.append({"regra":"P1","verificacao":"P1. Subclasses de APP dentro da APP Total","situacao":"OK","como_resolver":"Nenhuma correção necessária."})

    if not (_geom_registro(escolhidas,"RESERVA_SUPRIMIDA") and _geom_registro(escolhidas,"RESERVA_LEGAL")):
        conferencias.append({"regra":"P2","verificacao":"P2. Área de Reserva Legal Suprimida dentro da Área de Reserva Legal - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue Área de Reserva Legal e Área de Reserva Legal Suprimida."})
    elif not registrar_posicao("P2","RESERVA_SUPRIMIDA","RESERVA_LEGAL"):
        conferencias.append({"regra":"P2","verificacao":"P2. Área de Reserva Legal Suprimida dentro da Área de Reserva Legal","situacao":"OK","como_resolver":"Nenhuma correção necessária."})

    gp=_geom_registro(escolhidas,"SUPRESSAO_PASSIVEL_TOTAL")
    if not gp:
        gp=_uniao_geometrias([_geom_registro(escolhidas,"SUPRESSAO_PASSIVEL_ANTES_2019"),_geom_registro(escolhidas,"SUPRESSAO_PASSIVEL_DEPOIS_2019")])
    app=_geom_registro(escolhidas,"APP_TOTAL"); rl=_geom_registro(escolhidas,"RESERVA_LEGAL")
    if not (gp and app and rl):
        conferencias.append({"regra":"P3","verificacao":"P3. Supressão em Área Passível fora da APP Total e da Área de Reserva Legal - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue Supressão em Área Passível, APP Total e Área de Reserva Legal."})
    else:
        erro=False
        for nome_b,gb in (("APP Total",app),("Área de Reserva Legal",rl)):
            inter=gp.intersection(gb); area=_area_ha(d,inter,densificar)
            if area >= TOL_HA:
                ps=_partes_geom(inter,d,densificar); _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,"P3","Violação de posição",QUADRO_POR_REGRA["P3"],f"P3. Supressão em Área Passível invade {nome_b}","ALERTA",area,ps,_como_resolver("Violação de posição",a="Supressão em Área Passível",b=nome_b),["Supressão em Área Passível",nome_b]); erro=True
        if not erro: conferencias.append({"regra":"P3","verificacao":"P3. Supressão em Área Passível fora da APP Total e da Área de Reserva Legal","situacao":"OK","como_resolver":"Nenhuma correção necessária."})

    p4_req=("APP_PRESERVADA","RESERVA_PRESERVADA","AREA_DE_VEGETACAO")
    if not all(_geom_registro(escolhidas,x) for x in p4_req):
        conferencias.append({"regra":"P4","verificacao":"P4. Áreas preservadas dentro da Vegetação Nativa - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue APP Preservada, Área de Reserva Legal Preservada e Área de Vegetação Nativa."})
    else:
        erro=False
        for arq in ("APP_PRESERVADA","RESERVA_PRESERVADA"): erro=registrar_posicao("P4",arq,"AREA_DE_VEGETACAO") or erro
        if not erro: conferencias.append({"regra":"P4","verificacao":"P4. Áreas preservadas dentro da Vegetação Nativa","situacao":"OK","como_resolver":"Nenhuma correção necessária."})

    p5_req=("AREA_DE_VEGETACAO","AREA_CONSOLIDADA","AREA_SUPRIMIDA_ANTES_2019","AREA_SUPRIMIDA_DEPOIS_2019")
    if not all(_geom_registro(escolhidas,x) for x in p5_req):
        conferencias.append({"regra":"P5","verificacao":"P5. Vegetação Nativa sem sobreposição com consolidada/suprimidas - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue Vegetação Nativa, Área Consolidada e as duas Áreas Suprimidas temporais."})
    else:
        erro=False
        for arq in p5_req[1:]: erro=registrar_posicao("P5","AREA_DE_VEGETACAO",arq,"Sobreposição","inter") or erro
        if not erro: conferencias.append({"regra":"P5","verificacao":"P5. Vegetação Nativa sem sobreposição com consolidada/suprimidas","situacao":"OK","como_resolver":"Nenhuma correção necessária."})

    rl=_geom_registro(escolhidas,"RESERVA_LEGAL"); cons=_geom_registro(escolhidas,"AREA_CONSOLIDADA")
    if not (rl and cons):
        conferencias.append({"regra":"P6","verificacao":"P6. Área de Reserva Legal sobre Área Consolidada - dados ausentes","situacao":"SEM DADOS","como_resolver":"Carregue Área de Reserva Legal e Área Consolidada."})
    else:
        inter=rl.intersection(cons); area=_area_ha(d,inter,densificar)
        if area >= TOL_HA and not _geom_registro(escolhidas,"RESERVA_CONSOLIDADA"):
            ps=_partes_geom(inter,d,densificar); _registrar_problema(conferencias,problemas_texto,problemas_detalhados,geoms_conf,"P6","VERIFICAR",QUADRO_POR_REGRA["P6"],"P6. Área de Reserva Legal sobre Área Consolidada","VERIFICAR",area,ps,_como_resolver("VERIFICAR"),[_nome_catalogo(indice,"RESERVA_LEGAL"),_nome_catalogo(indice,"AREA_CONSOLIDADA")])
        else:
            conferencias.append({"regra":"P6","verificacao":"P6. Área de Reserva Legal sobre Área Consolidada","a":area,"situacao":"OK","como_resolver":"Nenhuma decisão pendente pela regra P6."})

def _fechamento_geometrico(escolhidas, imovel, fechamento, d, alvo, context, feedback,
                           indice, conferencias, problemas, problemas_detalhados,
                           geoms_conf, avisos, densificar=False):
    """Executa R1 com geometrias já limpas, recortadas e densificadas."""
    resultado={"classes":list(fechamento),"area_sem_classificacao":0.0,"sobreposicoes":[],"tem_alerta":False}
    if not imovel or not imovel.get("geom_considerada"):
        conferencias.append({"regra":"R1","verificacao":"R1. Fechamento do imóvel - camada Área Total do Imóvel ausente","situacao":"SEM DADOS","como_resolver":"Carregue a camada Área Total do Imóvel."}); return resultado
    classes=[]; faltantes=[]
    for arq in fechamento:
        reg=escolhidas.get(arq); geom=reg.get("geom_considerada") if reg else None
        if reg and reg.get("tipo")=="Polígono" and geom and not geom.isEmpty(): classes.append((arq,QgsGeometry(geom)))
        else: faltantes.append(_nome_catalogo(indice,arq))
    if faltantes:
        conferencias.append({"regra":"R1","verificacao":"R1. Fechamento do imóvel - dados ausentes: "+", ".join(faltantes),"situacao":"SEM DADOS","como_resolver":"Carregue todas as classes configuradas no fechamento do imóvel."}); return resultado
    imovel_geom=QgsGeometry(imovel["geom_considerada"])
    try:
        uniao=_uniao_geometrias([g for _,g in classes]); sem=imovel_geom.difference(uniao) if uniao else QgsGeometry(imovel_geom)
        area_sem=_area_ha(d,sem,densificar); resultado["area_sem_classificacao"]=area_sem; partes=_partes_geom(sem,d,densificar)
        area_sem, partes = _area_significativa(partes)
        if area_sem >= TOL_HA:
            locs=[]
            for parte in [x for x in partes if x["area_m2"] > TOL_PARTE_M2][:3]:
                cob=_coberturas_parte(parte,escolhidas,set(fechamento),d,indice,densificar); loc=f"E {parte['e']:.0f} / N {parte['n']:.0f}"
                if cob: loc += " - " + "; ".join(cob)
                locs.append(loc)
            _registrar_problema(conferencias,problemas,problemas_detalhados,geoms_conf,"R1","Sem cobertura","Áreas Totais do Imóvel","R1. Área do imóvel sem classe","ALERTA",area_sem,partes,_como_resolver("Sem cobertura"),[_nome_catalogo(indice,"AREA_DO_IMOVEL")],detalhe_local="; ".join(locs)); resultado["tem_alerta"]=True
        for i in range(len(classes)):
            a_arq,ga=classes[i]
            for j in range(i+1,len(classes)):
                b_arq,gb=classes[j]; inter=ga.intersection(gb); area=_area_ha(d,inter,densificar)
                if area < TOL_HA: continue
                ps=_partes_geom(inter,d,densificar); na,nb=_nome_catalogo(indice,a_arq),_nome_catalogo(indice,b_arq)
                if {a_arq,b_arq} & set(AGUA_FECHAMENTO) and {a_arq,b_arq} & set(SUPRESSAO_ANTES_DA_AGUA):
                    # v0.4.0: barragem/rio feito em área suprimida: as duas coisas são verdade (permitido)
                    conferencias.append({"regra":"R1","verificacao":f"R1. {na} x {nb}: água feita em área suprimida - {area:.4f} ha (permitido; no quadro conta como suprimida)","a":area,"situacao":"OK","como_resolver":"Nada a fazer."})
                    continue
                _registrar_problema(conferencias,problemas,problemas_detalhados,geoms_conf,"R1","Sobreposição","Áreas Totais do Imóvel",f"R1. Sobreposição entre {na} e {nb}","ALERTA",area,ps,_como_resolver("Sobreposição",a=na,b=nb),[na,nb]); resultado["sobreposicoes"].append({"a":a_arq,"b":b_arq,"area":area}); resultado["tem_alerta"]=True
        if not resultado["tem_alerta"]:
            conferencias.append({"regra":"R1","verificacao":"R1. Fechamento geométrico do imóvel","situacao":"OK","como_resolver":"Nenhuma correção necessária."})
    except Exception as exc:
        avisos.append(f"Falha no fechamento do imóvel: {exc}"); conferencias.append({"regra":"R1","verificacao":f"R1. Falha no fechamento do imóvel: {exc}","situacao":"ALERTA","como_resolver":"Revise as geometrias das classes do fechamento."}); resultado["tem_alerta"]=True
    return resultado


EXIBIDOS_NOS_QUADROS = {
    "RESERVA_LEGAL", "APP_PRESERVADA", "APP_CONSOLIDADA", "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019",
    "HIDROGRAFIA", "BARRAGEM", "CACIMBA", "TANQUE", "LAGOA_NATURAL", "AREA_SUPRIMIDA_ANTES_2019",
    "AREA_SUPRIMIDA_DEPOIS_2019", "AREA_CONSOLIDADA", "AREA_DE_VEGETACAO", "AREA_DO_IMOVEL",
    "SUPRESSAO_PASSIVEL_ANTES_2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019", "COMPENSACAO_DANOS",
    "COMPENSACAO_FLORESTAL", "AREA_RECOMPOSICAO", "RESERVA_SUPRIMIDA_ANTES_2019", "RESERVA_SUPRIMIDA_DEPOIS_2019",
}
APP_SUBCLASSES = ("APP_PRESERVADA", "APP_CONSOLIDADA", "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019")
PRIORIDADE_FECHAMENTO_PADRAO = [
    "HIDROGRAFIA", "AREA_SUPRIMIDA_DEPOIS_2019", "AREA_SUPRIMIDA_ANTES_2019", "AREA_CONSOLIDADA", "AREA_DE_VEGETACAO",
]
PRIORIDADE_APP_PADRAO = ["APP_ANTROPIZADA_APOS_2019", "APP_ANTROPIZADA_ANTES_2019", "APP_CONSOLIDADA", "APP_PRESERVADA"]
PRIORIDADE_RESERVA_PADRAO = ["RESERVA_SUPRIMIDA", "RESERVA_CONSOLIDADA", "RESERVA_PRESERVADA"]
PRIORIDADE_ANTROPIZADA_PADRAO = ["RL", "PASSIVEL"]
PERIODOS_ANTROPIZADA = (
    ("antes", "AREA_SUPRIMIDA_ANTES_2019", "APP_ANTROPIZADA_ANTES_2019", "RESERVA_SUPRIMIDA_ANTES_2019",
     "SUPRESSAO_PASSIVEL_ANTES_2019", "Área antropizada antes de 2019", "RL_SUP_ANTES", "__SEM_ANTES__"),
    ("apos", "AREA_SUPRIMIDA_DEPOIS_2019", "APP_ANTROPIZADA_APOS_2019", "RESERVA_SUPRIMIDA_DEPOIS_2019",
     "SUPRESSAO_PASSIVEL_DEPOIS_2019", "Área antropizada após 2019", "RL_SUP_APOS", "__SEM_APOS__"),
)
TOL_FECHAMENTO_ARREDONDADO = 0.0003


def _ordenar_prioridade(classes, prioridade):
    prioridade = [str(x).upper() for x in (prioridade or [])]
    dentro = [x for x in prioridade if x in classes]
    return dentro + [x for x in classes if x not in dentro]


def _resolver_quadro(escolhidas, imovel_geom, fechamento, config, d, densificar, alvo, indice,
                     conferencias, geoms_conf, avisos, extras_quadro=None):
    """v3.9: divide cada quadro hierárquico sem sobreposição, só em memória.

    Imóvel -> classes do fechamento; APP Total -> subclasses (APP suprimida também
    recortada pela Área Suprimida do período); Reserva Legal -> subclasses;
    Área Suprimida do período -> APP + RL suprimida + passível. Lascas finas são
    somadas à classe vizinha e cada ajuste é registrado (T1-T4, situação AJUSTADO).
    """
    params = topo.parametros_geometria(alvo)
    try:
        largura = float(config.get("largura_max_lasca_m", topo.LARGURA_LASCA_M))
    except Exception:
        largura = topo.LARGURA_LASCA_M
    res, sem, especiais, ajustes = {}, {}, {}, []
    esperados = {}
    rotulos = {
        "RL_SUP_ANTES": "Área de Reserva Legal Suprimida antes de 2019",
        "RL_SUP_APOS": "Área de Reserva Legal Suprimida depois de 2019",
    }

    def geom(arq):
        reg = escolhidas.get(arq)
        if not reg or reg.get("tipo") != "Polígono":
            return None
        g = reg.get("geom_considerada")
        return None if topo.vazia(g) else QgsGeometry(g)

    def rot(chave):
        return rotulos.get(chave) or _nome_catalogo(indice, chave)

    def atual(arq):
        return res.get(arq) if arq in res else geom(arq)

    def registrar(regra, texto, g, como):
        try:
            area = _area_ha(d, g, densificar)
            if area * 10000.0 < 0.1:  # abaixo de 0,1 m² é ruído numérico: resolvido, mas não listado
                return
            partes = _partes_geom(g, d, densificar)
            onde = _local_partes(partes)
        except Exception:
            return
        conferencias.append({
            "regra": regra, "a": area, "situacao": "AJUSTADO", "como_resolver": como,
            "verificacao": f"{texto} - {_texto_tamanho(area)}" + (f" - {onde}" if onde else ""),
        })
        ajustes.append(regra)
        for parte in partes[:20]:
            if float(parte.get("area_m2") or 0.0) <= 0.01:
                continue
            geoms_conf.append({
                "tipo": "Ajuste no quadro", "regra": regra, "camada": texto[:150],
                "area_m2": float(parte["area_m2"]), "e": float(parte["e"]), "n": float(parte["n"]),
                "geom": parte["geom"],
            })

    def executar(quadro, pai, nome_pai, filhos, pais_extras=None, mostrar_sem=True, sem_lasca=None, permitidos=None):
        # v3.9.2: nenhuma classe desenhada neste quadro -> não há o que resolver.
        # O "todo" inteiro fica como sem classificação, sem gerar geometria de ajuste
        # (a regra R correspondente já registra SEM DADOS).
        if all(topo.so_poligonos(g) is None for _, g in filhos):
            if pai is not None and mostrar_sem:
                a_sem = _area_ha(d, pai, densificar)
                sem[quadro] = a_sem if a_sem >= TOL_HA else 0.0
            return {ch: None for ch, _ in filhos}
        try:
            part = topo.particionar(pai, filhos, params, largura, absorver=True, pais_extras=pais_extras, sem_lasca=sem_lasca,
                                    permitidos=permitidos)
        except Exception as exc:
            avisos.append(f"Falha na resolução topológica de {quadro}: {exc}. Valores mantidos sem ajuste.")
            conferencias.append({
                "regra": "T1", "verificacao": f"Falha na resolução topológica de {quadro}: {exc}",
                "situacao": "ALERTA",
                "como_resolver": "Corrija as geometrias das camadas do quadro; os valores foram mantidos sem ajuste.",
            })
            return {ch: topo.so_poligonos(g) for ch, g in filhos}
        pares = {}
        for ganhou, perdeu, g in part["sobreposicoes"]:
            # v0.5.0: água feita em área suprimida é permitida (R1 já diz OK): não é ajuste de desenho
            if ganhou in SUPRESSAO_ANTES_DA_AGUA and perdeu in AGUA_FECHAMENTO:
                continue
            # v0.5.0: RL Suprimida dentro da APP Suprimida também é permitida (R4/R5 dizem OK); conta na APP
            if ganhou in ("APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019") and perdeu in ("RL_SUP_ANTES", "RL_SUP_APOS"):
                continue
            pares.setdefault((ganhou, perdeu), []).append(g)
        for (ganhou, perdeu), gs in pares.items():
            registrar("T1",
                      f"T1. {quadro}: sobreposição entre {rot(ganhou)} e {rot(perdeu)} atribuída a {rot(ganhou)}",
                      topo.uniao(gs, params),
                      f"No quadro a área ficou com {rot(ganhou)} pela prioridade configurada. No desenho, retire essa área de {rot(perdeu)} (Vetor > Geoprocessamento > Diferença).")
        foras = {}
        for ch, nome_extra, g in part["fora"]:
            foras.setdefault((ch, nome_extra or nome_pai), []).append(g)
        for (ch, nome_fora), gs in foras.items():
            registrar("T2", f"T2. {quadro}: parte de {rot(ch)} fora de {nome_fora} desconsiderada no quadro",
                      topo.uniao(gs, params),
                      f"Recorte {rot(ch)} por {nome_fora} (Vetor > Geoprocessamento > Recortar) ou ajuste {nome_fora}.")
        lascas = {}
        for ch, g in part["lascas"]:
            lascas.setdefault(ch, []).append(g)
        for ch, gs in lascas.items():
            registrar("T3", f"T3. {quadro}: {len(gs)} lasca(s) entre classes somada(s) a {rot(ch)}",
                      topo.uniao(gs, params),
                      "Frestas de desenho mais finas que a tolerância foram somadas à classe vizinha. Ligue a aderência e redesenhe a divisa.")
        if pai is not None and mostrar_sem:
            a_sem = _area_ha(d, part["vazio"], densificar) if part["vazio"] is not None else 0.0
            sem[quadro] = a_sem if a_sem >= TOL_HA else 0.0
            if a_sem >= TOL_HA:
                registrar("T4", f"T4. {quadro}: {nome_pai} sem classificação", part["vazio"],
                          "Desenhe a classe correta sobre a área indicada; até lá o quadro mostra a linha 'Área sem classificação'.")
        return part["resolvidos"]

    # 1) Imóvel -> classes do fechamento.
    agua_f = [a for a in AGUA_FECHAMENTO if a in fechamento]
    sup_f = [a for a in SUPRESSAO_ANTES_DA_AGUA if a in fechamento] if agua_f else []
    prio_f = sup_f + agua_f + _ordenar_prioridade([x for x in fechamento if x not in agua_f and x not in sup_f],
                                                  config.get("prioridade_fechamento") or PRIORIDADE_FECHAMENTO_PADRAO)
    agua_fech_g = {}
    if prio_f and (any(geom(a) is not None for a in prio_f) or imovel_geom is not None):
        res.update(executar("Áreas Totais do Imóvel", imovel_geom, _nome_catalogo(indice, "AREA_DO_IMOVEL"),
                            [(a, geom(a)) for a in prio_f]))
        # v0.4.0: água feita em área suprimida conta como Suprimida no fechamento, mas o quadro Área Hidrográfica
        # mostra a água inteira: guarda a parte do fechamento à parte e devolve a geometria inteira da água.
        if sup_f:
            for a in agua_f:
                if a in res:
                    agua_fech_g[a] = res[a]
                    res[a] = geom(a)

    # 2) APP Total -> subclasses; APP suprimida também dentro da Área Suprimida do período.
    app_total = geom("APP_TOTAL")
    if app_total is not None:
        res["APP_TOTAL"] = app_total
    extras = {}
    for _, sup_arq, app_arq, *_resto in PERIODOS_ANTROPIZADA:
        sup_g = atual(sup_arq)
        if sup_arq in escolhidas and sup_g is not None:
            extras[app_arq] = (_nome_catalogo(indice, sup_arq), sup_g)
    prio_app = _ordenar_prioridade(list(APP_SUBCLASSES), config.get("prioridade_app") or PRIORIDADE_APP_PADRAO)
    if config.get("app_separada", True):
        # v0.4.0 (pedido do escritório): cada camada de APP é calculada sozinha, do jeito que foi desenhada
        # (APP Total, Preservada, Consolidada, Suprimida, Suprimida antes e depois de 2019). Nada é juntado,
        # recortado entre elas ou preenchido; a conferência R2 só avisa se a soma não bater com a APP Total.
        for a in list(APP_SUBCLASSES) + ["APP_SUPRIMIDA"]:
            if geom(a) is not None:
                res[a] = geom(a)
    elif any(geom(a) is not None for a in APP_SUBCLASSES):
        res.update(executar("Área de Preservação Permanente", app_total, _nome_catalogo(indice, "APP_TOTAL"),
                            [(a, geom(a)) for a in prio_app], extras))

    # 3) Reserva Legal -> subclasses (não é quadro próprio; sem linha de sem classificação).
    rl = geom("RESERVA_LEGAL")
    if rl is not None:
        res["RESERVA_LEGAL"] = rl
    prio_rl = _ordenar_prioridade(list(PRIORIDADE_RESERVA_PADRAO), config.get("prioridade_reserva") or PRIORIDADE_RESERVA_PADRAO)
    if any(geom(a) is not None for a in prio_rl):
        # v3.9.4: sem recorte pela RL. Com RL proposta/relocada, a supressão fica na RL
        # antiga e seria zerada. Só resolve sobreposição entre as partes; P2 avisa.
        res.update(executar("Áreas Remanescentes", None, _nome_catalogo(indice, "RESERVA_LEGAL"),
                            [(a, geom(a)) for a in prio_rl], mostrar_sem=False))

    # 4) Área Suprimida do período -> APP (fixa, já resolvida) + RL suprimida + passível.
    prio_ant = [x for x in [str(y).upper() for y in (config.get("prioridade_antropizada") or PRIORIDADE_ANTROPIZADA_PADRAO)]
                if x in ("RL", "PASSIVEL")]
    for x in ("RL", "PASSIVEL"):
        if x not in prio_ant:
            prio_ant.append(x)
    for periodo, sup_arq, app_arq, rl_direto, pas_arq, quadro, chave_rl, _chave_sem in PERIODOS_ANTROPIZADA:
        pai = atual(sup_arq)
        if geom(rl_direto) is not None:
            rl_g = geom(rl_direto)
        else:
            base = atual("RESERVA_SUPRIMIDA")
            try:
                rl_g = topo.intersecao(base, pai, params) if (base is not None and pai is not None) else None
            except Exception:
                rl_g = None
        app_g = atual(app_arq)
        filhos = [(app_arq, app_g)] + [((chave_rl, rl_g) if x == "RL" else (pas_arq, geom(pas_arq))) for x in prio_ant]
        if pai is None and all(g is None for _, g in filhos):
            especiais[f"reserva_suprimida_{periodo}"] = 0.0
            continue
        # O valor da APP vem do quadro de APP: aqui ela não recebe frestas.
        # v0.7.0: lasca (fresta) segue a definição, como na correção: Passível não recebe lasca dentro da RL ou da APP
        # Total e a RL Suprimida não recebe lasca fora da RL. Sem isso, a sobra fina que a correção deixa sem classe
        # (ex.: dentro da RL, num imóvel sem camada de RL Suprimida) ia para a Passível só no quadro, e o aviso "ainda
        # há diferença entre o desenho e o quadro" aparecia (caso real de cliente, 2,2 m²).
        permitidos = {}
        rl_tot, app_tot = geom("RESERVA_LEGAL"), geom("APP_TOTAL")
        try:
            proib_pas = topo.uniao([g for g in (rl_tot, app_tot) if g is not None], params) if (rl_tot is not None or app_tot is not None) else None
        except Exception:
            proib_pas = None
        if proib_pas is not None:
            permitidos[pas_arq] = (None, proib_pas)
        if rl_tot is not None:
            permitidos[chave_rl] = (rl_tot, None)
        r = executar(quadro, pai, _nome_catalogo(indice, sup_arq), filhos, sem_lasca={app_arq}, permitidos=permitidos)
        # v0.5.0: RL Suprimida dentro da APP Suprimida é desenho certo (RL pode conter APP); no quadro a área conta na
        # APP para não somar duas vezes. Essa diferença entre a camada e o quadro é ESPERADA (não é erro de desenho).
        if rl_direto in escolhidas and rl_g is not None and app_g is not None:
            try:
                comum = topo.intersecao(rl_g, app_g, params)
                if comum is not None and pai is not None:
                    comum = topo.intersecao(comum, pai, params)
                esperados[rl_direto] = _area_ha(d, comum, densificar) if comum is not None else 0.0
            except Exception:
                pass
        if app_arq not in res:
            res[app_arq] = r.get(app_arq)
        res[pas_arq] = r.get(pas_arq)
        res[chave_rl] = r.get(chave_rl)
        if rl_direto in escolhidas:
            res[rl_direto] = r.get(chave_rl)
        especiais[f"reserva_suprimida_{periodo}"] = _area_ha(d, r.get(chave_rl), densificar)

    # 5) Área Fora da RL e APP com a vegetação resolvida.
    veg = atual("AREA_DE_VEGETACAO")
    if veg is not None:
        try:
            cobre = topo.uniao([res.get("RESERVA_LEGAL"), res.get("APP_TOTAL")], params)
            especiais["area_fora_rl_app"] = _area_ha(d, topo.diferenca(veg, cobre, params), densificar)
        except Exception as exc:
            avisos.append(f"Falha em Área Fora da RL e APP: {exc}")

    # 6) Hidrografia x feições hidrográficas: só conferência (não altera valores).
    hidro_g = atual("HIDROGRAFIA")
    for arq in HIDRO_FEICOES:
        g = geom(arq)
        if hidro_g is None or g is None:
            continue
        try:
            inter = topo.intersecao(hidro_g, g, params)
            area = _area_ha(d, inter, densificar)
        except Exception:
            continue
        if area >= TOL_HA:
            conferencias.append({
                "regra": "G3", "a": area, "situacao": "CONFERIR",
                "verificacao": f"Sobreposição na Área Hidrográfica: Hidrografia x {_nome_catalogo(indice, arq)} - {_texto_tamanho(area)} - {_local_partes(_partes_geom(inter, d, densificar))}",
                "como_resolver": "O quadro Área Hidrográfica soma as duas camadas. Retire a área de uma delas se não deve ser contada duas vezes.",
            })

    # 6b) v3.9.6: camadas personalizadas somadas num quadro simples. Cada uma recebe só
    # a parte que ainda não está em outra linha do mesmo quadro (sem dupla contagem).
    for quadro_x, arqs_x in (extras_quadro or {}).items():
        ocupado = None
        try:
            ocupado = topo.uniao([atual(a) for a in BASE_QUADROS_SOMADOS.get(quadro_x, ())], params)
        except Exception:
            ocupado = None
        for arq in arqs_x:
            g = geom(arq)
            if g is None:
                continue
            try:
                if ocupado is not None and not topo.vazia(ocupado):
                    inter = topo.intersecao(g, ocupado, params)
                    if inter is not None and not topo.vazia(inter):
                        registrar("T1", f"T1. {quadro_x}: parte de {rot(arq)} que já está em outra linha do quadro foi descontada",
                                  inter, f"No quadro essa área ficou só na outra linha. Se ela é de {rot(arq)}, retire-a da outra camada (Vetor > Geoprocessamento > Diferença).")
                    g = topo.diferenca(g, ocupado, params)
                res[arq] = g
                ocupado = topo.uniao([ocupado, g], params)
            except Exception as exc:
                avisos.append(f"Falha ao separar {rot(arq)} no quadro {quadro_x}: {exc}. Valor mantido sem ajuste.")

    # 7) Área do quadro por camada.
    valores = {}
    for arquivo, reg in escolhidas.items():
        base = float(reg.get("area_considerada") if reg.get("area_considerada") is not None else reg.get("area") or 0.0)
        if reg.get("tipo") == "Polígono" and arquivo in res:
            area_q = _area_ha(d, res[arquivo], densificar) if res[arquivo] is not None else 0.0
            reg["ajuste_topologico"] = base - area_q
            reg["ajuste_esperado"] = float(esperados.get(arquivo, 0.0))
        else:
            area_q = base
            reg["ajuste_topologico"] = 0.0 if reg.get("tipo") == "Polígono" else None
        reg["area_quadro"] = area_q if reg.get("tipo") == "Polígono" else None
        valores[arquivo] = area_q
    especiais.setdefault("reserva_suprimida_antes", 0.0)
    especiais.setdefault("reserva_suprimida_apos", 0.0)
    agua_fech = {a: (_area_ha(d, g, densificar) if g is not None else 0.0) for a, g in agua_fech_g.items()}
    return {"valores": valores, "especiais": especiais, "sem": sem, "tem_ajustes": bool(ajustes), "agua_fechamento": agua_fech}


def _valores_quadro(valores, especiais, sem, fechamento, agua_fech=None, app_separada=True):
    """Valores com 4 casas que fecham exatamente: imóvel -> fechamento; APP Total -> APP;
    Área Suprimida do período -> APP (fixa) + RL + passível + sem classificação."""
    vq = {k: round(float(v or 0.0), 4) for k, v in valores.items()}
    vq["RL_SUP_ANTES"] = round(float(especiais.get("reserva_suprimida_antes") or 0.0), 4)
    vq["RL_SUP_APOS"] = round(float(especiais.get("reserva_suprimida_apos") or 0.0), 4)
    vq["FORA_RL_APP"] = round(float(especiais.get("area_fora_rl_app") or 0.0), 4)

    agua_fech = agua_fech or {}
    itens = {(PREFIXO_FECH + a if a in agua_fech else a): float(agua_fech[a] if a in agua_fech else valores.get(a, 0.0))
             for a in fechamento}
    itens["__SEM_FECHAMENTO__"] = float(sem.get("Áreas Totais do Imóvel") or 0.0)
    alvo = valores.get("AREA_DO_IMOVEL") if "AREA_DO_IMOVEL" in valores else None
    vq.update(topo.arredondar_fechando(itens, alvo, tolerancia=TOL_FECHAMENTO_ARREDONDADO))

    if not app_separada:
        itens = {a: float(valores.get(a, 0.0)) for a in APP_SUBCLASSES}
        itens["__SEM_APP__"] = float(sem.get("Área de Preservação Permanente") or 0.0)
        alvo = valores.get("APP_TOTAL") if "APP_TOTAL" in valores else None
        vq.update(topo.arredondar_fechando(itens, alvo, tolerancia=TOL_FECHAMENTO_ARREDONDADO))

    for periodo, sup_arq, app_arq, rl_direto, pas_arq, quadro, chave_rl, chave_sem in PERIODOS_ANTROPIZADA:
        itens = {
            app_arq: float(valores.get(app_arq, 0.0)),
            chave_rl: float(especiais.get(f"reserva_suprimida_{periodo}") or 0.0),
            pas_arq: float(valores.get(pas_arq, 0.0)),
            chave_sem: float(sem.get(quadro) or 0.0),
        }
        alvo = vq.get(sup_arq) if sup_arq in valores else None
        r = topo.arredondar_fechando(itens, alvo, fixos={app_arq: vq.get(app_arq, 0.0)},
                                     tolerancia=TOL_FECHAMENTO_ARREDONDADO)
        vq.update({k: v for k, v in r.items() if k != app_arq})
        if rl_direto in valores:
            vq[rl_direto] = vq[chave_rl]
    return vq


def _problemas_por_quadro(problemas):
    saida={}
    for item in problemas or []:
        quadro=str(item.get("quadro") or "").strip()
        if quadro: saida.setdefault(quadro,[]).append(dict(item))
    for quadro in saida:
        saida[quadro].sort(key=lambda x:(float(x.get("area_ha") or 0.0),float(x.get("comprimento_m") or 0.0),int(x.get("quantidade") or 0)),reverse=True)
    return saida


def _registro_publico(reg):
    excluir = {
        "layer_id", "corrigida", "corrigida_bruta", "dissolvida", "dissolvida_bruta",
        "geom_considerada", "local_mapa", "hidro", "area_sem_densificar",
    }
    return {k:v for k,v in reg.items() if k not in excluir}


def calcular_areas(camadas, srid, metodo, indice_catalogo, progresso=None,
                   apelidos_manuais=None, overrides=None, pasta_mapa="", configuracao=None):
    """Calcula áreas consideradas sem alterar qualquer camada/arquivo de entrada."""
    projeto = QgsProject.instance()
    context = QgsProcessingContext(); context.setProject(projeto)
    feedback = QgsProcessingFeedback(); alvo = QgsCoordinateReferenceSystem(srid); avisos = []
    d, ell = _medidor(srid, metodo, avisos)
    densificar = bool(metodo.startswith("Elipsoidal"))
    config = dict(configuracao or configuracao_geometrica())
    fechamento = [str(x).upper() for x in config.get("fechamento", FECHAMENTO_PADRAO)]
    if config.get("fechamento_inclui_hidrografia") and "HIDROGRAFIA" not in fechamento:
        fechamento.append("HIDROGRAFIA")
    fechamento = list(dict.fromkeys(x for x in fechamento if x in indice_catalogo))
    nao_recortar = {str(x).upper() for x in (config.get("nao_recortar") or [])}

    alertas_coordenadas, conferencias, problemas = [], [], []
    problemas_detalhados = []
    geoms_conf = []
    previsoes, ambiguos = prever_reconhecimentos(
        camadas, srid, indice_catalogo, apelidos_manuais or {}, overrides or {}
    )
    for alias, destinos in sorted(ambiguos.items()):
        avisos.append(f"Apelido ambíguo ignorado: {alias} -> {', '.join(destinos)}.")

    raiz_shp = os.path.join(pasta_mapa, "shapefiles") if pasta_mapa else ""

    # Mesmo arquivo carregado mais de uma vez: escolhe um representante antes de qualquer Processing.
    por_fonte = {}
    for camada in camadas:
        rec = previsoes.get(camada.id(), {})
        chave = _chave_fonte(camada, rec)
        if chave:
            por_fonte.setdefault(chave, []).append(camada)
    duplicadas_fonte = set()
    for chave, grupo in por_fonte.items():
        if len(grupo) <= 1:
            continue
        usada = max(grupo, key=lambda c: (VIA_PRIORIDADE.get(previsoes[c.id()].get("via"), 0), contar_feicoes(c)))
        nomes = [c.name() for c in grupo]
        duplicadas_fonte.update(c.id() for c in grupo if c.id() != usada.id())
        texto_dup = f"Mesmo arquivo carregado {len(grupo)} vezes: {', '.join(nomes)}"
        conferencias.append({
            "regra":"A6", "verificacao": texto_dup, "situacao":"OK",
            "como_resolver": _como_resolver("Mesmo arquivo carregado mais de uma vez"),
        })
        problemas.append(f"Mesmo arquivo carregado {len(grupo)} vezes no projeto - contado uma vez.")
        problemas_detalhados.append({
            "regra":"A6", "tipo":"Mesmo arquivo carregado mais de uma vez", "quadro":"",
            "descricao":texto_dup, "situacao":"CONFERIR", "area_ha":None,
            "comprimento_m":None, "quantidade":len(grupo), "tamanho":f"{len(grupo)} cópias",
            "onde":"", "como_resolver":_como_resolver("Mesmo arquivo carregado mais de uma vez"),
            "camadas":nomes,
        })

    kml_espelhos = _kml_espelho_ids(camadas, previsoes, pasta_mapa)

    registros = []
    candidatos = {}
    for i, camada in enumerate(camadas):
        if progresso:
            progresso(i, len(camadas), f"Processando {camada.name()}...")
        QApplication.processEvents()
        fonte = arquivo_fonte(camada); tipo = _tipo_geometria(camada); rec = dict(previsoes.get(camada.id(), {}))
        original_crs = camada.crs().authid() or camada.crs().description()
        reconhecida = str(rec.get("arquivo", "") or "")
        registro = {
            "layer_id":camada.id(), "grupo":grupo_da_camada(camada), "nome":camada.name(), "arquivo_origem":fonte,
            "tipo":tipo, "feicoes":contar_feicoes(camada), "area":None, "area_m2":None,
            "area_bruta":None, "fora_imovel":None, "area_considerada":None,
            "area_sem_densificar":None, "area_quadro":None, "ajuste_topologico":None,
            "comprimento":None, "registros_sem_geometria":0, "geometrias_corrigidas":0,
            "srid_original":original_crs, "reconhecida":reconhecida, "via":rec.get("via", ""),
            "reconhecida_texto":rotulo_reconhecimento(rec, indice_catalogo),
            "corrigida":None, "corrigida_bruta":None, "dissolvida":None, "dissolvida_bruta":None,
            "geom_considerada":None, "local_mapa":bool(fonte and raiz_shp and _dentro(fonte, raiz_shp)),
            "hidro":[], "razao":float(rec.get("razao") or 0.0),
        }
        registros.append(registro)

        if not camada.isValid():
            registro["reconhecida_texto"] = "arquivo não encontrado - não calculada"
            avisos.append(f"Arquivo não encontrado - não calculada: {camada.name()} ({fonte}).")
            conferencias.append({
                "regra":"A7", "verificacao":f"Arquivo da camada não encontrado - não calculada: {camada.name()} ({fonte})",
                "situacao":"ALERTA",
                "como_resolver":"Corrija o caminho da camada (botão direito > Alterar fonte de dados) ou remova-a do projeto.",
            })
            continue

        if camada.id() in kml_espelhos:
            registro["reconhecida_texto"] = "KML espelho - não calculada"
            conferencias.append({"verificacao":f"KML espelho ignorado: {camada.name()}", "situacao":"OK"})
            continue
        if camada.id() in duplicadas_fonte:
            registro["reconhecida_texto"] += " - mesmo arquivo já contado"
            continue
        if rec.get("referencia"):
            conferencias.append({"verificacao":f"Referência - não calculada: {camada.name()}", "situacao":"OK"})
            continue
        if rec.get("ignorar"):
            conferencias.append({"verificacao":f"Ignorada pelo usuário - não calculada: {camada.name()}", "situacao":"OK"})
            continue
        if not reconhecida or reconhecida not in indice_catalogo:
            avisos.append(f"Não reconhecida - não calculada: {camada.name()}.")
            conferencias.append({"verificacao":f"Não reconhecida - não calculada: {camada.name()}", "situacao":"ALERTA"})
            continue

        src_usado, src_assumido = _src_assumido(camada, srid)
        if src_assumido and not camada.extent().isNull() and not camada.extent().isEmpty():
            nome_ex = _nome_catalogo(indice_catalogo, reconhecida)
            avisos.append(f"Camada sem SRC definido ou com SRC incompatível com as coordenadas: {camada.name()} - assumido {src_usado}.")
            conferencias.append({
                "regra": "G4", "situacao": "CONFERIR",
                "verificacao": f"Camada sem SRC definido ou com SRC incompatível com as coordenadas: {nome_ex} ({camada.name()}) - o cálculo assumiu {src_usado}",
                "como_resolver": "Defina o SRC da camada (botão direito > Definir SRC da camada) ou salve-a novamente com o SRC correto.",
            })
        if not src_assumido and (camada.crs().isGeographic() or camada.crs().authid().upper() == "EPSG:3857"):
            avisos.append(f"Camada reprojetada de SRC geográfico ou EPSG:3857: {camada.name()} ({original_crs}).")

        try:
            reprojetada, corrigida, sem_geom, invalidas, variacao, locais_inv = _preparar_camada(
                camada, alvo, context, feedback, tipo == "Polígono"
            )
            registro["registros_sem_geometria"] = int(sem_geom)
            registro["geometrias_corrigidas"] = int(invalidas)
            if sem_geom:
                nome_ex = _nome_catalogo(indice_catalogo, reconhecida)
                _registrar_problema(
                    conferencias, problemas, problemas_detalhados, geoms_conf,
                    "G1", "Registros sem geometria", _quadro_arquivo(reconhecida),
                    f"Registros sem geometria ignorados: {nome_ex} - {sem_geom} registro(s)",
                    "CONFERIR", quantidade=int(sem_geom),
                    como_resolver=_como_resolver("Registros sem geometria", a=nome_ex), camadas=[nome_ex]
                )
            if invalidas and abs(variacao) < 0.01 and not any(x[0] >= 0.01 for x in locais_inv):
                # v0.5.0: inválida só por arredondamento numérico (variação de área < 0,01 m²): corrigida em silêncio
                invalidas = 0
                registro["geometrias_corrigidas"] = 0
            if invalidas:
                nome_ex = _nome_catalogo(indice_catalogo, reconhecida)
                _registrar_problema(
                    conferencias, problemas, problemas_detalhados, geoms_conf,
                    "G1", "Geometria corrigida no cálculo", _quadro_arquivo(reconhecida),
                    f"Geometrias corrigidas no cálculo: {nome_ex} - {invalidas} (variação de área {variacao:+.1f} m²)",
                    "CONFERIR", quantidade=int(invalidas),
                    detalhe_local="; ".join(f"E {e:.0f} / N {n:.0f}" for _, e, n in locais_inv[:3]),
                    como_resolver=_como_resolver("Geometria corrigida no cálculo", a=nome_ex), camadas=[nome_ex]
                )

            if not reprojetada or not corrigida or corrigida.featureCount() <= 0:
                if camada.featureCount() <= 0:
                    avisos.append(f"Camada vazia: {camada.name()}.")
                if tipo == "Polígono":
                    registro.update(area=0.0, area_m2=0.0, area_bruta=0.0, fora_imovel=0.0, area_considerada=0.0)
                elif tipo == "Linha":
                    registro["comprimento"] = 0.0
                elif tipo == "Ponto":
                    registro["feicoes"] = 0
            else:
                alerta = _alerta_coordenadas(reprojetada, camada.name())
                if alerta:
                    avisos.append(alerta); alertas_coordenadas.append(alerta)
                # G8: no método elipsoidal TODAS as geometrias usadas no cálculo
                # são densificadas uniformemente a cada 10 m, somente em memória.
                # A cópia sem densificar é mantida apenas para a conferência do imóvel.
                corrigida_sem_densificar = corrigida
                if tipo == "Polígono" and reconhecida == "AREA_DO_IMOVEL" and densificar:
                    dissolvida_sem = _dissolver(corrigida_sem_densificar, context, feedback)
                    registro["area_sem_densificar"] = _area_total_camada(dissolvida_sem, d, False)
                corrigida = corrigida_sem_densificar  # v3.9: densifica só na medição, parte a parte
                registro["corrigida_bruta"] = corrigida
                registro["corrigida"] = corrigida
                if tipo == "Polígono":
                    dissolvida = _dissolver(corrigida, context, feedback)
                    registro["dissolvida_bruta"] = dissolvida
                    registro["dissolvida"] = dissolvida
                    soma = _area_total_camada(corrigida, d, densificar)
                    total = _area_total_camada(dissolvida, d, densificar)
                    registro.update(area=total, area_m2=total*10000.0, area_bruta=total,
                                    fora_imovel=0.0, area_considerada=total,
                                    geom_considerada=_geom_dissolvida(dissolvida))
                    # G1 - lascas são mantidas no cálculo, mas registradas para conferência.
                    lascas = [x for x in _partes_camada(corrigida, d, densificar)
                              if 0.0 < float(x.get("area_m2") or 0.0) < 1.0]
                    if lascas:
                        nome_ex = _nome_catalogo(indice_catalogo, reconhecida)
                        soma_lascas = sum(float(x.get("area_m2") or 0.0) for x in lascas)
                        _registrar_problema(
                            conferencias, problemas, problemas_detalhados, geoms_conf,
                            "G1", "Lasca", _quadro_arquivo(reconhecida),
                            f"Lasca: {nome_ex} - {len(lascas)} parte(s) menor(es) que 1 m²",
                            "CONFERIR", area_ha=soma_lascas/10000.0, quantidade=len(lascas),
                            partes=[], como_resolver=_como_resolver("Lasca"), camadas=[nome_ex]
                        )
                        # Mesmo abaixo de 1 m², a lasca entra na camada de conferência para inspeção visual.
                        for parte in lascas:
                            geoms_conf.append({
                                "tipo":"Lasca", "regra":"G1", "camada":nome_ex,
                                "area_m2":float(parte.get("area_m2") or 0.0),
                                "e":float(parte.get("e") or 0.0), "n":float(parte.get("n") or 0.0),
                                "geom":parte.get("geom"),
                            })
                    if total > 0.0 and total < TOL_HA:
                        avisos.append(f"Área menor que 0,0001 ha - confira a geometria: {camada.name()} ({total*10000.0:.4f} m² / {total:.8f} ha).")
                    if abs(soma-total) > TOL_HA:
                        avisos.append(f"Sobreposição interna: {camada.name()} - soma {soma:.4f} ha x dissolvida {total:.4f} ha.")
                elif tipo == "Linha":
                    registro["comprimento"] = sum(
                        _comprimento_m(d, f.geometry(), densificar) for f in corrigida.getFeatures()
                    )
                elif tipo == "Ponto":
                    registro["feicoes"] = int(corrigida.featureCount())
        except Exception as exc:
            avisos.append(f"Falha de processing em {camada.name()}: {exc}")
            conferencias.append({"verificacao":f"Falha de processing em {camada.name()}: {exc}", "situacao":"ALERTA"})
            if tipo == "Polígono":
                registro.update(area=0.0, area_m2=0.0, area_bruta=0.0, fora_imovel=0.0, area_considerada=0.0)
            elif tipo == "Linha":
                registro["comprimento"] = 0.0
            elif tipo == "Ponto":
                registro["feicoes"] = 0

        candidatos.setdefault(reconhecida, []).append(registro)
        if registro["via"] == "semelhança":
            conferencias.append({
                "verificacao":f"Reconhecida por semelhança: {camada.name()} -> {_nome_catalogo(indice_catalogo,reconhecida)} (razão {registro['razao']:.3f})",
                "situacao":"CONFERIR",
            })

    # Uma única camada por ARQUIVO do catálogo.
    escolhidas = {}
    for arquivo, regs in candidatos.items():
        ordenadas = sorted(regs, key=_prioridade_registro, reverse=True)
        usada = ordenadas[0]; escolhidas[arquivo] = usada
        for outra in ordenadas[1:]:
            outra["reconhecida_texto"] = f"{outra.get('reconhecida_texto','')} - duplicada, contada pela camada '{usada['nome']}'"
            a, b = usada.get("area_bruta"), outra.get("area_bruta")
            if a is not None and b is not None:
                dif = abs(float(a or 0.0)-float(b or 0.0)); identica = dif <= TOL_HA
                situacao = "OK" if identica else "ALERTA"
                texto = "Camada duplicada (idêntica)" if identica else "Camada duplicada"
                conferencias.append({
                    "verificacao":f"{texto}: {arquivo} - usada '{usada['nome']}', descartada '{outra['nome']}'",
                    "a":float(a or 0.0), "b":float(b or 0.0), "situacao":situacao,
                })
                if not identica:
                    avisos.append(f"Camada duplicada: {arquivo}. Áreas {a:.4f} ha x {b:.4f} ha; usada '{usada['nome']}'.")
            else:
                conferencias.append({
                    "verificacao":f"Camada duplicada: {arquivo} - usada '{usada['nome']}', descartada '{outra['nome']}'",
                    "situacao":"ALERTA",
                })

    # Recorte em memória no limite dissolvido do imóvel.
    imovel = escolhidas.get("AREA_DO_IMOVEL")
    if densificar and imovel and imovel.get("area_sem_densificar") is not None:
        conferencias.append({
            "verificacao":"Área do imóvel pela calculadora de campo ($area, sem densificar)",
            "a":float(imovel.get("area_sem_densificar") or 0.0),
            "situacao":"OK",
        })
    imovel_geom = _geom_dissolvida(imovel.get("dissolvida_bruta")) if imovel else None
    houve_recorte = False
    if not imovel or not imovel.get("dissolvida_bruta") or not imovel_geom:
        conferencias.append({
            "verificacao":"Recorte no imóvel não aplicado - camada do imóvel ausente",
            "situacao":"SEM DADOS",
        })
        problemas.append("Recorte no imóvel não aplicado - camada Área Total do Imóvel ausente.")
    else:
        for arquivo, reg in escolhidas.items():
            if reg.get("tipo") != "Polígono" or not reg.get("corrigida_bruta"):
                continue
            if arquivo == "AREA_DO_IMOVEL" or arquivo in nao_recortar:
                reg["corrigida"] = reg["corrigida_bruta"]
                reg["dissolvida"] = reg["dissolvida_bruta"]
                reg["area_considerada"] = float(reg.get("area_bruta") or 0.0)
                reg["area"] = reg["area_considerada"]
                reg["area_m2"] = reg["area"] * 10000.0
                reg["geom_considerada"] = _geom_dissolvida(reg["dissolvida"])
                continue
            try:
                considerada = _intersecao(reg["corrigida_bruta"], imovel["dissolvida_bruta"], context, feedback)
                fora = _diferenca(reg["corrigida_bruta"], imovel["dissolvida_bruta"], context, feedback)
                dissolvida = _dissolver(considerada, context, feedback)
                area_cons = _area_total_camada(dissolvida, d, densificar)
                # v3.9: bruta - considerada; somar a diferença feição a feição dobrava sobreposições internas.
                area_fora = max(0.0, float(reg.get("area_bruta") or 0.0) - area_cons)
                g_cons = _geom_dissolvida(dissolvida)
                # v0.5.0: o recorte no imóvel usa as MESMAS operações (topologia.py: exata, grade só de reserva) da
                # correção e da divisão dos quadros, para "considerada", "fora" e "quadro" saírem da mesma conta.
                try:
                    p_grade = topo.parametros_geometria(alvo)
                    g_bruta = _geom_dissolvida(reg["dissolvida_bruta"])
                    g_c2 = topo.intersecao(g_bruta, imovel_geom, p_grade)
                    g_f2 = topo.diferenca(g_bruta, imovel_geom, p_grade)
                    if g_c2 is not None or g_f2 is None:
                        g_cons = g_c2
                        area_cons = _area_ha(d, g_c2, densificar) if g_c2 is not None else 0.0
                        area_fora = _area_ha(d, g_f2, densificar) if g_f2 is not None else 0.0
                except Exception:
                    pass
                reg["corrigida"] = considerada
                reg["dissolvida"] = dissolvida
                reg["area_considerada"] = area_cons
                reg["fora_imovel"] = area_fora
                reg["area"] = area_cons
                reg["area_m2"] = area_cons * 10000.0
                reg["geom_considerada"] = g_cons
                if area_fora >= TOL_HA and pode_sair_do_imovel(arquivo, indice_catalogo):
                    conferencias.append({
                        "regra": "G2", "situacao": "OK", "a": area_fora,
                        "verificacao": f"{_nome_catalogo(indice_catalogo, arquivo)} passa do limite do imóvel (permitido para a hidrografia): "
                                       f"{_texto_tamanho(area_fora)} fora - no quadro conta só a parte de dentro",
                    })
                elif area_fora >= TOL_HA:
                    houve_recorte = True
                    partes = _partes_camada(fora, d, densificar)
                    nome_ex = _nome_catalogo(indice_catalogo, arquivo)
                    _registrar_problema(
                        conferencias, problemas, problemas_detalhados, geoms_conf,
                        "G2", "Fora do imóvel", _quadro_arquivo(arquivo),
                        f"Área fora do imóvel desconsiderada: {nome_ex}", "ALERTA",
                        area_ha=area_fora, partes=partes,
                        como_resolver=_como_resolver("Fora do imóvel", a=nome_ex, b=_nome_catalogo(indice_catalogo, "AREA_DO_IMOVEL")),
                        camadas=[nome_ex, _nome_catalogo(indice_catalogo, "AREA_DO_IMOVEL")]
                    )
            except Exception as exc:
                avisos.append(f"Falha ao recortar {arquivo} no imóvel: {exc}")
                nome_ex = _nome_catalogo(indice_catalogo, arquivo)
                conferencias.append({"verificacao":f"Falha ao recortar {nome_ex} no imóvel: {exc}", "situacao":"ALERTA"})
                problemas.append(f"{nome_ex}: falha no recorte em memória - confira a aba Conferências.")
                # Falha de recorte não pode inflar o quadro: área considerada fica zerada.
                reg["corrigida"] = None; reg["dissolvida"] = None; reg["geom_considerada"] = None
                reg["area_considerada"] = 0.0; reg["area"] = 0.0; reg["area_m2"] = 0.0

        # Linhas não são recortadas, mas trechos fora do imóvel são conferidos.
        for arquivo, reg in escolhidas.items():
            if reg.get("tipo") != "Linha" or not reg.get("corrigida") or pode_sair_do_imovel(arquivo, indice_catalogo):
                continue
            try:
                fora_linha = []
                total_fora_m = 0.0
                for feat in reg["corrigida"].getFeatures():
                    geom = feat.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    gfora = geom.difference(imovel_geom)
                    if not gfora or gfora.isEmpty():
                        continue
                    comp = _comprimento_m(d, gfora, densificar)
                    if comp <= 0:
                        continue
                    c = gfora.centroid().asPoint()
                    fora_linha.append({"comprimento_m":comp,"e":float(c.x()),"n":float(c.y())})
                    total_fora_m += comp
                if fora_linha:
                    nome_ex = _nome_catalogo(indice_catalogo, arquivo)
                    onde = "; ".join(f"E {x['e']:.0f} / N {x['n']:.0f}" for x in sorted(fora_linha,key=lambda x:x['comprimento_m'],reverse=True)[:3])
                    descricao = f"Linha fora do imóvel: {nome_ex} - {total_fora_m:.1f} m"
                    conferencias.append({"regra":"G2","verificacao":descricao,"situacao":"ALERTA","como_resolver":_como_resolver("Fora do imóvel",a=nome_ex,b=_nome_catalogo(indice_catalogo,"AREA_DO_IMOVEL"))})
                    problemas.append(descricao + (f" ({onde})" if onde else "") + ".")
                    problemas_detalhados.append({"regra":"G2","tipo":"Fora do imóvel","quadro":_quadro_arquivo(arquivo),"descricao":descricao,"situacao":"ALERTA","area_ha":None,"comprimento_m":total_fora_m,"quantidade":None,"tamanho":f"{total_fora_m:.1f} m","onde":onde,"como_resolver":_como_resolver("Fora do imóvel",a=nome_ex,b=_nome_catalogo(indice_catalogo,"AREA_DO_IMOVEL")),"camadas":[nome_ex]})
            except Exception:
                pass

        # Pontos não são recortados, mas os que estão fora são conferidos.
        for arquivo, reg in escolhidas.items():
            if reg.get("tipo") != "Ponto" or not reg.get("corrigida") or pode_sair_do_imovel(arquivo, indice_catalogo):
                continue
            fora_pts = []
            for feat in reg["corrigida"].getFeatures():
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                try:
                    dentro = imovel_geom.intersects(geom)
                except Exception:
                    dentro = True
                if not dentro:
                    try:
                        pt = geom.asPoint()
                        fora_pts.append((float(pt.x()), float(pt.y())))
                    except Exception:
                        fora_pts.append((0.0,0.0))
            if fora_pts:
                nome_ex = _nome_catalogo(indice_catalogo, arquivo)
                detalhe = "; ".join(f"E {e:.0f} / N {n:.0f}" for e,n in fora_pts[:3])
                descricao = f"Pontos fora do imóvel: {nome_ex} - {len(fora_pts)} ponto(s)"
                conferencias.append({"regra":"G2","verificacao":descricao,"situacao":"ALERTA","como_resolver":_como_resolver("Fora do imóvel",a=nome_ex,b=_nome_catalogo(indice_catalogo,"AREA_DO_IMOVEL"))})
                problemas.append(descricao + (f" ({detalhe})" if detalhe else "") + ".")
                problemas_detalhados.append({"regra":"G2","tipo":"Fora do imóvel","quadro":_quadro_arquivo(arquivo),"descricao":descricao,"situacao":"ALERTA","area_ha":None,"comprimento_m":None,"quantidade":len(fora_pts),"tamanho":f"{len(fora_pts)} ponto(s)","onde":detalhe,"como_resolver":_como_resolver("Fora do imóvel",a=nome_ex,b=_nome_catalogo(indice_catalogo,"AREA_DO_IMOVEL")),"camadas":[nome_ex]})

    # Hidrografia por feição usa a geometria já recortada/considerada.
    hidro = []
    for arquivo in ("BARRAGEM","CACIMBA","TANQUE","LAGOA_NATURAL"):
        if arquivo in escolhidas:
            escolhidas[arquivo]["hidro"] = _linhas_hidrograficas(
                arquivo, escolhidas[arquivo].get("corrigida"), d, densificar
            )
            hidro.extend(escolhidas[arquivo].get("hidro") or [])

    if progresso:
        progresso(len(camadas), len(camadas), "Calculando operações entre camadas...")
    QApplication.processEvents()

    # Ausências reconhecidas no projeto inteiro sem processar geometria.
    vetores = [x for x in projeto.mapLayers().values() if isinstance(x, QgsVectorLayer) and str(x.customProperty("norteagro/conferencia", "") or "") != "1"]
    prev_proj, _ = prever_reconhecimentos(vetores, srid, indice_catalogo, apelidos_manuais or {}, {})
    presentes = {r.get("arquivo") for r in prev_proj.values() if r.get("arquivo") in indice_catalogo}
    ausentes = sorted(x for x in REQUERIDAS if x not in presentes)
    if ausentes:
        avisos.append("Camadas do catálogo ausentes no projeto: " + ", ".join(ausentes) + ".")

    # v0.3.0: água dentro do imóvel entra no fechamento (linha Hidrografia), antes das coberturas.
    agua_no_imovel = [a for a in AGUA_FECHAMENTO if a in escolhidas and escolhidas[a].get("tipo") == "Polígono"
                      and float(escolhidas[a].get("area_considerada") or 0.0) >= TOL_HA]
    if agua_no_imovel and config.get("agua_no_fechamento", True):
        sup_no = [x for x in SUPRESSAO_ANTES_DA_AGUA if x in fechamento]
        fechamento[:] = sup_no + agua_no_imovel + [x for x in fechamento if x not in AGUA_FECHAMENTO and x not in sup_no]
        conferencias.append({
            "verificacao": "Água dentro do imóvel (" + ", ".join(_nome_catalogo(indice_catalogo, a) for a in agua_no_imovel)
                           + ") entra no quadro Áreas Totais do Imóvel na linha Hidrografia, sem sobrepor as coberturas",
            "situacao": "OK",
        })

    # v3.9.6: camadas personalizadas entram no quadro escolhido na criação/catálogo.
    _QUADRO_PERSONALIZADO.clear()
    lugares = {}
    for arquivo, reg in escolhidas.items():
        if arquivo in USADAS_NOS_QUADROS or arquivo in REQUERIDAS:
            continue
        cod = lugar_quadro(indice_catalogo.get(arquivo))
        if not cod:
            continue
        if reg.get("tipo") != "Polígono":
            cod = "NENHUM"
        lugares[arquivo] = cod
        _QUADRO_PERSONALIZADO[arquivo] = QUADRO_DO_LUGAR.get(cod) or "Todas as camadas"
    for arquivo in sorted(lugares, key=lambda a: _nome_catalogo(indice_catalogo, a).casefold()):
        if lugares[arquivo] == "IMOVEL" and arquivo not in fechamento:
            fechamento.append(arquivo)
    extras_quadro = {}
    for arquivo in sorted(lugares, key=lambda a: _nome_catalogo(indice_catalogo, a).casefold()):
        if lugares[arquivo] in ("PASSIVOS", "HIDRO", "COMPENSACAO"):
            extras_quadro.setdefault(QUADRO_DO_LUGAR[lugares[arquivo]], []).append(arquivo)

    # v3.9: resolução topológica em memória. As regras R/P continuam avaliando o
    # desenho (geom_considerada); somente os valores do quadro usam a geometria resolvida.
    quadro_res = _resolver_quadro(
        escolhidas, imovel_geom if (imovel and imovel_geom) else None, fechamento, config,
        d, densificar, alvo, indice_catalogo, conferencias, geoms_conf, avisos, extras_quadro=extras_quadro
    )
    valores = quadro_res["valores"]
    especiais = _operacoes_especiais(escolhidas, d, alvo, context, feedback, avisos, conferencias, densificar)
    especiais.update(quadro_res["especiais"])
    sem_quadros = quadro_res["sem"]
    agua_fech = dict(quadro_res.get("agua_fechamento") or {})

    def vf(arq):  # valor da classe dentro do fechamento do imóvel
        return float(agua_fech[arq]) if arq in agua_fech else float(valores.get(arq, 0.0) or 0.0)

    # Fechamento geométrico do imóvel: detecção sobre o desenho.
    fechamento_res = _fechamento_geometrico(
        escolhidas, imovel, fechamento, d, alvo, context, feedback,
        indice_catalogo, conferencias, problemas, problemas_detalhados,
        geoms_conf, avisos, densificar
    )
    fechamento_res["area_sem_classificacao_desenho"] = float(fechamento_res.get("area_sem_classificacao") or 0.0)
    if "Áreas Totais do Imóvel" in sem_quadros:
        fechamento_res["area_sem_classificacao"] = float(sem_quadros.get("Áreas Totais do Imóvel") or 0.0)
    _avaliar_regras_consistencia(
        escolhidas, d, densificar, indice_catalogo, fechamento,
        bool(config.get("fechamento_inclui_hidrografia")),
        conferencias, problemas, problemas_detalhados, geoms_conf
    )

    # Outras = camadas personalizadas com lugar "Outras camadas" (padrão das antigas).
    outras = []
    for arquivo in sorted(lugares, key=lambda a: _nome_catalogo(indice_catalogo, a).casefold()):
        if lugares[arquivo] == "OUTRAS" and arquivo not in fechamento:
            outras.append({"arquivo":arquivo, "nome":_nome_catalogo(indice_catalogo,arquivo), "area":float(valores.get(arquivo) or 0.0)})
    linhas_personalizadas = {
        q: [{"arquivo":a, "nome":_nome_catalogo(indice_catalogo,a), "area":float(valores.get(a) or 0.0)} for a in arqs]
        for q, arqs in extras_quadro.items()
    }

    total_imovel = sum(vf(arq) for arq in fechamento) + float(
        fechamento_res.get("area_sem_classificacao") or 0.0
    )
    fechamento_linhas = []
    fechamento_restantes = list(fechamento)
    if "AREA_SUPRIMIDA_ANTES_2019" in fechamento_restantes and "AREA_SUPRIMIDA_DEPOIS_2019" in fechamento_restantes:
        fechamento_linhas.append({
            "descricao":"Área Antropizada não Consolidada",
            "arquivos":["AREA_SUPRIMIDA_ANTES_2019","AREA_SUPRIMIDA_DEPOIS_2019"],
            "area":valores.get("AREA_SUPRIMIDA_ANTES_2019",0.0)+valores.get("AREA_SUPRIMIDA_DEPOIS_2019",0.0),
        })
        fechamento_restantes = [
            x for x in fechamento_restantes
            if x not in {"AREA_SUPRIMIDA_ANTES_2019","AREA_SUPRIMIDA_DEPOIS_2019"}
        ]
    agua_linha = [a for a in fechamento_restantes if a in AGUA_FECHAMENTO]
    for arq in fechamento_restantes:
        if arq in agua_linha:
            continue
        fechamento_linhas.append({
            "descricao":_nome_catalogo(indice_catalogo, arq),
            "arquivos":[arq],
            "area":valores.get(arq, 0.0),
        })
    if agua_linha:  # v0.3.0: toda a água numa linha só, no fim do quadro
        fechamento_linhas.append({
            "descricao":_nome_catalogo(indice_catalogo, "HIDROGRAFIA") if agua_linha == ["HIDROGRAFIA"] else "Hidrografia e reservatórios",
            "arquivos":[(PREFIXO_FECH + a if a in agua_fech else a) for a in agua_linha],
            "area":sum(vf(a) for a in agua_linha),
        })
    total_app = sum(valores.get(a, 0.0) for a in APP_SUBCLASSES) + float(sem_quadros.get("Área de Preservação Permanente") or 0.0)
    total_antes = (valores.get("APP_ANTROPIZADA_ANTES_2019",0.0) + especiais["reserva_suprimida_antes"]
                   + valores.get("SUPRESSAO_PASSIVEL_ANTES_2019",0.0) + float(sem_quadros.get("Área antropizada antes de 2019") or 0.0))
    total_apos = (valores.get("APP_ANTROPIZADA_APOS_2019",0.0) + especiais["reserva_suprimida_apos"]
                  + valores.get("SUPRESSAO_PASSIVEL_DEPOIS_2019",0.0) + float(sem_quadros.get("Área antropizada após 2019") or 0.0))
    conjuntos = [
        (set(fechamento) | {"AREA_DO_IMOVEL"}, "Fechamento do imóvel: Total x Área Total do Imóvel", total_imovel, valores.get("AREA_DO_IMOVEL",0.0), TOL_FECHAMENTO_ARREDONDADO),
        ({"APP_PRESERVADA","APP_CONSOLIDADA","APP_ANTROPIZADA_ANTES_2019","APP_ANTROPIZADA_APOS_2019","APP_TOTAL"}, "Total Área de Preservação Permanente x APP_TOTAL", total_app, valores.get("APP_TOTAL",0.0), None if config.get("app_separada", True) else TOL_HA),
        ({"APP_ANTROPIZADA_ANTES_2019","SUPRESSAO_PASSIVEL_ANTES_2019","AREA_SUPRIMIDA_ANTES_2019"}, "Total Área antropizada antes de 2019 x AREA_SUPRIMIDA_ANTES_2019", total_antes, valores.get("AREA_SUPRIMIDA_ANTES_2019",0.0), TOL_HA),
        ({"APP_ANTROPIZADA_APOS_2019","SUPRESSAO_PASSIVEL_DEPOIS_2019","AREA_SUPRIMIDA_DEPOIS_2019"}, "Total Área antropizada após 2019 x AREA_SUPRIMIDA_DEPOIS_2019", total_apos, valores.get("AREA_SUPRIMIDA_DEPOIS_2019",0.0), TOL_HA),
    ]
    for req, nome_conf, a, b, tolerancia in conjuntos:
        tem = req.issubset(escolhidas.keys())
        item = {"verificacao":nome_conf, "a":a, "b":b, "tem_dados":tem}
        if tem and tolerancia is not None:
            item["tolerancia"] = float(tolerancia)
            item["situacao"] = "OK" if abs(float(a)-float(b)) < tolerancia else "ALERTA"
        conferencias.append(item)

    valores_quadro = _valores_quadro(valores, especiais, sem_quadros, fechamento, agua_fech,
                                     app_separada=bool(config.get("app_separada", True)))

    # v3.9: toda camada reconhecida e calculada aparece na planilha. As que não têm
    # linha própria nos quadros vão para "Demais camadas calculadas" (não somam).
    exibidos = set(EXIBIDOS_NOS_QUADROS) | set(fechamento) | {x["arquivo"] for x in outras} | {
        a for arqs in extras_quadro.values() for a in arqs}
    demais = []
    for arquivo, reg in escolhidas.items():
        if arquivo in exibidos:
            continue
        nome_dm = _nome_catalogo(indice_catalogo, arquivo)
        if reg.get("tipo") == "Polígono":
            demais.append({"arquivo":arquivo, "nome":nome_dm, "valor":float(valores.get(arquivo) or 0.0), "unidade":"ha"})
        elif reg.get("tipo") == "Linha":
            demais.append({"arquivo":arquivo, "nome":nome_dm, "valor":float(reg.get("comprimento") or 0.0), "unidade":"m"})
        elif reg.get("tipo") == "Ponto":
            demais.append({"arquivo":arquivo, "nome":nome_dm, "valor":int(reg.get("feicoes") or 0), "unidade":"un"})
    demais.sort(key=lambda x: str(x["nome"]).casefold())

    # Atualiza linhas de Todas as camadas depois do recorte/seleção.
    todas = [_registro_publico(x) for x in registros]

    quadro_origens = {
        "RESERVA_LEGAL":"Áreas Remanescentes", "APP_PRESERVADA":"Área de Preservação Permanente",
        "APP_CONSOLIDADA":"Área de Preservação Permanente", "HIDROGRAFIA":"Área Hidrográfica",
        "BARRAGEM":"Área Hidrográfica", "CACIMBA":"Área Hidrográfica", "TANQUE":"Área Hidrográfica", "LAGOA_NATURAL":"Área Hidrográfica",
        "AREA_CONSOLIDADA":"Áreas Totais do Imóvel", "AREA_DE_VEGETACAO":"Áreas Totais do Imóvel", "AREA_DO_IMOVEL":"Áreas Totais do Imóvel",
        "AREA_SUPRIMIDA_ANTES_2019":"Passivos ambientais", "AREA_SUPRIMIDA_DEPOIS_2019":"Passivos ambientais",
        "APP_ANTROPIZADA_APOS_2019":"Área antropizada após 2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019":"Área antropizada após 2019",
        "APP_ANTROPIZADA_ANTES_2019":"Área antropizada antes de 2019", "SUPRESSAO_PASSIVEL_ANTES_2019":"Área antropizada antes de 2019",
        "COMPENSACAO_DANOS":"Área Total de Compensação", "COMPENSACAO_FLORESTAL":"Área Total de Compensação", "AREA_RECOMPOSICAO":"Área Total de Compensação",
    }
    for x in outras:
        quadro_origens[x["arquivo"]] = "Outras camadas"
    for arquivo, cod in lugares.items():
        if QUADRO_DO_LUGAR.get(cod):
            quadro_origens[arquivo] = QUADRO_DO_LUGAR[cod]
    nomes_catalogo = {a:e.get("nome",a) for a,e in indice_catalogo.items()}

    # Deduplica mensagens simples sem perder a ordem.
    problemas_unicos = []
    for x in problemas:
        if x not in problemas_unicos:
            problemas_unicos.append(x)

    if progresso:
        progresso(len(camadas), len(camadas), "Concluído")
    return {
        "metodo":metodo, "casas":4, "srid":srid, "elipsoide":ell, "gerado_em":datetime.now(), "usuario":getpass.getuser(),
        "valores":valores, "valores_quadro":valores_quadro, "sem_classificacao":quadro_res["sem"],
        "tem_ajustes":quadro_res["tem_ajustes"], "demais":demais, "especiais":especiais, "hidro":hidro, "outras":outras, "linhas_personalizadas":linhas_personalizadas, "todas":todas,
        "conferencias":conferencias, "avisos":avisos, "alertas_coordenadas":alertas_coordenadas,
        "quadro_origens":quadro_origens, "nomes_catalogo":nomes_catalogo,
        "fechamento":fechamento_res, "fechamento_classes":fechamento,
        "fechamento_linhas":fechamento_linhas,
        "fechamento_inclui_hidrografia":bool(config.get("fechamento_inclui_hidrografia")),
        "nao_recortar":sorted(nao_recortar), "houve_recorte":houve_recorte,
        "densificacao_m":DENSIFICACAO_ELIPSOIDAL_M if densificar else 0.0,
        "problemas_desenho":problemas_unicos,
        "problemas_detalhados":problemas_detalhados,
        "problemas_por_quadro":_problemas_por_quadro(problemas_detalhados),
        "tem_problemas_geometricos":bool(problemas_detalhados or problemas_unicos or fechamento_res.get("tem_alerta")),
        "geometrias_conferencia":geoms_conf,
    }


def atualizar_camada_conferencia(resultado, srid, mostrar=True):
    """Substitui a camada temporária de erros; não grava nada em disco."""
    projeto = QgsProject.instance()
    antigos = []
    for camada in list(projeto.mapLayers().values()):
        try:
            if str(camada.customProperty("norteagro/conferencia", "") or "") == "1" or camada.name() == "Conferência de geometria":
                antigos.append(camada.id())
        except Exception:
            continue
    if antigos:
        projeto.removeMapLayers(antigos)

    if not mostrar or not resultado or not resultado.get("geometrias_conferencia"):
        # v3.9.2: sem problemas para mostrar, o grupo "Conferência" vazio também sai do painel.
        try:
            raiz_v = projeto.layerTreeRoot(); grupo_v = raiz_v.findGroup("Conferência")
            if grupo_v is not None and len(grupo_v.children()) == 0:
                raiz_v.removeChildNode(grupo_v)
        except Exception:
            pass
        return ""

    camada = QgsVectorLayer(f"Polygon?crs={srid}", "Conferência de geometria", "memory")
    prov = camada.dataProvider()
    prov.addAttributes([
        QgsField("tipo", compat.CAMPO_TEXTO), QgsField("regra", compat.CAMPO_TEXTO), QgsField("camada", compat.CAMPO_TEXTO),
        QgsField("area_m2", compat.CAMPO_REAL), QgsField("e", compat.CAMPO_REAL), QgsField("n", compat.CAMPO_REAL),
    ])
    camada.updateFields()
    feats = []
    for item in resultado.get("geometrias_conferencia", []):
        geom = item.get("geom")
        if not geom or geom.isEmpty():
            continue
        f = QgsFeature(camada.fields())
        f.setGeometry(QgsGeometry(geom))
        f.setAttributes([
            str(item.get("tipo", "")), str(item.get("regra", "")), str(item.get("camada", "")),
            float(item.get("area_m2", 0.0)), float(item.get("e", 0.0)), float(item.get("n", 0.0)),
        ])
        feats.append(f)
    if feats:
        prov.addFeatures(feats)
        camada.updateExtents()
    camada.setCustomProperty("norteagro/conferencia", "1")

    categorias = []
    presentes = {str(item.get("tipo", "")) for item in resultado.get("geometrias_conferencia", [])}
    estilos = {
        "Sem classe": ("255,0,0,70", "#FF0000"),
        "Sem cobertura": ("255,0,0,70", "#FF0000"),
        "Fora do imóvel": ("180,0,0,85", "#B40000"),
        "Fora do todo": ("190,60,0,85", "#B43A00"),
        "Sobreposição": ("255,90,90,100", "#8B0000"),
        "Violação de posição": ("255,165,0,85", "#A86A00"),
        "Lasca": ("180,80,180,90", "#7A347A"),
        "VERIFICAR": ("255,190,0,80", "#A86A00"),
        "Ajuste no quadro": ("70,130,200,60", "#1F4E79"),
    }
    for tipo in sorted(presentes - set(estilos)):
        estilos[tipo] = ("200,200,200,80", "#555555")
    # v3.9.2: a legenda mostra só os tipos que existem neste cálculo.
    for tipo, (cor, borda) in [(t_, e_) for t_, e_ in estilos.items() if t_ in presentes]:
        simb = QgsFillSymbol.createSimple({"color":cor, "outline_color":borda, "outline_width":"0.5"})
        categorias.append(QgsRendererCategory(tipo, simb, tipo))
    camada.setRenderer(QgsCategorizedSymbolRenderer("tipo", categorias))

    pal = QgsPalLayerSettings()
    pal.fieldName = 'format_number("area_m2", 1) || \' m²\''
    pal.isExpression = True
    fmt = QgsTextFormat(); fmt.setSize(9); fmt.setColor(QColor("#8B0000")); pal.setFormat(fmt)
    camada.setLabelsEnabled(True); camada.setLabeling(QgsVectorLayerSimpleLabeling(pal))

    raiz = projeto.layerTreeRoot()
    grupo = raiz.findGroup("Conferência")
    if grupo is not None and len(grupo.children()) == 0:  # v3.9: childCount() não existe no PyQGIS
        try:
            raiz.removeChildNode(grupo)
            grupo = None
        except Exception:
            pass
    if grupo is None:
        grupo = raiz.insertGroup(0, "Conferência")
    projeto.addMapLayer(camada, False)
    grupo.addLayer(camada)
    return camada.id()
