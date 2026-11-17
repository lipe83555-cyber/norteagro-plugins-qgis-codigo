# -*- coding: utf-8 -*-
"""Teste de integração da conferência geométrica.

Executar DENTRO do console Python do QGIS 3.44, depois de instalar/recarregar o plugin:

    import norteagro_uso_solo.testes_conferencia as t
    t.executar()

O teste usa somente camadas temporárias em memória e as remove ao final. Ele NÃO grava
SHP/QML/KML. Os testes de hash de arquivos reais continuam no roteiro TESTES_MANUAIS.txt.
"""
from . import compat
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis, QgsFeature, QgsGeometry, QgsProject, QgsRectangle, QgsVectorLayer

from .areas import calcular_areas, atualizar_camada_conferencia
from .catalogo import indice_reconhecimento
from .planilha import gerar_planilha

SRID = "EPSG:31982"
X0 = 654740.0
Y0 = 8468000.0
H = 6559.649  # 1000 m * H = 6.559.649 m² = 655,9649 ha


def _rect(x1, y1, x2, y2):
    return QgsGeometry.fromRect(QgsRectangle(float(x1), float(y1), float(x2), float(y2)))


def _retangulo_centro(e, n, largura, area_m2):
    altura = float(area_m2) / float(largura)
    return _rect(e-largura/2.0, n-altura/2.0, e+largura/2.0, n+altura/2.0)


def _camada(nome, arquivo, geoms, nulos=0):
    lyr = QgsVectorLayer(f"Polygon?crs={SRID}&field=id:integer", nome, "memory")
    lyr.setCustomProperty("norteagro/arquivo", arquivo)
    p = lyr.dataProvider()
    feats = []
    for i, geom in enumerate(geoms, 1):
        f = QgsFeature(lyr.fields())
        f.setAttribute("id", i)
        f.setGeometry(QgsGeometry(geom))
        feats.append(f)
    for j in range(nulos):
        f = QgsFeature(lyr.fields())
        f.setAttribute("id", len(feats)+1+j)
        feats.append(f)  # propositalmente sem geometria
    p.addFeatures(feats)
    lyr.updateExtents()
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def _testar_tela_areas_preenchimento(projeto):
    """3.8.1: TelaAreas deve nascer preenchida, sem depender de exec_() ou ação posterior."""
    from qgis.utils import iface
    from .tela_areas import TelaAreas

    teste = QgsVectorLayer(f"Polygon?crs={SRID}&field=id:integer", "Teste TelaAreas 3.8.1", "memory")
    teste.setCustomProperty("norteagro/arquivo", "AREA_DE_VEGETACAO")
    f = QgsFeature(teste.fields()); f.setAttribute("id", 1); f.setGeometry(_rect(X0, Y0, X0+10.0, Y0+10.0))
    teste.dataProvider().addFeature(f); teste.updateExtents(); projeto.addMapLayer(teste)

    class _PluginStub:
        def __init__(self): self.iface = iface
        def memoria_basica(self): return "", SRID
        def log(self, _msg): pass

    dlg = None
    try:
        esperadas = [
            l for l in projeto.mapLayers().values()
            if l.type() == compat.CAMADA_VETOR
            and str(l.customProperty("norteagro/conferencia", "") or "") != "1"
        ]
        dlg = TelaAreas(_PluginStub(), iface.mainWindow(), modo_so_calcular=True)
        itens=[]
        for i in range(dlg.arvore.topLevelItemCount()):
            pai=dlg.arvore.topLevelItem(i)
            for j in range(pai.childCount()): itens.append(pai.child(j))
        assert len(itens) == len(esperadas), (len(itens), len(esperadas), [x.name() for x in esperadas])
        por_id = {str(x.data(0, Qt.ItemDataRole.UserRole) or ""): x for x in itens}
        permitidos = ("ogr", "memory", "spatialite", "delimitedtext")
        for layer in esperadas:
            item = por_id.get(layer.id()); assert item is not None, layer.name()
            combo = dlg.arvore.itemWidget(item, 5); selo = dlg.arvore.itemWidget(item, 6)
            assert combo is not None and combo.currentText().strip(), (layer.name(), "Reconhecer como vazio")
            assert selo is not None and selo.text().strip(), (layer.name(), "Situação vazia")
            assert item.text(5).strip() and item.text(6).strip(), (layer.name(), item.text(5), item.text(6))
            if layer.providerType() in permitidos and layer.featureCount() > 0:
                assert item.checkState(0) == Qt.CheckState.Checked, (layer.name(), "deveria iniciar marcada")
        assert dlg.srid_calculo() == SRID, dlg.srid_calculo()
        assert dlg._itens_marcados(), "deveria haver ao menos uma camada marcada"
        assert dlg.calcular_btn.isEnabled(), "Calcular e gerar planilha deveria estar habilitado"
        assert dlg.rodape.text().startswith(str(len(dlg._itens_marcados()))), dlg.rodape.text()
        assert not dlg.pendencias.isVisible(), dlg.pendencias.text()
    finally:
        if dlg is not None:
            dlg.close(); dlg.deleteLater()
        if projeto.mapLayer(teste.id()): projeto.removeMapLayer(teste.id())


def _area_m2_layer(layer):
    return sum(
        f.geometry().area()
        for f in layer.getFeatures()
        if f.hasGeometry() and f.geometry() and not f.geometry().isEmpty()
    )


def _config(hidro=False, fechamento=None, agua=False, app=False):
    # v0.4.0: agua=True liga a regra nova (água entra sozinha no fechamento); os critérios antigos usam False.
    # app=True: camadas de APP calculadas cada uma sozinha (padrão do plugin); os critérios antigos usam o modo
    # antigo (subclasses dentro da APP Total).
    return {
        "agua_no_fechamento": bool(agua),
        "app_separada": bool(app),
        "fechamento": fechamento or [
            "AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019",
            "AREA_CONSOLIDADA", "AREA_DE_VEGETACAO",
        ],
        "fechamento_inclui_hidrografia": bool(hidro),
        "nao_recortar": [],
    }

