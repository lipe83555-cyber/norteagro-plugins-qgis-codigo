# -*- coding: utf-8 -*-
"""Rodada de testes de interface de ponta a ponta (v3.9.9).

Uso no Terminal Python do QGIS:
    from norteagro_uso_solo import testes_interface; testes_interface.executar()

Usa catálogo, modelos e pastas TEMPORÁRIOS, camadas de teste com nomes próprios e restaura o
projeto aberto no fim (camadas, variáveis, pasta do mapa). Não troca nenhuma função do Qt/QGIS:
as respostas das mensagens são simuladas só dentro dos módulos do plugin.
"""
import json
import os
import shutil
import tempfile
import time
import traceback

import qgis.utils
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMenu, QPushButton, QTreeWidget, QTreeWidgetItemIterator
from qgis.core import (
    QgsExpressionContextUtils, QgsFeature, QgsFillSymbol, QgsGeometry, QgsProject, QgsRectangle, QgsSettings,
    QgsSingleSymbolRenderer, QgsVectorLayer,
)

X0, Y0 = 760000.0, 8486000.0
VARS = ["norteagro_pasta", "norteagro_srid", "norteagro_extras", "norteagro_modelo_pasta", "norteagro_grupos", "norteagro_kml_automatico", "norteagro_nomes_maes"]
MODULOS = ["plugin", "tela_nova_camada", "tela_camadas", "tela_modelos", "tela_inicial", "tela_areas", "tela_padronizar",
           "tela_substituir", "pasta", "tela_referencias", "tela_escolha", "tela_avulsa"]


class _Rodada:
    def __init__(self):
        self.res = []; self.reg = []; self.resp = True; self.patches = []

    def ok(self, nome, cond, info=""):
        self.res.append(("OK " if cond else "FALHOU ") + nome + (f" ({info})" if info else ""))

    def trocar(self, obj, nome, valor):
        self.patches.append((obj, nome, getattr(obj, nome), nome in getattr(obj, "__dict__", {})))
        setattr(obj, nome, valor)

    def desfazer(self):
        for obj, nome, antigo, proprio in reversed(self.patches):
            try:
                if proprio: setattr(obj, nome, antigo)
                else: delattr(obj, nome)
            except Exception:
                pass
        self.patches.clear()


def _ret(a, b, c, d):
    return QgsGeometry.fromRect(QgsRectangle(X0 + a, Y0 + b, X0 + c, Y0 + d))


def _desenhar(camada, *geoms):
    feats = []
    for g in geoms:
        f = QgsFeature(camada.fields()); f.setGeometry(g); feats.append(f)
    camada.dataProvider().addFeatures(feats); camada.updateExtents(); camada.reload()


def _salvar_edicao(camada, geom):
    camada.startEditing(); f = QgsFeature(camada.fields()); f.setGeometry(geom); camada.addFeature(f); return camada.commitChanges()


def _clicar(widget, texto):
    botoes = [b for b in widget.findChildren(QPushButton) if b.text() == texto]
    if not botoes:
        raise AssertionError(f'botão "{texto}" não encontrado')
    botoes[0].click()


def _cor(projeto, arquivo, pasta=""):
    for c in projeto.mapLayers().values():
        if str(c.customProperty("norteagro/arquivo", "")) == arquivo and (not pasta or pasta.lower() in c.source().replace("\\", "/").lower()):
            return c.renderer().symbol().color().name(), c
    return None, None


def apontar_catalogo(caminho):
    """v0.0.0: aponta o catálogo para `caminho` em TODAS as cópias do módulo catalogo que estão na memória
    (depois de recarregar o plugin sem reiniciar o QGIS pode haver mais de uma) e devolve como desfazer.
    Assim um teste nunca grava no catálogo real do escritório."""
    import gc, sys, types
    nome = (__package__ or "norteagro_uso_solo") + ".catalogo"
    mods = {}
    if nome in sys.modules:
        mods[id(sys.modules[nome])] = sys.modules[nome]
    for o in gc.get_objects():
        if isinstance(o, types.ModuleType) and getattr(o, "__name__", "") == nome:
            mods[id(o)] = o
    antigos = [(m, m.CATALOGO_ESCRITORIO) for m in mods.values()]
    for m in mods.values():
        m.CATALOGO_ESCRITORIO = caminho
        try: m.estado_catalogo_escritorio(True)
        except Exception: pass

    def desfazer():
        for m, c in antigos:
            m.CATALOGO_ESCRITORIO = c
            try: m.estado_catalogo_escritorio(True)
            except Exception: pass
    return desfazer


