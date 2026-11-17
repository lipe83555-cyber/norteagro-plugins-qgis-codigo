# -*- coding: utf-8 -*-
"""Tela principal, manutenção do catálogo compartilhado e ações das camadas."""
from . import compat
import os
from qgis.PyQt.QtCore import Qt, QSize, QSignalBlocker
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QCheckBox, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QProgressBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout
)
from qgis.core import (
    Qgis, QgsLayerTreeGroup, QgsMapLayer, QgsProject, QgsRenderContext, QgsSingleSymbolRenderer, QgsStyle,
    QgsSymbolLayerUtils, QgsVectorLayer, QgsWkbTypes
)
from qgis.gui import QgsMapLayerComboBox, QgsSymbolSelectorDialog
from .estilo import (
    aplicar_selo, botao_principal, botao_secundario, cabecalho, configurar_caminho,
    confirmar, dialogo_acoes, erro, icone_tema, informar, preparar_dialogo,
    secao, sucesso, alertar,
)
from .catalogo import (
    arquivos_catalogados_escritorio, catalogar_escritorio, itens_removidos_escritorio,
    normalizar_arquivo, remover_catalogo_escritorio, restaurar_catalogo_escritorio,
    simbolo_entrada, simbolo_para_xml, lugar_quadro, definir_lugar_quadro_escritorio,
    estilos_padrao_ativos, remover_estilo_padrao, salvar_estilo_padrao,
)
from .tela_nova_camada import CampoLugarQuadro, escolher_lugar_quadro
from .catalogo import LUGARES_QUADRO as _LUGARES
from .semad import EXPLICACAO as _SEMAD_EXPLICACAO
from .semad import vai_para_uso_do_solo as _vai_para_uso_do_solo


def codigo_texto(codigo):
    return next((x[1] for x in _LUGARES if x[0] == codigo), codigo)


class DialogoAdicionarCatalogo(QDialog):
    """Cataloga explicitamente uma camada vetorial já carregada no QGIS."""
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin = plugin
        preparar_dialogo(self,"adicionar_catalogo","Norte Agro - Adicionar ao catálogo do escritório",(560,400)); self.resize(700,470)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Adicionar ao catálogo do escritório","Publique uma camada vetorial para reutilizá-la nos demais projetos."))
        raiz.addWidget(secao("Camada")); form = QFormLayout(); form.setVerticalSpacing(8); raiz.addLayout(form)
        self.camada = QgsMapLayerComboBox(); self.camada.setFilters(compat.FILTRO_VETOR)
        self.camada.setAllowEmptyLayer(True, "Selecione uma camada...")
        excluidas = []
        catalogadas = arquivos_catalogados_escritorio()
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer): continue
            arq = str(lyr.customProperty("norteagro/arquivo", "") or "").upper()
            if arq in catalogadas or (not arq and normalizar_arquivo(lyr.name()) in catalogadas): excluidas.append(lyr)
        if hasattr(self.camada, "setExceptedLayerList"): self.camada.setExceptedLayerList(excluidas)
        self.camada.layerChanged.connect(self.camada_mudou); form.addRow("Camada:", self.camada)
        self.nome = QLineEdit(); self.nome.textChanged.connect(self.nome_mudou); form.addRow("Nome:", self.nome)
        self.arquivo = QLabel("-"); form.addRow("ARQUIVO:", self.arquivo)
        self.tipo = QLabel("-"); form.addRow("Tipo:", self.tipo)
        self.grupo = QComboBox(); self.preencher_grupos(); form.addRow("Grupo:", self.grupo)
        self.lugar = CampoLugarQuadro(form, self)
        self.preview = QLabel(); self.preview.setFixedSize(48, 48); form.addRow("Estilo:", self.preview)
        botoes = QHBoxLayout(); botoes.addStretch(); cancelar = botao_secundario("Fechar",self); ok = botao_principal("Adicionar ao catálogo",self)
        ok.clicked.connect(self.confirmar); cancelar.clicked.connect(self.reject); botoes.addWidget(cancelar); botoes.addWidget(ok); raiz.addLayout(botoes)
        self._arquivo_preservado = ""; self._simbolo = None; self.camada_mudou(self.camada.currentLayer())

    def preencher_grupos(self):
        grupos = list(self.plugin.catalogo_atual().keys())
        for no in QgsProject.instance().layerTreeRoot().children():
            if isinstance(no, QgsLayerTreeGroup) and no.name() not in grupos: grupos.append(no.name())
        for g in grupos: self.grupo.addItem(g, g)
        self.grupo.addItem("Novo grupo...", "__novo__")

    @staticmethod
    def _tipo_camada(camada):
        if not camada: return "", "-"
        geom = QgsWkbTypes.geometryType(camada.wkbType())
        if geom == compat.GEOM_POLIGONO: return "P", "Polígono"
        if geom == compat.GEOM_LINHA: return "L", "Linha"
        if geom == compat.GEOM_PONTO: return "Pt", "Ponto"
        return "", "Desconhecido"

    def _estilo_camada(self, camada):
        try:
            simbolos = camada.renderer().symbols(QgsRenderContext()) if camada and camada.renderer() else []
            return simbolos[0].clone() if simbolos else None
        except Exception: return None

    def camada_mudou(self, camada):
        self._simbolo = self._estilo_camada(camada); tipo, texto = self._tipo_camada(camada); self.tipo.setText(texto)
        self._arquivo_preservado = ""
        if camada:
            arq = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
            entrada = self.plugin.indice_atual().get(arq) if arq else None
            if arq and entrada and entrada.get("origem") == "projeto": self._arquivo_preservado = arq
            self.nome.setText(str(camada.customProperty("norteagro/nome", "") or camada.name()))
            if entrada:
                idx = self.grupo.findData(entrada.get("grupo"));
                if idx >= 0: self.grupo.setCurrentIndex(idx)
                if lugar_quadro(entrada): self.lugar.definir(lugar_quadro(entrada))
        self.lugar.ajustar_tipo(tipo)
        self.nome_mudou(); self._atualizar_preview()

    def nome_mudou(self):
        self.arquivo.setText(self._arquivo_preservado or normalizar_arquivo(self.nome.text()) or "-")

    def _atualizar_preview(self):
        self.preview.clear()
        if self._simbolo:
            ico = QgsSymbolLayerUtils.symbolPreviewIcon(self._simbolo, QSize(42, 42)); self.preview.setPixmap(ico.pixmap(QSize(42, 42)))

    def _grupo(self):
        if self.grupo.currentData() != "__novo__": return str(self.grupo.currentData() or "").strip()
        from qgis.PyQt.QtWidgets import QInputDialog
        nome, ok = QInputDialog.getText(self, "Novo grupo", "Nome do novo grupo:"); nome = nome.strip()
        return nome if ok and nome else ""

    def confirmar(self):
        camada = self.camada.currentLayer(); nome = self.nome.text().strip(); arquivo = self._arquivo_preservado or normalizar_arquivo(nome)
        tipo, _ = self._tipo_camada(camada); grupo = self._grupo()
        if not camada or not nome or not arquivo or not tipo or not grupo or not self._simbolo:
            alertar(self, "Adicionar ao catálogo", "Preencha uma camada vetorial, nome, grupo e estilo válidos."); return
        catalogadas = arquivos_catalogados_escritorio()
        if arquivo in catalogadas:
            alertar(self, "Adicionar ao catálogo", f"O ARQUIVO {arquivo} já existe no catálogo do escritório."); return
        existente = self.plugin.indice_atual().get(arquivo)
        camada_arq = str(camada.customProperty("norteagro/arquivo", "") or "").upper()
        if existente and not (existente.get("origem") == "projeto" and camada_arq == arquivo):
            alertar(self, "Adicionar ao catálogo", f"Já existe uma camada com o ARQUIVO {arquivo}."); return
        entrada = {"arquivo":arquivo, "nome":nome, "tipo":tipo, "grupo":grupo,
                   "estilo_xml":simbolo_para_xml(self._simbolo), "personalizada":True, "ordem":100000, "quadro":self.lugar.codigo()}
        try:
            catalogar_escritorio(entrada)
        except Exception as exc:
            self.plugin.log(f"Falha ao alterar catálogo do escritório: {exc}")
            alertar(self, "Adicionar ao catálogo", "O catálogo do escritório não foi alterado.", str(exc)); return
        # Se já era uma camada exclusiva deste projeto, atualiza também seus metadados locais.
        if self._arquivo_preservado:
            self.plugin.salvar_extra_projeto(entrada)
            camada.setCustomProperty("norteagro/arquivo", arquivo); camada.setCustomProperty("norteagro/nome", nome)
            QgsProject.instance().setDirty(True)
        sucesso(self, "Catálogo atualizado", f"{nome} foi adicionada ao catálogo do escritório."); self.accept()


