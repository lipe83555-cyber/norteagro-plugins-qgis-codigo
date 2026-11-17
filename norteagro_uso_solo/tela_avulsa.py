# -*- coding: utf-8 -*-
"""Criação de uma ou várias camadas do catálogo em qualquer pasta escolhida."""
from . import compat
import os

from qgis.PyQt.QtCore import Qt, QSize, QSignalBlocker, QItemSelectionModel, pyqtSignal
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QScrollArea, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import Qgis, QgsProject, QgsSymbolLayerUtils

from .catalogo import apelidos_para_indice, catalogo_avulsa, indice_catalogo_avulsa, simbolo_entrada
from .estilo import (
    PainelPendencias, aplicar_selo, botao_icone, botao_principal, botao_secundario,
    cabecalho, confirmar, dialogo_acoes, icone_tema, preparar_dialogo, secao,
)
from .reconhecimento import normalizar_chave

ROLE_ARQUIVO = Qt.ItemDataRole.UserRole + 1
ROLE_SEARCH = Qt.ItemDataRole.UserRole + 11


class _CompleterCatalogo(QCompleter):
    def pathFromIndex(self, index):
        return str(index.data(Qt.ItemDataRole.DisplayRole) or "")


class ComboCatalogo(QComboBox):
    enterPressed = pyqtSignal(bool)

    def __init__(self, grupos, tabela_apelidos, plugin, parent=None):
        super().__init__(parent)
        self._grupos = grupos; self._apelidos = tabela_apelidos; self._plugin = plugin
        self.setEditable(True); self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert); self.setMinimumWidth(280)
        self._montar_modelo()
        comp = _CompleterCatalogo(self.model(), self); comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); comp.setFilterMode(Qt.MatchFlag.MatchContains); comp.setCompletionRole(ROLE_SEARCH)
        self.setCompleter(comp); self.lineEdit().textEdited.connect(self._buscar); comp.activated[str].connect(self._ativado)
        self.setCurrentIndex(-1); self.lineEdit().setPlaceholderText("Digite para buscar no catálogo...")
        self.setToolTip("Digite o nome, o ARQUIVO ou um apelido da camada.")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enterPressed.emit(bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)); event.accept(); return
        super().keyPressEvent(event)

    def _montar_modelo(self):
        modelo = QStandardItemModel(self)
        custom = QStandardItem("+ Camada personalizada..."); custom.setData("__CUSTOM__", ROLE_ARQUIVO); custom.setData("CAMADA_PERSONALIZADA", ROLE_SEARCH); modelo.appendRow(custom)
        for grupo, itens in self._grupos.items():
            cab = QStandardItem(grupo); cab.setEnabled(False); cab.setData(normalizar_chave(grupo), ROLE_SEARCH); f=cab.font(); f.setBold(True); cab.setFont(f); modelo.appendRow(cab)
            for entrada in itens:
                arquivo = entrada["arquivo"]; tipo={"P":"Polígono","L":"Linha","Pt":"Ponto"}.get(entrada.get("tipo"),str(entrada.get("tipo","")))
                texto = f"{entrada.get('nome', arquivo)} - {tipo}"
                item=QStandardItem(texto); item.setData(arquivo,ROLE_ARQUIVO); item.setToolTip(f"ARQUIVO: {arquivo}")
                if not self._plugin.entrada_valida(arquivo):
                    item.setEnabled(False); item.setToolTip(f"ARQUIVO: {arquivo}\nDesabilitada por inconsistência no catálogo.")
                busca=[normalizar_chave(texto),normalizar_chave(arquivo),normalizar_chave(entrada.get("nome",""))]; busca.extend(self._apelidos.get(arquivo,[])); item.setData(" ".join(x for x in busca if x),ROLE_SEARCH)
                try: item.setIcon(QgsSymbolLayerUtils.symbolPreviewIcon(simbolo_entrada(entrada),QSize(22,22)))
                except Exception: pass
                modelo.appendRow(item)
        self.setModel(modelo)

    def _buscar(self,texto):
        self.completer().setCompletionPrefix(normalizar_chave(texto)); self.completer().complete()

    def _ativado(self,texto):
        for i in range(self.count()):
            if self.itemText(i)==texto: self.setCurrentIndex(i); return

    def arquivo(self):
        i=self.currentIndex()
        if i<0 or self.lineEdit().text().strip()!=self.itemText(i).strip(): return ""
        return str(self.currentData(ROLE_ARQUIVO) or "")