def executar(mostrar=True):
    import importlib
    from . import catalogo, modelos as M
    mods = {n: importlib.import_module(f"{__package__}.{n}") for n in MODULOS}
    plug = qgis.utils.plugins.get(__package__)
    pr = QgsProject.instance(); esc = lambda: QgsExpressionContextUtils.projectScope(pr)
    t = _Rodada(); ok = t.ok
    real = catalogo.CATALOGO_ESCRITORIO
    arquivo_projeto = pr.fileName()
    foto = {"vars": {v: esc().variable(v) for v in VARS}, "ids": set(pr.mapLayers()), "dirty": pr.isDirty(),
            "tabela": QgsSettings().value("norteagro/modelo_tabela"),
            "qgz": (os.path.getmtime(arquivo_projeto), os.path.getsize(arquivo_projeto)) if arquivo_projeto and os.path.isfile(arquivo_projeto) else None}
    tmp = tempfile.mkdtemp(prefix="NORTEAGRO_TESTE_INTERFACE_")
    shutil.copy2(real, os.path.join(tmp, "catalogo_extra.json")) if os.path.isfile(real) else None
    desfazer_catalogo = apontar_catalogo(os.path.join(tmp, "catalogo_extra.json"))

    def registrar(nome):
        return lambda *a, **k: t.reg.append((nome, a[1:3] if len(a) > 2 else a[1:], a[3] if len(a) > 3 else k.get("detalhes"))) or 0
    for m in mods.values():
        for n in ("alertar", "sucesso", "informar", "erro", "dialogo_acoes"):
            if hasattr(m, n): t.trocar(m, n, registrar(n))
        if hasattr(m, "confirmar"): t.trocar(m, "confirmar", lambda *a, **k: (t.reg.append(("confirmar", a[1:3], k.get("detalhes"))), t.resp)[1])
    TM, tn, tcm, TI, TA = mods["tela_modelos"], mods["tela_nova_camada"], mods["tela_camadas"], mods["tela_inicial"], mods["tela_areas"]

    class _SemJanelaDeArquivo:
        """v0.6.0: o teste nunca abre a janela "Salvar projeto" na frente de quem está usando o QGIS."""
        @staticmethod
        def getSaveFileName(*a, **k): t.reg.append(("salvar_arquivo", a[1:3])); return "", ""
        @staticmethod
        def getOpenFileName(*a, **k): return "", ""
        @staticmethod
        def getExistingDirectory(*a, **k): return ""
    t.trocar(mods["plugin"], "QFileDialog", _SemJanelaDeArquivo)
    try:
        # ================================================================ A - camada nova no quadro
        mapa = os.path.join(tmp, "FAZENDA A", "MAPA USO DO SOLO"); plug.preparar_estrutura(mapa)
        QgsExpressionContextUtils.setProjectVariable(pr, "norteagro_pasta", mapa); QgsExpressionContextUtils.setProjectVariable(pr, "norteagro_srid", "EPSG:31982")
        QgsExpressionContextUtils.setProjectVariable(pr, "norteagro_kml_automatico", "1")
        d = tn.TelaNovaCamada(plug); d.nome.setText("Pastagem Teste NA"); d.grupo.setCurrentIndex(max(0, d.grupo.findData("Uso do Solo"))); d.lugar.definir("IMOVEL")
        t.resp = False; d.confirmar(); t.resp = True
        cam = plug.camada_plugin("PASTAGEM_TESTE_NA"); ent = plug.entrada("PASTAGEM_TESTE_NA")
        ok("A1 Nova camada cria o SHP na pasta do mapa", cam is not None and os.path.isfile(cam.source().split("|")[0]))
        ok("A1   guarda o lugar no quadro", ent and catalogo.lugar_quadro(ent) == "IMOVEL")
        ok("A1   grava a definição na camada", json.loads(cam.customProperty("norteagro/definicao"))["quadro"] == "IMOVEL")
        ok("A1   não catalogou (respondeu Não)", "PASTAGEM_TESTE_NA" not in catalogo.arquivos_catalogados_escritorio())
        d = tn.TelaNovaCamada(plug); d.nome.setText("Cerca Teste NA"); d.tipo.setCurrentIndex(d.tipo.findData("L")); d.confirmar()
        ok("A2 linha catalogada fica fora do quadro", catalogo.lugar_quadro(plug.entrada("CERCA_TESTE_NA")) == "NENHUM" and "CERCA_TESTE_NA" in catalogo.arquivos_catalogados_escritorio())
        mem = QgsVectorLayer("Polygon?crs=EPSG:31982", "Embargo Teste NA", "memory"); pr.addMapLayer(mem)
        a = tcm.DialogoAdicionarCatalogo(plug); a.camada.setLayer(mem); a.lugar.definir("PASSIVOS"); a.grupo.setCurrentIndex(0); a.confirmar()
        ok("A3 Adicionar ao catálogo grava o lugar", catalogo.lugar_quadro(catalogo.indice_reconhecimento(pr).get("EMBARGO_TESTE_NA")) == "PASSIVOS")
        tela = tcm.TelaCamadas(plug); alvo = None; it = QTreeWidgetItemIterator(tela.arvore)
        while it.value():
            if it.value().data(0, tela.PAPEL_ARQUIVO) == "PASTAGEM_TESTE_NA": alvo = it.value()
            it += 1
        textos = []

        class MenuTeste(QMenu):
            def exec(self, *a):
                textos.extend(x.text() for x in self.actions()); return next((x for x in self.actions() if "Lugar" in x.text()), None)
        t.trocar(tcm, "QMenu", MenuTeste); t.trocar(tcm, "escolher_lugar_quadro", lambda *a, **k: "OUTRAS")
        tela.menu_contexto(tela.arvore.visualItemRect(alvo).center())
        ok("A4 botão direito: Substituir e Lugar no Quadro de Áreas", "Lugar no Quadro de Áreas..." in textos and "Substituir..." in textos, str(textos))
        ok("A4   muda o lugar", catalogo.lugar_quadro(plug.entrada("PASTAGEM_TESTE_NA")) == "OUTRAS")
        t.trocar(tcm, "escolher_lugar_quadro", lambda *a, **k: "IMOVEL"); tela.definir_lugar_quadro("PASTAGEM_TESTE_NA"); tela.deleteLater()
        extras = str(esc().variable("norteagro_extras"))
        av = os.path.join(tmp, "AVULSA", "shapefiles"); os.makedirs(av)
        dn = tn.TelaNovaCamada(plug, somente_definicao=True); dn.nome.setText("Represa Teste NA"); dn.lugar.definir("HIDRO"); dn.confirmar()
        okv, _, erro, lav = plug.criar_ou_carregar_destino(dict(dn.entrada_resultado), av, "EPSG:31982", kml_dir=os.path.join(tmp, "AVULSA", "kml"), avulsa=True)
        ok("A5 Criar camadas em uma pasta: personalizada criada e reconhecida", okv and catalogo.lugar_quadro(catalogo.indice_reconhecimento(pr).get("REPRESA_TESTE_NA")) == "HIDRO", erro)
        ok("A5   sem mexer nos extras do projeto", str(esc().variable("norteagro_extras")) == extras)
        for arq in ("AREA_DO_IMOVEL", "AREA_DE_VEGETACAO", "AREA_CONSOLIDADA", "AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019", "HIDROGRAFIA"):
            okc, _, errc = plug.criar_ou_carregar(arq)
            if not okc: raise AssertionError(f"{arq}: {errc}")
        G = {"AREA_DO_IMOVEL": _ret(0, 0, 100, 100), "AREA_DE_VEGETACAO": _ret(0, 0, 50, 100), "AREA_CONSOLIDADA": _ret(50, 0, 70, 100),
             "AREA_SUPRIMIDA_ANTES_2019": _ret(70, 0, 75, 100), "AREA_SUPRIMIDA_DEPOIS_2019": _ret(75, 0, 80, 100),
             "PASTAGEM_TESTE_NA": _ret(78, 0, 100, 100), "HIDROGRAFIA": _ret(0, 0, 5, 5)}
        for arq, g in G.items(): _desenhar(plug.camada_plugin(arq), g)
        _desenhar(lav, _ret(0, 0, 10, 10)); _desenhar(mem, _ret(70, 0, 90, 50))
        from .areas import calcular_areas
        novas = [pr.mapLayer(i) for i in pr.mapLayers() if i not in foto["ids"]]
        dados = calcular_areas(novas, "EPSG:31982", "Plano UTM", catalogo.indice_reconhecimento(pr), pasta_mapa=mapa); vq = dados["valores_quadro"]
        fe = [c for c in dados["conferencias"] if str(c.get("verificacao", "")).startswith("Fechamento do imóvel")]
        ok("A6 Pastagem no fechamento e o imóvel fecha", "PASTAGEM_TESTE_NA" in dados["fechamento_classes"] and abs(vq["PASTAGEM_TESTE_NA"] - 0.2) < 1e-6 and fe and fe[0]["situacao"] == "OK")
        ok("A6 Embargo em Passivos sem dupla contagem", abs(vq["EMBARGO_TESTE_NA"] - 0.05) < 1e-6)
        ok("A6 Represa na Hidrografia sem dupla contagem", abs(vq["REPRESA_TESTE_NA"] - 0.0075) < 1e-6)
        ok("A6 sobreposições avisadas (T1)", sum(1 for c in dados["conferencias"] if c.get("regra") == "T1") >= 3)
        ok("A6 linha fora dos quadros", "CERCA_TESTE_NA" not in dados["quadro_origens"])
        ta = TA.TelaAreas(plug, qgis.utils.iface.mainWindow(), modo_so_calcular=True); ta.resultado = dados
        saida = os.path.join(tmp, "quadro_A.xlsx"); ok("A7 Calcular áreas gera a planilha", ta._salvar_resultado(saida) and os.path.isfile(saida)); ta.deleteLater()
        import openpyxl
        ws = openpyxl.load_workbook(saida)["Quadro de Áreas"]; cel = {}
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.column in (2, 5): cel.setdefault(c.value, ws.cell(c.row, c.column + 1).value)
        ok("A7   linhas novas com o valor certo", abs(cel.get("Pastagem Teste NA", 0) - 0.2) < 1e-9 and abs(cel.get("Embargo Teste NA", 0) - 0.05) < 1e-9 and abs(cel.get("Represa Teste NA", 0) - 0.0075) < 1e-9, str(cel.get("Pastagem Teste NA")))

        # ================================================================ B - modelos de pastas
        tela = TM.TelaModelos(plug, qgis.utils.iface.mainWindow(), 0); a = tela.pastas
        _clicar(a, "Novo"); a.nome.setText("Modelo Teste NA")

        class EntradaTexto:
            valor = ""
            @staticmethod
            def getText(*args, **kw): return EntradaTexto.valor, True
        t.trocar(TM, "QInputDialog", EntradaTexto)
        F = "FAZENDA MODELO"
        ok("B1 Novo começa vazio", a.raiz is not None and a.raiz.childCount() == 0 and a.caminhos_pastas() == [] and a.pasta_mapa() == "")
        EntradaTexto.valor = F + "; DOCUMENTOS GERAIS"; _clicar(a, "+ Pasta mãe")
        ok("B1 + Pasta mãe (várias de uma vez; camadas na primeira)", [a.raiz.child(i).text(0) for i in range(a.raiz.childCount())] == [F, "DOCUMENTOS GERAIS"]
           and a.pasta_mapa() == F)
        a.pastas.setCurrentItem(a._achar_caminho(F)); EntradaTexto.valor = "layout; plantas pdf; documentos/fotos; kml; projetos"; _clicar(a, "+ Subpasta")
        ok("B1 + Subpasta: várias de uma vez e continua na mesma pasta", a.pastas.currentItem() is not None and a.pastas.currentItem().text(0) == F
           and len(a.caminhos_pastas()) == 6, str(a.caminhos_pastas()))
        a.pastas.setCurrentItem(a._achar_caminho(F + "/kml")); EntradaTexto.valor = "x"; n = len(t.reg); _clicar(a, "+ Subpasta")
        ok("B1 recusa subpasta dentro do kml da pasta do mapa", len(a.caminhos_pastas()) == 6 and len(t.reg) > n and t.reg[-1][0] == "alertar")
        a.pastas.setCurrentItem(a._achar_caminho(F + "/documentos")); EntradaTexto.valor = "relatorios/2026"; _clicar(a, "+ Subpasta")
        ok("B1 + Subpasta em vários níveis", F + "/documentos/relatorios/2026" in a.caminhos_pastas(), str(a.caminhos_pastas()))
        a.pastas.setCurrentItem(a._achar_caminho(F + "/documentos/relatorios")); _clicar(a, "Remover pasta")
        ok("B1 Remover pasta com subpastas", F + "/documentos/relatorios/2026" not in a.caminhos_pastas() and F + "/documentos/fotos" in a.caminhos_pastas())
        a.pastas.setCurrentItem(a._achar_caminho(F + "/layout")); _clicar(a, "Remover pasta")
        a.pastas.setCurrentItem(a._achar_caminho("DOCUMENTOS GERAIS")); _clicar(a, "Remover pasta")
        ok("B1 Remover pasta", a.caminhos_pastas() == [F + "/plantas pdf", F + "/documentos/fotos", F + "/kml", F + "/projetos"], str(a.caminhos_pastas()))

        class DialogoMarca(QDialog):
            def exec(self):
                arv = self.findChild(QTreeWidget); it = QTreeWidgetItemIterator(arv)
                while it.value():
                    if it.value().data(0, Qt.ItemDataRole.UserRole) in ("RESERVA_LEGAL", "EMBARGO_TESTE_NA"): it.value().setCheckState(0, Qt.CheckState.Checked)
                    it += 1
                return QDialog.DialogCode.Accepted
        t.trocar(TM, "QDialog", DialogoMarca); _clicar(a, "+ Do catálogo..."); t.trocar(TM, "QDialog", QDialog)
        ok("B1 + Do catálogo adiciona as marcadas", a.camadas.topLevelItemCount() == 2)

        def nova(self):
            self.nome.setText("Servidao Teste NA"); self.lugar.definir("OUTRAS"); self.confirmar(); return QDialog.DialogCode.Accepted
        t.trocar(tn.TelaNovaCamada, "exec", nova); _clicar(a, "+ Nova camada...")
        ok("B1 + Nova camada", a.camadas.topLevelItemCount() == 3 and a.camadas.topLevelItem(2).text(4) == "Nova")
        a.camadas.setCurrentItem(a.camadas.topLevelItem(2))

        def editar(self):
            self.tipo.setCurrentIndex(self.tipo.findData("P")); self.lugar.definir("COMPENSACAO"); self.confirmar(); return QDialog.DialogCode.Accepted
        t.trocar(tn.TelaNovaCamada, "exec", editar); _clicar(a, "Editar camada...")
        ok("B1 Editar camada", a.camadas.topLevelItem(2).data(0, Qt.ItemDataRole.UserRole)["nova"]["quadro"] == "COMPENSACAO")
        kml = a._achar_caminho(F + "/kml")
        ok("B1 árvore explica as pastas do plugin", "KML" in kml.text(1) and "pasta mãe" in a._achar_caminho(F).text(1), kml.text(1))
        a.pastas.setCurrentItem(a._achar_caminho(F + "/documentos")); _clicar(a, "Pasta do mapa aqui")
        ok("B1 Pasta do mapa aqui", a.pasta_mapa() == F + "/documentos" and "pasta do mapa" in a._achar_caminho(F + "/documentos").text(1), a.pasta_mapa())
        a.pastas.setCurrentItem(a._achar_caminho(F)); _clicar(a, "Pasta do mapa aqui"); ok("B1 pasta do mapa volta para a pasta mãe", a.pasta_mapa() == F)
        _clicar(a, "Salvar modelo"); m = M.modelo_pasta("Modelo Teste NA"); nm = M.normalizar_modelo_pasta(m or {})
        ok("B1 Salvar modelo", m and m["pastas"] == [F + "/plantas pdf", F + "/documentos/fotos", F + "/kml", F + "/projetos"] and m["pasta_mapa"] == F
           and nm["gerar_kml"] and nm["pasta_projetos"] and len(m["camadas"]) == 3, str(m and m["pastas"]))
        _clicar(a, "Duplicar"); _clicar(a, "Salvar modelo"); ok("B2 Duplicar", M.modelo_pasta("Modelo Teste NA (cópia)") is not None)
        _clicar(a, "Excluir"); ok("B2 Excluir", M.modelo_pasta("Modelo Teste NA (cópia)") is None)
        for i in range(a.lista.count()):
            if a.lista.item(i).data(Qt.ItemDataRole.UserRole) == "Modelo Teste NA": a.lista.setCurrentRow(i)
        a.nome.setText(M.PADRAO); n = len(t.reg); _clicar(a, "Salvar modelo"); ok("B2 recusa nome do padrão", t.reg[-1][0] == "alertar" and len(t.reg) > n)
        a.nome.setText("Modelo Teste NA"); a._foto = a.coletar()
        antes = set(pr.mapLayers()); _clicar(a, "Aplicar neste projeto")
        criadas = sorted(str(pr.mapLayer(i).customProperty("norteagro/arquivo")) for i in pr.mapLayers() if i not in antes)
        ok("B3 Aplicar neste projeto cria pastas e camadas", os.path.isdir(os.path.join(mapa, "documentos", "fotos")) and criadas == ["EMBARGO_TESTE_NA", "RESERVA_LEGAL", "SERVIDAO_TESTE_NA"], str(criadas))
        res = plug.aplicar_modelo_pasta("Modelo Teste NA")
        ok("B3 reaplicar não duplica", not res["criadas"] and len(res["carregadas"]) == 3 and not res["ausentes"])

        # ================================================================ C - temas de cores
        c = tela.cores; TESTE = {"SERVIDAO_TESTE_NA", "PASTAGEM_TESTE_NA", "REPRESA_TESTE_NA"}
        for arq, rgb in (("SERVIDAO_TESTE_NA", "255,0,0,255"), ("PASTAGEM_TESTE_NA", "0,128,0,255"), ("REPRESA_TESTE_NA", "0,0,255,255")):
            _cor(pr, arq)[1].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": rgb})))
        _clicar(c, "+ Novo tema com as cores do projeto")
        for i in range(c.tabela.topLevelItemCount()):
            it = c.tabela.topLevelItem(i); it.setSelected(it.data(0, Qt.ItemDataRole.UserRole) not in TESTE)
        _clicar(c, "Remover camada do tema"); ok("C1 Novo tema + Remover camada do tema", c.tabela.topLevelItemCount() == 3)
        c.nome.setText("Tema Teste NA"); _clicar(c, "Salvar tema"); ok("C1 Salvar tema", set((M.tema_cores("Tema Teste NA") or {}).get("estilos", {})) == TESTE)
        for arq in TESTE: _cor(pr, arq)[1].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "200,200,200,255"})))
        _clicar(c, "Aplicar neste projeto")
        ok("C2 Aplicar tema (com confirmação)", [_cor(pr, x)[0] for x in ("SERVIDAO_TESTE_NA", "PASTAGEM_TESTE_NA", "REPRESA_TESTE_NA")] == ["#ff0000", "#008000", "#0000ff"]
           and any(r[0] == "confirmar" and "Muda a cor de 3" in str(r[2]) for r in t.reg))
        t.resp = False; _cor(pr, "PASTAGEM_TESTE_NA")[1].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "1,1,1,255"})))
        _clicar(c, "Aplicar neste projeto"); ok("C2 Cancelar não muda nada", _cor(pr, "PASTAGEM_TESTE_NA")[0] == "#010101"); t.resp = True
        _cor(pr, "PASTAGEM_TESTE_NA")[1].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "255,255,0,255"})))
        _clicar(c, "Atualizar com as cores do projeto"); _clicar(c, "Salvar tema")
        ok("C3 Atualizar só as do tema", c.tabela.topLevelItemCount() == 3 and M.renderer_de_xml(M.tema_cores("Tema Teste NA")["estilos"]["PASTAGEM_TESTE_NA"]).symbol().color().name() == "#ffff00")
        from qgis.core import QgsLineSymbol, QgsMarkerSymbol
        tipos = {}
        for geom, arq, simb in (("Point", "PONTO_TESTE_NA", QgsMarkerSymbol.createSimple({"name": "triangle", "color": "0,0,255", "size": "4"})),
                                ("LineString", "LINHA_TESTE_NA", QgsLineSymbol.createSimple({"line_color": "255,0,0", "line_style": "dash"})),
                                ("Polygon", "POLIGONO_TESTE_NA", QgsFillSymbol.createSimple({"color": "0,128,0,120"}))):
            lyr = QgsVectorLayer(f"{geom}?crs=EPSG:31982", arq, "memory"); lyr.setCustomProperty("norteagro/arquivo", arq); pr.addMapLayer(lyr, False)
            lyr.setRenderer(QgsSingleSymbolRenderer(simb)); tipos[arq] = lyr
        tema_tipos = {"nome": "tipos", "estilos": M.capturar_tema(pr, list(tipos.values()))}
        for lyr in tipos.values(): lyr.setRenderer(QgsSingleSymbolRenderer(type(lyr.renderer().symbol()).createSimple({"color": "1,1,1"})))
        M.aplicar_tema(tema_tipos, pr, gravar_qml=False, camadas=list(tipos.values()))
        # o tipo é lido pela camada de símbolo (C++); type() do Python pode vir errado quando o sip reaproveita endereço
        _lido = [tipos[a].renderer().symbol().symbolLayer(0).layerType() + tipos[a].renderer().symbol().color().name()
                 for a in ("PONTO_TESTE_NA", "LINHA_TESTE_NA", "POLIGONO_TESTE_NA")]
        ok("C5 tema com ponto, linha e polígono", _lido == ["SimpleMarker#0000ff", "SimpleLine#ff0000", "SimpleFill#008000"],
           str(_lido) + " " + str(sorted(tema_tipos["estilos"])))
        trocado = QgsVectorLayer("Point?crs=EPSG:31982", "POLIGONO_TESTE_NA ponto", "memory"); trocado.setCustomProperty("norteagro/arquivo", "POLIGONO_TESTE_NA"); pr.addMapLayer(trocado, False)
        _a, _s, errs = M.aplicar_tema(tema_tipos, pr, gravar_qml=False, camadas=[trocado])
        simb_trocado = {0: "QgsMarkerSymbol", 1: "QgsLineSymbol", 2: "QgsFillSymbol"}.get(int(trocado.renderer().symbol().type()), "?") if trocado.renderer() and trocado.renderer().symbol() else str(trocado.renderer() and trocado.renderer().type())
        ok("C5 tipo diferente: não aplica e avisa", (not _a) and bool(errs) and "polígono" in errs[0] and simb_trocado == "QgsMarkerSymbol", f"{_a} {errs} {simb_trocado}")
        m = M.modelo_pasta("Modelo Teste NA"); m["tema_cores"] = "Tema Teste NA"; M.salvar_modelo_pasta(m, "Modelo Teste NA")
        _cor(pr, "SERVIDAO_TESTE_NA")[1].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "9,9,9,255"})))
        res = plug.aplicar_modelo_pasta("Modelo Teste NA")
        ok("C4 modelo aplica o tema (só na pasta do mapa)", _cor(pr, "SERVIDAO_TESTE_NA")[0] == "#ff0000" and _cor(pr, "REPRESA_TESTE_NA")[0] == "#0000ff")

        # ================================================================ D - modelos de tabela
        tb = tela.tabela; tela.abas.setCurrentIndex(2); tb.lista.setCurrentRow(0); _clicar(tb, "Duplicar"); tb.nome.setText("Tabela Teste NA")
        tb.titulo.setText("{imovel} - QUADRO ({data})")
        for r in range(tb.quadros.rowCount()):
            q = tb.quadros.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if q == "HIDRO": tb.quadros.item(r, 0).setCheckState(Qt.CheckState.Unchecked)
            if q == "IMOVEL": tb.quadros.item(r, 1).setText("Uso do solo")
        tb.quadros.selectRow(0); _clicar(tb, "Descer"); ok("D1 Descer quadro", [q["id"] for q in tb._quadros_lidos()][:2] == ["PASSIVOS", "IMOVEL"])
        EntradaTexto.valor = "Pastagem Teste NA"; _clicar(tb, "+ Outra linha"); tb.linhas.item(tb.linhas.rowCount() - 1, 1).setText("Pastagem")

        class Arquivos:
            @staticmethod
            def getOpenFileName(*a, **k): return os.path.join(os.path.dirname(__file__), "icon.png"), ""
        t.trocar(TM, "QFileDialog", Arquivos); _clicar(tb, "Escolher imagem..."); ok("D1 logo", bool(tb._logo))
        tb.fonte.setCurrentFont(QFont("Arial")); tb.cores["titulo_fundo"].setColor(QColor("#7B2C2C")); tb.col_m2.setChecked(True); tb.col_pct.setChecked(True)
        _clicar(tb, "Salvar modelo"); mt = M.modelo_tabela("Tabela Teste NA")
        ok("D1 Salvar modelo de tabela", mt["fonte"] == "Arial" and mt["cores"]["titulo_fundo"] == "#7B2C2C" and mt["logo_png"] and mt["colunas"] == {"m2": True, "pct": True} and mt["linhas"] == {"Pastagem Teste NA": "Pastagem"})
        ok("D1 Ver exemplo no Excel", os.path.isfile(tb.exemplo(abrir=False)))
        ta = TA.TelaAreas(plug, qgis.utils.iface.mainWindow(), modo_so_calcular=True)
        ok("D2 Calcular áreas lista o modelo", ta.modelo_tabela.findData("Tabela Teste NA") > 0)
        ta.modelo_tabela.setCurrentIndex(ta.modelo_tabela.findData("Tabela Teste NA")); ta.resultado = dados; saida = os.path.join(tmp, "quadro_D.xlsx"); ta._salvar_resultado(saida); ta.deleteLater()
        ws = openpyxl.load_workbook(saida)["Quadro de Áreas"]; txt = {x.value: (x.row, x.column) for r in ws.iter_rows() for x in r if isinstance(x.value, str)}
        ok("D2 planilha segue o modelo", "Uso do solo" in txt and "Pastagem" in txt and "Área Hidrográfica" not in txt and "m²" in txt and "% do imóvel" in txt and len(ws._images) == 1
           and ws.cell(*txt["Uso do solo"]).fill.fgColor.rgb.endswith("7B2C2C"))
        rng = [(r.min_row, r.min_col, r.max_row, r.max_col) for r in ws.merged_cells.ranges]
        ok("D2 nenhum quadro sobreposto", not [(x, y) for i, x in enumerate(rng) for y in rng[i + 1:] if not (x[2] < y[0] or y[2] < x[0] or x[3] < y[1] or y[3] < x[1])])
        ok("D2 modelo lembrado", QgsSettings().value("norteagro/modelo_tabela") == "Tabela Teste NA")
        tela.deleteLater()

        # ================================================================ E - configurar pasta, acessos, referências, robustez
        M.salvar_modelo_pasta({"nome": "Enxuto Teste NA", "pastas": ["documentos"], "camadas": [{"arquivo": "AREA_DO_IMOVEL"}], "gerar_kml": False, "pasta_projetos": False})
        ti = TI.TelaInicial(plug); os.makedirs(os.path.join(tmp, "FAZENDA B")); ti.local.setText(os.path.join(tmp, "FAZENDA B")); ti.nome.setText("MAPA")
        ti.modelo.setCurrentIndex(ti.modelo.findData("Enxuto Teste NA")); ok("E1 Configurar pasta descreve o modelo", "Sem KML automático" in ti.modelo_info.text())
        antes = set(pr.mapLayers()); ti.confirmar(); mapa_b = os.path.join(tmp, "FAZENDA B", "MAPA")
        ok("E1 cria só shapefiles e documentos", sorted(os.listdir(mapa_b)) == ["documentos", "shapefiles"], str(sorted(os.listdir(mapa_b))))
        cam_b = [pr.mapLayer(i) for i in pr.mapLayers() if i not in antes][0]
        ok("F1 salvar sem KML automático", _salvar_edicao(cam_b, _ret(0, 0, 50, 50)) and not os.path.exists(os.path.join(mapa_b, "kml")))
        okx, _, dest = plug.kml.exportar(cam_b); ok("F1 Exportar KML manual funciona", okx and os.path.isfile(dest))
        ok("F1 .qgz sugerido na pasta do mapa", plug._pasta_projetos(mapa_b) == mapa_b)
        ti = TI.TelaInicial(plug); os.makedirs(os.path.join(tmp, "FAZENDA C")); ti.local.setText(os.path.join(tmp, "FAZENDA C")); ti.nome.setText("MAPA")
        ti.modelo.setCurrentIndex(ti.modelo.findData("Modelo Teste NA")); antes = set(pr.mapLayers()); ti.confirmar(); mapa_c = os.path.join(tmp, "FAZENDA C", "MAPA")
        novas_c = [pr.mapLayer(i) for i in pr.mapLayers() if i not in antes]
        ok("E2 Configurar pasta com modelo completo: pastas, camadas e tema", sorted(os.listdir(mapa_c)) == ["documentos", "kml", "plantas pdf", "projetos", "shapefiles"] and len(novas_c) == 3
           and _cor(pr, "SERVIDAO_TESTE_NA", "FAZENDA C")[0] == "#ff0000", str(sorted(os.listdir(mapa_c))))
        serv_c = _cor(pr, "SERVIDAO_TESTE_NA", "FAZENDA C")[1]
        ok("F2 com kml ligado, salvar grava o KML", _salvar_edicao(serv_c, _ret(0, 0, 10, 10)) and any(f.endswith(".kml") for d_, _, fs in os.walk(os.path.join(mapa_c, "kml")) for f in fs))
        # v0.0.0: várias pastas mãe, pasta do mapa numa subpasta e nomes trocados em Configurar pasta
        M.salvar_modelo_pasta({"nome": "Varias Maes Teste NA", "formato_pastas": 2, "pasta_mapa": "FAZENDA/03 Mapas",
                               "pastas": ["FAZENDA/01 Documentos/CAR/2026", "FAZENDA/03 Mapas/kml", "FOTOS/2026", "DOCUMENTOS DO CLIENTE"]})
        os.makedirs(os.path.join(tmp, "CLIENTES"))
        ti = TI.TelaInicial(plug); ti.modelo.setCurrentIndex(ti.modelo.findData("Varias Maes Teste NA")); ti.local.setText(os.path.join(tmp, "CLIENTES"))
        ok("E3 um campo para cada pasta mãe", [o for o, _, _ in ti.campos_maes] == ["FAZENDA", "FOTOS", "DOCUMENTOS DO CLIENTE"])
        ti.campos_maes[0][1].setText("Fazenda Sol"); ti.campos_maes[1][1].setText("Fotos Sol"); ti._validar()
        ti.modelo.setCurrentIndex(ti.modelo.findData(M.PADRAO)); ti.modelo.setCurrentIndex(ti.modelo.findData("Varias Maes Teste NA"))
        ok("E3 trocar de modelo e voltar mantém os nomes digitados", [c.text() for _, c, _ in ti.campos_maes] == ["Fazenda Sol", "Fotos Sol", "DOCUMENTOS DO CLIENTE"])
        ti.confirmar(); base_e3 = os.path.join(tmp, "CLIENTES"); mapa_e3 = os.path.join(base_e3, "Fazenda Sol", "03 Mapas")
        ok("E3 cria todas as pastas com os nomes trocados", all(os.path.isdir(os.path.join(base_e3, *c.split("/"))) for c in
           ("Fazenda Sol/01 Documentos/CAR/2026", "Fazenda Sol/03 Mapas/kml", "Fotos Sol/2026", "DOCUMENTOS DO CLIENTE")) and not os.path.exists(os.path.join(base_e3, "FAZENDA")))
        ok("E3 projeto aponta para a pasta do mapa, com KML automático", os.path.normcase(str(esc().variable("norteagro_pasta"))) == os.path.normcase(mapa_e3)
           and str(esc().variable("norteagro_kml_automatico")) == "1")
        shutil.rmtree(os.path.join(base_e3, "Fotos Sol")); r_e3 = plug.aplicar_modelo_pasta("Varias Maes Teste NA")
        ok("E3 Aplicar neste projeto usa os nomes guardados", r_e3["pastas"] == ["Fotos Sol/2026"] and not os.path.exists(os.path.join(base_e3, "FOTOS")), str(r_e3["pastas"]))
        ti.deleteLater()
        abertas = []
        t.trocar(TM.TelaModelos, "exec", lambda self: abertas.append(self.abas.currentIndex()) or 0)
        te = mods["tela_escolha"].TelaEscolha(plug); _clicar(te, "Modelos"); te.deleteLater()
        for cls in (tcm.TelaCamadas, mods["tela_avulsa"].TelaAvulsa):
            dd = cls(plug); [x for x in dd.ferramentas.menu().actions() if x.text().startswith("Modelos")][0].trigger(); dd.deleteLater()
        ti2 = TI.TelaInicial(plug); _clicar(ti2, "Modelos..."); ti2.deleteLater()
        ta = TA.TelaAreas(plug, qgis.utils.iface.mainWindow(), modo_so_calcular=True); _clicar(ta, "Modelos..."); ta.deleteLater()
        ok("E3 Modelos abre de todos os lugares", abertas == [0, 0, 0, 0, 2], str(abertas))
        catalogo.adicionar_referencia_escritorio("Fitofisionomia")
        ref = QgsVectorLayer("Polygon?crs=EPSG:31982", "Fitofisionomia teste NA", "memory"); pr.addMapLayer(ref)
        ta = TA.TelaAreas(plug, qgis.utils.iface.mainWindow(), modo_so_calcular=True); sit = None
        for i in range(ta.arvore.topLevelItemCount()):
            g = ta.arvore.topLevelItem(i)
            for j in range(g.childCount()):
                if str(g.child(j).data(0, Qt.ItemDataRole.UserRole)) == ref.id(): sit = g.child(j).text(6)
        ta.deleteLater(); ok("E4 referência do escritório", sit == "Referência", str(sit))
        try:
            catalogo.adicionar_referencia_escritorio("APP"); ok("E4 recusa nome genérico", False)
        except ValueError:
            ok("E4 recusa nome genérico", True)
        catalogo.remover_referencia_escritorio("Fitofisionomia")
        trava = M.caminho_modelos() + ".lock"; open(trava, "w").write("x"); t0 = time.time()
        try:
            M.salvar_modelo_pasta({"nome": "Z"}); ok("E5 outro usuário gravando: espera e avisa", False)
        except TimeoutError:
            ok("E5 outro usuário gravando: espera e avisa", time.time() - t0 < 8)
        os.utime(trava, (time.time() - 60, time.time() - 60)); M.salvar_modelo_pasta({"nome": "Z"}); M.remover_modelo_pasta("Z")
        ok("E5 trava esquecida é liberada", not os.path.exists(trava))
        bom = open(M.caminho_modelos(), encoding="utf-8").read(); open(M.caminho_modelos(), "w", encoding="utf-8").write("{x")
        try:
            M.salvar_modelo_pasta({"nome": "Y"}); ok("E5 arquivo corrompido não é sobrescrito", False)
        except RuntimeError:
            ok("E5 arquivo corrompido não é sobrescrito", open(M.caminho_modelos(), encoding="utf-8").read() == "{x")
        open(M.caminho_modelos(), "w", encoding="utf-8").write(bom)

        # ================================================================ G - funções antigas na pasta temporária
        # Apagar grupo e Renomear pasta SALVAM o projeto (é parte delas): durante estes testes o projeto
        # aponta para um .qgz temporário, para nunca gravar por cima do arquivo do projeto aberto.
        pr.setFileName(os.path.join(tmp, "projeto_teste.qgz"))
        QgsExpressionContextUtils.setProjectVariable(pr, "norteagro_pasta", mapa); QgsExpressionContextUtils.setProjectVariable(pr, "norteagro_kml_automatico", "1")
        tela = tcm.TelaCamadas(plug); marcar = {"RESERVA_PRESERVADA", "APP_TOTAL"}; it = QTreeWidgetItemIterator(tela.arvore)
        while it.value():
            if it.value().data(0, tela.PAPEL_ARQUIVO) in marcar: it.value().setCheckState(0, Qt.CheckState.Checked)
            it += 1
        tela.processar(); ok("G1 Criar camadas marcadas", all(plug.camada_plugin(x) is not None for x in marcar)); tela.deleteLater()
        cli = QgsVectorLayer("Polygon?crs=EPSG:31982&field=id:integer", "Mata do cliente NA", "memory"); pr.addMapLayer(cli); _desenhar(cli, _ret(0, 0, 40, 40), _ret(40, 0, 50, 40))
        from .tela_padronizar import padronizar_camada
        veg = plug.camada_plugin("AREA_DE_VEGETACAO"); r = padronizar_camada(plug, cli, destino_forcado="AREA_DE_VEGETACAO", perguntar_original=False, mostrar_resumo=False)
        veg = plug.camada_plugin("AREA_DE_VEGETACAO")
        ok("G2 Padronizar substitui o conteúdo com backup", r and r[0] and veg.featureCount() == 2 and os.path.isdir(os.path.join(os.path.dirname(veg.source().split("|")[0]), "_backup")), str(r))
        ok("G2   KML atualizado", os.path.isfile(plug.kml.caminho_kml(veg)))
        cli2 = QgsVectorLayer("Polygon?crs=EPSG:31982&field=id:integer", "Consolidada cliente NA", "memory"); pr.addMapLayer(cli2); _desenhar(cli2, _ret(50, 0, 70, 100))
        id_cli2 = cli2.id()
        ts = mods["tela_substituir"].TelaSubstituir(plug, arquivo_destino="AREA_CONSOLIDADA"); ts.origem.setLayer(cli2); ts.remover.setChecked(True); ts.executar()
        cons = plug.camada_plugin("AREA_CONSOLIDADA")
        ok("G3 Substituir conteúdo e remover origem", cons.featureCount() == 1 and pr.mapLayer(id_cli2) is None, str(cons.featureCount()))
        okg, err = plug.criar_grupo_projeto("Grupo Teste NA"); ok("G4 criar grupo", okg, err)
        e = {"arquivo": "LIXO_TESTE_NA", "nome": "Lixo Teste NA", "tipo": "P", "grupo": "Grupo Teste NA", "estilo_xml": "", "personalizada": True, "origem": "projeto", "ordem": 100000}
        plug.salvar_extra_projeto(e); plug.criar_ou_carregar("LIXO_TESTE_NA"); shp_lixo = plug.caminho_shp("LIXO_TESTE_NA")
        plug.apagar_grupo_projeto("Grupo Teste NA")
        ok("G4 apagar grupo move para _apagados", not os.path.exists(shp_lixo) and os.path.isdir(os.path.join(mapa, "_apagados")) and plug.camada_plugin("LIXO_TESTE_NA") is None)
        from .pasta import DialogoRenomearPasta
        dr = DialogoRenomearPasta(plug); dr.nome.setText("MAPA RENOMEADO"); dr.executar(); novo = os.path.join(os.path.dirname(mapa), "MAPA RENOMEADO")
        veg = plug.camada_plugin("AREA_DE_VEGETACAO")
        ok("G5 Renomear pasta e reapontar camadas", os.path.isdir(novo) and not os.path.exists(mapa) and veg is not None and veg.isValid() and "MAPA RENOMEADO" in veg.source() and veg.featureCount() == 2)
        mapa = novo
        from .operacoes import backup_shapefile
        b1 = backup_shapefile(veg); b2 = backup_shapefile(veg); ok("G6 backups no mesmo segundo não se sobrescrevem", b1 != b2 and os.path.isdir(b1) and os.path.isdir(b2))
        # ================================================================ H - ajuda ("?")
        from qgis.PyQt.QtWidgets import QToolButton
        from .tela_ajuda import TelaAjuda, TOPICOS
        def ajudas(): return [w for w in QApplication.topLevelWidgets() if isinstance(w, TelaAjuda) and w.isVisible()]
        for nome, fab, esperado in (("tela inicial", lambda: mods["tela_escolha"].TelaEscolha(plug), "tela_inicial"),
                                    ("Criar/gerenciar", lambda: tcm.TelaCamadas(plug), "gerenciar"),
                                    ("Calcular áreas", lambda: TA.TelaAreas(plug, qgis.utils.iface.mainWindow(), modo_so_calcular=True), "calcular"),
                                    ("Modelos (Tabela)", lambda: TM.TelaModelos(plug, qgis.utils.iface.mainWindow(), 2), "modelos_tabela")):
            dd = fab(); botoes = [b for b in dd.findChildren(QToolButton) if b.text() == "?"]
            if botoes: botoes[0].click()
            QApplication.processEvents(); aa = ajudas()
            ok(f"H1 ? de {nome} abre a ajuda em {esperado}", bool(botoes) and len(aa) == 1 and aa[0].lista.currentItem().data(Qt.ItemDataRole.UserRole) == esperado
               and bool(dd.windowFlags() & Qt.WindowType.WindowContextHelpButtonHint))
            for w in aa: w.close()
            dd.deleteLater(); QApplication.processEvents()
        ids = {x[0] for x in TOPICOS}; import re as _re
        ok(f"H2 ajuda: {len(TOPICOS)} assuntos (com Correção) e nenhum link quebrado", len(TOPICOS) >= 23 and "correcao" in ids and not (set(_re.findall(r'href="#(\w+)"', "".join(x[2] for x in TOPICOS))) - ids))
    except Exception:
        t.res.append("FALHOU erro inesperado: " + traceback.format_exc()[-900:])
    finally:
        t.desfazer()
        for c in list(pr.mapLayers().values()):
            if c.id() not in foto["ids"]:
                try:
                    if c.isEditable(): c.rollBack()
                except Exception:
                    pass
        pr.removeMapLayers([i for i in pr.mapLayers() if i not in foto["ids"]])
        pr.setFileName(arquivo_projeto)
        for v, val in foto["vars"].items():
            if val is None: QgsExpressionContextUtils.removeProjectVariable(pr, v)
            else: QgsExpressionContextUtils.setProjectVariable(pr, v, val)
        desfazer_catalogo()
        if foto["tabela"] is None: QgsSettings().remove("norteagro/modelo_tabela")
        else: QgsSettings().setValue("norteagro/modelo_tabela", foto["tabela"])
        try:
            plug.kml.desconectar_todos(); plug.kml.reconectar()
        except Exception:
            pass
        pr.setDirty(foto["dirty"]); QApplication.processEvents()
        for _ in range(10):
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.exists(tmp): break
            QApplication.processEvents(); time.sleep(0.3)
    if foto["qgz"] is not None:
        t.ok("Z1 arquivo do projeto aberto não foi gravado pelos testes",
             os.path.isfile(arquivo_projeto) and (os.path.getmtime(arquivo_projeto), os.path.getsize(arquivo_projeto)) == foto["qgz"])
    t.ok("Z2 projeto aberto restaurado (camadas e configurações)", set(pr.mapLayers()) == foto["ids"] and pr.fileName() == arquivo_projeto
         and all(esc().variable(v) == val for v, val in foto["vars"].items()))
    if os.path.exists(tmp):
        # O QGIS solta os arquivos dos Shapefiles removidos alguns segundos depois: apaga em seguida.
        for atraso in (2000, 6000, 15000):
            QTimer.singleShot(atraso, lambda c=tmp: shutil.rmtree(c, ignore_errors=True))
        t.ok("Z3 pasta temporária agendada para apagar (o QGIS ainda segurava arquivos)", True)
    else:
        t.ok("Z3 pasta temporária apagada", True)
    falhas = [r for r in t.res if r.startswith("FALHOU")]
    if mostrar:
        print("\n".join(t.res)); print(f"\nRESULTADO: {len(t.res) - len(falhas)} OK / {len(falhas)} FALHOU")
    return not falhas, t.res