class DialogoRestaurarCatalogo(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); preparar_dialogo(self,"restaurar_catalogo","Norte Agro - Restaurar removidas",(460,400)); self.resize(560,500)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Restaurar camadas do catálogo","Marque as camadas que devem voltar a aparecer para o escritório.")); raiz.addWidget(secao("Camadas removidas"))
        self.lista = QListWidget(); raiz.addWidget(self.lista, 1)
        for entrada in itens_removidos_escritorio():
            classe = "fixa" if entrada.get("classe_removida") == "fixa" else "catalogada"
            item = QListWidgetItem(f"{entrada.get('nome', entrada['arquivo'])}  [{classe}]")
            item.setData(Qt.ItemDataRole.UserRole, entrada["arquivo"]); item.setCheckState(Qt.CheckState.Unchecked); self.lista.addItem(item)
        h = QHBoxLayout(); h.addStretch(); cancelar = botao_secundario("Fechar",self); ok = botao_principal("Restaurar marcadas",self)
        ok.clicked.connect(self.validar); cancelar.clicked.connect(self.reject); h.addWidget(cancelar); h.addWidget(ok); raiz.addLayout(h)

    def marcadas(self):
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count()) if self.lista.item(i).checkState() == Qt.CheckState.Checked]

    def validar(self):
        if not self.marcadas(): informar(self, "Restaurar catálogo", "Marque ao menos uma camada para restaurar."); return
        self.accept()


