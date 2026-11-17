# -*- coding: utf-8 -*-
"""Diálogo único para cálculo de áreas e exportação do quadro em Excel."""
from . import compat
import os
import re
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QUrl, QStandardPaths, QSignalBlocker
from qgis.PyQt.QtGui import QBrush, QColor, QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSpinBox, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsProject

from .estilo import (
    PainelPendencias, aplicar_selo, alertar, botao_principal, botao_secundario,
    cabecalho, configurar_alerta_texto, confirmar, dialogo_acoes, icone_tema,
    informar, preparar_dialogo, secao, sucesso,
)
from .areas import (
    atualizar_camada_conferencia, calcular_areas, chave_manual_camada, contar_feicoes, grupo_da_camada,
    prever_reconhecimentos,
)
from .catalogo import (
    apelidos_manuais_projeto, indice_reconhecimento, salvar_apelido_escritorio,
    salvar_apelidos_manuais_projeto,
)
from .planilha import gerar_planilha


class TelaAreas(QDialog):
    """Usada tanto pelo gerenciador quanto pelo modo independente 'Só calcular áreas'."""

    def __init__(self, plugin, parent=None, modo_so_calcular=False):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin=plugin; self.modo_so_calcular=bool(modo_so_calcular); self.resultado=None; self._cache_ocultos={}; self._camada_ids=set(); self._preview={}; self._combos={}; self.indice={}; self.manuais={}
        preparar_dialogo(self,"tela_areas","Norte Agro - Calcular áreas",(880,620)); self.resize(1180,820)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Calcular áreas","Confira o reconhecimento, o método e a saída antes de gerar a planilha.",os.path.join(os.path.dirname(__file__),"icon.png")))

        raiz.addWidget(secao("Camadas"))
        busca_l=QHBoxLayout(); busca_l.addWidget(QLabel("Buscar:")); self.busca=QLineEdit(); self.busca.setPlaceholderText("Buscar camada..."); self.busca.textChanged.connect(self._filtrar); busca_l.addWidget(self.busca,1); self.todos=QCheckBox("Selecionar todos"); self.todos.setTristate(True); self.todos.stateChanged.connect(self._todos_mudou); busca_l.addWidget(self.todos); raiz.addLayout(busca_l)
        self.arvore=QTreeWidget(); self.arvore.setColumnCount(8); self.arvore.setHeaderLabels(["✓","Grupo","Nome","Tipo","Feições","Reconhecer como","Situação","Ações"])
        # v3.9.1: coluna 0 larga o bastante para a caixinha das camadas (o recuo do grupo comia 40 px).
        for col,largura in enumerate([78,160,230,80,80,280,120,90]): self.arvore.setColumnWidth(col,largura)
        self.arvore.header().setMinimumSectionSize(30)
        self.arvore.itemPressed.connect(self._antes_clique); self.arvore.itemChanged.connect(self._item_mudou); raiz.addWidget(self.arvore,1)
        linha_aux=QHBoxLayout(); self.rodape=QLabel("0 camada(s) selecionada(s)"); self.rodape.setProperty("naSubtitle",True); linha_aux.addWidget(self.rodape); linha_aux.addStretch(); self.salvar_apelido_btn=botao_secundario("Nomes não reconhecidos...",self); self.salvar_apelido_btn.setIcon(icone_tema("/mActionEditTable.svg","/mActionOpenTable.svg")); self.salvar_apelido_btn.setToolTip("Escrever o nome de uma camada que o plugin não reconhece e escolher em qual linha da tabela ela entra (vale para o escritório ou só para este projeto)."); self.salvar_apelido_btn.clicked.connect(self.salvar_apelido_escritorio); self.padronizar_todas_btn=botao_secundario("Padronizar todas as reconhecidas",self); self.padronizar_todas_btn.clicked.connect(self.padronizar_todas); self.referencias_btn=botao_secundario("+ Referência",self); self.referencias_btn.setIcon(icone_tema("/mActionAdd.svg")); self.referencias_btn.setToolTip("Cadastrar o nome da camada selecionada (ou outro nome) como camada de referência do escritório."); self.referencias_btn.clicked.connect(self.abrir_referencias); linha_aux.addWidget(self.referencias_btn); linha_aux.addWidget(self.salvar_apelido_btn); linha_aux.addWidget(self.padronizar_todas_btn); raiz.addLayout(linha_aux)
        raiz.addWidget(secao("Método e SRC"))
        met=QHBoxLayout(); met.addWidget(QLabel("Método:")); self.metodo=QComboBox(); self.metodo.addItems(["Elipsoidal (GRS80, vértices a cada 10 m)","Plano UTM"]); met.addWidget(self.metodo,1); self.src_info=QLabel(); met.addWidget(self.src_info); self.src_combo=QComboBox(); self._preencher_src(); self.src_combo.currentIndexChanged.connect(self._src_mudou); met.addWidget(self.src_combo); raiz.addLayout(met)

        raiz.addWidget(secao("Saída"))
        saida_l=QHBoxLayout(); saida_l.addWidget(QLabel("Planilha:")); self.saida=QLineEdit(); self.saida.setReadOnly(True); self.saida.setText(self._sugestao_planilha()); escolher=botao_secundario("Escolher...",self); escolher.clicked.connect(self._escolher_saida); saida_l.addWidget(self.saida,1); saida_l.addWidget(escolher); raiz.addLayout(saida_l)
        # v0.3.0: confere e corrige o desenho das camadas antes de calcular (sobreposição, fora do imóvel...).
        from qgis.core import QgsSettings
        corr_l=QHBoxLayout(); self.corrigir_antes=QCheckBox("Conferir e corrigir as camadas antes de calcular (sobreposição, fora do imóvel, frestas, geometria)")
        self.corrigir_antes.setToolTip("Mostra os problemas do desenho, pergunta qual camada cede a área nas sobreposições largas e corrige as camadas (com cópia de segurança), para o quadro bater com o desenho.")
        self.corrigir_antes.setChecked(str(QgsSettings().value("norteagro_uso_solo/corrigir_antes","1"))!="0")
        self.corrigir_antes.toggled.connect(lambda v: QgsSettings().setValue("norteagro_uso_solo/corrigir_antes","1" if v else "0"))
        corr_l.addWidget(self.corrigir_antes); corr_l.addStretch(); raiz.addLayout(corr_l)
        # v3.9.6: modelo de tabela (estilo do Quadro de Áreas) do escritório.
        mod_l=QHBoxLayout(); mod_l.addWidget(QLabel("Modelo da tabela:")); self.modelo_tabela=QComboBox(); self.modelo_tabela.setToolTip("Quadros, títulos, nomes das linhas, cores, fonte, logo e colunas extras da planilha."); mod_l.addWidget(self.modelo_tabela,1)
        modelos_btn=botao_secundario("Modelos...",self); modelos_btn.clicked.connect(self._editar_modelos_tabela); mod_l.addWidget(modelos_btn); raiz.addLayout(mod_l); self._preencher_modelos_tabela()
        self.resumo_problemas=configurar_alerta_texto(QLabel()); self.resumo_problemas.setVisible(False); raiz.addWidget(self.resumo_problemas)
        self.pendencias=PainelPendencias(self); raiz.addWidget(self.pendencias)
        self.progresso=QProgressBar(); self.progresso.setVisible(False); raiz.addWidget(self.progresso)

        b=QHBoxLayout(); self.ver_mapa=botao_secundario("Ver no mapa",self); self.ver_mapa.clicked.connect(self._zoom_conferencia); self.ver_mapa.setEnabled(False); b.addWidget(self.ver_mapa); self.baixar_btn=botao_secundario("Salvar novamente",self); self.baixar_btn.setEnabled(False); self.baixar_btn.clicked.connect(self.baixar); b.addWidget(self.baixar_btn); b.addStretch(); fechar=botao_secundario("Fechar",self); fechar.clicked.connect(self.accept); self.calcular_btn=botao_principal("Calcular e gerar planilha",self); self.calcular_btn.clicked.connect(self.calcular); b.addWidget(fechar); b.addWidget(self.calcular_btn); raiz.addLayout(b)
        self._src_mudou()
        self._preencher()
    def _src_inicial(self):
        _, salvo = self.plugin.memoria_basica()
        if salvo:
            crs = QgsCoordinateReferenceSystem(salvo)
            if crs.isValid(): return salvo, crs.authid() or salvo
        crs = QgsProject.instance().crs()
        if crs.isValid() and not crs.isGeographic() and crs.mapUnits() == compat.UNID_METROS:
            return crs.authid() or crs.toWkt(), crs.authid() or "SRC projetado do projeto"
        return "", ""

    def _preencher_src(self):
        valor, rotulo = self._src_inicial(); self.src_combo.addItem("Selecione o SRC para o cálculo...", "")
        self.src_combo.addItem("EPSG:31982 - SIRGAS 2000 / UTM 22S", "EPSG:31982"); self.src_combo.addItem("EPSG:31983 - SIRGAS 2000 / UTM 23S", "EPSG:31983")
        if valor:
            i = self.src_combo.findData(valor)
            if i < 0: self.src_combo.addItem(rotulo, valor); i = self.src_combo.count()-1
            self.src_combo.setCurrentIndex(i)
        else: self.src_combo.setCurrentIndex(0)

    def _src_mudou(self):
        srid = self.srid_calculo(); exibido = self.src_combo.currentText().split(" - ")[0] if srid else "não selecionado"
        self.src_info.setText(f"<b>SRC do cálculo:</b> {exibido}")
        if hasattr(self, "calcular_btn"):
            if hasattr(self, "arvore"):
                self._atualizar_estados()
            else:
                self.calcular_btn.setEnabled(bool(srid))
        if hasattr(self, "baixar_btn") and self.resultado is not None:
            self.resultado = None
            self.baixar_btn.setEnabled(False)
            try:
                atualizar_camada_conferencia(None, srid or "EPSG:31982", False)
            except Exception:
                pass
            if hasattr(self, "resumo_problemas"):
                self.resumo_problemas.setText("")
        if hasattr(self, "arvore") and self.arvore.topLevelItemCount(): self._atualizar_reconhecimentos()

    def srid_calculo(self): return str(self.src_combo.currentData() or "")

    def _preencher(self):
        projeto = QgsProject.instance(); permitidos = ("ogr", "memory", "spatialite", "delimitedtext")
        grupos = {}; self._camada_ids = set(); camadas_vivas = []
        for camada in projeto.mapLayers().values():
            if camada.type() != compat.CAMADA_VETOR: continue
            if str(camada.customProperty("norteagro/conferencia", "") or "") == "1": continue
            self._camada_ids.add(camada.id()); camadas_vivas.append(camada)
            grupos.setdefault(grupo_da_camada(camada) or "Sem grupo", []).append(camada)
        self.indice = indice_reconhecimento(projeto); self.manuais = apelidos_manuais_projeto(projeto)
        self._preview, _ = prever_reconhecimentos(camadas_vivas, self.srid_calculo(), self.indice, self.manuais, {})
        bloqueio = QSignalBlocker(self.arvore); self.arvore.clear(); self._combos = {}
        for grupo in sorted(grupos, key=lambda x:x.casefold()):
            pai = QTreeWidgetItem(["", grupo, "", "", "", "", "", ""]); pai.setData(0, Qt.ItemDataRole.UserRole+20, grupo)
            f = pai.font(1); f.setBold(True); pai.setFont(1, f); pai.setFlags((pai.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate); pai.setCheckState(0, Qt.CheckState.Unchecked)
            self.arvore.addTopLevelItem(pai); pai.setExpanded(True)
            for camada in sorted(grupos[grupo], key=lambda l:l.name().casefold()):
                tipo = {compat.GEOM_POLIGONO:"Polígono", compat.GEOM_LINHA:"Linha", compat.GEOM_PONTO:"Ponto"}.get(camada.geometryType(), "Outro")
                rec = self._preview.get(camada.id(), {})
                arquivo_rec = str(rec.get("arquivo", "") or "")
                nome_lista = self.indice.get(arquivo_rec, {}).get("nome", camada.name()) if arquivo_rec else camada.name()
                n_feicoes = contar_feicoes(camada)  # v3.9: KML devolve -2 em featureCount()
                item = QTreeWidgetItem(["", grupo, nome_lista, tipo, str(n_feicoes) if camada.isValid() else "-", "", "", ""]); item.setData(0, Qt.ItemDataRole.UserRole, camada.id()); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(2, f"Nome no QGIS: {camada.name()}" + (f"\nARQUIVO: {arquivo_rec}" if arquivo_rec else ""))
                marcado = camada.isValid() and camada.providerType() in permitidos and n_feicoes > 0; item.setCheckState(0, Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked); pai.addChild(item)
                combo = self._criar_combo(camada, item, self._preview.get(camada.id(), {})); self.arvore.setItemWidget(item, 5, combo); self._combos[camada.id()] = combo
                if not str(camada.customProperty("norteagro/arquivo", "") or ""):
                    self.arvore.setItemWidget(item, 7, self._botao_acoes(camada))
                self._colorir_item(item, self._preview.get(camada.id(), {}), combo)
        del bloqueio; self._atualizar_estados()

    def _texto_auto(self, rec):
        if rec.get("referencia"): return "Automático: referência - não calcular"
        if rec.get("ignorar"): return "Automático: ignorada - não calcular"
        if rec.get("arquivo"):
            arq = rec["arquivo"]; nome = self.indice.get(arq, {}).get("nome", arq)
            return f"Automático: {nome} (via {rec.get('via','nome')})"
        return "Automático: não reconhecida"

    def _criar_combo(self, camada, item, rec):
        # v0.1.1: destinos agrupados pelo quadro da tabela onde a linha aparece.
        from .tela_apelidos import preencher_combo_destinos
        combo = QComboBox(); combo.setMaxVisibleItems(24)
        preencher_combo_destinos(combo, self.indice, antes=[(self._texto_auto(rec), "__AUTO__")],
                                 depois=[("Ignorar no cálculo", "__IGNORAR__"), ("Referência (não calcular)", "__REFERENCIA__")])
        auto_data = "__AUTO__"
        if rec.get("referencia"):
            auto_data = "__REFERENCIA__"; combo.setCurrentIndex(combo.findData("__REFERENCIA__"))
        elif rec.get("ignorar"):
            auto_data = "__IGNORAR__"; combo.setCurrentIndex(combo.findData("__IGNORAR__"))
        else: combo.setCurrentIndex(0)
        item.setData(0, Qt.ItemDataRole.UserRole+30, auto_data)
        item.setText(5, combo.currentText())
        combo.currentIndexChanged.connect(lambda _i, it=item, cb=combo:self._combo_mudou(it, cb))
        return combo

    def _combo_mudou(self, item, combo):
        camada_id = item.data(0, Qt.ItemDataRole.UserRole); rec = self._preview.get(camada_id, {})
        escolhido = str(combo.currentData() or "")
        if escolhido and not escolhido.startswith("__") and escolhido in self.indice:
            item.setText(2, str(self.indice[escolhido].get("nome") or escolhido))
            camada = QgsProject.instance().mapLayer(camada_id)
            item.setToolTip(2, f"Nome no QGIS: {camada.name() if camada else ''}\nARQUIVO: {escolhido}")
        elif escolhido == "__AUTO__":
            arq = rec.get("arquivo")
            camada = QgsProject.instance().mapLayer(camada_id)
            item.setText(2, str(self.indice.get(arq, {}).get("nome") or (camada.name() if camada else "")))
        item.setText(5, combo.currentText())
        self._colorir_item(item, rec, combo)
        self._atualizar_estados()

    def _colorir_item(self, item, rec, combo):
        branco = QBrush(); vermelho = QBrush(QColor("#FFD6D6")); amarelo = QBrush(QColor("#FFF2B2"))
        atual = combo.currentData() if combo else "__AUTO__"; auto = item.data(0, Qt.ItemDataRole.UserRole+30)
        manual = atual not in ("__AUTO__", auto)
        pincel = branco
        if not manual:
            if rec.get("via") == "semelhança": pincel = amarelo
            elif not rec.get("arquivo") and not rec.get("referencia") and not rec.get("ignorar"): pincel = vermelho
        for col in range(8): item.setBackground(col, pincel)
        selo=QLabel(); situacao="OK"
        if atual == "__REFERENCIA__" or (atual == "__AUTO__" and rec.get("referencia")): situacao="Referência"
        elif atual == "__IGNORAR__" or (atual == "__AUTO__" and rec.get("ignorar")): situacao="Ignorada"
        elif not manual and rec.get("via") == "semelhança": situacao="Semelhança"
        elif not manual and not rec.get("arquivo"): situacao="Não reconhecida"
        camada_sel = QgsProject.instance().mapLayer(item.data(0, Qt.ItemDataRole.UserRole))
        if camada_sel is not None and not camada_sel.isValid():
            situacao = "Arquivo não encontrado"
            item.setToolTip(6, "O arquivo desta camada não existe neste computador. Corrija a fonte de dados ou remova a camada.")
            for col in range(8): item.setBackground(col, vermelho)
        item.setText(6, situacao)
        aplicar_selo(selo,situacao); self.arvore.setItemWidget(item,6,selo)

    def _atualizar_reconhecimentos(self):
        if not self._camada_ids: return
        overrides = self._overrides(explicitos_apenas=True)
        projeto = QgsProject.instance()
        camadas = [projeto.mapLayer(lid) for lid in list(self._camada_ids)]
        camadas = [c for c in camadas if c is not None]
        self._camada_ids = {c.id() for c in camadas}
        self.indice = indice_reconhecimento(projeto); self.manuais = apelidos_manuais_projeto(projeto)
        self._preview, _ = prever_reconhecimentos(camadas, self.srid_calculo(), self.indice, self.manuais, overrides)
        for i in range(self.arvore.topLevelItemCount()):
            pai = self.arvore.topLevelItem(i)
            for j in range(pai.childCount()):
                item = pai.child(j); lid = item.data(0, Qt.ItemDataRole.UserRole); combo = self._combos.get(lid); rec = self._preview.get(lid, {})
                if not combo: continue
                if combo.currentData() == "__AUTO__":
                    combo.setItemText(0, self._texto_auto(rec))
                    if rec.get("arquivo") in self.indice: item.setText(2, str(self.indice[rec["arquivo"]].get("nome") or rec["arquivo"]))
                item.setText(5, combo.currentText())
                self._colorir_item(item, rec, combo)
        self._atualizar_estados()

    def _filhos(self, pai, visiveis=False):
        return [pai.child(i) for i in range(pai.childCount()) if (not visiveis or not pai.child(i).isHidden()) and (pai.child(i).flags() & Qt.ItemFlag.ItemIsUserCheckable)]

    def _antes_clique(self, item, coluna):
        if item and item.data(0, Qt.ItemDataRole.UserRole+20): self._cache_ocultos = {id(x):x.checkState(0) for x in self._filhos(item) if x.isHidden()}
        else: self._cache_ocultos = {}

    def _item_mudou(self, item, coluna):
        if coluna != 0: return
        bloqueio = QSignalBlocker(self.arvore)
        if item.data(0, Qt.ItemDataRole.UserRole+20):
            alvo = Qt.CheckState.Checked if item.checkState(0) != Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
            for filho in self._filhos(item, True): filho.setCheckState(0, alvo)
            for filho in self._filhos(item):
                if filho.isHidden() and id(filho) in self._cache_ocultos: filho.setCheckState(0, self._cache_ocultos[id(filho)])
        del bloqueio; self._cache_ocultos = {}; self._atualizar_estados()

    def _todos_mudou(self, estado):
        alvo = Qt.CheckState.Checked if estado != Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        ba = QSignalBlocker(self.arvore); bt = QSignalBlocker(self.todos)
        for i in range(self.arvore.topLevelItemCount()):
            pai = self.arvore.topLevelItem(i)
            if pai.isHidden(): continue
            for item in self._filhos(pai, True): item.setCheckState(0, alvo)
        del ba, bt; self._atualizar_estados()

    def _atualizar_estados(self):
        estados = []; total = 0; ba = QSignalBlocker(self.arvore); bt = QSignalBlocker(self.todos)
        for i in range(self.arvore.topLevelItemCount()):
            pai = self.arvore.topLevelItem(i); todos = self._filhos(pai); vis = self._filhos(pai, True); total += sum(1 for x in todos if x.checkState(0) == Qt.CheckState.Checked)
            if vis:
                marc = sum(1 for x in vis if x.checkState(0) == Qt.CheckState.Checked); pai.setCheckState(0, Qt.CheckState.Checked if marc == len(vis) else Qt.CheckState.Unchecked if marc == 0 else Qt.CheckState.PartiallyChecked)
                if not pai.isHidden(): estados.extend(x.checkState(0) for x in vis)
        if estados:
            self.todos.setEnabled(True); marc = sum(1 for x in estados if x == Qt.CheckState.Checked); self.todos.setCheckState(Qt.CheckState.Checked if marc == len(estados) else Qt.CheckState.Unchecked if marc == 0 else Qt.CheckState.PartiallyChecked)
        else: self.todos.setEnabled(False); self.todos.setCheckState(Qt.CheckState.Unchecked)
        del ba, bt
        self.rodape.setText(f"{total} camada(s) selecionada(s)")
        pend=[]
        if total <= 0:
            pend.append("Marque ao menos uma camada vetorial.")
        if not self.srid_calculo():
            pend.append("Escolha o SRC para o cálculo.")
        if hasattr(self, "pendencias"):
            self.pendencias.definir(pend)
        if hasattr(self, "calcular_btn"):
            self.calcular_btn.setEnabled(not pend)

    def _filtrar(self, texto):
        q = texto.strip().casefold(); bloqueio = QSignalBlocker(self.arvore)
        for i in range(self.arvore.topLevelItemCount()):
            pai = self.arvore.topLevelItem(i); vis = 0
            for j in range(pai.childCount()):
                item = pai.child(j); ocultar = bool(q) and q not in item.text(2).casefold(); item.setHidden(ocultar); vis += 0 if ocultar else 1
            pai.setHidden(vis == 0)
        del bloqueio; self._atualizar_estados()

    def _itens_marcados(self):
        itens = []
        for i in range(self.arvore.topLevelItemCount()):
            pai = self.arvore.topLevelItem(i)
            for item in self._filhos(pai):
                if item.checkState(0) == Qt.CheckState.Checked: itens.append(item)
        return itens

    def _camadas(self):
        projeto = QgsProject.instance(); saida = []
        for item in self._itens_marcados():
            camada = projeto.mapLayer(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
            if camada is not None: saida.append(camada)
        return saida

    def _overrides(self, explicitos_apenas=False):
        saida = {}
        for lid, combo in self._combos.items():
            item = None
            for i in range(self.arvore.topLevelItemCount()):
                pai = self.arvore.topLevelItem(i)
                for j in range(pai.childCount()):
                    if pai.child(j).data(0, Qt.ItemDataRole.UserRole) == lid: item = pai.child(j); break
                if item: break
            if not item: continue
            atual = str(combo.currentData() or "__AUTO__"); auto = str(item.data(0, Qt.ItemDataRole.UserRole+30) or "__AUTO__")
            if atual == "__AUTO__" or atual == auto: continue
            saida[lid] = atual
        return saida

    def _salvar_escolhas_manuais(self, overrides):
        if self.modo_so_calcular or not overrides: return
        dados = apelidos_manuais_projeto(QgsProject.instance())
        for lid, destino in overrides.items():
            camada = QgsProject.instance().mapLayer(lid)
            if camada: dados[chave_manual_camada(camada)] = destino
        salvar_apelidos_manuais_projeto(QgsProject.instance(), dados); self.manuais = dados

    def abrir_referencias(self, nome_inicial=None):
        """v3.9.5: + Referência - pré-preenche com a camada selecionada na lista."""
        from .tela_referencias import abrir_referencias
        if not nome_inicial:
            item = self.arvore.currentItem(); nome_inicial = ""
            if item and not item.data(0, Qt.ItemDataRole.UserRole+20):
                camada = QgsProject.instance().mapLayer(item.data(0, Qt.ItemDataRole.UserRole))
                nome_inicial = camada.name() if camada else ""
        if abrir_referencias(self.plugin, self, nome_inicial):
            self._atualizar_reconhecimentos()

    def salvar_apelido_escritorio(self):
        """v0.1.1: abre a tela Nomes não reconhecidos, já com a camada selecionada (se houver)."""
        nome = ""; destino = ""
        item = self.arvore.currentItem()
        if item and not item.data(0, Qt.ItemDataRole.UserRole+20):
            lid = item.data(0, Qt.ItemDataRole.UserRole); camada = QgsProject.instance().mapLayer(lid)
            if camada is not None:
                nome = camada.name()
                if str((self._combos.get(lid).currentData() if self._combos.get(lid) else "") or "") == "__REFERENCIA__":
                    self.abrir_referencias(nome); return
                destino = self._destino_atual(lid)
        self.ensinar_nome(nome, destino)

    def ensinar_nome(self, nome="", destino=""):
        from .tela_apelidos import abrir_apelidos
        if abrir_apelidos(self.plugin, self, nome, destino):
            self._atualizar_reconhecimentos()

    def ensinar_nome_camada(self, lid):
        camada = QgsProject.instance().mapLayer(lid)
        if camada is not None:
            self.ensinar_nome(camada.name(), self._destino_atual(lid))

    def _salvar_apelido_rapido(self):
        """Fluxo antigo (um clique): mantido para compatibilidade."""
        item = self.arvore.currentItem()
        if not item or item.data(0, Qt.ItemDataRole.UserRole+20):
            informar(self, "Camadas", "Selecione uma camada na lista."); return
        lid = item.data(0, Qt.ItemDataRole.UserRole); camada = QgsProject.instance().mapLayer(lid); combo = self._combos.get(lid)
        if not camada or not combo: return
        atual = str(combo.currentData() or "__AUTO__")
        if atual == "__REFERENCIA__":
            # v3.9.5: referência vai para a lista de referências do escritório.
            self.abrir_referencias(camada.name()); return
        if atual in ("__AUTO__", "__REFERENCIA__", "__IGNORAR__"):
            destino = self._preview.get(lid, {}).get("arquivo", "")
        else: destino = atual
        if not destino or destino not in self.indice:
            alertar(self, "Reconhecer como", "Escolha primeiro um ARQUIVO válido em 'Reconhecer como'."); return
        if not confirmar(self, "Apelido do escritório", f"Salvar o nome {camada.name()} como apelido de {destino} para todos os usuários?", "Salvar"): return
        try:
            salvar_apelido_escritorio(camada.name(), destino, self.indice)
            sucesso(self, "Apelido do escritório", "Apelido salvo no catálogo do plugin.")
            self._atualizar_reconhecimentos()
        except Exception as exc:
            self.plugin.log(f"Falha ao salvar apelido do escritório: {exc}"); alertar(self, "Apelido do escritório", "Não foi possível alterar o catálogo do escritório.", str(exc))

    def _botao_acoes(self, camada):
        botao = QPushButton("Ações")
        menu = QMenu(botao)
        ens = menu.addAction("Ensinar este nome (escolher a linha da tabela)...")
        pad = menu.addAction("Criar camada padrão com este conteúdo")
        rem = menu.addAction("Remover camada")
        ens.triggered.connect(lambda _=False, lid=camada.id(): self.ensinar_nome_camada(lid))
        pad.triggered.connect(lambda _=False, lid=camada.id(): self.padronizar_uma(lid))
        rem.triggered.connect(lambda _=False, lid=camada.id(): self.remover_uma(lid))
        botao.setMenu(menu)
        return botao

    def _destino_atual(self, lid):
        combo = self._combos.get(lid); rec = self._preview.get(lid, {})
        if combo:
            atual = str(combo.currentData() or "__AUTO__")
            if atual not in ("__AUTO__", "__REFERENCIA__", "__IGNORAR__") and atual in self.indice:
                return atual
        return str(rec.get("arquivo", "") or "")

    def padronizar_uma(self, lid):
        camada = QgsProject.instance().mapLayer(lid)
        if not camada: return
        from .tela_padronizar import padronizar_camada
        padronizar_camada(self.plugin, camada, self._destino_atual(lid), self.srid_calculo(), self)
        self._preencher()

    def remover_uma(self, lid):
        camada = QgsProject.instance().mapLayer(lid)
        if not camada: return
        from .tela_padronizar import remover_camada_com_confirmacao
        if remover_camada_com_confirmacao(self.plugin, camada, self):
            self._preencher()

    def padronizar_todas(self):
        from .catalogo import indice_catalogo_avulsa
        alvos_catalogo=indice_catalogo_avulsa(QgsProject.instance())
        candidatos=[]
        projeto = QgsProject.instance()
        for lid in list(self._camada_ids):
            camada = projeto.mapLayer(lid)
            if camada is None:
                continue
            if str(camada.customProperty("norteagro/arquivo", "") or ""):
                continue
            combo = self._combos.get(lid)
            escolha = str(combo.currentData() or "__AUTO__") if combo else "__AUTO__"
            if escolha in ("__REFERENCIA__", "__IGNORAR__"):
                continue
            rec=self._preview.get(lid,{})
            arquivo=self._destino_atual(lid)
            if arquivo and arquivo in alvos_catalogo and not (escolha == "__AUTO__" and (rec.get("referencia") or rec.get("ignorar"))):
                candidatos.append((camada,arquivo))
        if not candidatos:
            informar(self,"Padronizar camadas","Não há camadas reconhecidas sem padrão para padronizar."); return
        from .tela_padronizar import DialogoDestinoExterno, DialogoPadronizarTodas, padronizar_camada
        pasta,srid_mem=self.plugin.memoria_basica(); pasta_valida=pasta if pasta and os.path.isdir(pasta) else ""
        srid=srid_mem if pasta_valida else self.srid_calculo(); base=None; kml=None
        if pasta_valida:
            base=os.path.join(pasta_valida,"shapefiles"); kml=os.path.join(pasta_valida,"kml")
        else:
            dd=DialogoDestinoExterno(self.plugin,srid,self)
            if not compat.aceito(dd.exec()): return
            base,srid,kml=dd.valores()
        prev=DialogoPadronizarTodas(self.plugin,candidatos,srid,base,self)
        if not compat.aceito(prev.exec()): return
        marcadas=prev.marcadas(); ok=[]; falhas=[]
        self.progresso.setRange(0,max(1,len(marcadas))); self.progresso.setValue(0); self.progresso.setVisible(True); self.padronizar_todas_btn.setEnabled(False); self.calcular_btn.setEnabled(False); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i,(camada,arquivo) in enumerate(marcadas,1):
                self.progresso.setFormat(f"Padronizando {i} de {len(marcadas)}..."); QApplication.processEvents()
                certo,det=padronizar_camada(self.plugin,camada,arquivo,srid,self,
                    base_externa=base if not pasta_valida else None,kml_externo=kml,
                    perguntar_original=False,destino_forcado=arquivo,corrigir_forcado=True,mostrar_resumo=False)
                if certo: ok.append(arquivo)
                elif det!="cancelado": falhas.append(f"{camada.name()}: {det}")
                self.progresso.setValue(i)
        finally:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False); self.padronizar_todas_btn.setEnabled(True); self.calcular_btn.setEnabled(bool(self.srid_calculo()))
        texto=f"Padronizadas: {len(ok)}\nFalhas: {len(falhas)}\n\nAs camadas originais foram mantidas no projeto."
        if falhas: texto+="\n\n"+"\n".join(falhas[:12])
        informar(self,"Padronização concluída",texto); self._preencher()

    def _geoms_problemas(self):
        """Geometrias dos problemas que sobraram (o que o plugin não corrige sozinho)."""
        return [x["geom"] for x in (self.resultado or {}).get("geometrias_conferencia", []) or []
                if x.get("geom") is not None and not x["geom"].isEmpty()]

    def _zoom_conferencia(self):
        """v0.4.0: mostra os problemas piscando no mapa, sem criar camada."""
        geoms = self._geoms_problemas()
        if not geoms:
            return
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry
            canvas = self.plugin.iface.mapCanvas(); destino = canvas.mapSettings().destinationCrs()
            origem = QgsCoordinateReferenceSystem(self.srid_calculo() or "EPSG:31982")
            tr = QgsCoordinateTransform(origem, destino, QgsProject.instance().transformContext()) if origem != destino else None
            gs = []
            for g in geoms:
                g = QgsGeometry(g)
                if tr is not None: g.transform(tr)
                gs.append(g)
            caixa = gs[0].boundingBox()
            for g in gs[1:]: caixa.combineExtentWith(g.boundingBox())
            caixa.grow(max(caixa.width(), caixa.height(), 30.0) * 0.3)
            canvas.setExtent(caixa); canvas.refresh(); canvas.flashGeometries(gs, destino)
        except Exception as exc:
            self.plugin.log(f"Falha ao mostrar os problemas no mapa: {exc}")

    def _avisar_problemas_desenho(self):
        detalhes=list((self.resultado or {}).get("problemas_detalhados",[])); simples=list((self.resultado or {}).get("problemas_desenho",[]))
        if not detalhes and not simples:
            # v0.4.0: sem camada de erros, o que sobrou no mapa (ex.: área sem classificação) é avisado aqui
            for x in (self.resultado or {}).get("geometrias_conferencia",[]) or []:
                txt=str(x.get("camada") or x.get("tipo") or "Problema"); txt=txt.split(". ",1)[-1] if txt[:3].strip(". ").isalnum() and ". " in txt[:6] else txt
                simples.append(f"{txt} - {float(x.get('area_m2',0))/10000:.4f} ha".replace(".",",") + (f" - E {x['e']:.0f} / N {x['n']:.0f}" if x.get("e") else ""))
        if not detalhes and not simples:
            self.resumo_problemas.clear(); self.resumo_problemas.setVisible(False); self.ver_mapa.setEnabled(False); return
        por_quadro=(self.resultado or {}).get("problemas_por_quadro",{}) or {}; total=len(detalhes) if detalhes else len(simples)
        resumo=", ".join(f"{q}: {len(v)}" for q,v in por_quadro.items() if v)
        self.resumo_problemas.setText(f"{total} problema(s) de desenho encontrado(s). " + (resumo if resumo else "Veja a aba Conferências.")); self.resumo_problemas.setVisible(True); self.ver_mapa.setEnabled(bool(self._geoms_problemas()))
        itens=[]
        for x in detalhes[:10]:
            texto=f"{x.get('descricao','Problema')}: {x.get('tamanho','')}".strip()
            if x.get('onde'): texto += f" - {x['onde']}"
            itens.append(texto)
        if not itens: itens=simples[:10]
        acao=dialogo_acoes(self,"Problemas de desenho encontrados",("Ainda restam os pontos abaixo, que o plugin não corrige sozinho (ex.: área sem classificação). Confira o desenho antes de entregar os arquivos." if ((getattr(self,"_correcao_info",None) or {}).get("gravadas") or (getattr(self,"corrigir_antes",None) is not None and self.corrigir_antes.isChecked())) else "O cálculo foi feito desconsiderando os problemas abaixo. As camadas NÃO foram alteradas; marque \"Conferir e corrigir as camadas antes de calcular\" para o plugin corrigir o desenho."),itens,[("Ver no mapa",QMessageBox.ButtonRole.ActionRole),("Continuar",QMessageBox.ButtonRole.AcceptRole)],"alerta","Continuar")
        if acao=="Ver no mapa": self._zoom_conferencia()

    def calcular(self):
        camadas=self._camadas(); srid=self.srid_calculo()
        pend=[]
        if not camadas: pend.append("Marque ao menos uma camada vetorial.")
        if not srid: pend.append("Escolha o SRC para o cálculo.")
        self.pendencias.definir(pend)
        if pend: return
        overrides=self._overrides(); self._salvar_escolhas_manuais(overrides)
        previsoes,_=prever_reconhecimentos(camadas,srid,self.indice,self.manuais,overrides)
        nao=[c.name() for c in camadas if not previsoes[c.id()].get("arquivo") and not previsoes[c.id()].get("referencia") and not previsoes[c.id()].get("ignorar")]
        if nao:
            acao=dialogo_acoes(self,"Camadas não reconhecidas","Há camadas marcadas sem destino de reconhecimento.",nao,[("Voltar e escolher o destino",QMessageBox.ButtonRole.RejectRole),("Calcular sem elas",QMessageBox.ButtonRole.AcceptRole)],"alerta","Voltar e escolher o destino")
            if acao!="Calcular sem elas": return
        self._correcao_info=None; self._descartar=set()
        if getattr(self,"corrigir_antes",None) is not None and self.corrigir_antes.isChecked():
            if not self._conferir_camadas(camadas,srid,overrides): return
            if self._descartar: camadas=[c for c in camadas if c.id() not in self._descartar]
        self.progresso.setRange(0,max(1,len(camadas))); self.progresso.setVisible(True); self.calcular_btn.setEnabled(False); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        def atualizar(valor,total,texto):
            self.progresso.setMaximum(max(1,total)); self.progresso.setValue(min(valor,total)); self.progresso.setFormat(texto); QApplication.processEvents()
        try:
            pasta,_=self.plugin.memoria_basica(); pasta=pasta if pasta and os.path.isdir(pasta) else ""
            self.resultado=calcular_areas(camadas,srid,self.metodo.currentText(),self.indice,atualizar,self.manuais,overrides,pasta)
            self.resultado["casas"]=4; projeto=QgsProject.instance(); self.resultado["imovel_nome"]=(os.path.basename(os.path.dirname(pasta.rstrip(os.sep))) or os.path.basename(pasta.rstrip(os.sep))) if pasta else (projeto.baseName() or "PROJETO")
            atualizar_camada_conferencia(None,srid,False)  # v0.4.0: sem camada de erros; só limpa a de versões antigas
            alertas_coord=self.resultado.get("alertas_coordenadas",[])
            if alertas_coord: alertar(self,"Coordenadas fora do lugar","Foram encontradas camadas com coordenadas fora da faixa esperada para o SRC do cálculo.",alertas_coord)
            self._informar_correcao(); self._avisar_problemas_desenho(); self.baixar_btn.setEnabled(True); self.ver_mapa.setEnabled(bool(self._geoms_problemas()))
            self._salvar_resultado(self.saida.text().strip(), perguntar_local=not bool(self.saida.text().strip()))
        except Exception as exc:
            self.plugin.log(f"Erro geral no cálculo de áreas: {exc}"); alertar(self,"Cálculo não concluído","Não foi possível concluir o cálculo.",[str(exc)])
        finally:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False); self._atualizar_estados()

    def _conferir_camadas(self, camadas, srid, overrides):
        """v0.3.0: diagnóstico + pergunta + correção das camadas. False = usuário cancelou."""
        from .correcao import Correcao
        from .tela_correcao import TelaCorrecao
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pasta,_=self.plugin.memoria_basica(); pasta=pasta if pasta and os.path.isdir(pasta) else ""
            def andamento(texto):
                self.progresso.setVisible(True); self.progresso.setRange(0,0); self.progresso.setFormat(texto)
            corr=Correcao(camadas,srid,self.indice,self.manuais,overrides,pasta,progresso=andamento); rel=corr.executar()
        except Exception as exc:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False); self.plugin.log(f"Conferência das camadas: {exc}")
            alertar(self,"Conferir camadas","Não foi possível conferir as camadas; o cálculo segue sem correção.",[str(exc)]); return True
        QApplication.restoreOverrideCursor(); self.progresso.setVisible(False)
        if not rel.get("corrigir"):
            return True
        tela=TelaCorrecao(self.plugin,corr,rel,self); tela.exec()
        if tela.decisao is None: return False
        if tela.decisao!="corrigir": return True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        nao_corrigidas={}; fora_sugestao=0
        try:
            escolhas=tela.escolhas()
            # v0.7.0: quantas decisões a pessoa trocou da sugestão do plugin (a diferença que sobrar pode vir delas)
            fora_sugestao=sum(1 for k in (rel.get("conflitos") or []) if k.get("id") in escolhas and escolhas[k["id"]]!=k.get("sugestao"))
            corr.executar(escolhas); gravadas,erros,backups=corr.gravar()
            self._descartar=set(getattr(corr,"descartadas",set()) or set())  # v0.4.0: repetidas ficam fora do cálculo
            nao_corrigidas=corr.nao_corrigidas() if hasattr(corr,"nao_corrigidas") else {}
        except Exception as exc:
            gravadas,erros,backups=[],[str(exc)],[]
        finally:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False)
        self._correcao_info={"gravadas":gravadas,"erros":erros,"backups":backups,"nao_corrigidas":nao_corrigidas,"fora_sugestao":fora_sugestao}
        if erros: alertar(self,"Correção das camadas","Algumas camadas não puderam ser corrigidas (as outras foram).",erros)
        return True

    def _informar_correcao(self):
        info=getattr(self,"_correcao_info",None)
        if not info or not (info.get("gravadas") or info.get("nao_corrigidas")): return
        from .correcao import conferir_resultado
        faltam=conferir_resultado(self.resultado,indice=self.indice)
        det=[f"Camadas corrigidas: {', '.join(info['gravadas'])}."] if info.get("gravadas") else []
        if info.get("backups"): det.append("Cópia de segurança de cada uma na pasta _backup ao lado do arquivo.")
        if not faltam:
            if info.get("gravadas"):
                sucesso(self,"Camadas corrigidas","As camadas foram corrigidas e o Quadro de Áreas bate com o desenho.",det)
            return
        # v0.7.0: diz POR QUE ainda há diferença - camada que o plugin não pôde alterar, ou decisão trocada na tela de
        # correção - em vez de só avisar que há diferença.
        nao=info.get("nao_corrigidas") or {}
        presas=[f for f in faltam if f.split(":",1)[0] in nao]
        outras=[f for f in faltam if f not in presas]
        linhas=list(det)
        if presas:
            linhas.append("Não puderam ser alteradas (o quadro usa o desenho delas só na parte certa):")
            linhas += [f"  {f} - motivo: {nao[f.split(':',1)[0]]}" for f in presas]
        if outras:
            if info.get("fora_sugestao"):
                linhas.append(f"Diferença que vem das {info['fora_sugestao']} decisão(ões) que você trocou na tela de correção (ex.: \"Não mexer\" / \"Deixar\"):")
            else:
                linhas.append("Ainda diferente:")
            linhas += [f"  {f}" for f in outras]
        if presas and not outras:
            texto="As camadas foram corrigidas, menos as abaixo, que o plugin não pôde alterar. Resolva o motivo indicado e calcule de novo com \"Conferir e corrigir\" marcado:"
        elif outras and info.get("fora_sugestao") and not presas:
            texto="As camadas foram corrigidas como você escolheu. Onde você decidiu não mexer, o quadro continua diferente do desenho:"
        else:
            texto="As camadas foram corrigidas, mas ainda há diferença entre o desenho e o quadro:"
        alertar(self,"Camadas corrigidas",texto,linhas)

    @staticmethod
    def _nome_seguro(texto):
        texto = re.sub(r'[\\/:*?"<>|]', "_", str(texto or "")).strip(); return texto or "PROJETO"

    def _sugestao_planilha(self):
        projeto = QgsProject.instance(); pasta_mapa, _ = self.plugin.memoria_basica()
        if pasta_mapa and os.path.isdir(pasta_mapa): destino = pasta_mapa; base = os.path.basename(os.path.dirname(pasta_mapa.rstrip(os.sep))) or "PROJETO"
        elif projeto.fileName() and projeto.absolutePath(): destino = projeto.absolutePath(); base = projeto.baseName() or "PROJETO"
        else: destino = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~/Documents"); base = "PROJETO"
        return os.path.join(destino, f"QUADRO_DE_AREAS_{self._nome_seguro(base)}_{datetime.now().strftime('%Y-%m-%d')}.xlsx")

    def _preencher_modelos_tabela(self, manter=None):
        from qgis.core import QgsSettings
        from .modelos import PADRAO, modelos_tabela
        atual = manter or str(QgsSettings().value("norteagro/modelo_tabela", PADRAO) or PADRAO)
        self.modelo_tabela.clear()
        for m in modelos_tabela(): self.modelo_tabela.addItem(m["nome"], m["nome"])
        i = self.modelo_tabela.findData(atual); self.modelo_tabela.setCurrentIndex(i if i >= 0 else 0)

    def _editar_modelos_tabela(self):
        atual = self.modelo_tabela.currentData(); self.plugin.abrir_modelos(self, 2); self._preencher_modelos_tabela(atual)

    def _modelo_tabela_escolhido(self):
        from qgis.core import QgsSettings
        from .modelos import modelo_tabela
        nome = self.modelo_tabela.currentData() if hasattr(self, "modelo_tabela") else None
        if nome: QgsSettings().setValue("norteagro/modelo_tabela", nome)
        return modelo_tabela(nome)

    def _escolher_saida(self):
        caminho,_=QFileDialog.getSaveFileName(self,"Salvar planilha",self.saida.text().strip() or self._sugestao_planilha(),"Planilha Excel (*.xlsx)")
        if caminho:
            if not caminho.lower().endswith(".xlsx"): caminho += ".xlsx"
            self.saida.setText(caminho)

    def _salvar_resultado(self, caminho="", perguntar_local=False):
        if not self.resultado: return False
        if perguntar_local or not caminho:
            caminho,_=QFileDialog.getSaveFileName(self,"Salvar planilha",self._sugestao_planilha(),"Planilha Excel (*.xlsx)")
            if not caminho: return False
        if not caminho.lower().endswith(".xlsx"): caminho += ".xlsx"
        try: gerar_planilha(caminho,self.resultado,self._modelo_tabela_escolhido())
        except PermissionError: alertar(self,"Planilha em uso","A planilha está aberta no Excel. Feche-a e tente de novo."); return False
        except Exception as exc: self.plugin.log(f"Erro ao gerar planilha: {exc}"); alertar(self,"Planilha não gerada","Não foi possível gerar a planilha.",[str(exc)]); return False
        self.saida.setText(caminho); sucesso(self,"Planilha gerada","A planilha foi salva com sucesso.",[caminho]); return True

    def baixar(self):
        if not self.resultado: return
        self._salvar_resultado(self.saida.text().strip(), perguntar_local=False)