class LinhaCamada(QWidget):
    def __init__(self, numero, dialogo):
        super().__init__(dialogo); self.dialogo=dialogo; self.numero=numero; self.custom=None
        layout=QGridLayout(self); layout.setContentsMargins(2,2,2,2); layout.setHorizontalSpacing(8); layout.setVerticalSpacing(0)
        self.num=QLabel(str(numero)); self.num.setFixedWidth(28); self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo=ComboCatalogo(dialogo.grupos,dialogo.apelidos,dialogo.plugin,self); self.combo.currentIndexChanged.connect(self._mudou); self.combo.enterPressed.connect(self._enter)
        self.tipo_wrap=QWidget(self); tipo_l=QHBoxLayout(self.tipo_wrap); tipo_l.setContentsMargins(0,0,0,0); tipo_l.setSpacing(4)
        self.tipo_icone=QLabel(); self.tipo_icone.setFixedSize(18,18); self.tipo=QLabel(""); self.tipo.setMinimumWidth(82); tipo_l.addWidget(self.tipo_icone); tipo_l.addWidget(self.tipo); tipo_l.addStretch()
        self.preview=QLabel(); self.preview.setFixedSize(28,28); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status=QLabel(); self.status.setMinimumWidth(140); aplicar_selo(self.status,"Vazia")
        self.remover=botao_icone(icone_tema("/mActionDeleteSelected.svg","/mActionRemove.svg"),"Remover esta linha",self); self.remover.clicked.connect(lambda: dialogo.remover_linha(self))
        layout.addWidget(self.num,0,0); layout.addWidget(self.combo,0,1); layout.addWidget(self.tipo_wrap,0,2); layout.addWidget(self.preview,0,3); layout.addWidget(self.status,0,4); layout.addWidget(self.remover,0,5)
        self.setMinimumHeight(34); self.setMaximumHeight(38)

    def _enter(self, ctrl):
        if ctrl: self.dialogo.executar(); return
        self.dialogo.avancar_linha(self)

    def entrada(self):
        if self.custom: return self.custom
        return self.dialogo.indice.get(self.combo.arquivo())

    def preenchida(self): return self.entrada() is not None

    def _mudou(self):
        arq=self.combo.arquivo()
        if arq=="__CUSTOM__":
            from .tela_nova_camada import TelaNovaCamada
            dlg=TelaNovaCamada(self.dialogo.plugin,self.dialogo,somente_definicao=True)
            if compat.aceito(dlg.exec()) and dlg.entrada_resultado:
                self.custom=dict(dlg.entrada_resultado); texto=f"{self.custom['nome']} - personalizada"
                item=QStandardItem(texto); item.setData(self.custom["arquivo"],ROLE_ARQUIVO); item.setData(normalizar_chave(texto),ROLE_SEARCH)
                try: item.setIcon(QgsSymbolLayerUtils.symbolPreviewIcon(simbolo_entrada(self.custom),QSize(22,22)))
                except Exception: pass
                self.combo.model().appendRow(item); self.combo.setCurrentIndex(self.combo.count()-1)
            else:
                self.custom=None; self.combo.setCurrentIndex(-1)
        elif not (self.custom and arq==self.custom.get("arquivo")): self.custom=None
        self.atualizar_visual(); self.dialogo.validar()

    def atualizar_visual(self):
        e=self.entrada()
        if not e:
            self.tipo.setText(""); self.tipo_icone.clear(); self.preview.clear(); aplicar_selo(self.status,"Vazia"); return
        tipo=e.get("tipo"); self.tipo.setText({"P":"Polígono","L":"Linha","Pt":"Ponto"}.get(tipo,str(tipo or "")))
        nomes={"P":("/mIconPolygonLayer.svg",),"L":("/mIconLineLayer.svg",),"Pt":("/mIconPointLayer.svg",)}
        ico=icone_tema(*nomes.get(tipo,("/mIconVector.svg",))); self.tipo_icone.setPixmap(ico.pixmap(QSize(16,16))) if not ico.isNull() else self.tipo_icone.clear()
        try: self.preview.setPixmap(QgsSymbolLayerUtils.symbolPreviewIcon(simbolo_entrada(e),QSize(22,22)).pixmap(QSize(22,22)))
        except Exception: self.preview.clear()
        shp=self.dialogo.caminho_shp(e["arquivo"]); aplicar_selo(self.status,"Já existe nesta pasta" if shp and os.path.isfile(shp) else "OK")