class TelaCamadas(QDialog):
    PAPEL_ARQUIVO = Qt.ItemDataRole.UserRole
    PAPEL_ORIGEM = Qt.ItemDataRole.UserRole + 1
    PAPEL_GRUPO = Qt.ItemDataRole.UserRole + 20

    def __init__(self, plugin):
        super().__init__(plugin.iface.mainWindow())
        self.plugin = plugin; self._cache_ocultos = {}
        preparar_dialogo(self, "tela_camadas", "Norte Agro - Uso do Solo", (760, 620))
        self.resize(1000, 820)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho(
            "Criar e gerenciar camadas",
            "Crie, carregue e organize as camadas padronizadas do mapa de uso do solo.",
            os.path.join(os.path.dirname(__file__), "icon.png"),
        ))

        # Pasta atual e SRC.
        topo = QHBoxLayout(); self.info_pasta = QLabel(); self.info_pasta.setProperty("naSubtitle", True); self.info_pasta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_src = QLabel(); self.info_src.setProperty("naSubtitle", True)
        topo.addWidget(self.info_pasta,1); topo.addWidget(self.info_src); raiz.addLayout(topo)

        # Barra de ferramentas agrupada por assunto.
        barra = QHBoxLayout(); barra.setSpacing(6)
        def add(txt, slot, ico=""):
            b=botao_secundario(txt,self); b.clicked.connect(slot)
            if ico: b.setIcon(icone_tema(ico))
            barra.addWidget(b); return b
        barra.addWidget(QLabel("Pasta:")); add("Trocar",self.trocar_pasta,"/mActionFileOpen.svg"); add("Renomear",self.renomear_pasta,"/mActionEdit.svg")
        barra.addSpacing(12); barra.addWidget(QLabel("Grupos:")); add("Criar",self.criar_grupo,"/mActionAddGroup.svg"); self.apagar_grupo_btn=add("Apagar",self.apagar_grupo,"/mActionDeleteSelected.svg")
        barra.addSpacing(12); barra.addWidget(QLabel("Catálogo:")); add("Adicionar",self.adicionar_catalogo,"/mActionAdd.svg"); self.remover_cat=add("Remover",self.remover_catalogo,"/mActionRemove.svg"); add("Restaurar",self.restaurar_catalogo,"/mActionUndo.svg")
        barra.addStretch()
        self.ferramentas = QToolButton(self); self.ferramentas.setText("Ferramentas"); self.ferramentas.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(self.ferramentas); menu.addAction("Ajustar nomes no QGIS",self.ajustar_nomes); menu.addAction("Voltar nomes de arquivo",self.voltar_nomes); menu.addSeparator(); menu.addAction("Exportar KML",self.exportar_kml); menu.addSeparator(); menu.addAction(icone_tema("/mActionAdd.svg"),"+ Camadas de referência...",self.abrir_referencias); menu.addAction(icone_tema("/mActionEditTable.svg","/mActionOpenTable.svg"),"Nomes não reconhecidos (linha da tabela)...",self.abrir_apelidos); menu.addAction(icone_tema("/mActionOptions.svg","/mActionPropertiesWidget.svg"),"Modelos (pastas, cores e tabela)...",lambda: self.plugin.abrir_modelos(self)); menu.addAction("Criar camadas em uma pasta",self.criar_avulsa); menu.addSeparator(); menu.addAction(icone_tema("/mActionAddWfsLayer.svg","/mActionAddOgrLayer.svg"),"Camadas da SEMAD (SIGA): murundus, APP de relevo, UC...",self.abrir_semad); self.ferramentas.setMenu(menu); barra.addWidget(self.ferramentas)
        raiz.addLayout(barra)

        raiz.addWidget(secao("Camadas"))
        busca_l=QHBoxLayout(); lupa=QLabel(); lupa.setPixmap(icone_tema("/mActionSearch.svg").pixmap(QSize(18,18))); busca_l.addWidget(lupa)
        self.busca=QLineEdit(); self.busca.setPlaceholderText("Buscar camada..."); self.busca.textChanged.connect(self.filtrar); busca_l.addWidget(self.busca,1)
        self.todos=QCheckBox("Selecionar todos"); self.todos.setTristate(True); self.todos.stateChanged.connect(self._todos_mudou); busca_l.addWidget(self.todos); raiz.addLayout(busca_l)
        self.arvore=QTreeWidget(); self.arvore.setColumnCount(3); self.arvore.setHeaderLabels(["Camada","Tipo","Situação"]); self.arvore.setIconSize(QSize(22,22)); self.arvore.setColumnWidth(0,520); self.arvore.setColumnWidth(1,100); self.arvore.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.arvore.itemSelectionChanged.connect(self.atualizar_botoes); self.arvore.itemPressed.connect(self._antes_clique); self.arvore.itemChanged.connect(self._item_mudou); self.arvore.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.arvore.customContextMenuRequested.connect(self.menu_contexto); self.arvore.itemDoubleClicked.connect(lambda it, _c: self.editar_cor(it)); raiz.addWidget(self.arvore,1)
        dica=QLabel("Dica: dê dois cliques numa camada (ou clique com o botão direito > Mudar cor padrão) para trocar a cor padrão dela."); dica.setProperty("naSubtitle",True); dica.setWordWrap(True); raiz.addWidget(dica)
        self.progresso=QProgressBar(); self.progresso.setVisible(False); raiz.addWidget(self.progresso)

        rodape=QHBoxLayout(); self.rodape=QLabel("0 camada(s) selecionada(s)"); self.rodape.setProperty("naSubtitle",True); rodape.addWidget(self.rodape); rodape.addStretch()
        nova=botao_secundario("+ Nova camada",self); nova.clicked.connect(self.nova_camada); nova.setToolTip("Criar uma camada personalizada neste projeto.")
        areas=botao_secundario("Calcular áreas",self); areas.clicked.connect(self.calcular_areas)
        fechar=botao_secundario("Fechar",self); fechar.clicked.connect(self.accept)
        self.criar_btn=botao_principal("Criar selecionadas",self); self.criar_btn.clicked.connect(self.processar)
        semad_b=botao_secundario("SEMAD",self); semad_b.setIcon(icone_tema("/mActionAddWfsLayer.svg","/mActionAddOgrLayer.svg")); semad_b.setToolTip("Consulta o SIGA da SEMAD pelo limite do imóvel e atualiza o grupo SEMAD - SIGA: murundus, APP de declividade, borda de chapada e topo de morro (só a parte dentro do imóvel) e Unidades de Conservação (inteiras, com nome e descrição)."); semad_b.clicked.connect(self.abrir_semad)
        rodape.addWidget(semad_b); rodape.addWidget(nova); rodape.addWidget(areas); rodape.addWidget(fechar); rodape.addWidget(self.criar_btn); raiz.addLayout(rodape)
        self.atualizar()
        # v0.5.0: "toda vez" - ao abrir, confere sozinho as camadas da SEMAD no imóvel (pode desligar na tela SEMAD)
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(600, self._semad_automatico)

    def _filhos_selecionaveis(self, pai, somente_visiveis=False):
        saida=[]
        for i in range(pai.childCount()):
            item=pai.child(i)
            if somente_visiveis and item.isHidden(): continue
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable: saida.append(item)
        return saida

    def _antes_clique(self, item, coluna):
        if item and item.data(0, self.PAPEL_GRUPO):
            self._cache_ocultos = {id(x): x.checkState(0) for x in self._filhos_selecionaveis(item) if x.isHidden()}
        else:
            self._cache_ocultos = {}

    def _item_mudou(self, item, coluna):
        if coluna != 0: return
        bloqueio = QSignalBlocker(self.arvore)
        if item.data(0, self.PAPEL_GRUPO) and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            alvo = Qt.CheckState.Checked if item.checkState(0) != Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
            for filho in self._filhos_selecionaveis(item, somente_visiveis=True): filho.setCheckState(0, alvo)
            for filho in self._filhos_selecionaveis(item):
                if filho.isHidden() and id(filho) in self._cache_ocultos: filho.setCheckState(0, self._cache_ocultos[id(filho)])
        del bloqueio
        self._cache_ocultos = {}; self._atualizar_estados()

    def _todos_mudou(self, estado):
        alvo = Qt.CheckState.Checked if estado != Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        bloqueio_arvore = QSignalBlocker(self.arvore); bloqueio_todos = QSignalBlocker(self.todos)
        for i in range(self.arvore.topLevelItemCount()):
            pai=self.arvore.topLevelItem(i)
            if pai.isHidden(): continue
            for item in self._filhos_selecionaveis(pai, somente_visiveis=True): item.setCheckState(0, alvo)
        del bloqueio_arvore, bloqueio_todos
        self._atualizar_estados()

    def _atualizar_estados(self):
        estados=[]; total_marcado=0
        bloqueio_arvore = QSignalBlocker(self.arvore); bloqueio_todos = QSignalBlocker(self.todos)
        for i in range(self.arvore.topLevelItemCount()):
            pai=self.arvore.topLevelItem(i); todos_itens=self._filhos_selecionaveis(pai); vis=self._filhos_selecionaveis(pai, True)
            total_marcado += sum(1 for x in todos_itens if x.checkState(0)==Qt.CheckState.Checked)
            if not todos_itens:
                pai.setFlags(pai.flags() & ~Qt.ItemFlag.ItemIsUserCheckable); pai.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                pai.setFlags((pai.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)  # v3.9.1: estado do grupo calculado em _atualizar_estados
                if vis:
                    marc=sum(1 for x in vis if x.checkState(0)==Qt.CheckState.Checked)
                    estado=Qt.CheckState.Checked if marc==len(vis) else Qt.CheckState.Unchecked if marc==0 else Qt.CheckState.PartiallyChecked
                    pai.setCheckState(0,estado)
                    if not pai.isHidden(): estados.extend(x.checkState(0) for x in vis)
        if not estados:
            self.todos.setEnabled(False); self.todos.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.todos.setEnabled(True); marc=sum(1 for e in estados if e==Qt.CheckState.Checked)
            self.todos.setCheckState(Qt.CheckState.Checked if marc==len(estados) else Qt.CheckState.Unchecked if marc==0 else Qt.CheckState.PartiallyChecked)
        del bloqueio_arvore, bloqueio_todos
        self.rodape.setText(f"{total_marcado} camada(s) selecionada(s)")

    def atualizar(self):
        self.plugin.adotar_camadas_antigas(); pasta, srid = self.plugin.memoria_basica(); configurar_caminho(self.info_pasta, f"Pasta atual: {pasta}", 90); self.info_pasta.setToolTip(pasta); self.info_src.setText(f"SRC: {srid}")
        bloqueio = QSignalBlocker(self.arvore)
        self.arvore.clear(); cinza = QBrush(QColor("#888888"))
        # A lista principal também mostra avulsas personalizadas carregadas, sem
        # transformá-las em norteagro_extras nem em itens do catálogo do escritório.
        catalogo_tela = {g:list(itens) for g,itens in self.plugin.catalogo_atual().items()}
        conhecidos = {str(e.get("arquivo", "")).upper() for itens in catalogo_tela.values() for e in itens}
        for camada_av in self.plugin.camadas_avulsas():
            arquivo_av = str(camada_av.customProperty("norteagro/arquivo", "") or "").upper()
            if not arquivo_av or arquivo_av in conhecidos:
                continue
            no_av = QgsProject.instance().layerTreeRoot().findLayer(camada_av.id())
            pai_av = no_av.parent() if no_av else None
            grupo_av = pai_av.name() if pai_av and isinstance(pai_av, QgsLayerTreeGroup) else "Uso do Solo"
            tipo_av, _ = DialogoAdicionarCatalogo._tipo_camada(camada_av)
            simbolos_av = camada_av.renderer().symbols(QgsRenderContext()) if camada_av.renderer() else []
            entrada_av = {
                "arquivo":arquivo_av,
                "nome":str(camada_av.customProperty("norteagro/nome", "") or camada_av.name()),
                "tipo":tipo_av or "P", "grupo":grupo_av, "origem":"avulsa", "personalizada":True,
                "ordem":100000, "estilo_xml":simbolo_para_xml(simbolos_av[0]) if simbolos_av else "",
            }
            catalogo_tela.setdefault(grupo_av, []).append(entrada_av); conhecidos.add(arquivo_av)
        for grupo, itens in catalogo_tela.items():
            pai=QTreeWidgetItem([grupo,"",""]); pai.setData(0,self.PAPEL_GRUPO,grupo); fonte=pai.font(0); fonte.setBold(True); pai.setFont(0,fonte)
            pai.setFlags((pai.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsAutoTristate)  # v3.9.1: estado do grupo calculado em _atualizar_estados; pai.setCheckState(0,Qt.Unchecked)
            self.arvore.addTopLevelItem(pai); pai.setExpanded(True)
            if not itens:
                vazio=QTreeWidgetItem(["(vazio - use + Nova camada)","",""]); vazio.setFlags(vazio.flags() & ~Qt.ItemFlag.ItemIsUserCheckable); vazio.setForeground(0,cinza); pai.addChild(vazio)
            for entrada in itens:
                arquivo=entrada["arquivo"]; shp=self.plugin.caminho_shp(arquivo); camada=self.plugin.camada_plugin(arquivo)
                avulsas=self.plugin.camadas_avulsas(arquivo)
                if os.path.isfile(shp) and camada: situacao="Criada"
                elif os.path.isfile(shp): situacao="Criada - não carregada"
                elif avulsas: situacao="Criada (avulsa)"
                else: situacao="Nova"
                origem=entrada.get("origem","fixa"); sufixo=" (catalogada)" if origem=="catalogada" else " (deste projeto)" if origem=="projeto" else ""
                tipo={"P":"Polígono","L":"Linha","Pt":"Ponto"}.get(entrada["tipo"],entrada["tipo"])
                item=QTreeWidgetItem([entrada["nome"]+sufixo,tipo,situacao]); item.setData(0,self.PAPEL_ARQUIVO,arquivo); item.setData(0,self.PAPEL_ORIGEM,origem); item.setCheckState(0,Qt.CheckState.Unchecked)
                item.setToolTip(0, f"ARQUIVO: {arquivo}\nDois cliques: mudar a cor padrão desta camada")
                if arquivo in _SEMAD_EXPLICACAO:
                    # v0.5.0: camada da SEMAD - ao criar, consulta o SIGA e grava só o que há no imóvel
                    if situacao=="Nova": situacao="Nova - consulta o SIGA"
                    item.setText(2, situacao)
                    if _vai_para_uso_do_solo(arquivo):
                        # v0.7.0: Murundus do Uso do Solo - recebe os murundus do SIGA e entra no cálculo
                        item.setToolTip(0, _SEMAD_EXPLICACAO[arquivo] + "\n\nAo criar, o plugin consulta o SIGA da SEMAD e grava nela "
                                        "os murundus que existem no imóvel (só a parte de dentro). Sem murundus no imóvel, ela não é "
                                        "criada. Também é criada sozinha ao abrir esta tela, quando o limite do imóvel já está "
                                        "desenhado. Desenho feito à mão nela nunca é substituído. Entra no Quadro de Áreas."
                                        "\nARQUIVO: " + arquivo)
                    else:
                        item.setToolTip(0, _SEMAD_EXPLICACAO[arquivo] + "\n\nAo criar (ou criar de novo) o plugin consulta o SIGA da SEMAD agora "
                                        "e grava só o que existe no imóvel. Precisa da Área Total do Imóvel desenhada. "
                                        "Não entra no cálculo de áreas.\nARQUIVO: " + arquivo)
                try: item.setIcon(0,QgsSymbolLayerUtils.symbolPreviewIcon(simbolo_entrada(entrada),QSize(22,22)))
                except Exception: pass
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if not self.plugin.entrada_valida(arquivo):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setToolTip(0, item.toolTip(0) + "\nDesabilitada por inconsistência no catálogo.")
                if situacao=="Criada" or origem=="avulsa":
                    # Avulsa personalizada é informativa aqui; a seleção para KML é feita no painel Layers.
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    if situacao=="Criada":
                        for col in range(3): item.setForeground(col,cinza)
                if avulsas:
                    item.setToolTip(0, f"ARQUIVO: {arquivo}\nCamada(s) avulsa(s):\n" + "\n".join(self.plugin._fonte(c) for c in avulsas))
                    item.setToolTip(2, item.toolTip(0))
                pai.addChild(item)
                selo = QLabel(); aplicar_selo(selo, situacao if situacao not in ("Nova", "Criada - não carregada") else ("Vazia" if situacao == "Nova" else "Já existe nesta pasta"))
                if situacao == "Nova": selo.setText("Nova")
                elif situacao == "Criada - não carregada": selo.setText("Criada - não carregada")
                self.arvore.setItemWidget(item, 2, selo)
        del bloqueio
        self.filtrar(self.busca.text()); self.atualizar_botoes(); self._atualizar_estados()

    def definir_lugar_quadro(self, arquivo):
        """v3.9.6: muda onde uma camada personalizada entra no Quadro de Áreas."""
        entrada=self.plugin.entrada(arquivo) or {}
        if not entrada.get("personalizada"): return False
        nome=entrada.get("nome") or arquivo
        codigo=escolher_lugar_quadro(self, nome, lugar_quadro(entrada) or "OUTRAS", entrada.get("tipo","P"))
        if not codigo: return False
        try:
            if entrada.get("origem")=="catalogada": definir_lugar_quadro_escritorio(arquivo, codigo)
            else:
                local=dict(entrada); local["quadro"]=codigo; local["origem"]="projeto"; self.plugin.salvar_extra_projeto(local)
        except Exception as exc:
            self.plugin.log(f"Falha ao mudar o lugar no quadro: {exc}")
            alertar(self,"Lugar no Quadro de Áreas","Nada foi alterado.",str(exc)); return False
        sucesso(self,"Quadro de Áreas atualizado",f"{nome} vai aparecer em: {codigo_texto(codigo)}.",["Vale a partir do próximo cálculo."])
        self.atualizar(); return True

    def item_atual(self):
        itens=self.arvore.selectedItems(); return itens[0] if itens and itens[0].data(0,self.PAPEL_ARQUIVO) else None

    def grupo_atual(self):
        itens=self.arvore.selectedItems();
        return str(itens[0].data(0,self.PAPEL_GRUPO) or "") if itens else ""

    def atualizar_botoes(self):
        item=self.item_atual(); origem=item.data(0,self.PAPEL_ORIGEM) if item else ""; self.remover_cat.setEnabled(origem in ("fixa","catalogada"))
        grupo=self.grupo_atual(); pode=self.plugin.grupo_pode_ser_apagado(grupo)
        self.apagar_grupo_btn.setEnabled(pode)
        self.apagar_grupo_btn.setToolTip("Grupo padrão do escritório não pode ser apagado" if grupo in ("Uso do Solo","Passivos e Compensação","Ocultos (Salvar na pasta)") else "")

    def filtrar(self, texto):
        consulta=texto.strip().casefold()
        bloqueio = QSignalBlocker(self.arvore)
        for i in range(self.arvore.topLevelItemCount()):
            pai=self.arvore.topLevelItem(i); visiveis=0
            for j in range(pai.childCount()):
                item=pai.child(j); ocultar=bool(consulta) and consulta not in item.text(0).casefold(); item.setHidden(ocultar); visiveis += 0 if ocultar else 1
            pai.setHidden(visiveis==0)
        del bloqueio
        self._atualizar_estados()

    def selecionadas(self):
        saida=[]
        for i in range(self.arvore.topLevelItemCount()):
            pai=self.arvore.topLevelItem(i)
            for item in self._filhos_selecionaveis(pai):
                if item.checkState(0)==Qt.CheckState.Checked and item.data(0,self.PAPEL_ARQUIVO): saida.append(item.data(0,self.PAPEL_ARQUIVO))
        return saida

    def processar(self):
        from . import semad
        arquivos=self.selecionadas()
        if not arquivos: alertar(self,"Criar camadas","Marque ao menos uma camada."); return
        # v0.5.0: as da SEMAD vêm por último (dependem da Área Total do Imóvel) e precisam do imóvel desenhado.
        normais=[a for a in arquivos if not semad.eh_semad(a)]; da_semad=[a for a in arquivos if semad.eh_semad(a)]
        depois=[]  # v0.7.0: Murundus do Uso do Solo que ficam para quando o imóvel estiver desenhado
        if da_semad and normais and semad.problema_imovel(self.plugin) and all(semad.vai_para_uso_do_solo(a) for a in da_semad):
            # criando o grupo Uso do Solo com o imóvel ainda sem desenho: a Murundus vem depois, sozinha, sem perguntar
            depois=list(da_semad); da_semad=[]
        if da_semad and not self._imovel_para_semad(normais, da_semad): da_semad=[]
        arquivos=normais+da_semad
        if not arquivos: return
        criadas=carregadas=0; falhas=[]; semad_ok=[]; semad_sem=[]; problema_imovel=""
        self.progresso.setRange(0,len(arquivos)); self.progresso.setVisible(True); self.criar_btn.setEnabled(False); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i,arquivo in enumerate(arquivos,1):
                nome=(self.plugin.entrada(arquivo) or {}).get("nome",arquivo)
                if semad.eh_semad(arquivo):
                    self.progresso.setFormat(f"Consultando o SIGA da SEMAD: {nome} ({i} de {len(arquivos)})...")
                else:
                    self.progresso.setFormat(f"Criando {i} de {len(arquivos)}...")
                QApplication.processEvents()
                if semad.eh_semad(arquivo) and problema_imovel:
                    self.progresso.setValue(i); continue
                ok,acao,erro=self.plugin.criar_ou_carregar(arquivo)
                if acao in ("sem_imovel","imovel_vazio"): problema_imovel=acao
                elif semad.eh_semad(arquivo) and ok and acao=="sem_dados": semad_sem.append(f"{nome}: {erro}")
                elif semad.eh_semad(arquivo) and ok: semad_ok.append(f"{nome}: {erro}")
                elif ok and acao=="criada": criadas+=1
                elif ok: carregadas+=1
                else: falhas.append(f"{nome}: {erro}")
                self.progresso.setValue(i)
        finally:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False); self.criar_btn.setEnabled(True)
        detalhes=[f"{x}" for x in falhas]
        # v3.9.3: texto claro - toda camada criada também é carregada no projeto.
        partes_msg=[]
        if normais or criadas or carregadas:
            partes_msg.append(f"{criadas} camada(s) criada(s) e carregada(s) no projeto.")
        if carregadas: partes_msg.append(f"{carregadas} já existia(m) na pasta e foi(ram) apenas carregada(s), sem sobrescrever.")
        if semad_ok:
            partes_msg.append(f"SEMAD (SIGA): {len(semad_ok)} camada(s) com dados no imóvel, criada(s)/atualizada(s) agora.")
            detalhes += ["SEMAD - " + x for x in semad_ok]
        if semad_sem:
            partes_msg.append(f"SEMAD (SIGA): {len(semad_sem)} camada(s) sem nada no imóvel - não foram criadas.")
            detalhes += ["SEMAD - " + x for x in semad_sem]
        if problema_imovel:
            falhas.append("SEMAD"); partes_msg.append("Camadas da SEMAD não geradas: " + semad.texto_problema_imovel(problema_imovel))
        if depois:
            nomes_d=", ".join((self.plugin.entrada(a) or {}).get("nome",a) for a in depois)
            partes_msg.append(f"{nomes_d}: será criada sozinha, já com os murundus da SEMAD, quando o limite do imóvel estiver "
                              "desenhado e salvo (ao abrir de novo Criar / gerenciar camadas, ou no botão SEMAD). "
                              "Se o imóvel não tiver murundus, ela não é criada.")
        partes_msg.append(f"Falhas: {len(falhas)}." if falhas else "Nenhuma falha.")
        dialogo_acoes(self,"Criação concluída","\n".join(partes_msg),detalhes,[("Fechar",QMessageBox.ButtonRole.AcceptRole)],"alerta" if falhas else "sucesso")
        self.atualizar()

    def _imovel_para_semad(self, normais, da_semad):
        """v0.5.0: as camadas da SEMAD são analisadas pelo limite do imóvel. Sem a Área Total do Imóvel (ou com ela
        sem desenho) pede para gerar/desenhar o imóvel antes. Devolve True se pode seguir com as da SEMAD."""
        from . import semad
        problema=semad.problema_imovel(self.plugin)
        if not problema: return True
        nomes="\n".join("- "+(self.plugin.entrada(a) or {}).get("nome",a) for a in da_semad)
        if problema=="sem_imovel":
            if "AREA_DO_IMOVEL" in normais:
                frase=("Você marcou a Área Total do Imóvel junto. Ela será criada agora, mas ainda sem desenho: as camadas "
                       "da SEMAD abaixo só podem ser geradas depois que o limite do imóvel estiver desenhado.\n\n"+nomes+
                       "\n\nDesenhe (ou cole) o limite do imóvel, salve e volte aqui para gerar as camadas da SEMAD.")
                informar(self,"Camadas da SEMAD",frase); return False
            frase=("As camadas da SEMAD são analisadas pelo limite do imóvel (a parte de dentro fica, o resto é descartado; "
                   "as Unidades de Conservação vêm inteiras, mas é o imóvel que diz quais sobrepõem). Este projeto ainda "
                   "não tem a camada Área Total do Imóvel.\n\n"+nomes+"\n\nGere primeiro a Área Total do Imóvel?")
            if confirmar(self,"Gerar a Área Total do Imóvel primeiro",frase,"Gerar a Área Total do Imóvel","Cancelar"):
                if "AREA_DO_IMOVEL" not in normais: normais.insert(0,"AREA_DO_IMOVEL")
                informar(self,"Camadas da SEMAD","A Área Total do Imóvel será criada agora. Desenhe (ou cole) o limite do "
                         "imóvel, salve e depois gere as camadas da SEMAD.")
            return False
        informar(self,"Camadas da SEMAD",semad.texto_problema_imovel(problema)+"\n\n"+nomes)
        if "AREA_DO_IMOVEL" not in normais:
            camada=self.plugin.camada_plugin("AREA_DO_IMOVEL")
            try:
                if camada is not None: self.plugin.iface.setActiveLayer(camada)
            except Exception: pass
        return False

    def nova_camada(self):
        from .tela_nova_camada import TelaNovaCamada
        TelaNovaCamada(self.plugin,self).exec(); self.atualizar()

    def criar_avulsa(self):
        self.plugin.abrir_avulsa(self); self.atualizar()

    def criar_grupo(self):
        nome,ok=QInputDialog.getText(self,"Criar grupo","Nome do novo grupo:"); nome=nome.strip()
        if not ok: return
        certo,erro=self.plugin.criar_grupo_projeto(nome)
        if not certo: alertar(self,"Criar grupo",erro); return
        sucesso(self,"Grupo criado",f"Grupo criado: {nome}",["Nenhuma pasta foi criada no disco."]); self.atualizar()

    def apagar_grupo(self):
        grupo=self.grupo_atual()
        if not self.plugin.grupo_pode_ser_apagado(grupo): return
        internos,externos=self.plugin.dados_grupo_apagar(grupo); pasta,_=self.plugin.memoria_basica()
        if internos or externos:
            linhas=[f"Tem certeza que deseja apagar o grupo {grupo} e todas as camadas dele?",
                   f"As camadas abaixo serão removidas do QGIS e os arquivos movidos para {os.path.join(pasta,'_apagados')}:"]
            linhas += [f"- {r['nome']} ({r.get('arquivo') or os.path.basename(r.get('fonte',''))})" for r in internos]
            if externos:
                linhas += ["", "Camadas de fora da pasta do mapa serão apenas removidas do projeto, sem mexer nos arquivos:"]
                linhas += [f"- {r['nome']} ({r.get('fonte') or 'camada temporária/serviço'})" for r in externos]
            texto="\n".join(linhas)
        else:
            texto=f"Tem certeza que deseja apagar o grupo {grupo}?"
        if not confirmar(self,"Apagar grupo",texto,"Sim, apagar","Cancelar",destrutivo=True): return
        resumo=self.plugin.apagar_grupo_projeto(grupo)
        if resumo.get("erro"): alertar(self,"Apagar grupo",resumo["erro"]); return
        texto=f"Camadas removidas: {resumo['camadas']}\nArquivos movidos: {len(resumo['movidos'])}\nCamadas só removidas do projeto: {len(resumo['removidos'])}\nFalhas: {len(resumo['falhas'])}"
        if resumo['movidos']: texto += "\n\nMovidos para:\n" + resumo['apagados'] + "\n" + "\n".join(resumo['movidos'][:12])
        if resumo['removidos']: texto += "\n\nSó removidas do projeto:\n" + "\n".join(resumo['removidos'][:12])
        if resumo['falhas']: texto += "\n\nFalhas:\n" + "\n".join(resumo['falhas'][:12])
        informar(self,"Apagar grupo",texto); self.atualizar()

    def adicionar_catalogo(self):
        if compat.aceito(DialogoAdicionarCatalogo(self.plugin,self).exec()): self.atualizar()

    def remover_catalogo(self):
        item=self.item_atual()
        if not item: return
        arquivo=item.data(0,self.PAPEL_ARQUIVO); origem=item.data(0,self.PAPEL_ORIGEM)
        if origem not in ("fixa","catalogada"): return
        entrada=self.plugin.entrada(arquivo); nome=entrada["nome"] if entrada else arquivo
        pergunta=f"Remover {nome} do catálogo do escritório? Ela deixará de aparecer na lista de todos os usuários. Nenhum arquivo será apagado."
        if not confirmar(self,"Remover do catálogo",pergunta,"Remover",destrutivo=True): return
        try:
            remover_catalogo_escritorio(arquivo)
            if entrada and os.path.isfile(self.plugin.caminho_shp(arquivo)):
                local=dict(entrada); local.pop("origem",None); local["personalizada"]=True; self.plugin.salvar_extra_projeto(local)
            sucesso(self,"Catálogo atualizado",f"{nome} foi removida do catálogo.",["Nenhum SHP, QML ou KML foi apagado."])
        except Exception as exc:
            self.plugin.log(f"Falha ao remover do catálogo: {exc}"); alertar(self,"Remover do catálogo","O catálogo do escritório não foi alterado.",str(exc))
        self.atualizar()

    def restaurar_catalogo(self):
        try: dlg=DialogoRestaurarCatalogo(self)
        except Exception as exc: alertar(self,"Restaurar catálogo","Não foi possível ler o catálogo do escritório.",str(exc)); return
        if dlg.lista.count()==0: informar(self,"Restaurar catálogo","Não há camadas removidas para restaurar."); return
        if not compat.aceito(dlg.exec()): return
        try:
            restaurar_catalogo_escritorio(dlg.marcadas()); sucesso(self,"Catálogo atualizado",f"{len(dlg.marcadas())} camada(s) restaurada(s) no catálogo.")
        except Exception as exc:
            self.plugin.log(f"Falha ao restaurar catálogo: {exc}"); alertar(self,"Restaurar catálogo","O catálogo do escritório não foi alterado.",str(exc))
        self.atualizar()

    def substituir(self, arquivo=None):
        from .tela_substituir import TelaSubstituir
        TelaSubstituir(self.plugin,arquivo_destino=arquivo,parent=self).exec(); self.atualizar()

    def menu_contexto(self,pos):
        item=self.arvore.itemAt(pos)
        if not item: return
        arquivo=item.data(0,self.PAPEL_ARQUIVO)
        if not arquivo: return
        entrada=self.plugin.entrada(arquivo) or {}
        menu=QMenu(self); acao=None; acao_lugar=None
        acao_cor=menu.addAction(icone_tema("/mActionStyleManager.svg","/symbologyEdit.svg"),"Mudar cor padrão...")
        acao_voltar=menu.addAction("Voltar à cor original do plugin") if arquivo.upper() in estilos_padrao_ativos() else None
        menu.addSeparator()
        if os.path.isfile(self.plugin.caminho_shp(arquivo)): acao=menu.addAction("Substituir...")
        if entrada.get("personalizada"): acao_lugar=menu.addAction("Lugar no Quadro de Áreas...")
        escolhida=menu.exec(self.arvore.viewport().mapToGlobal(pos))
        if escolhida is not None and escolhida==acao_cor: self.editar_cor(item); return
        if escolhida is not None and acao_voltar is not None and escolhida==acao_voltar: self.voltar_cor(item); return
        if escolhida is not None and escolhida==acao_lugar: self.definir_lugar_quadro(arquivo); return
        if escolhida is not None and escolhida==acao:
            if not self.plugin.camada_plugin(arquivo): self.plugin.criar_ou_carregar(arquivo)
            self.substituir(arquivo)

    # ------------------------------------------------------------ cor padrão
    def _camadas_da_entrada(self, arquivo):
        saida = []
        principal = self.plugin.camada_plugin(arquivo)
        if principal: saida.append(principal)
        for c in self.plugin.camadas_avulsas(arquivo):
            if c not in saida: saida.append(c)
        return saida

    def _aplicar_nas_camadas(self, camadas, simbolo):
        """Pinta as camadas deste projeto com o símbolo e regrava o .qml ao lado do shapefile."""
        categorias = compat.categorias_sem_propriedades()
        for camada in camadas:
            camada.setRenderer(QgsSingleSymbolRenderer(simbolo.clone()))
            camada.triggerRepaint()
            fonte = camada.source().split("|")[0]
            if fonte.lower().endswith(".shp") and os.path.isfile(fonte):
                try: camada.saveNamedStyle(os.path.splitext(fonte)[0] + ".qml", categories=categorias)
                except Exception as exc: self.plugin.log(f"Falha ao gravar o QML de {camada.name()}: {exc}")
            try: self.plugin.iface.layerTreeView().refreshLayerSymbology(camada.id())
            except Exception: pass

    def editar_cor(self, item):
        """Abre o editor de símbolo do QGIS e grava o resultado como a cor padrão desta camada."""
        arquivo = item.data(0, self.PAPEL_ARQUIVO) if item else None
        if not arquivo: return
        entrada = self.plugin.entrada(arquivo)
        if not entrada: return
        simbolo = compat.editar_simbolo(simbolo_entrada(entrada), self, None, f"Cor padrão - {entrada.get('nome') or arquivo}")
        if simbolo is None: return
        try:
            onde = salvar_estilo_padrao(arquivo, simbolo_para_xml(simbolo))
        except Exception as exc:
            erro(self, "Cor padrão", "Não foi possível gravar a nova cor.", str(exc)); return
        camadas = self._camadas_da_entrada(arquivo)
        if camadas and confirmar(self, "Cor padrão", "Aplicar a nova cor também na camada deste projeto?", "Aplicar",
                                 "Agora não", detalhes=["A cor nova também fica gravada no .qml da camada, para valer quando ela for aberta de novo."]):
            self._aplicar_nas_camadas(camadas, simbolo)
        detalhe = ["Fica guardada no catálogo dentro do plugin."]
        sucesso(self, "Cor padrão", f"Nova cor padrão de {entrada.get('nome') or arquivo} salva.",
                detalhe + ["As próximas camadas criadas pelo plugin já vêm com esta cor."])
        self.atualizar()

    def voltar_cor(self, item):
        arquivo = item.data(0, self.PAPEL_ARQUIVO) if item else None
        if not arquivo: return
        entrada = self.plugin.entrada(arquivo) or {}
        if not confirmar(self, "Cor padrão", f"Voltar {entrada.get('nome') or arquivo} para a cor original do plugin?", "Voltar"):
            return
        try:
            remover_estilo_padrao(arquivo)
        except Exception as exc:
            erro(self, "Cor padrão", "Não foi possível voltar a cor original.", str(exc)); return
        camadas = self._camadas_da_entrada(arquivo)
        if camadas and confirmar(self, "Cor padrão", "Aplicar a cor original também na camada deste projeto?", "Aplicar", "Agora não"):
            self._aplicar_nas_camadas(camadas, simbolo_entrada(self.plugin.entrada(arquivo) or entrada))
        self.atualizar()

    def ajustar_nomes(self):
        total,alteracoes=self.plugin.ajustar_nomes_qgis()
        if not total: informar(self,"Ajustar nomes","Nenhuma camada para alterar o nome."); return
        dialogo_acoes(self,"Ajustar nomes",f"{total} camada(s) renomeada(s).",[f"{a} -> {d}" for a,d in alteracoes],[("Fechar",QMessageBox.ButtonRole.AcceptRole)]); self.atualizar()

    def voltar_nomes(self):
        total,alteracoes=self.plugin.voltar_nomes_arquivo()
        if not total: informar(self,"Ajustar nomes","Nenhuma camada para alterar o nome."); return
        dialogo_acoes(self,"Voltar nomes",f"{total} camada(s) restaurada(s).",[f"{a} -> {d}" for a,d in alteracoes],[("Fechar",QMessageBox.ButtonRole.AcceptRole)]); self.atualizar()

    def calcular_areas(self):
        from .tela_areas import TelaAreas
        TelaAreas(self.plugin,self).exec()

    def abrir_semad(self):
        """v0.5.0: camadas da SEMAD (SIGA) no imóvel."""
        self.plugin.abrir_semad(self)

    def _semad_automatico(self):
        from .tela_semad import auto_ligado, verificar_em_silencio
        if not auto_ligado():
            return
        try:
            self.progresso.setVisible(True); self.progresso.setRange(0, 0); self.progresso.setFormat("Consultando o SIGA da SEMAD...")
            def andamento(i, total, texto):
                self.progresso.setRange(0, max(1, total)); self.progresso.setValue(i); self.progresso.setFormat(texto)
                QApplication.processEvents()
            tem=verificar_em_silencio(self.plugin, andamento)
            if tem: self.atualizar()  # v0.7.0: a Murundus pode ter sido criada agora no grupo Uso do Solo
        except Exception as exc:
            self.plugin.log(f"Camadas da SEMAD: {exc}")
        finally:
            self.progresso.setVisible(False)

    def exportar_kml(self):
        gravados,falhas=self.plugin.kml.exportar_todos(); texto=f"KML exportados: {len(gravados)}\nFalhas: {len(falhas)}"
        if gravados: texto += "\n\nArquivos gravados:\n"+"\n".join(gravados[:20])
        if falhas: texto += "\n\nFalhas:\n"+"\n".join(falhas[:10])
        dialogo_acoes(self,"Exportar KML",f"KML exportados: {len(gravados)}. Falhas: {len(falhas)}.",([f"Gravado: {x}" for x in gravados[:20]]+[f"Falha: {x}" for x in falhas[:10]]),[("Fechar",QMessageBox.ButtonRole.AcceptRole)],"alerta" if falhas else "sucesso")

    def trocar_pasta(self):
        if self.plugin.trocar_pasta(self): self.atualizar()

    def renomear_pasta(self):
        from .pasta import DialogoRenomearPasta
        if compat.aceito(DialogoRenomearPasta(self.plugin,self).exec()): self.atualizar()

    def abrir_apelidos(self):
        """v0.1.1: nome que o plugin não reconhece -> linha da tabela."""
        from .tela_apelidos import abrir_apelidos
        abrir_apelidos(self.plugin, self)

    def abrir_referencias(self):
        """v3.9.5: lista de camadas de referência do escritório."""
        from .tela_referencias import abrir_referencias
        abrir_referencias(self.plugin, self)