def _textos_quadro_xlsx(caminho):
    """Lê textos da primeira aba sem depender de openpyxl."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(caminho) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iterfind(".//m:t", ns)))
        raiz = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        textos = []
        for cel in raiz.findall(".//m:c", ns):
            valor = cel.find("m:v", ns)
            if valor is None:
                continue
            if cel.get("t") == "s":
                textos.append(shared[int(valor.text)])
            elif cel.get("t") == "inlineStr":
                textos.append("".join(t.text or "" for t in cel.iterfind(".//m:t", ns)))
        return textos


def _testar_g9_planilha(dados, deve_ter_diferenca):
    fd, caminho = tempfile.mkstemp(prefix="norteagro_g9_", suffix=".xlsx")
    os.close(fd)
    try:
        gerar_planilha(caminho, dados)
        textos = _textos_quadro_xlsx(caminho)
        assert ("Diferença" in textos) is bool(deve_ter_diferenca), textos
        if str(dados.get("metodo", "")).startswith("Elipsoidal"):
            assert any("elipsoidal (grs80, vértices a cada 10 m)" in x.lower() for x in textos), textos
            assert not any("igual à calculadora de campo" in x for x in textos if "Gerado em" in x), textos
        else:
            assert any("plano utm" in x.lower() for x in textos), textos
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass


def _caso_principal(projeto):
    """Monta aproximação geométrica de um caso real de cliente."""
    criadas = []
    imovel_geom = _rect(X0, Y0, X0+1000.0, Y0+H)
    imovel = _camada("imovel", "AREA_DO_IMOVEL", [imovel_geom]); criadas.append(imovel)
    imovel2 = _camada("AREA DE IMOVEL", "AREA_DO_IMOVEL", [imovel_geom]); criadas.append(imovel2)

    # Áreas consideradas da especificação, em m².
    a_veg = 1565436.0
    a_cons = 3292060.0
    a_antes = 1674864.6
    a_apos = 27085.7

    # Lacunas: 198,4 m² + 4,0 m² + 3 lascas de 0,096 m² ~= 202,7 m².
    gap_grande = _retangulo_centro(655052.2, 8471402.1, 14.0, 198.4)
    gap_4 = _retangulo_centro(655598.1, 8471972.3, 2.0, 4.0)
    gaps_min = [
        _retangulo_centro(655110.0, 8471450.0, 0.3, 0.096),
        _retangulo_centro(655130.0, 8471470.0, 0.3, 0.096),
        _retangulo_centro(655150.0, 8471490.0, 0.3, 0.096),
    ]
    gap_cons_total = 198.4 + 3*0.096

    x = X0
    w_veg = a_veg / H
    veg_geom = _rect(x, Y0, x+w_veg, Y0+H)
    x += w_veg
    veg = _camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [veg_geom]); criadas.append(veg)

    # Consolidada: polígono principal de 329,2052 ha, lasca de 8 m² e 3 nulos.
    area_main_cons = (a_cons - 8.0) + gap_cons_total
    w_main_cons = area_main_cons / H
    cons_main = _rect(x, Y0, x+w_main_cons, Y0+H)
    for buraco in [gap_grande] + gaps_min:
        cons_main = cons_main.difference(buraco)
    x += w_main_cons
    w_lasca = 8.0 / H
    cons_lasca = _rect(x, Y0, x+w_lasca, Y0+H)
    x += w_lasca
    consolidada = _camada(
        "Área Consolidada", "AREA_CONSOLIDADA",
        [cons_main, cons_lasca], nulos=3
    )
    criadas.append(consolidada)

    # Suprimida antes: gap de 4 m² interno + 0,4 m² fora.
    w_antes = (a_antes + 4.0) / H
    antes_in = _rect(x, Y0, x+w_antes, Y0+H).difference(gap_4)
    x += w_antes
    antes_out = _retangulo_centro(655740.05, 8472600.0, 0.1, 0.4)
    antes = _camada(
        "Área Suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019",
        [antes_in, antes_out]
    )
    criadas.append(antes)

    # Suprimida depois: 2,70857 ha dentro + 99,3 m² fora = 2,7185 ha bruta.
    w_apos = a_apos / H
    apos_in = _rect(x, Y0, x+w_apos, Y0+H)
    x += w_apos
    apos_out = _retangulo_centro(655740.05, 8472068.4, 0.1, 99.3)
    apos = _camada(
        "Área Suprimida depois de 2019", "AREA_SUPRIMIDA_DEPOIS_2019",
        [apos_in, apos_out]
    )
    criadas.append(apos)

    assert abs((X0+1000.0)-x) < 0.001, (X0+1000.0)-x

    # APP cobre o imóvel; Hidrografia ocupa 45 m² do maior buraco.
    app = _camada("APP Total", "APP_TOTAL", [imovel_geom]); criadas.append(app)
    hidro_geom = _retangulo_centro(655052.2, 8471402.1, 5.0, 45.0)
    hidro = _camada("Hidrografia", "HIDROGRAFIA", [hidro_geom]); criadas.append(hidro)

    return criadas, {
        "consolidada": consolidada,
        "apos": apos,
        "apos_bruta_m2": _area_m2_layer(apos),
    }


def _testar_sobreposicao(projeto):
    """Critério 32: 100 m² de sobreposição entre Vegetação e Consolidada."""
    criadas = []
    x, y = 670000.0, 8470000.0
    imovel_geom = _rect(x, y, x+100.0, y+100.0)
    imovel = _camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [imovel_geom]); criadas.append(imovel)
    veg = _camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO",
                  [_rect(x, y, x+50.0, y+100.0)]); criadas.append(veg)
    cons = _camada("Área Consolidada", "AREA_CONSOLIDADA",
                   [_rect(x+49.0, y, x+100.0, y+100.0)]); criadas.append(cons)
    try:
        indice = indice_reconhecimento(projeto)
        dados = calcular_areas(
            criadas, SRID, "Plana UTM", indice,
            pasta_mapa="", configuracao=_config(
                False, ["AREA_CONSOLIDADA", "AREA_DE_VEGETACAO"]
            )
        )
        sobre = dados["fechamento"]["sobreposicoes"]
        assert sobre, sobre
        area_sobre = sum(x["area"] for x in sobre)
        assert abs(area_sobre - 0.01) <= 0.00001, area_sobre
        # v3.9: o quadro resolve a sobreposição pela prioridade e fecha exatamente.
        total = sum(x["area"] for x in dados["fechamento_linhas"]) + dados["fechamento"]["area_sem_classificacao"]
        diferenca = total - dados["valores"]["AREA_DO_IMOVEL"]
        assert abs(diferenca) <= 0.00001, diferenca
        assert abs(dados["valores"]["AREA_CONSOLIDADA"] - 0.51) < 1e-6, dados["valores"]
        assert abs(dados["valores"]["AREA_DE_VEGETACAO"] - 0.49) < 1e-6, dados["valores"]
        texto = "\n".join(str(x.get("verificacao", "")) for x in dados["conferencias"])
        assert "Sobreposição entre" in texto
        t1 = [x for x in dados["conferencias"] if x.get("regra") == "T1" and x.get("situacao") == "AJUSTADO"]
        assert t1 and abs(float(t1[0]["a"]) - 0.01) < 1e-6, t1
        _testar_g9_planilha(dados, False)
    finally:
        projeto.removeMapLayers([x.id() for x in criadas if projeto.mapLayer(x.id())])



def _testar_densificacao_elipsoidal(criadas, indice):
    """G8: fechamento elipsoidal usa densificação uniforme de 10 m e fecha dentro da tolerância."""
    dados = calcular_areas(
        list(criadas), SRID, "Elipsoidal (GRS80, vértices a cada 10 m)", indice,
        pasta_mapa="", configuracao=_config(False)
    )
    assert abs(float(dados.get("densificacao_m") or 0.0) - 10.0) < 1e-9, dados.get("densificacao_m")
    total = sum(x["area"] for x in dados["fechamento_linhas"]) + dados["fechamento"]["area_sem_classificacao"]
    imovel = dados["valores"]["AREA_DO_IMOVEL"]
    # O mesmo limite e as suas partes densificadas uniformemente devem fechar
    # com resíduo inferior a 0,01 m².
    assert abs(total - imovel) * 10000.0 < 0.01, (total, imovel, (total-imovel)*10000.0)
    conf = [
        x for x in dados["conferencias"]
        if str(x.get("verificacao", "")).startswith(
            "Área do imóvel pela calculadora de campo ($area, sem densificar)"
        )
    ]
    assert conf and conf[0].get("situacao") == "OK" and conf[0].get("a") is not None, conf
    # G9: mesmo quando a linha Diferença não aparece no Quadro, o fechamento
    # continua registrado na aba Conferências.
    fechamento_conf = [
        x for x in dados["conferencias"]
        if str(x.get("verificacao", "")) == "Fechamento do imóvel: Total x Área Total do Imóvel"
    ]
    assert fechamento_conf, dados["conferencias"]
    assert fechamento_conf[0].get("situacao") == "OK", fechamento_conf
    assert abs(float(fechamento_conf[0].get("a") or 0.0) - float(fechamento_conf[0].get("b") or 0.0)) < 0.0001, fechamento_conf
    _testar_g9_planilha(dados, False)
    return dados


def _testar_regras_v38(projeto):
    """V3.8: confere R2 e P6 com problemas controlados, sem gravar arquivos."""
    criadas=[]
    x,y=690000.0,8475000.0
    imovel=_camada("Área Total do Imóvel","AREA_DO_IMOVEL",[_rect(x,y,x+100,y+100)]); criadas.append(imovel)
    app_total=_camada("APP Total","APP_TOTAL",[_rect(x,y,x+20,y+100)]); criadas.append(app_total)
    app_pres=_camada("APP Preservada","APP_PRESERVADA",[_rect(x,y,x+7,y+100)]); criadas.append(app_pres)
    app_cons=_camada("APP Consolidada","APP_CONSOLIDADA",[_rect(x+7,y,x+12,y+100)]); criadas.append(app_cons)
    app_ant=_camada("APP Suprimida antes de 2019","APP_ANTROPIZADA_ANTES_2019",[_rect(x+12,y,x+15,y+100)]); criadas.append(app_ant)
    # Deixa 288,9 m² de APP Total sem subclasse e 38,4 m² sobrepostos entre subclasses.
    app_apos=_camada("APP Suprimida depois de 2019","APP_ANTROPIZADA_APOS_2019",[_rect(x+14.616,y,x+17.111,y+100)]); criadas.append(app_apos)
    app_sup=_camada("APP Suprimida","APP_SUPRIMIDA",[_rect(x+12,y,x+17.111,y+100)]); criadas.append(app_sup)
    rl=_camada("Área de Reserva Legal","RESERVA_LEGAL",[_rect(x+60,y,x+90,y+100)]); criadas.append(rl)
    cons=_camada("Área Consolidada","AREA_CONSOLIDADA",[_rect(x+80,y,x+100,y+100)]); criadas.append(cons)
    veg=_camada("Área de Vegetação Nativa","AREA_DE_VEGETACAO",[_rect(x+20,y,x+80,y+100)]); criadas.append(veg)
    antes=_camada("Área Suprimida antes de 2019","AREA_SUPRIMIDA_ANTES_2019",[_rect(x+90,y,x+95,y+100)]); criadas.append(antes)
    apos=_camada("Área Suprimida depois de 2019","AREA_SUPRIMIDA_DEPOIS_2019",[_rect(x+95,y,x+100,y+100)]); criadas.append(apos)
    try:
        dados=calcular_areas(criadas,SRID,"Plana UTM",indice_reconhecimento(projeto),pasta_mapa="",configuracao=_config(False))
        conf=dados.get("conferencias",[])
        r2=[c for c in conf if str(c.get("regra",""))=="R2"]
        assert r2 and any("Sobreposição" in str(c.get("verificacao","")) for c in r2), r2
        assert any("sem cobertura" in str(c.get("verificacao","")).lower() for c in r2), r2
        d2=[x for x in dados.get("problemas_detalhados",[]) if x.get("regra")=="R2"]
        areas={x.get("tipo"):float(x.get("area_ha") or 0.0)*10000.0 for x in d2}
        assert abs(areas.get("Sem cobertura",0.0)-288.9)<0.5, areas
        assert abs(areas.get("Sobreposição",0.0)-38.4)<0.5, areas
        p6=[c for c in conf if str(c.get("regra",""))=="P6"]
        assert p6 and any(c.get("situacao")=="VERIFICAR" for c in p6), p6
        detalhados=dados.get("problemas_detalhados",[])
        assert any(x.get("regra")=="R2" and x.get("tipo")=="Sobreposição" for x in detalhados), detalhados
        assert any(x.get("regra")=="P6" and x.get("situacao")=="VERIFICAR" for x in detalhados), detalhados
    finally:
        projeto.removeMapLayers([x.id() for x in criadas if projeto.mapLayer(x.id())])


def _testar_regras_supressao_v38(projeto):
    """V3.8: reproduz R4 com 14,1 m² sobrepostos/4,0 m² fora e R5 com 49,1 m² sem classificação."""
    criadas=[]; x,y=710000.0,8476000.0; h=100.0
    imovel=_camada("Área Total do Imóvel","AREA_DO_IMOVEL",[_rect(x,y,x+100,y+h)]); criadas.append(imovel)
    antes=_camada("Área Suprimida antes de 2019","AREA_SUPRIMIDA_ANTES_2019",[_rect(x,y,x+20,y+h)]); criadas.append(antes)
    depois=_camada("Área Suprimida depois de 2019","AREA_SUPRIMIDA_DEPOIS_2019",[_rect(x+30,y,x+50,y+h)]); criadas.append(depois)
    app_a=_camada("APP Suprimida antes de 2019","APP_ANTROPIZADA_ANTES_2019",[_rect(x,y,x+8,y+h)]); criadas.append(app_a)
    app_d=_camada("APP Suprimida depois de 2019","APP_ANTROPIZADA_APOS_2019",[_rect(x+30,y,x+38,y+h)]); criadas.append(app_d)
    # RESERVA_SUPRIMIDA produz, por interseção, as parcelas temporais de R4/R5.
    rl=_camada("Área de Reserva Legal Suprimida","RESERVA_SUPRIMIDA",[_rect(x+8,y,x+14,y+h),_rect(x+38,y,x+44,y+h)]); criadas.append(rl)
    # R4: 14,1 m² de sobreposição com RL e 4,0 m² fora do todo.
    pass_a=_camada("Supressão em Área Passível antes de 2019","SUPRESSAO_PASSIVEL_ANTES_2019",[_rect(x+13.859,y,x+20.04,y+h)]); criadas.append(pass_a)
    # R5: deixa 49,1 m² sem cobertura entre RL e passível.
    pass_d=_camada("Supressão em Área Passível após 2019","SUPRESSAO_PASSIVEL_DEPOIS_2019",[_rect(x+44.491,y,x+50,y+h)]); criadas.append(pass_d)
    try:
        dados=calcular_areas(criadas,SRID,"Plana UTM",indice_reconhecimento(projeto),pasta_mapa="",configuracao=_config(False))
        det=dados.get("problemas_detalhados",[])
        r4=[z for z in det if z.get("regra")=="R4"]; r5=[z for z in det if z.get("regra")=="R5"]
        r4_sobre=sum(float(z.get("area_ha") or 0.0)*10000.0 for z in r4 if z.get("tipo")=="Sobreposição")
        r4_fora=sum(float(z.get("area_ha") or 0.0)*10000.0 for z in r4 if z.get("tipo")=="Fora do todo")
        r5_sem=sum(float(z.get("area_ha") or 0.0)*10000.0 for z in r5 if z.get("tipo")=="Sem cobertura")
        assert abs(r4_sobre-14.1)<0.5,(r4_sobre,r4)
        assert abs(r4_fora-4.0)<0.5,(r4_fora,r4)
        assert abs(r5_sem-49.1)<0.5,(r5_sem,r5)
        assert all(z.get("como_resolver") for z in r4+r5), r4+r5
    finally:
        projeto.removeMapLayers([z.id() for z in criadas if projeto.mapLayer(z.id())])

def _executar_tudo():
    projeto = QgsProject.instance()
    _testar_tela_areas_preenchimento(projeto)
    criadas = []
    try:
        criadas, refs = _caso_principal(projeto)
        indice = indice_reconhecimento(projeto)
        snapshot = {
            lyr.id(): (lyr.featureCount(), round(_area_m2_layer(lyr), 6))
            for lyr in criadas
        }

        dados = calcular_areas(
            list(criadas), SRID, "Plana UTM", indice,
            pasta_mapa="", configuracao=_config(False)
        )

        # Critério 29.
        linha_apos = next(
            x for x in dados["todas"]
            if x.get("reconhecida") == "AREA_SUPRIMIDA_DEPOIS_2019"
            and x.get("area_bruta") is not None
        )
        assert abs(linha_apos["area_bruta"] - 2.7185) < 0.00005, linha_apos
        assert abs(linha_apos["fora_imovel"] - 0.00993) < 0.00005, linha_apos
        assert abs(linha_apos["area_considerada"] - 2.70857) < 0.00005, linha_apos

        # Critério 30.
        sem = dados["fechamento"]["area_sem_classificacao"]
        assert abs(sem*10000.0 - 202.7) < 1.0, sem
        total = sum(x["area"] for x in dados["fechamento_linhas"]) + sem
        assert abs(total - dados["valores"]["AREA_DO_IMOVEL"]) <= 0.0001
        assert not dados["fechamento"]["sobreposicoes"]

        # v0.4.0: com a regra da água (padrão do plugin), os 45 m² de rio saem de "sem classificação" e entram na
        # linha Hidrografia do quadro do imóvel; o total continua fechando.
        dados_agua = calcular_areas(list(criadas), SRID, "Plana UTM", indice, pasta_mapa="", configuracao=_config(False, agua=True))
        sem_agua = dados_agua["fechamento"]["area_sem_classificacao"]
        linha_h = [x for x in dados_agua["fechamento_linhas"]
                   if any(str(a).endswith("HIDROGRAFIA") for a in x.get("arquivos", []))]
        assert linha_h and abs(linha_h[0]["area"] * 10000.0 - 45.0) < 1.0, linha_h
        assert abs((sem - sem_agua) * 10000.0 - 45.0) < 1.0, (sem, sem_agua)
        total_a = sum(x["area"] for x in dados_agua["fechamento_linhas"]) + sem_agua
        assert abs(total_a - dados_agua["valores"]["AREA_DO_IMOVEL"]) <= 0.0001

        # Critério 31.
        conf = "\n".join(str(x.get("verificacao", "")) for x in dados["conferencias"])
        assert "99.3 m²" in conf and "655740" in conf and "8472068" in conf, conf
        assert "Área do imóvel sem classe" in conf and "655052" in conf and "8471402" in conf, conf
        assert "dentro de APP Total" in conf and "45.0 m² sobre Hidrografia" in conf, conf
        assert "Registros sem geometria ignorados: Área Consolidada - 3" in conf, conf
        assert "Mesmo arquivo carregado 2 vezes" in conf, conf

        # Critério 33.
        lid1 = atualizar_camada_conferencia(dados, SRID, True)
        lid2 = atualizar_camada_conferencia(dados, SRID, True)
        conf_layers = [
            l for l in projeto.mapLayers().values()
            if str(l.customProperty("norteagro/conferencia", "") or "") == "1"
        ]
        assert lid1 and lid2 and len(conf_layers) == 1 and conf_layers[0].id() == lid2

        # Critério 34, parcela verificável com camadas em memória.
        for lyr in criadas:
            assert snapshot[lyr.id()] == (lyr.featureCount(), round(_area_m2_layer(lyr), 6))
        assert refs["consolidada"].featureCount() == 5
        assert abs(_area_m2_layer(refs["apos"]) / 10000.0 - 2.7185) < 0.00005

        # Critério 35.
        dados_h = calcular_areas(
            list(criadas), SRID, "Plana UTM", indice,
            pasta_mapa="", configuracao=_config(True)
        )
        queda = (
            dados["fechamento"]["area_sem_classificacao"]
            - dados_h["fechamento"]["area_sem_classificacao"]
        ) * 10000.0
        assert abs(queda - 45.0) < 0.5, queda

        # G8: densificação elipsoidal uniforme e conferência do valor sem densificar.
        _testar_densificacao_elipsoidal(criadas, indice)

        # Critério 32, cenário separado.
        _testar_sobreposicao(projeto)
        # V3.8: regras de consistência R2/P6 e problemas estruturados.
        _testar_regras_v38(projeto)
        # V3.8: R4/R5 reproduzem sobreposição, parte fora do todo e falta de classificação.
        _testar_regras_supressao_v38(projeto)
        # V3.9: resolução topológica do quadro, arredondamento e layout.
        executar_v39()
        _testar_casos_reais_v394(projeto)
        _testar_lugar_quadro_v396(projeto)
        _testar_modelos_v396()

        print(
            "OK - TelaAreas 3.8.1 + critérios 29-35 + G8/G9 + regras v3.8: área bruta/considerada, 202,7 m² sem classe, "
            "99,3 m² fora nas coordenadas esperadas, 3 nulos, duplicidade, "
            "sobreposição, R2/R4/R5/P6, camada de conferência, hidrografia e fechamento elipsoidal densificado validados."
        )
        return True
    finally:
        ids = []
        for lyr in list(criadas):
            try:
                if projeto.mapLayer(lyr.id()):
                    ids.append(lyr.id())
            except Exception:
                pass
        ids += [
            l.id() for l in projeto.mapLayers().values()
            if str(l.customProperty("norteagro/conferencia", "") or "") == "1"
        ]
        if ids:
            projeto.removeMapLayers(list(dict.fromkeys(ids)))


# ---------------------------------------------------------------- v3.9.0

def _unidades(v):
    return int(round(float(v) * 10000.0))


def _conf(dados, regra, situacao=None):
    return [x for x in dados.get("conferencias", []) if str(x.get("regra", "")) == regra
            and (situacao is None or x.get("situacao") == situacao)]


def _layout_planilha_ok(caminho):
    """Títulos dos quadros com altura normal, sem "(ver obs.)", quadros pareados na mesma linha e nada sobreposto."""
    import re
    with zipfile.ZipFile(caminho) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    alturas = {}
    for num, attrs in re.findall(r'<row r="(\d+)"([^>]*)>', xml):
        m = re.search(r'ht="([0-9.]+)"', attrs)
        if m:
            alturas[int(num)] = float(m.group(1))

    def faixa(ref):
        a, b = ref.split(":")
        def rc(c):
            m = re.match(r"([A-Z]+)(\d+)", c); col = 0
            for ch in m.group(1): col = col * 26 + ord(ch) - 64
            return int(m.group(2)), col
        (r1, c1), (r2, c2) = rc(a), rc(b)
        return r1, c1, r2, c2
    faixas = [faixa(x) for x in re.findall(r'<mergeCell ref="([A-Z]+\d+:[A-Z]+\d+)"', xml)]
    for i in range(len(faixas)):
        for j in range(i + 1, len(faixas)):
            a, b = faixas[i], faixas[j]
            cruza = not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])
            assert not cruza, (a, b)
    titulos = [f for f in faixas if f[0] == f[2] and (f[1], f[3]) in ((2, 3), (5, 6))]
    assert titulos, faixas
    for f in titulos:
        assert alturas.get(f[0], 15.0) <= 24, (f, alturas.get(f[0]))
    esq = sorted(f[0] for f in titulos if f[1] == 2); dir_ = sorted(f[0] for f in titulos if f[1] == 5)
    assert all(r in esq for r in dir_), (esq, dir_)   # cada quadro da direita começa na linha de um da esquerda
    textos = _textos_quadro_xlsx(caminho)
    assert not any("ver obs" in x for x in textos), textos
    assert not any(x.startswith(("Observações", "Atenção", "Valores com ajuste")) for x in textos), textos
    with zipfile.ZipFile(caminho) as z:
        livro = z.read("xl/workbook.xml").decode("utf-8")
    nomes_abas = re.findall(r'<sheet name="([^"]+)"', livro)
    assert nomes_abas[:2] == ["Quadro de Áreas", "Observações"], nomes_abas


def _testar_lasca_e_lacuna(projeto):
    criadas = []
    x, y = 750000.0, 8480000.0
    criadas.append(_camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [_rect(x, y, x+100, y+100)]))
    criadas.append(_camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [_rect(x, y, x+50, y+100)]))
    cons = _rect(x+50.2, y, x+100, y+100).difference(_rect(x+70, y+40, x+80, y+50))
    criadas.append(_camada("Área Consolidada", "AREA_CONSOLIDADA", [cons]))
    try:
        for metodo in ("Plana UTM", "Elipsoidal (GRS80, vértices a cada 10 m)"):
            dados = calcular_areas(criadas, SRID, metodo, indice_reconhecimento(projeto), pasta_mapa="",
                                   configuracao=_config(False, ["AREA_CONSOLIDADA", "AREA_DE_VEGETACAO"]))
            sem = dados["fechamento"]["area_sem_classificacao"]
            assert abs(sem - 0.01) < 0.00002, sem               # lacuna real 10 x 10 m continua
            assert _conf(dados, "T3", "AJUSTADO"), dados["conferencias"]   # fresta de 0,2 m absorvida
            assert _conf(dados, "T4", "AJUSTADO"), dados["conferencias"]
            vq = dados["valores_quadro"]
            assert _unidades(vq["AREA_CONSOLIDADA"]) + _unidades(vq["AREA_DE_VEGETACAO"]) + _unidades(vq["__SEM_FECHAMENTO__"]) \
                == _unidades(vq["AREA_DO_IMOVEL"]), vq
        fd, caminho = tempfile.mkstemp(prefix="norteagro_v39_", suffix=".xlsx"); os.close(fd)
        try:
            gerar_planilha(caminho, dados)
            textos = _textos_quadro_xlsx(caminho)
            assert "Área sem classificação" in textos and "Diferença" not in textos, textos
        finally:
            os.remove(caminho)
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])


def _testar_laco_e_fora_duplicado(projeto):
    criadas = []
    x, y = 730000.0, 8478000.0
    laco = QgsGeometry.fromWkt(
        f"POLYGON(({x} {y},{x+100} {y},{x+100} {y+100},{x} {y+100},{x} {y+50},{x+60} {y+50},"
        f"{x+60} {y+70},{x+20} {y+70},{x+20} {y+30},{x} {y+30},{x} {y}))")
    criadas.append(_camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [_rect(x, y, x+200, y+200)]))
    criadas.append(_camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [laco]))
    fora = _rect(x+210, y, x+212, y+5)
    criadas.append(_camada("Área Consolidada", "AREA_CONSOLIDADA", [_rect(x+100, y, x+200, y+200), fora, QgsGeometry(fora)]))
    try:
        dados = calcular_areas(criadas, SRID, "Plana UTM", indice_reconhecimento(projeto), pasta_mapa="",
                               configuracao=_config(False, ["AREA_CONSOLIDADA", "AREA_DE_VEGETACAO"]))
        veg = next(r for r in dados["todas"] if r.get("reconhecida") == "AREA_DE_VEGETACAO")
        assert abs(veg["area_considerada"] - 0.96) < 0.0001, veg       # método Structure
        g1 = [c for c in dados["conferencias"] if "Geometrias corrigidas" in str(c.get("verificacao", ""))]
        assert g1 and "variação de área -800.0 m²" in g1[0]["verificacao"], g1
        cons = next(r for r in dados["todas"] if r.get("reconhecida") == "AREA_CONSOLIDADA")
        assert abs(cons["fora_imovel"] - 0.001) < 0.00001, cons         # não conta 2 vezes
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])


def _testar_coerencia_app_antropizada(projeto):
    criadas = []
    x, y = 770000.0, 8482000.0
    R = lambda a, b, c, d: _rect(x+a, y+b, x+c, y+d)
    for nome, arq, g in (
        ("Área Total do Imóvel", "AREA_DO_IMOVEL", R(0, 0, 100, 100)),
        ("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", R(0, 0, 50, 100)),
        ("Área Consolidada", "AREA_CONSOLIDADA", R(50, 0, 70, 100)),
        ("Área Suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019", R(70, 0, 85, 100)),
        ("Área Suprimida depois de 2019", "AREA_SUPRIMIDA_DEPOIS_2019", R(85, 0, 100, 100)),
        ("APP Total", "APP_TOTAL", R(0, 0, 100, 20)),
        ("APP Preservada", "APP_PRESERVADA", R(0, 0, 55, 20)),
        ("APP Consolidada", "APP_CONSOLIDADA", R(50, 0, 72, 20)),
        ("APP Suprimida antes de 2019", "APP_ANTROPIZADA_ANTES_2019", R(70, 0, 90, 25)),
        ("APP Suprimida depois de 2019", "APP_ANTROPIZADA_APOS_2019", R(85, 0, 100, 20)),
        ("Área de Reserva Legal Suprimida", "RESERVA_SUPRIMIDA", R(60, 50, 80, 100)),
        ("Supressão em Área Passível antes de 2019", "SUPRESSAO_PASSIVEL_ANTES_2019", R(72, 20, 85, 100)),
        ("Supressão em Área Passível após 2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019", R(85, 20, 100, 100)),
    ):
        criadas.append(_camada(nome, arq, [g]))
    try:
        # v0.4.0: modo padrão - cada camada de APP é a área dela mesma; o Total é a camada APP Total.
        dados = calcular_areas(criadas, SRID, "Plana UTM", indice_reconhecimento(projeto), pasta_mapa="",
                               configuracao=_config(False, app=True))
        vq = dados["valores_quadro"]
        for arq, esperado in (("APP_TOTAL", 0.2), ("APP_PRESERVADA", 0.11), ("APP_CONSOLIDADA", 0.044),
                              ("APP_ANTROPIZADA_ANTES_2019", 0.05), ("APP_ANTROPIZADA_APOS_2019", 0.03)):
            assert abs(vq[arq] - esperado) < 0.00005, (arq, vq[arq], esperado)
        assert "__SEM_APP__" not in vq, vq
        for metodo in ("Plana UTM", "Elipsoidal (GRS80, vértices a cada 10 m)"):
            dados = calcular_areas(criadas, SRID, metodo, indice_reconhecimento(projeto), pasta_mapa="",
                                   configuracao=_config(False))
            vq = dados["valores_quadro"]
            # APP: subclasses somam exatamente a APP Total.
            app = ["APP_PRESERVADA", "APP_CONSOLIDADA", "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019", "__SEM_APP__"]
            assert sum(_unidades(vq[k]) for k in app) == _unidades(vq["APP_TOTAL"]), vq
            # Antropizada antes/após: APP + RL + passível + sem = Área Suprimida do período.
            antes = ["APP_ANTROPIZADA_ANTES_2019", "RL_SUP_ANTES", "SUPRESSAO_PASSIVEL_ANTES_2019", "__SEM_ANTES__"]
            apos = ["APP_ANTROPIZADA_APOS_2019", "RL_SUP_APOS", "SUPRESSAO_PASSIVEL_DEPOIS_2019", "__SEM_APOS__"]
            assert sum(_unidades(vq[k]) for k in antes) == _unidades(vq["AREA_SUPRIMIDA_ANTES_2019"]), vq
            assert sum(_unidades(vq[k]) for k in apos) == _unidades(vq["AREA_SUPRIMIDA_DEPOIS_2019"]), vq
            fech = ["AREA_DE_VEGETACAO", "AREA_CONSOLIDADA", "AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019", "__SEM_FECHAMENTO__"]
            assert sum(_unidades(vq[k]) for k in fech) == _unidades(vq["AREA_DO_IMOVEL"]), vq
            if metodo == "Plana UTM":
                esperado = {"APP_PRESERVADA": 0.1, "APP_CONSOLIDADA": 0.04, "APP_ANTROPIZADA_ANTES_2019": 0.03,
                            "APP_ANTROPIZADA_APOS_2019": 0.03, "RL_SUP_ANTES": 0.05, "SUPRESSAO_PASSIVEL_ANTES_2019": 0.064,
                            "__SEM_ANTES__": 0.006, "SUPRESSAO_PASSIVEL_DEPOIS_2019": 0.12, "AREA_SUPRIMIDA_ANTES_2019": 0.15}
                for k, v in esperado.items():
                    assert abs(vq[k] - v) < 0.00001, (k, vq[k], v)
                assert len(_conf(dados, "T2", "AJUSTADO")) >= 2, _conf(dados, "T2")
                assert _conf(dados, "T1", "AJUSTADO"), dados["conferencias"]
        fd, caminho = tempfile.mkstemp(prefix="norteagro_v39_", suffix=".xlsx"); os.close(fd)
        try:
            gerar_planilha(caminho, dados)
            _layout_planilha_ok(caminho)
            textos = _textos_quadro_xlsx(caminho)
            assert "Diferença" not in textos, textos
        finally:
            os.remove(caminho)
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])


def _testar_arredondamento(projeto):
    criadas = []
    x, y, h = 790000.0, 8484000.0, 70.3692
    w1, w2 = 12345.4 / h, 23456.4 / h
    criadas.append(_camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [_rect(x, y, x+1000, y+h)]))
    criadas.append(_camada("Área Consolidada", "AREA_CONSOLIDADA", [_rect(x, y, x+w1, y+h)]))
    criadas.append(_camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [_rect(x+w1, y, x+w1+w2, y+h)]))
    criadas.append(_camada("Área Suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019", [_rect(x+w1+w2, y, x+1000, y+h)]))
    try:
        dados = calcular_areas(criadas, SRID, "Plana UTM", indice_reconhecimento(projeto), pasta_mapa="",
                               configuracao=_config(False, ["AREA_CONSOLIDADA", "AREA_DE_VEGETACAO", "AREA_SUPRIMIDA_ANTES_2019"]))
        vq = dados["valores_quadro"]
        assert _unidades(vq["AREA_DO_IMOVEL"]) == 70369, vq
        soma = sum(_unidades(vq[k]) for k in ("AREA_CONSOLIDADA", "AREA_DE_VEGETACAO", "AREA_SUPRIMIDA_ANTES_2019", "__SEM_FECHAMENTO__"))
        assert soma == 70369, (soma, vq)
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])


def executar_v39():
    projeto = QgsProject.instance()
    _testar_lasca_e_lacuna(projeto)
    _testar_laco_e_fora_duplicado(projeto)
    _testar_coerencia_app_antropizada(projeto)
    _testar_arredondamento(projeto)
    print("OK - v3.9.0: lasca absorvida, lacuna real mantida, laço corrigido por Structure, fora sem dupla contagem, "
          "APP e antropizadas coerentes e fechando, arredondamento exato e layout da planilha.")
    return True



def _testar_casos_reais_v394(projeto):
    """Casos encontrados em projetos reais de clientes."""
    from .areas import _reconhecer_basico
    from .catalogo import apelidos_para_indice
    idx = indice_reconhecimento(projeto); tab, alias, _ = apelidos_para_indice(idx)
    def rec(nome):
        l = QgsVectorLayer("Polygon?crs=EPSG:31982", nome, "memory")
        return _reconhecer_basico(l, idx, alias, tab, {}).get("arquivo", "")
    # Compensação nunca vira supressão; nomes sem acento e com palavra a mais são reconhecidos.
    for nome in ("Compensação por supressão em APP", "Compensação por supressão em reserva",
                 "Compensação por supressão em área passível"):
        assert rec(nome) == "", (nome, rec(nome))
    assert rec("supresso_em_rea_passvel_aps_2019") == "SUPRESSAO_PASSIVEL_DEPOIS_2019"
    assert rec("supresso_em_rea_passvel__antes_de_2019") == "SUPRESSAO_PASSIVEL_ANTES_2019"
    assert rec("hidrografia rio") == "HIDROGRAFIA" and rec("nascente gps") == "NASCENTE"
    assert rec("area consolidada em app") == ""  # ambíguo: não arrisca

    criadas = []
    x, y = 760000.0, 8486000.0
    R = lambda a, b, c, d: _rect(x+a, y+b, x+c, y+d)
    criadas.append(_camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [R(0, 0, 100, 100)]))
    criadas.append(_camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [R(0, 0, 60, 100)]))
    criadas.append(_camada("Área Consolidada", "AREA_CONSOLIDADA", [R(60, 0, 80, 100)]))
    criadas.append(_camada("Área Suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019", [R(80, 0, 90, 100)]))
    criadas.append(_camada("Área Suprimida depois de 2019", "AREA_SUPRIMIDA_DEPOIS_2019", [R(90, 0, 100, 100)]))
    # RL proposta em outro lugar; a supressão aconteceu na RL antiga (dentro da suprimida depois).
    criadas.append(_camada("Área de Reserva Legal", "RESERVA_LEGAL", [R(0, 0, 30, 100)]))
    criadas.append(_camada("Área de Reserva Legal Suprimida", "RESERVA_SUPRIMIDA", [R(90, 0, 100, 50)]))
    # Camada sem SRC com coordenadas UTM.
    sem_src = QgsVectorLayer("Polygon?field=id:integer", "Supressão em área passível após 2019", "memory")
    sem_src.setCustomProperty("norteagro/arquivo", "SUPRESSAO_PASSIVEL_DEPOIS_2019")
    f = QgsFeature(sem_src.fields()); f.setAttribute("id", 1); f.setGeometry(R(90, 50, 100, 100))
    sem_src.dataProvider().addFeature(f); sem_src.updateExtents(); QgsProject.instance().addMapLayer(sem_src); criadas.append(sem_src)
    try:
        dados = calcular_areas(criadas, SRID, "Plana UTM", idx, pasta_mapa="", configuracao=_config(False))
        vq = dados["valores_quadro"]
        assert abs(vq["RL_SUP_APOS"] - 0.05) < 1e-6, vq          # não zera a RL suprimida
        assert abs(vq["SUPRESSAO_PASSIVEL_DEPOIS_2019"] - 0.05) < 1e-6, vq   # camada sem SRC não some
        assert any(c.get("regra") == "G4" for c in dados["conferencias"])
        assert any(c.get("regra") == "P2" and c.get("situacao") == "ALERTA" for c in dados["conferencias"])
        tot = [c for c in dados["conferencias"] if str(c.get("verificacao", "")).startswith(("Fechamento do imóvel", "Total Área antropizada após"))]
        assert tot and all(c.get("situacao") != "ALERTA" and abs(float(c["a"]) - float(c["b"])) < 0.0001 for c in tot), tot
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])
    print("OK - v3.9.4: compensação x supressão, nomes sem acento/palavra a mais, RL relocada, camada sem SRC.")


def _testar_lugar_quadro_v396(projeto):
    """Camadas criadas com nome novo entram no quadro escolhido, sem dupla contagem."""
    idx = dict(indice_reconhecimento(projeto))
    def nova(arq, nome, quadro=None, tipo="P"):
        e = {"arquivo": arq, "nome": nome, "nome_exibicao": nome, "tipo": tipo, "grupo": "Teste",
             "personalizada": True, "origem": "projeto", "estilo_xml": ""}
        if quadro is not None:
            e["quadro"] = quadro
        idx[arq] = e
    nova("TESTE_PASTAGEM", "Área de Pastagem", "IMOVEL")
    nova("TESTE_EMBARGO", "Área Embargada", "PASSIVOS")
    nova("TESTE_REPRESA", "Represa nova", "HIDRO")
    nova("TESTE_COMPENSA", "Compensação nova", "COMPENSACAO")
    nova("TESTE_ANTIGA", "Camada antiga sem lugar")            # sem o campo: Outras camadas
    nova("TESTE_FORA", "Só consulta", "NENHUM")
    criadas = []
    x, y = 760000.0, 8486000.0
    R = lambda a, b, c, d: _rect(x+a, y+b, x+c, y+d)
    criadas.append(_camada("Área Total do Imóvel", "AREA_DO_IMOVEL", [R(0, 0, 100, 100)]))
    criadas.append(_camada("Área de Vegetação Nativa", "AREA_DE_VEGETACAO", [R(0, 0, 50, 100)]))
    criadas.append(_camada("Área Consolidada", "AREA_CONSOLIDADA", [R(50, 0, 70, 100)]))
    criadas.append(_camada("Área Suprimida antes de 2019", "AREA_SUPRIMIDA_ANTES_2019", [R(70, 0, 75, 100)]))
    criadas.append(_camada("Área Suprimida depois de 2019", "AREA_SUPRIMIDA_DEPOIS_2019", [R(75, 0, 80, 100)]))
    criadas.append(_camada("Área de Pastagem", "TESTE_PASTAGEM", [R(78, 0, 100, 100)]))      # 2 m sobre a suprimida
    criadas.append(_camada("Área Embargada", "TESTE_EMBARGO", [R(70, 0, 90, 50)]))           # metade sobre as suprimidas
    criadas.append(_camada("Represa nova", "TESTE_REPRESA", [R(0, 0, 10, 10)]))
    criadas.append(_camada("Compensação nova", "TESTE_COMPENSA", [R(0, 90, 20, 100)]))
    criadas.append(_camada("Camada antiga sem lugar", "TESTE_ANTIGA", [R(0, 0, 30, 10)]))
    criadas.append(_camada("Só consulta", "TESTE_FORA", [R(0, 0, 10, 10)]))
    saida = os.path.join(tempfile.gettempdir(), "norteagro_teste_lugar_quadro.xlsx")
    try:
        dados = calcular_areas(criadas, SRID, "Plana UTM", idx, pasta_mapa="", configuracao=_config(False))
        vq = dados["valores_quadro"]
        assert "TESTE_PASTAGEM" in dados["fechamento_classes"], dados["fechamento_classes"]
        assert abs(vq["TESTE_PASTAGEM"] - 0.20) < 1e-6, vq.get("TESTE_PASTAGEM")          # perdeu os 2 m da suprimida
        assert abs(vq["AREA_SUPRIMIDA_DEPOIS_2019"] - 0.05) < 1e-6, vq                    # a classe padrão não perde nada
        fech = [c for c in dados["conferencias"] if str(c.get("verificacao", "")).startswith("Fechamento do imóvel")]
        assert fech and fech[0].get("situacao") == "OK", fech
        assert abs(vq["TESTE_EMBARGO"] - 0.05) < 1e-6, vq.get("TESTE_EMBARGO")            # descontou 0,05 ha das suprimidas
        assert abs(vq["TESTE_REPRESA"] - 0.01) < 1e-6 and abs(vq["TESTE_COMPENSA"] - 0.02) < 1e-6
        assert any(c.get("regra") == "T1" and "Área Embargada" in str(c.get("verificacao")) for c in dados["conferencias"])
        assert any(c.get("regra") == "T1" and "Área de Pastagem" in str(c.get("verificacao")) for c in dados["conferencias"])
        lp = dados["linhas_personalizadas"]
        assert [x["arquivo"] for x in lp.get("Passivos ambientais", [])] == ["TESTE_EMBARGO"], lp
        assert [x["arquivo"] for x in lp.get("Área Hidrográfica", [])] == ["TESTE_REPRESA"], lp
        assert [x["arquivo"] for x in lp.get("Área Total de Compensação", [])] == ["TESTE_COMPENSA"], lp
        assert [x["arquivo"] for x in dados["outras"]] == ["TESTE_ANTIGA"], dados["outras"]
        assert dados["quadro_origens"].get("TESTE_EMBARGO") == "Passivos ambientais"
        assert "TESTE_FORA" not in dados["quadro_origens"]
        gerar_planilha(saida, dados)
        _layout_planilha_ok(saida)
        import openpyxl
        ws = openpyxl.load_workbook(saida)["Quadro de Áreas"]
        cel = {}
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.column in (2, 5):
                    cel.setdefault(c.value, ws.cell(c.row, c.column + 1).value)
        assert abs(cel.get("Área de Pastagem") - 0.2) < 1e-9, cel
        assert abs(cel.get("Área Embargada") - 0.05) < 1e-9, cel
        assert abs(cel.get("Represa nova") - 0.01) < 1e-9 and abs(cel.get("Compensação nova") - 0.02) < 1e-9, cel
        assert "Camada antiga sem lugar" in cel and "Só consulta" not in cel, cel
        todas = openpyxl.load_workbook(saida)["Todas as camadas"]
        assert any(r[1] == "Só consulta" for r in todas.iter_rows(values_only=True)), "Só consulta fora de Todas as camadas"
    finally:
        projeto.removeMapLayers([c.id() for c in criadas if projeto.mapLayer(c.id())])
        try: os.remove(saida)
        except Exception: pass
    print("OK - v3.9.6: camada nova no quadro escolhido (imóvel, passivos, hidrografia, compensação, outras, fora), sem dupla contagem.")


def _testar_modelos_v396():
    """Modelos do escritório num catálogo temporário: pastas, tabela e planilha (nunca toca o drive G:)."""
    import shutil
    import openpyxl
    from . import catalogo, modelos as M
    from .tela_modelos import dados_exemplo
    from .testes_interface import apontar_catalogo
    tmp = tempfile.mkdtemp(prefix="norteagro_modelos_")
    desfazer_catalogo = apontar_catalogo(os.path.join(tmp, "catalogo_extra.json"))   # nunca grava no catálogo real
    try:
        M.salvar_modelo_pasta({"nome": "Teste", "pastas": ["layout", "documentos/fotos"], "camadas": [{"arquivo": "AREA_DO_IMOVEL"}]})
        criadas = M.criar_pastas(os.path.join(tmp, "MAPA"), M.modelo_pasta("Teste"))
        assert set(criadas) == {"MAPA/shapefiles", "MAPA/kml", "MAPA/projetos", "MAPA/layout", "MAPA/documentos/fotos"}, criadas
        for ruim in ("shapefiles/x", "a/../b", "c:*"):
            try:
                M.limpar_subpasta(ruim, ""); raise AssertionError(ruim)
            except ValueError:
                pass
        # v0.0.0: várias pastas mãe; a pasta do mapa numa subpasta; nomes trocados ao criar
        mm = {"nome": "Maes", "formato_pastas": 2, "pasta_mapa": "FAZENDA NORTE/03 Mapas/QGIS",
              "pastas": ["FAZENDA NORTE/01 Documentos/CAR/2026", "FAZENDA NORTE/03 Mapas/QGIS/kml", "FAZENDA NORTE/03 Mapas/QGIS/layout",
                         "OUTRA MAE/Licencas", "TERCEIRA"]}
        assert M.pastas_maes(mm) == ["FAZENDA NORTE", "OUTRA MAE", "TERCEIRA"] and M.normalizar_modelo_pasta(mm)["gerar_kml"]
        base = os.path.join(tmp, "CLIENTES"); mapa_m = M.caminho_pasta_mapa(base, mm)
        criadas = M.criar_pastas(mapa_m, mm)
        assert set(criadas) == {"FAZENDA NORTE/01 Documentos/CAR/2026", "FAZENDA NORTE/03 Mapas/QGIS/kml", "FAZENDA NORTE/03 Mapas/QGIS/layout",
                                "OUTRA MAE/Licencas", "TERCEIRA"}, criadas
        assert os.path.normcase(M.pasta_base(mapa_m, mm)) == os.path.normcase(base) and M.pasta_base(os.path.join(tmp, "OUTRA"), mm) is None
        ren = M.renomear_maes(mm, {"FAZENDA NORTE": "Fazenda Sol"}); mapa_r = M.caminho_pasta_mapa(os.path.join(tmp, "C2"), ren)
        assert mapa_r.endswith(os.path.join("Fazenda Sol", "03 Mapas", "QGIS"))
        assert "Fazenda Sol/03 Mapas/QGIS/layout" in M.criar_pastas(mapa_r, mm), "nome trocado no disco: o modelo original se ajusta"
        assert os.path.isdir(os.path.join(tmp, "C2", "OUTRA MAE", "Licencas"))
        assert M.limpar_subpasta("kml/x", "FAZENDA NORTE/03 Mapas/QGIS") == "kml/x"
        try:
            M.limpar_subpasta("FAZENDA NORTE/03 Mapas/QGIS/kml/x", "FAZENDA NORTE/03 Mapas/QGIS"); raise AssertionError("kml dentro da pasta do mapa")
        except ValueError:
            pass
        outra = os.path.join(tmp, "SOLTA", "QGIS"); os.makedirs(outra)
        assert set(M.criar_pastas(outra, mm)) == {"kml", "layout"}, "pasta do mapa fora do lugar: só cria o que fica dentro dela"
        assert M.normalizar_modelo_pasta(M.modelo_pasta_vazio())["pastas"] == []
        M.salvar_modelo_tabela({"nome": "T", "linhas": {"Total": "TOTAL"}, "colunas": {"m2": True},
                                "quadros": [{"id": "HIDRO", "titulo": "Hidro", "lado": "E", "visivel": False},
                                            {"id": "APP", "titulo": "APP", "lado": "D", "visivel": True}]})
        saida = os.path.join(tmp, "t.xlsx")
        gerar_planilha(saida, dados_exemplo(), M.modelo_tabela("T"))
        ws = openpyxl.load_workbook(saida)["Quadro de Áreas"]
        textos = [c.value for r in ws.iter_rows() for c in r if isinstance(c.value, str)]
        assert "TOTAL" in textos and "Total" not in textos and "m²" in textos and "Área Hidrográfica" not in textos and "Hidro" not in textos, textos
        padrao = os.path.join(tmp, "p.xlsx"); gerar_planilha(padrao, dados_exemplo()); _layout_planilha_ok(padrao)
        M.remover_modelo_tabela("T"); M.remover_modelo_pasta("Teste")
        assert [m["nome"] for m in M.modelos_tabela()] == [M.PADRAO] and [m["nome"] for m in M.modelos_pasta()] == [M.PADRAO]
    finally:
        desfazer_catalogo()
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK - v3.9.6: modelos de pastas e de tabela (catálogo temporário), planilha padrão inalterada.")


def executar():
    """Roda a bateria e devolve ao projeto aberto a marca de "modificado" que ele tinha (v3.9.10)."""
    projeto = QgsProject.instance(); estava = projeto.isDirty()
    try:
        return _executar_tudo()
    finally:
        projeto.setDirty(estava)


if __name__ == "__main__":
    executar()
