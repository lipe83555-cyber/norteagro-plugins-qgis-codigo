# -*- coding: utf-8 -*-
"""v0.3.0: testes da correção das camadas (correcao.py) com camadas em memória e Shapefiles temporários.

Executar DENTRO do console Python do QGIS, com o plugin instalado:

    import norteagro_uso_solo.testes_correcao as t
    print(t.executar())

Cria as camadas num projeto qualquer, confere, corrige, calcula e remove tudo no fim. Não toca nas camadas do usuário.
"""
import os, tempfile


def _camada(nome, tipo, geoms):
    from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject
    lay = QgsVectorLayer(f"{tipo}?crs=EPSG:31982&field=id:integer", nome, "memory")
    fs = []
    for i, w in enumerate(geoms):
        f = QgsFeature(lay.fields()); f.setAttributes([i])
        f.setGeometry(QgsGeometry.fromWkt(w) if w else QgsGeometry())
        fs.append(f)
    lay.dataProvider().addFeatures(fs)
    QgsProject.instance().addMapLayer(lay)
    return lay


def R(x1, y1, x2, y2):
    return f"POLYGON(({x1} {y1},{x2} {y1},{x2} {y2},{x1} {y2},{x1} {y1}))"


def _teste_memoria(pacote):
    import importlib
    from qgis.core import QgsProject
    cat = importlib.import_module(pacote + ".catalogo")
    tmp = tempfile.mkdtemp(prefix="na_corr_")
    cor = importlib.import_module(pacote + ".correcao")
    areas = importlib.import_module(pacote + ".areas")
    pr = QgsProject.instance()
    camadas = [
        _camada("Área do Imóvel", "Polygon", [R(0, 0, 1000, 1000)]),
        _camada("Área de Vegetação Nativa", "Polygon", [
            R(0, 0, 600, 1000), R(1000, 0, 1100, 50), R(0, 0, 600, 1000),
            "POLYGON((300 300, 310 310, 310 300, 300 310, 300 300))", None]),
        _camada("Área Consolidada", "Polygon", [
            "POLYGON((599.5 0,1000 0,1000 1000,600.3 1000,600.3 500,599.5 500,599.5 0))", R(500, 0, 600, 100)]),
        _camada("APP Total", "Polygon", [R(0, 0, 200, 1000)]),
        _camada("APP Preservada", "Polygon", [R(0, 0, 250, 900)]),
        _camada("APP Consolidada", "Polygon", [R(0, 880, 200, 1000)]),
        _camada("Hidrografia", "Polygon", [R(900, 400, 1100, 500)]),
        _camada("Nascentes", "Point", ["POINT(1050 450)"]),
    ]
    saida = []
    try:
        indice = cat.indice_reconhecimento(pr)
        c = cor.Correcao(camadas, "EPSG:31982", indice)
        saida.append("camadas: " + ", ".join(f"{k}->{v.layer.name()}" for k, v in c.camadas.items()))
        rel = c.executar()
        for p in rel["problemas"]:
            saida.append(f"  [{p['acao']}] {p['camada']}: {p['titulo']} {('%.2f m2' % p['area_m2']) if p['area_m2'] else ''} {p['detalhe']}")
        for k in rel["conflitos"]:
            saida.append(f"  CONFLITO {k['id']} area={k['area_m2']:.1f} sugere ceder {k['sugestao']}")
        # usuário escolhe: no conflito de vegetação x consolidada, a CONSOLIDADA cede
        esc = {k["id"]: (k["a"] if "opcoes" not in k and "AREA_DE_VEGETACAO" in (k["a"], k["b"]) and k["b"] == "AREA_DE_VEGETACAO" else k["sugestao"]) for k in rel["conflitos"]}
        esc = {k: ("AREA_CONSOLIDADA" if "AREA_CONSOLIDADA" in k and not k.startswith(("FORA|", "MAE|")) else v) for k, v in esc.items()}
        rel2 = c.executar(esc)
        grav, erros, bk = c.gravar()
        saida.append(f"gravadas={grav} erros={erros}")
        res = areas.calcular_areas(camadas, "EPSG:31982", "Plano UTM", indice)
        saida.append(f"tem_ajustes={res.get('tem_ajustes')}")
        for reg in res["todas"]:
            if reg.get("tipo") == "Polígono":
                saida.append(f"  {reg['nome']}: considerada={reg.get('area_considerada')} quadro={reg.get('area_quadro')} fora={reg.get('fora_imovel')}")
        saida.append("conferência: " + (str(cor.conferir_resultado(res)) or "OK"))
        saida.append("fechamento: " + str([(x["descricao"], round(float(x["area"]), 4)) for x in res.get("fechamento_linhas", [])]))
        for conf in res.get("conferencias", []):
            if conf.get("situacao") in ("AJUSTADO", "ALERTA"):
                saida.append(f"  conf {conf.get('regra')} {conf.get('situacao')}: {conf.get('verificacao')[:160]}")
        # vegetação: esperado 600x1000 - 0 (consolidada cedeu a mancha larga; faixa fina saiu da vegetação)
        saida.append("feições vegetação: " + str([round(f.geometry().area(), 2) for f in camadas[1].getFeatures()]))
        saida.append("feições consolidada: " + str([round(f.geometry().area(), 2) for f in camadas[2].getFeatures()]))
        saida.append("hidro: " + str([round(f.geometry().area(), 2) for f in camadas[6].getFeatures()]))
        saida.append("nascentes: " + str(camadas[7].featureCount()))
    finally:
        for l in camadas:
            pr.removeMapLayer(l.id())
    return "\n".join(saida)