class TelaAvulsa(QDialog):
    """Cria de 1 a 50 camadas sem alterar norteagro_pasta/srid/extras."""
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin=plugin; self.linhas=[]; self._kml_manual=False; self._criadas_ids=[]
        preparar_dialogo(self,"tela_avulsa","Norte Agro - Criar camadas em uma pasta",(780,560)); self.resize(1080,760)
        self.grupos=catalogo_avulsa(QgsProject.instance()); self.indice=indice_catalogo_avulsa(QgsProject.instance()); self.apelidos,_,_=apelidos_para_indice(self.indice)
        raiz=QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Criar camadas em uma pasta","Escolha as camadas do catálogo e a pasta onde salvar.",os.path.join(os.path.dirname(__file__),"icon.png")))
        raiz.addWidget(secao("Camadas"))
        controles=QHBoxLayout(); controles.addWidget(QLabel("Quantidade")); self.qtd=QSpinBox(); self.qtd.setRange(1,50); self.qtd.setValue(1); self.qtd.valueChanged.connect(self._quantidade_mudou); controles.addWidget(self.qtd); controles.addStretch()
        self.remover_vazias=botao_secundario("Remover linhas vazias",self); self.remover_vazias.clicked.connect(self.remover_linhas_vazias); controles.addWidget(self.remover_vazias); raiz.addLayout(controles)
        cab=QGridLayout(); cab.setContentsMargins(2,0,2,0); cab.setHorizontalSpacing(8)
        titulos=[("Nº",0),("Camada",1),("Tipo",2),("Estilo",3),("Situação",4),("",5)]
        for txt,col in titulos:
            lab=QLabel(f"<b>{txt}</b>"); cab.addWidget(lab,0,col)
        cab.setColumnStretch(1,1); raiz.addLayout(cab)
        self.area=QScrollArea(); self.area.setWidgetResizable(True); self.container=QWidget(); self.lista_layout=QVBoxLayout(self.container); self.lista_layout.setContentsMargins(0,0,0,0); self.lista_layout.setSpacing(2); self.lista_layout.addStretch(); self.area.setWidget(self.container); raiz.addWidget(self.area,1)
        self.adicionar=botao_secundario("+ Adicionar camada",self); self.adicionar.clicked.connect(self.adicionar_linha); self.adicionar.setToolTip("Adicionar uma nova linha vazia ao final da lista."); self.adicionar.setMinimumWidth(320); raiz.addWidget(self.adicionar,0,Qt.AlignmentFlag.AlignLeft)

        raiz.addWidget(secao("Destino"))
        hp=QHBoxLayout(); hp.addWidget(QLabel("Pasta de destino:")); self.pasta=QLineEdit(); self.pasta.setToolTip("Pasta onde serão criadas as subpastas das camadas."); bp=botao_secundario("Escolher...",self); bp.setIcon(icone_tema("/mActionFileOpen.svg")); bp.clicked.connect(self._escolher_pasta); hp.addWidget(self.pasta,1); hp.addWidget(bp); raiz.addLayout(hp); self.pasta.textChanged.connect(self._destino_mudou)
        hs=QHBoxLayout(); hs.addWidget(QLabel("SRC:")); self.src=QComboBox(); self.src.addItem("Selecione...",""); self.src.addItem("EPSG:31982 - SIRGAS 2000 / UTM 22S","EPSG:31982"); self.src.addItem("EPSG:31983 - SIRGAS 2000 / UTM 23S","EPSG:31983"); hs.addWidget(self.src,1); raiz.addLayout(hs); self._preencher_src(); self.src.currentIndexChanged.connect(self.validar)
        hk=QHBoxLayout(); hk.addWidget(QLabel("Pasta do KML:")); self.kml=QLineEdit(); self.kml.setToolTip("Destino dos espelhos KML. É definido automaticamente ao escolher a pasta de destino."); self.kml.textEdited.connect(self._kml_editado); self.kml_info=QLabel("definida automaticamente"); self.kml_info.setProperty("naSubtitle",True); bk=botao_secundario("Alterar...",self); bk.clicked.connect(self._escolher_kml); hk.addWidget(self.kml,1); hk.addWidget(self.kml_info); hk.addWidget(bk); raiz.addLayout(hk)

        self.pendencias=PainelPendencias(self); raiz.addWidget(self.pendencias)
        self.progresso=QProgressBar(); self.progresso.setVisible(False); raiz.addWidget(self.progresso)
        rodape=QHBoxLayout()
        self.ferramentas=QToolButton(self); self.ferramentas.setText("Ferramentas"); self.ferramentas.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup); menu=QMenu(self.ferramentas)
        menu.addAction("Ajustar nomes no QGIS",self.ajustar_nomes); menu.addAction("Voltar nomes de arquivo",self.voltar_nomes); menu.addSeparator(); menu.addAction("Exportar KML",self.exportar_kml); menu.addSeparator(); menu.addAction(icone_tema("/mActionAdd.svg"),"+ Camadas de referência...",self.abrir_referencias); menu.addAction(icone_tema("/mActionOptions.svg","/mActionPropertiesWidget.svg"),"Modelos (pastas, cores e tabela)...",lambda: self.plugin.abrir_modelos(self)); self.ferramentas.setMenu(menu); rodape.addWidget(self.ferramentas); rodape.addStretch()
        fechar=botao_secundario("Fechar",self); fechar.clicked.connect(self.accept); self.criar=botao_principal("Criar 1 camada",self); self.criar.clicked.connect(self.executar); rodape.addWidget(fechar); rodape.addWidget(self.criar); raiz.addLayout(rodape)
        self._ajustar_linhas(1); self.validar()

    def _preencher_src(self):
        _,salvo=self.plugin.memoria_basica(); alvo=salvo if salvo in ("EPSG:31982","EPSG:31983") else ""
        if not alvo:
            crs=QgsProject.instance().crs(); auth=crs.authid() if crs.isValid() and not crs.isGeographic() and crs.mapUnits()==compat.UNID_METROS else ""
            if auth in ("EPSG:31982","EPSG:31983"): alvo=auth
        self.src.setCurrentIndex(max(0,self.src.findData(alvo)))

    def _quantidade_mudou(self,n):
        atual=len(self.linhas)
        if n<atual and any(x.preenchida() for x in self.linhas[n:]):
            if not confirmar(self,"Remover linhas","As últimas linhas possuem seleção. Removê-las?","Remover",destrutivo=True):
                b=QSignalBlocker(self.qtd); self.qtd.setValue(atual); del b; return
        self._ajustar_linhas(n); self.validar()

    def _ajustar_linhas(self,n):
        while len(self.linhas)<n:
            linha=LinhaCamada(len(self.linhas)+1,self); self.lista_layout.insertWidget(self.lista_layout.count()-1,linha); self.linhas.append(linha)
        while len(self.linhas)>n:
            linha=self.linhas.pop(); self.lista_layout.removeWidget(linha); linha.deleteLater()
        self._renumerar()

    def _renumerar(self):
        for i,linha in enumerate(self.linhas,1):
            linha.numero=i; linha.num.setText(str(i)); linha.remover.setEnabled(len(self.linhas)>1); linha.setProperty("naAltRow", bool(i % 2 == 0)); linha.style().unpolish(linha); linha.style().polish(linha)
        b=QSignalBlocker(self.qtd); self.qtd.setValue(len(self.linhas)); del b

    def adicionar_linha(self):
        self._ajustar_linhas(len(self.linhas)+1); self.validar(); linha=self.linhas[-1]
        self.area.ensureWidgetVisible(linha); linha.combo.setFocus(); linha.combo.lineEdit().setFocus()

    def remover_linha(self,linha):
        if len(self.linhas)<=1: return
        if linha.preenchida() and not confirmar(self,"Remover linha",f"Remover a camada escolhida na linha {linha.numero}?","Remover",destrutivo=True): return
        self.linhas.remove(linha); self.lista_layout.removeWidget(linha); linha.deleteLater(); self._renumerar(); self.validar()

    def remover_linhas_vazias(self):
        vazias=[x for x in self.linhas if not x.preenchida()]
        if len(vazias)>=len(self.linhas): vazias=vazias[1:]
        for linha in vazias:
            self.linhas.remove(linha); self.lista_layout.removeWidget(linha); linha.deleteLater()
        self._renumerar(); self.validar()

    def avancar_linha(self,linha):
        try: i=self.linhas.index(linha)
        except ValueError: return
        if i==len(self.linhas)-1: self.adicionar_linha()
        else:
            prox=self.linhas[i+1]; prox.combo.setFocus(); prox.combo.lineEdit().setFocus()

    def _escolher_pasta(self):
        p=QFileDialog.getExistingDirectory(self,"Escolha a pasta de destino",self.pasta.text() or os.path.expanduser("~"))
        if p: self.pasta.setText(p)

    def _destino_mudou(self):
        if not self._kml_manual and os.path.isdir(self.pasta.text().strip()):
            self.kml.setText(self.plugin.sugerir_kml_dir(self.pasta.text().strip())); self.kml_info.setText("definida automaticamente")
        for linha in self.linhas: linha.atualizar_visual()
        self.validar()

    def _kml_editado(self): self._kml_manual=True; self.kml_info.setText("alterada manualmente"); self.validar()
    def _escolher_kml(self):
        p=QFileDialog.getExistingDirectory(self,"Escolha a pasta do KML",self.kml.text() or self.pasta.text() or os.path.expanduser("~"))
        if p: self._kml_manual=True; self.kml_info.setText("alterada manualmente"); self.kml.setText(p)

    def caminho_shp(self,arquivo):
        base=self.pasta.text().strip()
        if not base: return ""
        entrada=self.indice.get(arquivo)
        if entrada is None:
            for linha in self.linhas:
                if linha.custom and linha.custom.get("arquivo")==arquivo: entrada=linha.custom; break
        return self.plugin.localizar_shp(base,entrada) if entrada else ""

    def validar(self):
        faltas=[]; entradas=[x.entrada() for x in self.linhas]; arquivos=[e["arquivo"] for e in entradas if e]; repetidos={a for a in arquivos if arquivos.count(a)>1}
        criar_n=0
        for linha in self.linhas:
            e=linha.entrada()
            if not e: aplicar_selo(linha.status,"Vazia")
            elif e["arquivo"] in repetidos: aplicar_selo(linha.status,"Repetida")
            elif os.path.isfile(self.caminho_shp(e["arquivo"])): aplicar_selo(linha.status,"Já existe nesta pasta")
            else: aplicar_selo(linha.status,"OK"); criar_n+=1
        for i,e in enumerate(entradas,1):
            if e is None: faltas.append(f"Escolha a camada da linha {i}.")
        if repetidos: faltas.append("Remova as camadas repetidas: "+", ".join(sorted(repetidos))+".")
        if not os.path.isdir(self.pasta.text().strip()): faltas.append("Escolha a pasta de destino.")
        if not self.src.currentData(): faltas.append("Escolha o SRC.")
        if not self.kml.text().strip(): faltas.append("Defina a pasta do KML.")
        self.pendencias.definir(faltas); self.remover_vazias.setEnabled(any(e is None for e in entradas) and len(self.linhas)>1); self.criar.setEnabled(not faltas)
        self.criar.setText(f"Criar {criar_n} camada" + ("s" if criar_n!=1 else ""))

    def _set_ocupado(self,ocupado):
        for w in (self.criar,self.adicionar,self.remover_vazias,self.ferramentas,self.qtd): w.setEnabled(not ocupado)
        self.progresso.setVisible(ocupado); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor) if ocupado else QApplication.restoreOverrideCursor()

    def executar(self):
        self.validar()
        if not self.criar.isEnabled(): return
        destino=os.path.abspath(self.pasta.text().strip()); kml=os.path.abspath(self.kml.text().strip()); srid=str(self.src.currentData())
        existentes=[e for e in (x.entrada() for x in self.linhas) if e and os.path.isfile(self.caminho_shp(e["arquivo"]))]
        carregar=False
        if existentes:
            acao=dialogo_acoes(self,"Camadas já existentes","Algumas camadas já existem e não serão sobrescritas.",[e.get("nome",e["arquivo"]) for e in existentes],[("Carregar existentes",QMessageBox.ButtonRole.AcceptRole),("Pular existentes",QMessageBox.ButtonRole.RejectRole)],"alerta","Pular existentes")
            carregar=acao=="Carregar existentes"
        criadas=[]; puladas=[]; carregadas=[]; falhas=[]; self._criadas_ids=[]
        self._set_ocupado(True); self.progresso.setRange(0,len(self.linhas)); self.progresso.setValue(0)
        try:
            for i,linha in enumerate(self.linhas,1):
                e=linha.entrada(); existe=os.path.isfile(self.caminho_shp(e["arquivo"])); self.progresso.setFormat(f"Criando {i} de {len(self.linhas)}..."); QApplication.processEvents()
                if existe and not carregar: puladas.append(e.get("nome",e["arquivo"])); self.progresso.setValue(i); continue
                ok,acao,erro,layer_obj=self.plugin.criar_ou_carregar_destino(e,destino,srid,kml_dir=kml,avulsa=True,carregar_existente=True)
                if ok:
                    (criadas if acao=="criada" else carregadas).append(e.get("nome",e["arquivo"]))
                    if layer_obj is not None: self._criadas_ids.append(layer_obj.id())
                else: falhas.append(f"{e.get('nome',e['arquivo'])}: {erro}")
                self.progresso.setValue(i); QApplication.processEvents()
        finally: self._set_ocupado(False)
        detalhes=[]
        if criadas: detalhes.append("Criadas:\n"+"\n".join("- "+x for x in criadas))
        if carregadas: detalhes.append("Já existiam e foram apenas carregadas:\n"+"\n".join("- "+x for x in carregadas))
        if puladas: detalhes.append("Já existiam:\n"+"\n".join("- "+x for x in puladas))
        if falhas: detalhes.append("Com erro:\n"+"\n".join("- "+x for x in falhas))
        acao=dialogo_acoes(self,"Criação concluída",f"Criadas {len(criadas)}, carregadas {len(carregadas)}, puladas {len(puladas)}, com erro {len(falhas)}.",detalhes,[("Ver no painel",QMessageBox.ButtonRole.ActionRole),("Fechar",QMessageBox.ButtonRole.AcceptRole)],"sucesso","Fechar")
        if acao=="Ver no painel" and self._criadas_ids:
            raiz=QgsProject.instance().layerTreeRoot(); view=self.plugin.iface.layerTreeView(); sel=view.selectionModel(); sel.clearSelection()
            primeiro=None
            for lid in self._criadas_ids:
                no=raiz.findLayer(lid)
                if no:
                    no.setItemVisibilityChecked(True)
                    try:
                        idx=view.layerTreeModel().node2index(no); sel.select(idx,QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
                    except Exception: pass
                    if primeiro is None: primeiro=QgsProject.instance().mapLayer(lid)
            if primeiro is not None:
                try: self.plugin.iface.setActiveLayer(primeiro)
                except Exception: pass
        for linha in self.linhas: linha.atualizar_visual()
        self.validar()

    def ajustar_nomes(self):
        total,alteracoes=self.plugin.ajustar_nomes_qgis(); dialogo_acoes(self,"Ajustar nomes",f"{total} camada(s) renomeada(s).",[f"{a} -> {b}" for a,b in alteracoes],[("Fechar",QMessageBox.ButtonRole.AcceptRole)])
    def voltar_nomes(self):
        total,alteracoes=self.plugin.voltar_nomes_arquivo(); dialogo_acoes(self,"Voltar nomes",f"{total} camada(s) restaurada(s).",[f"{a} -> {b}" for a,b in alteracoes],[("Fechar",QMessageBox.ButtonRole.AcceptRole)])
    def exportar_kml(self):
        gravados,falhas=self.plugin.kml.exportar_todos(); detalhes=[]
        if gravados: detalhes.append("Arquivos gravados:\n"+"\n".join("- "+x for x in gravados[:30]))
        if falhas: detalhes.append("Falhas:\n"+"\n".join("- "+x for x in falhas[:20]))
        dialogo_acoes(self,"Exportar KML",f"KML exportados: {len(gravados)}. Falhas: {len(falhas)}.",detalhes,[("Fechar",QMessageBox.ButtonRole.AcceptRole)],"alerta" if falhas else "sucesso")

    def abrir_referencias(self):
        """v3.9.5: lista de camadas de referência do escritório."""
        from .tela_referencias import abrir_referencias
        abrir_referencias(self.plugin, self)