def _shp(pasta, nome, tipo, wkts):
    from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsVectorFileWriter, QgsProject, QgsCoordinateTransformContext
    mem = QgsVectorLayer(f"{tipo}?crs=EPSG:31982&field=id:integer&field=obs:string", nome, "memory")
    fs = []
    for i, w in enumerate(wkts):
        f = QgsFeature(mem.fields()); f.setAttributes([i, f"feicao {i}"]); f.setGeometry(QgsGeometry.fromWkt(w)); fs.append(f)
    mem.dataProvider().addFeatures(fs)
    cam = os.path.join(pasta, nome.replace(" ", "_") + ".shp")
    op = QgsVectorFileWriter.SaveVectorOptions(); op.driverName = "ESRI Shapefile"; op.fileEncoding = "UTF-8"
    QgsVectorFileWriter.writeAsVectorFormatV3(mem, cam, QgsCoordinateTransformContext(), op)
    lay = QgsVectorLayer(cam, nome, "ogr"); QgsProject.instance().addMapLayer(lay)
    return lay


def _teste_shapefiles(pacote):
    import importlib, qgis.utils
    from qgis.core import QgsProject
    cat = importlib.import_module(pacote + ".catalogo")
    tmp = tempfile.mkdtemp(prefix="na_corr2_");
    cor = importlib.import_module(pacote + ".correcao"); areas = importlib.import_module(pacote + ".areas")
    pr = QgsProject.instance(); pasta = os.path.join(tmp, "shapes"); os.makedirs(pasta)
    L = [
        _shp(pasta, "Area do Imovel", "Polygon", [R(0, 0, 1000, 1000)]),
        # U que sai do imóvel pela direita: o recorte gera 2 partes numa camada Polygon (simples)
        _shp(pasta, "Area de Vegetacao Nativa", "Polygon", ["POLYGON((0 0,1200 0,1200 1000,0 1000,0 600,700 600,700 400,0 400,0 0))"]),
        _shp(pasta, "Area Consolidada", "Polygon", [R(0, 400, 700, 600)]),
        _shp(pasta, "Hidrografia", "Polygon", [R(300, 450, 1300, 470)]),
        _shp(pasta, "Barragem", "Polygon", [R(350, 440, 450, 480)]),
        _shp(pasta, "APP Total", "Polygon", [R(250, 380, 1000, 540)]),
        _shp(pasta, "APP Antropizada antes de 2019", "Polygon", [R(300, 400, 400, 420)]),
        _shp(pasta, "Area Suprimida antes de 2019", "Polygon", [R(280, 395, 420, 425)]),
        _shp(pasta, "Supressao Passivel antes de 2019", "Polygon", [R(280, 395, 420, 425)]),
    ]
    out = []
    try:
        indice = cat.indice_reconhecimento(pr)
        c = cor.Correcao(L, "EPSG:31982", indice)
        out.append("camadas: " + ", ".join(c.camadas))
        rel = c.executar()
        for p in rel["problemas"]:
            out.append(f"  [{p['acao']}{'!' if p['grave'] else ''}] {p['camada']}: {p['titulo']} {cor._texto_area(p['area_m2']) if p['area_m2'] else ''}")
        for k in rel["conflitos"]:
            out.append(f"  CONFLITO {k['id']} {k['area_m2']:.1f} m2 sugere {k['sugestao']}")
        # tela (sem abrir)
        tc = importlib.import_module(pacote + ".tela_correcao")
        class P:  # plugin mínimo
            iface = qgis.utils.iface
            def log(self, m): print("LOG", m)
        tela = tc.TelaCorrecao(P(), c, rel)
        out.append(f"tela: {tela.lista.topLevelItemCount()} linhas, escolhas={tela.escolhas()}")
        tela._zoom(rel["conflitos"][0]["geom"] if rel["conflitos"] else None)
        tela.deleteLater()
        c.executar(tela.escolhas())
        grav, erros, bk = c.gravar()
        out.append(f"gravadas={grav} erros={erros} backups={len(bk)} ok={all(os.path.isdir(b) for b in bk)}")
        res = areas.calcular_areas(L, "EPSG:31982", "Elipsoidal (GRS80, vértices a cada 10 m)", indice)
        out.append(f"tem_ajustes={res.get('tem_ajustes')} conferir={cor.conferir_resultado(res, indice=indice)}")
        for reg in res["todas"]:
            if reg.get("tipo") == "Polígono":
                out.append(f"  {reg['nome']}: considerada={reg.get('area_considerada'):.4f} quadro={reg.get('area_quadro'):.4f}")
        for conf in res.get("conferencias", []):
            if conf.get("situacao") in ("AJUSTADO", "ALERTA"):
                out.append(f"  conf {conf.get('regra')} {conf.get('situacao')}: {str(conf.get('verificacao'))[:150]}")
        veg = L[1]; out.append(f"vegetação feições={veg.featureCount()} attrs={[f.attributes() for f in veg.getFeatures()]}")
        # segunda passada: nada mais a corrigir
        c2 = cor.Correcao(L, "EPSG:31982", indice); r2 = c2.executar()
        out.append("2a passada: " + str([(p['camada'], p['titulo']) for p in r2["problemas"]]) + f" conflitos={len([k for k in r2['conflitos'] if not k['id'].startswith('SEMCLASSE|')])}")
    finally:
        for l in L: pr.removeMapLayer(l.id())
    return "\n".join(out)


def executar():
    pacote = __package__ or "norteagro_uso_solo"
    s1 = _teste_memoria(pacote)
    s2 = _teste_shapefiles(pacote)
    ok = "('Hidrografia', 1.0)" in s1 and "conferência: []" in s1 and "conferir=[]" in s2 and "erros=[]" in s1 and "erros=[]" in s2 and "conflitos=0" in s2
    return ("TUDO CERTO\n" if ok else "FALHOU - veja abaixo\n") + s1 + "\n==========\n" + s2
