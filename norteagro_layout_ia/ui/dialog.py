# -*- coding: utf-8 -*-
"""Janela principal do plugin NorteAgro Layout.

Abas (v0.29.0: sem o modo IA):
  1. Planta (Modelo Norte Agro) - modelo, documentos do imóvel, dados, planilha de áreas, mapas e gerar.
  2. Configurações - responsável técnico, biblioteca, nomes de camadas.
  3. Buscar imagem.
"""

import json
import os
import tempfile
import time
import traceback
from datetime import date

from qgis.core import QgsApplication, QgsProject, QgsSettings
from qgis.gui import QgsCollapsibleGroupBox, QgsFileWidget
from qgis.PyQt.QtCore import QTimer, QDate, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont, QPixmap
from qgis.PyQt.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QCompleter, QDateEdit,
                                 QDialog, QMenu, QStackedWidget,
                                 QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
                                 QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                                 QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                                 QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                                 QToolButton, QVBoxLayout, QWidget)

from .. import builder, modelos
from ..core import config, documentos, identidade, log, planilha_areas
from ..core.correspondencia import Correspondencia
from .painel_mapa import PainelMapa
from .pagina_imagem import PaginaImagem
from .painel_passivos import PainelPassivos

PASTA_PLUGIN = os.path.dirname(os.path.dirname(__file__))
PAPEIS_MAPA = {"principal": "Mapa principal", "localizacao": "Mapa de localização", "detalhe": "Mapa secundário"}
NOMES_MAPA = {"mapa_principal": "Mapa principal", "mapa_localizacao": "Mapa de localização (município)",
              "mapa_esquerdo": "Mapa esquerdo (imagem antiga)", "mapa_direito": "Mapa direito (imagem atual)"}


ESTILO = """
/* Identidade Norte Agro (mesma paleta do plugin Criar camadas e calcular áreas) */
QDialog { background: #F6F7F3; color: #1F2A1B; font-family: "Segoe UI"; font-size: 9pt; }
QFrame#cabecalho { background: #FFFFFF; border-bottom: 1px solid #E2E7DC; }
QLabel#titulo_app { font-size: 15pt; font-weight: 700; color: #1F2A1B; }
QLabel#subtitulo_app { color: #6E5E4E; }
QPushButton#nav { border: none; border-bottom: 3px solid transparent; padding: 12px 16px 9px 16px;
                  background: transparent; color: #55604F; font-weight: 600; }
QPushButton#nav:hover { color: #46741F; }
QPushButton#nav:checked { color: #46741F; border-bottom: 3px solid #46741F; }
QPushButton#etapa { border: 1px solid #DCE3D3; border-radius: 15px; padding: 5px 16px; background: #FFFFFF;
                    color: #55604F; font-weight: 600; }
QPushButton#etapa:hover { border-color: #7DA63F; background: #F3F7ED; color: #3B6219; }
QPushButton#etapa:checked { background: #46741F; border-color: #46741F; color: #FFFFFF; }
QPushButton#primario { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #538529, stop:1 #46741F);
                       color: #FFFFFF; border: 1px solid #3B6219; border-radius: 6px; padding: 8px 28px;
                       font-weight: 700; }
QPushButton#primario:hover { background: #3B6219; }
QPushButton#primario:pressed { background: #2F5514; }
QPushButton#primario:disabled { background: #B9CDA5; border-color: #B9CDA5; }
QPushButton#secundario { border: 1px solid #46741F; color: #46741F; background: #FFFFFF; border-radius: 6px;
                         padding: 6px 16px; font-weight: 600; }
QPushButton#secundario:hover { background: #EEF4E6; }
QPushButton#secundario:disabled { border-color: #C9D1C2; color: #9AA393; }
QPushButton, QToolButton { background: #FFFFFF; border: 1px solid #D5DCCF; border-radius: 6px; padding: 5px 12px;
                           color: #1F2A1B; }
QPushButton:hover, QToolButton:hover { border-color: #7DA63F; background: #F3F7ED; }
QPushButton:pressed, QToolButton:pressed { background: #E4EDD8; }
QPushButton:disabled, QToolButton:disabled { color: #9AA393; background: #F3F4F1; border-color: #E2E6DE; }
QToolButton::menu-indicator { image: none; width: 0px; }
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
    background: #FFFFFF; border: 1px solid #D5DCCF; border-radius: 6px; padding: 4px 8px; min-height: 20px;
    selection-background-color: #46741F; selection-color: #FFFFFF; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #46741F; }
QScrollArea, QStackedWidget, QTabWidget::pane { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #D5DCCF; selection-background-color: #EEF4E6;
                              selection-color: #1F2A1B; outline: 0; }
QTableWidget, QTreeWidget, QListWidget { background: #FFFFFF; border: 1px solid #E2E7DC; border-radius: 8px;
    gridline-color: #EEF1EA; alternate-background-color: #FAFBF8; selection-background-color: #E4EDD8;
    selection-color: #1F2A1B; }
QHeaderView::section { background: #F2F4EF; color: #3E4838; border: none; border-bottom: 1px solid #E2E7DC;
                       padding: 6px 8px; font-weight: 700; }
QLabel#titulo_pagina { font-size: 13pt; font-weight: 700; color: #1F2A1B; }
QLabel#dica { color: #66705F; }
QLabel#status { padding: 7px 16px; color: #55604F; background: #FFFFFF; border-top: 1px solid #E2E7DC; }
QGroupBox#secao { font-weight: 700; background: #FFFFFF; border: 1px solid #E2E7DC; border-radius: 10px;
                  margin-top: 16px; padding: 14px 12px 10px 12px; }
QGroupBox#secao::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #46741F;
                         background: transparent; }
QFrame#rodape { border-top: 1px solid #E2E7DC; background: #F6F7F3; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
QMenu { background: #FFFFFF; border: 1px solid #DCE3D3; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 14px; border-radius: 5px; }
QMenu::item:selected { background: #EEF4E6; color: #1F2A1B; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #C9D3BF; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #7DA63F; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #C9D3BF; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background: #1F2A1B; color: #FFFFFF; border: none; padding: 5px 8px; border-radius: 4px; }
"""


def _secao(titulo):
    g = QGroupBox(titulo)
    g.setObjectName("secao")
    return g


def _dica(texto):
    lb = QLabel(texto)
    lb.setObjectName("dica")
    lb.setWordWrap(True)
    return lb


def _pagina(titulo, dica, *conteudo):
    """Página de uma etapa: título, explicação curta e o conteúdo, com rolagem."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(4, 8, 8, 4)
    t = QLabel(titulo)
    t.setObjectName("titulo_pagina")
    v.addWidget(t)
    if dica:
        v.addWidget(_dica(dica))
    for c in conteudo:
        if isinstance(c, QWidget):
            v.addWidget(c)
        else:
            v.addLayout(c)
    v.addStretch()
    return _rolavel(w)


def _menu_botao(texto, acoes, dica=""):
    """Botão 'Mais opções' com menu: guarda as ações secundárias fora da vista."""
    b = QToolButton()
    b.setText(texto)
    b.setToolTip(dica)
    b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    m = QMenu(b)
    for rotulo, func in acoes:
        if rotulo is None:
            m.addSeparator()
        else:
            a = m.addAction(rotulo)
            a.triggered.connect(lambda _c=False, f=func: f())
    b.setMenu(m)
    return b


def _rolavel(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(widget)
    return sa


def _aviso(parent, titulo, texto):
    QMessageBox.warning(parent, titulo, texto)


class LinhaFonte(QWidget):
    def __init__(self, texto, removivel, ao_remover, sugestoes):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.campo = QComboBox()
        self.campo.setEditable(True)
        self.campo.addItems([""] + sugestoes)
        self.campo.setCurrentText(texto)
        h.addWidget(self.campo, 1)
        if removivel:
            b = QToolButton()
            b.setText("-")
            b.setToolTip("Remover esta fonte")
            b.clicked.connect(lambda: ao_remover(self))
            h.addWidget(b)

    def texto(self):
        return self.campo.currentText().strip()


class DialogoPrincipal(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("NorteAgro - Layout de plantas")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1000, 760)  # tamanho de projeto; ao abrir vira proporcional à tela (ui/tamanho_tela.py)
        from .tamanho_tela import ajustar_a_tela
        ajustar_a_tela(self, "norteagro_layout_ia/janela")
        self.corr = Correspondencia.carregar(self._caminho_correspondencia())
        self.leituras_docs = []
        self.blocos = None
        self.avisos_planilha = []
        self.cfg_mapas = {}
        self.layout_planta = None
        self.meta_atual = None
        self.tarefa = None

        self.setStyleSheet(ESTILO)
        principal = QVBoxLayout(self)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(0)

        # cabeçalho: logo, título e as três áreas do plugin
        topo = QFrame()
        topo.setObjectName("cabecalho")
        ht = QHBoxLayout(topo)
        ht.setContentsMargins(16, 8, 16, 0)
        logo = QLabel()
        pix = QPixmap(config.logo())
        if not pix.isNull():
            logo.setPixmap(pix.scaledToHeight(38, Qt.TransformationMode.SmoothTransformation))
        ht.addWidget(logo)
        ht.addSpacing(10)
        tt = QVBoxLayout()
        tt.setSpacing(0)
        t = QLabel("Layout de plantas")
        t.setObjectName("titulo_app")
        st = QLabel("Uso do Solo e Passivos · Norte Agro Projetos")
        st.setObjectName("subtitulo_app")
        tt.addWidget(t)
        tt.addWidget(st)
        ht.addLayout(tt)
        ht.addStretch()
        self.nav = QButtonGroup(self)
        for i, nome in ((0, "Nova planta"), (2, "Buscar imagem"), (1, "Configurações")):
            b = QPushButton(nome)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, i=i: self.abas.setCurrentIndex(i))
            self.nav.addButton(b, i)
            ht.addWidget(b, 0, Qt.AlignmentFlag.AlignBottom)
        # "?" - ajuda no tópico da área/etapa atual (mesmo visual do plugin Criar camadas e calcular áreas)
        ajuda = QToolButton()
        ajuda.setText("?")
        ajuda.setToolTip("Ajuda: como usar esta tela")
        ajuda.setCursor(Qt.CursorShape.PointingHandCursor)
        ajuda.setFixedSize(26, 26)
        ajuda.setStyleSheet(
            "QToolButton { font-family:'Segoe UI'; font-weight:700; font-size:12px; color:white; background:#46741F;"
            " border:none; border-radius:13px; padding:0px; min-width:26px; max-width:26px; min-height:26px;"
            " max-height:26px; }"
            " QToolButton:hover { background:#7DA63F; } QToolButton:pressed { background:#2F5514; }")
        ajuda.clicked.connect(self._ajuda)
        ht.addSpacing(8)
        ht.addWidget(ajuda, 0, Qt.AlignmentFlag.AlignVCenter)
        principal.addWidget(topo)

        corpo = QWidget()
        cv = QVBoxLayout(corpo)
        cv.setContentsMargins(14, 8, 14, 8)
        self.abas = QTabWidget()
        self.abas.tabBar().hide()
        self.abas.setDocumentMode(True)
        cv.addWidget(self.abas)
        principal.addWidget(corpo, 1)
        self.abas.addTab(self._aba_planta(), "Nova planta")
        self.abas.addTab(_rolavel(self._aba_config()), "Configurações")
        self.pagina_imagem = PaginaImagem(self.iface, self.corr, lambda t: self.status.setText(t))
        self.abas.addTab(self.pagina_imagem, "Buscar imagem")
        self.abas.currentChanged.connect(lambda i: self.nav.button(i).setChecked(True))
        self.nav.button(0).setChecked(True)
        self.status = QLabel("Pronto.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        principal.addWidget(self.status)
        self.painel_passivos.ao_progresso = self.status.setText
        self._carregar_modelos()

    # =================================================================== ABA PLANTA
    def _aba_planta(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        # ---- barra de etapas
        barra = QHBoxLayout()
        barra.setSpacing(6)
        self.grupo_etapas = QButtonGroup(self)
        self.botoes_etapa = []
        for i, nome in enumerate(("1  Modelo", "2  Dados do imóvel", "3  Tabelas", "4  Imagem",
                                  "5  Legenda")):
            b = QPushButton(nome)
            b.setObjectName("etapa")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, i=i: self._ir_etapa(i))
            self.grupo_etapas.addButton(b, i)
            self.botoes_etapa.append(b)
            barra.addWidget(b)
        barra.addStretch()
        v.addLayout(barra)
        self.pilha = QStackedWidget()
        v.addWidget(self.pilha, 1)

        # ---- 1. modelo
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cb_modelo = QComboBox()
        self.cb_modelo.currentIndexChanged.connect(self._modelo_mudou)
        b_bib = QToolButton()
        b_bib.setText("↻")
        b_bib.setToolTip("Atualizar a lista de modelos (biblioteca)")
        b_bib.clicked.connect(self._carregar_modelos)
        h = QHBoxLayout()
        h.addWidget(self.cb_modelo, 1)
        h.addWidget(b_bib)
        f.addRow("Modelo:", h)
        self.cb_folha = QComboBox()
        self.cb_folha.addItems(["A4", "A3", "A2", "A1"])
        self.cb_folha.setCurrentText(config.valor("folha", "A3"))
        self.cb_folha.setMaximumWidth(120)
        f.addRow("Tamanho da folha:", self.cb_folha)
        self.lb_desc_modelo = _dica("")
        g = _secao("Planta")
        g.setLayout(f)
        f.addRow("", self.lb_desc_modelo)
        self.pilha.addWidget(_pagina("Qual planta você vai gerar?",
                                     "Os modelos de fábrica seguem o padrão do escritório. Modelos salvos por "
                                     "você aparecem como (biblioteca).", g))

        # ---- 2. imóvel
        gd = _secao("Documentos do imóvel (opcional)")
        gl = QVBoxLayout(gd)
        gl.addWidget(_dica("Adicione o recibo do CAR e/ou a certidão de matrícula em PDF. Os dados lidos "
                           "preenchem os campos abaixo como sugestão - confira antes de gerar."))
        h = QHBoxLayout()
        self.lista_docs = QListWidget()
        self.lista_docs.setMaximumHeight(72)
        h.addWidget(self.lista_docs, 1)
        bx = QVBoxLayout()
        b_add = QPushButton("Adicionar PDF...")
        b_add.clicked.connect(self._adicionar_docs)
        b_rm = QToolButton()
        b_rm.setText("Remover selecionado")
        b_rm.clicked.connect(lambda: [self.lista_docs.takeItem(self.lista_docs.row(i))
                                      for i in self.lista_docs.selectedItems()])
        b_ler = QPushButton("Ler documentos")
        b_ler.setObjectName("secundario")
        b_ler.clicked.connect(self._ler_documentos)
        bx.addWidget(b_add)
        bx.addWidget(b_ler)
        bx.addWidget(b_rm)
        bx.addStretch()
        h.addLayout(bx)
        gl.addLayout(h)
        self.lb_docs = _dica("")
        gl.addWidget(self.lb_docs)

        gi = _secao("Dados do imóvel")
        f = QFormLayout(gi)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ed_imovel = QComboBox()
        self.ed_imovel.setEditable(True)
        self.ed_proprietario = QComboBox()
        self.ed_proprietario.setEditable(True)
        self.ed_car = QLineEdit()
        self.ed_car.setPlaceholderText("GO-0000000-XXXX.XXXX.XXXX.XXXX.XXXX.XXXX.XXXX.XXXX")
        self.ed_matricula = QLineEdit()
        self.ed_matricula.setVisible(False)  # campo de matrícula retirado da tela (não vai para a planta)
        self.ed_municipio = QComboBox()
        self.ed_municipio.setEditable(True)
        nomes_mun = sorted(documentos.municipios().values())
        self.ed_municipio.addItems([""] + nomes_mun)
        comp = QCompleter(nomes_mun)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.ed_municipio.setCompleter(comp)
        self.ed_municipio.lineEdit().setPlaceholderText("achado sozinho pela área do imóvel")
        self.ed_municipio.setToolTip("O plugin acha o município pela posição da camada Área do Imóvel. "
                                     "Não precisa escrever; se quiser, dá para trocar aqui.")
        self.ed_uf = QLineEdit("Goiás")
        self.ed_uf.setMaximumWidth(160)
        self.cb_maiusculas = QCheckBox("Iniciais maiúsculas no nome do proprietário")
        self.cb_maiusculas.setChecked(config.valor("maiusculas_titulo", True, bool))
        f.addRow("Propriedade:", self.ed_imovel)
        f.addRow("Proprietário:", self.ed_proprietario)
        f.addRow("", self.cb_maiusculas)
        f.addRow("CAR:", self.ed_car)
        f.addRow("Município:", self.ed_municipio)
        f.addRow("Estado:", self.ed_uf)
        self.form_imovel = f
        self.campos_extras = {}
        self.pilha.addWidget(_pagina("Dados do imóvel", "", gd, gi))

        # ---- 3. projeto e áreas
        gp = _secao("Dados de projeto")
        f = QFormLayout(gp)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ed_elaboracao = QComboBox()
        self.ed_elaboracao.setEditable(True)
        hist = config.historico_elaboracao()
        self.ed_elaboracao.addItems(hist)
        self.ed_elaboracao.setCurrentText(hist[0] if hist else "")
        self.ed_elaboracao.lineEdit().setPlaceholderText("seu nome como deve sair na planta")
        self.ed_data = QDateEdit(QDate.currentDate())
        self.ed_data.setDisplayFormat("dd/MM/yyyy")
        self.ed_data.setCalendarPopup(True)
        self.ed_data.setMaximumWidth(140)
        f.addRow("Elaboração:", self.ed_elaboracao)
        f.addRow("Data:", self.ed_data)
        self.caixa_fontes = QVBoxLayout()
        self.linhas_fonte = []
        self._add_fonte(config.FONTE_PADRAO, removivel=False)
        b_mais = QToolButton()
        b_mais.setText("+ outra fonte")
        b_mais.setToolTip("Adicionar outra fonte (ex.: Imagem Planet, Levantamento topográfico)")
        b_mais.clicked.connect(lambda: self._add_fonte(""))
        caixa = QVBoxLayout()
        caixa.addLayout(self.caixa_fontes)
        caixa.addWidget(b_mais, 0, Qt.AlignmentFlag.AlignLeft)
        f.addRow("Fonte:", caixa)

        ga = _secao("Quadro de áreas")
        f = QGridLayout(ga)
        self.fw_planilha = QgsFileWidget()
        self.fw_planilha.setFilter("Planilha de áreas (*.xlsx *.xlsm *.csv)")
        self.fw_planilha.setDialogTitle("Escolha a planilha do Quadro de Áreas")
        self.fw_planilha.fileChanged.connect(self._planilha_mudou)
        self.sp_casas = QSpinBox()
        self.sp_casas.setRange(0, 6)
        self.sp_casas.setValue(config.valor("casas", 4, int))
        self.sp_casas.valueChanged.connect(lambda *_: self._planilha_mudou(self.fw_planilha.filePath()))
        self.tb_areas = QTableWidget(0, 3)
        self.tb_areas.setHorizontalHeaderLabels(["Quadro", "Descrição", "Hectares"])
        self.tb_areas.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tb_areas.verticalHeader().setVisible(False)
        self.tb_areas.setAlternatingRowColors(True)
        self.tb_areas.setMaximumHeight(190)
        self.tb_areas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lb_planilha = _dica("Sem planilha: as tabelas ficam com os campos para preencher no layout.")
        f.addWidget(_dica("Planilha gerada pelo plugin 'Norte Agro - Uso do Solo' (.xlsx ou .csv)."), 0, 0, 1, 4)
        f.addWidget(QLabel("Planilha:"), 1, 0)
        f.addWidget(self.fw_planilha, 1, 1)
        f.addWidget(QLabel("Casas decimais:"), 1, 2)
        f.addWidget(self.sp_casas, 1, 3)
        f.addWidget(self.tb_areas, 2, 0, 1, 4)
        f.addWidget(self.lb_planilha, 3, 0, 1, 4)
        f.setColumnStretch(1, 1)
        self.pilha.addWidget(_pagina("Dados de projeto e quadro de áreas", "", gp, ga))

        # ---- 4. mapas e imagens
        self.painel_passivos = PainelPassivos(self.iface, self.corr, self._definir_extra, self)
        self.painel_passivos.ao_progresso = self.status.setText if hasattr(self, "status") else None
        self._passivos_ativo = False
        self.grp_extras = _secao("Textos escritos nos mapas")
        self.form_extras = QFormLayout(self.grp_extras)
        self.form_extras.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grp_mapas = QgsCollapsibleGroupBox("Personalizar cada mapa (camadas, SRC e enquadramento)")
        self.grp_mapas.setCollapsed(True)
        self.grp_mapas.setSaveCollapsedState(False)
        gl = QVBoxLayout(self.grp_mapas)
        gl.addWidget(_dica("Opcional. Sem mexer aqui, o plugin escolhe as camadas visíveis do projeto e enquadra "
                           "o imóvel automaticamente."))
        h = QHBoxLayout()
        h.addWidget(QLabel("Mapa:"))
        self.cb_mapa = QComboBox()
        self.cb_mapa.currentIndexChanged.connect(self._mapa_selecionado)
        h.addWidget(self.cb_mapa, 1)
        gl.addLayout(h)
        self.painel_mapa = PainelMapa(self.iface, self.corr)
        self.painel_mapa.alterado.connect(self._guardar_cfg_mapa)
        gl.addWidget(self.painel_mapa)
        self.pilha.addWidget(_pagina("Mapas e imagens de satélite", "",
                                     self.painel_passivos.pagina_imagens, self.grp_extras, self.grp_mapas))

        # ---- 5. legenda
        self.pilha.addWidget(_pagina("Legenda",
                                     "Por padrão entram todas as camadas do grupo do modelo no painel de camadas "
                                     "(Uso do Solo ou Passivos). Escolha outro grupo se o seu projeto usa outro "
                                     "nome, e marque ou desmarque cada camada; também dá para renomear, acrescentar, "
                                     "remover e reordenar.", self.painel_passivos.pagina_legenda))

        # ---- rodapé
        rod = QFrame()
        rod.setObjectName("rodape")
        h = QHBoxLayout(rod)
        h.setContentsMargins(0, 8, 0, 0)
        h.addWidget(_menu_botao("Mais opções ▾", [("Salvar layout como modelo...", self._salvar_como_modelo),
                                                  ("Exportar pacote (QPT + prévia)...", self._exportar_pacote_planta)],
                                "Ações para o layout já gerado"))
        b_cancelar = QPushButton("Cancelar processo")
        b_cancelar.setToolTip("Interrompe buscas em andamento e volta para a etapa 1 (mantém o que já foi preenchido)")
        b_cancelar.clicked.connect(self._cancelar_processo)
        b_limpar = QPushButton("Limpar tudo")
        b_limpar.setToolTip("Apaga tudo o que foi preenchido (documentos, dados, planilha, imagens, legenda) e "
                            "deixa o plugin como se tivesse acabado de abrir")
        b_limpar.clicked.connect(self._limpar_tudo)
        h.addWidget(b_cancelar)
        h.addWidget(b_limpar)
        h.addStretch()
        self.b_voltar = QPushButton("‹ Voltar")
        self.b_voltar.clicked.connect(lambda: self._passo(-1))
        self.b_proximo = QPushButton("Próximo ›")
        self.b_proximo.clicked.connect(lambda: self._passo(1))
        self.b_gerar = QPushButton("Gerar planta")
        self.b_gerar.setObjectName("primario")
        self.b_gerar.setDefault(True)
        self.b_gerar.clicked.connect(self._gerar)
        h.addWidget(self.b_voltar)
        h.addWidget(self.b_proximo)
        h.addSpacing(8)
        h.addWidget(self.b_gerar)
        v.addWidget(rod)
        self._ir_etapa(0)
        return w

    # ------------------------------------------------------------ reiniciar
    def _parar_tarefas(self):
        """Cancela buscas e análises em andamento e solta as telas de andamento."""
        pp = getattr(self, "painel_passivos", None)
        pi = getattr(self, "pagina_imagem", None)
        for t in (getattr(pp, "tarefa", None), getattr(pi, "tarefa", None), getattr(self, "tarefa", None)):
            try:
                if t is not None:
                    t.cancel()
            except RuntimeError:
                pass
        if pp is not None:
            pp.ao_terminar_busca = None
            pp.tarefa = None
            pp.b_buscar.setEnabled(True)
            pp.cartao.setVisible(False)
            pp.cartao.tarefa = None
            pp.lb_busca.setVisible(True)
        if pi is not None:
            pi.tarefa = None
            pi.b_buscar.setEnabled(True)
            pi.cartao.setVisible(False)
            pi.cartao.tarefa = None
        self.b_gerar.setEnabled(True)
        self.abas.setEnabled(True)

    def _cancelar_processo(self):
        self._parar_tarefas()
        self.abas.setCurrentIndex(0)
        self._ir_etapa(0)
        self.status.setText("Processo cancelado. Os dados preenchidos foram mantidos.")

    def _limpar_tudo(self):
        if QMessageBox.question(
                self, "Limpar tudo",
                "Apagar tudo o que foi preenchido (documentos, dados do imóvel, planilha, imagens escolhidas e "
                "legenda) e começar do zero, como se o plugin tivesse acabado de abrir?\n\n"
                "As camadas e layouts já criados no projeto não são apagados.") != QMessageBox.StandardButton.Yes:
            return
        self._parar_tarefas()
        if callable(getattr(self, "ao_reiniciar", None)):
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(0, self.ao_reiniciar)  # o plugin fecha esta janela e abre uma nova, limpa
        else:
            self.status.setText("Feche e abra o plugin para começar do zero.")

    # ------------------------------------------------------------ etapas
    def _etapas_visiveis(self):
        return [i for i, b in enumerate(self.botoes_etapa) if not b.isHidden()]

    def _ajuda(self):
        from .ajuda import abrir_ajuda
        aba = self.abas.currentIndex()
        if aba == 0:
            etapas = ["modelo", "dados", "tabelas", "imagem", "legenda"]
            i = self.pilha.currentIndex() if hasattr(self, "pilha") else 0
            topico = etapas[i] if 0 <= i < len(etapas) else "inicio"
        else:
            topico = {1: "config", 2: "buscar"}.get(aba, "inicio")
        self._dialogo_ajuda = abrir_ajuda(self, topico)

    def _ir_etapa(self, i):
        self.pilha.setCurrentIndex(i)
        self.botoes_etapa[i].setChecked(True)
        vis = self._etapas_visiveis()
        pos = vis.index(i) if i in vis else 0
        self.b_voltar.setEnabled(pos > 0)
        self.b_proximo.setEnabled(pos < len(vis) - 1)
        if i == 1:
            self._preencher_municipio()

    def _preencher_municipio(self):
        """v0.29.0: município (e estado) pela posição da camada do imóvel, quando o campo está vazio."""
        if self.ed_municipio.currentText().strip():
            return
        try:
            nome, uf = builder.municipio_pelo_imovel(QgsProject.instance(), self.corr)
        except Exception:
            log.erro(traceback.format_exc())
            nome, uf = "", ""
        if nome:
            self.ed_municipio.setCurrentText(nome)
            if uf:
                self.ed_uf.setText(uf)
            self.status.setText(f"Município achado pela área do imóvel: {nome}" + (f" - {uf}." if uf else "."))

    def _passo(self, d):
        vis = self._etapas_visiveis()
        atual = self.pilha.currentIndex()
        pos = vis.index(atual) if atual in vis else 0
        self._ir_etapa(vis[max(0, min(len(vis) - 1, pos + d))])

    def _add_fonte(self, texto, removivel=True):
        linha = LinhaFonte(texto, removivel, self._remover_fonte, config.fontes_extras_usadas())
        self.linhas_fonte.append(linha)
        self.caixa_fontes.addWidget(linha)

    def _remover_fonte(self, linha):
        self.linhas_fonte.remove(linha)
        linha.setParent(None)
        linha.deleteLater()

    def _fontes(self):
        vistos = []
        for l in self.linhas_fonte:
            for parte in [p.strip() for p in l.texto().split(",")] if l is self.linhas_fonte[0] else [l.texto()]:
                if parte and parte not in vistos:
                    vistos.append(parte)
        return vistos

    # ------------------------------------------------------------ modelos
    def _carregar_modelos(self):
        atual = self.cb_modelo.currentData()
        self.cb_modelo.blockSignals(True)
        self.cb_modelo.clear()
        for chave, meta in modelos.modelos_fabrica():
            self.cb_modelo.addItem(f"{meta['nome']} (de fábrica)", f"fabrica:{chave}")
        for pasta, meta in modelos.listar_biblioteca():
            self.cb_modelo.addItem(f"{meta.get('nome', os.path.basename(pasta))} (biblioteca)", pasta)
        idx = self.cb_modelo.findData(atual) if atual else 0
        self.cb_modelo.setCurrentIndex(max(0, idx))
        self.cb_modelo.blockSignals(False)
        self._modelo_mudou()

    def _meta_modelo(self):
        origem = self.cb_modelo.currentData() or "fabrica:uso_solo"
        if origem.startswith("fabrica:"):
            return modelos.FABRICA[origem.split(":", 1)[1]]()["meta"]
        mj = os.path.join(origem, "modelo.json")
        if os.path.isfile(mj):
            try:
                with open(mj, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError) as e:
                log.aviso(f"modelo.json ilegível em {origem}: {e}")
        return {"mapas": {}, "variaveis_extras": []}

    def _modelo_mudou(self, *_):
        meta = self._meta_modelo()
        self.meta_atual = meta
        origem = self.cb_modelo.currentData() or ""
        self.cb_folha.setEnabled(origem.startswith("fabrica:"))
        self.lb_desc_modelo.setText(meta.get("descricao", ""))
        # campos extras (ex.: datas das imagens na planta de passivos)
        for var, (rot, campo) in list(self.campos_extras.items()):
            self.form_extras.removeRow(campo)
        self.campos_extras = {}
        escopo = builder.ler_variaveis_projeto(QgsProject.instance())
        for var, rotulo, padrao in meta.get("variaveis_extras", []):
            campo = QLineEdit(escopo.get(var) or padrao)
            self.form_extras.addRow(rotulo + ":", campo)
            self.campos_extras[var] = (rotulo, campo)
        # mapas
        self.cb_mapa.blockSignals(True)
        self.cb_mapa.clear()
        self.cfg_mapas = {}
        ids = list(meta.get("mapas", {}).keys())
        for ident, cfg in meta.get("mapas", {}).items():
            self.cb_mapa.addItem(NOMES_MAPA.get(ident, ident), ident)
            self.cfg_mapas[ident] = dict(cfg)
        self.cb_mapa.blockSignals(False)
        extras = [(f"igual:{i}", f"Igual ao {NOMES_MAPA.get(i, i).lower()}") for i in ids]
        self._extras_modo = extras
        self._mapa_selecionado()
        if self.blocos is not None or self.fw_planilha.filePath():
            self._planilha_mudou(self.fw_planilha.filePath())
        # imagens de satélite e legenda
        self._passivos_ativo = bool(meta.get("imagens") or modelos.legendas_do_meta(meta))  # Passivos e Uso do Solo
        self.painel_passivos.configurar(meta)
        self.painel_passivos.pagina_imagens.setVisible(self.painel_passivos.tem_imagens())
        self.grp_extras.setVisible(bool(self.campos_extras))
        self.botoes_etapa[4].setVisible(self.painel_passivos.tem_legenda())
        if self.pilha.currentIndex() == 4 and not self.painel_passivos.tem_legenda():
            self._ir_etapa(3)
        else:
            self._ir_etapa(self.pilha.currentIndex())

    def _definir_extra(self, var, texto):
        """Preenche um campo extra do modelo (ex.: data da imagem de cada mapa)."""
        par = self.campos_extras.get(var)
        if par is not None:
            par[1].setText(texto)

    def _mapa_selecionado(self, *_):
        ident = self.cb_mapa.currentData()
        if not ident:
            return
        self._mapa_em_edicao = None
        cfg = self.cfg_mapas.get(ident, {})
        self.painel_mapa.definir_modos_extra([e for e in getattr(self, "_extras_modo", [])
                                              if e[0] != f"igual:{ident}"])
        self.painel_mapa.carregar(cfg, cfg.get("role", "principal"), NOMES_MAPA.get(ident, ident))
        self._mapa_em_edicao = ident

    def _guardar_cfg_mapa(self):
        ident = getattr(self, "_mapa_em_edicao", None)
        if ident:
            self.cfg_mapas[ident] = self.painel_mapa.cfg()

    # ------------------------------------------------------------ documentos
    def _adicionar_docs(self):
        pasta = config.valor("pasta_docs", os.path.expanduser("~"))
        arqs, _ = QFileDialog.getOpenFileNames(self, "Documentos do imóvel", pasta, "PDF (*.pdf)")
        for a in arqs:
            if not self.lista_docs.findItems(a, Qt.MatchFlag.MatchExactly):
                self.lista_docs.addItem(a)
        if arqs:
            config.definir("pasta_docs", os.path.dirname(arqs[0]))

    def _ler_documentos(self):
        caminhos = [self.lista_docs.item(i).text() for i in range(self.lista_docs.count())]
        if not caminhos:
            self._adicionar_docs()
            caminhos = [self.lista_docs.item(i).text() for i in range(self.lista_docs.count())]
            if not caminhos:
                return
        leituras = []
        for c in caminhos:
            QApplicationProcessar()
            leitura = documentos.ler_documento(c)
            if leitura[0] == "digitalizado" and config.valor("python_suporte", ""):
                leitura = self._ler_com_ocr(c) or leitura
            leituras.append(leitura)
        final, avisos = documentos.combinar(leituras, "titulo" if self.cb_maiusculas.isChecked() else "documento")
        alvos = {"imovel": self.ed_imovel, "proprietario": self.ed_proprietario, "municipio": self.ed_municipio}
        linhas = []
        for chave, campo in final.items():
            if chave in alvos:
                cb = alvos[chave]
                cb.clear() if chave != "municipio" else None
                if chave != "municipio":
                    cb.addItems([campo.valor] + [a for a in campo.alternativas if a != campo.valor])
                cb.setCurrentText(campo.valor)
                cb.setStyleSheet("background: #fff6cc" if campo.confianca != "alta" else "")
            elif chave == "car":
                self.ed_car.setText(campo.valor)
            elif chave == "matricula":
                continue
            elif chave == "uf":
                self.ed_uf.setText(campo.valor)
            linhas.append(f"<b>{chave}</b>: {campo.valor} <i>({campo.documento}"
                          f"{'' if campo.confianca == 'alta' else ' - confira'})</i>")
        txt = "<br>".join(linhas) if linhas else "Nenhum dado encontrado."
        if avisos:
            txt += "<br><span style='color:#a15c00'>" + "<br>".join(avisos) + "</span>"
        self.lb_docs.setText(txt)
        log.info("Documentos lidos: " + "; ".join(f"{k}={'ok' if v.valor else '-'}" for k, v in final.items()))

    def _ler_com_ocr(self, caminho):
        """Documento digitalizado: OCR no ambiente de suporte (se configurado)."""
        import subprocess
        py = config.valor("python_suporte", "")
        script = os.path.join(PASTA_PLUGIN, "support", "ocr_referencia.py")
        saida = os.path.join(tempfile.mkdtemp(prefix="na_ocr_"), "ocr.json")
        try:
            r = subprocess.run([py, "-I", script, caminho, saida, "1"], capture_output=True, text=True, timeout=300,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                log.aviso(f"OCR falhou: {r.stderr[:300]}")
                return None
            with open(saida, encoding="utf-8") as fh:
                textos = [t["texto"] for t in json.load(fh)["textos"]]
            tmp_txt = "\n".join(textos)
            tipo = documentos._tipo(tmp_txt)
            leitor = {"matricula": documentos._ler_matricula, "recibo_sigcar": documentos._ler_recibo_sigcar}.get(
                tipo, documentos._ler_recibo_sicar)
            campos = leitor(tmp_txt, os.path.basename(caminho))
            for c in campos.values():
                c.confianca = "média"
            return tipo, campos, [f"'{os.path.basename(caminho)}' lido por OCR - confira com atenção."]
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            log.aviso(f"OCR indisponível: {e}")
            return None

    # ------------------------------------------------------------ planilha
    def _sugerir_planilha(self):
        """Se nenhuma planilha foi escolhida, usa o Quadro de Áreas mais recente da pasta do mapa (gerado pelo
        plugin Uso do Solo). Assim as tabelas da planta já saem com os hectares."""
        try:
            if self.fw_planilha.filePath():
                return
            from qgis.core import QgsExpressionContextUtils
            pr = QgsProject.instance()
            pastas = [str(QgsExpressionContextUtils.projectScope(pr).variable("norteagro_pasta") or "")]
            if pr.fileName():
                pastas.append(pr.absolutePath())
            achados = []
            for pasta in pastas:
                if pasta and os.path.isdir(pasta):
                    for nome in os.listdir(pasta):
                        if nome.upper().startswith("QUADRO_DE_AREAS") and nome.lower().endswith((".xlsx", ".xlsm")) \
                                and not nome.startswith("~$"):
                            caminho = os.path.join(pasta, nome)
                            achados.append((os.path.getmtime(caminho), caminho))
            if achados:
                self.fw_planilha.setFilePath(max(achados)[1])  # dispara _planilha_mudou
        except Exception as e:
            log.aviso(f"Planilha não sugerida: {e}")

    def closeEvent(self, evento):
        """Ao fechar: solta a ferramenta de desenhar do mapa, para o mapa do QGIS não ficar apontando para ela."""
        try:
            self.painel_mapa.soltar_ferramenta()
        except (AttributeError, RuntimeError):
            pass
        super().closeEvent(evento)

    def cancelar_tarefas(self):
        for t in (getattr(self, "tarefa", None), getattr(self, "_tarefa_download", None),
                  getattr(self, "_tarefa_imagens", None),
                  getattr(getattr(self, "painel_passivos", None), "tarefa", None),
                  getattr(getattr(self, "pagina_imagem", None), "tarefa", None)):
            try:
                if t is not None:
                    t.cancel()
            except RuntimeError:
                pass

    def showEvent(self, evento):
        super().showEvent(evento)
        QTimer.singleShot(0, self._sugerir_planilha)

    def _planilha_mudou(self, caminho):
        self.tb_areas.setRowCount(0)
        self.blocos = None
        if not caminho:
            self.lb_planilha.setText("Sem planilha: as tabelas ficam com os campos para preencher no layout.")
            return
        chaves = [b["chave"] for b in (self.meta_atual or {}).get("tabelas", {}).get("blocos", [])] or None
        try:
            self.blocos, self.avisos_planilha, aba = planilha_areas.importar(caminho, self.sp_casas.value(), chaves)
        except planilha_areas.ErroPlanilha as e:
            self.lb_planilha.setText(f"<span style='color:#b00'>{e}</span>")
            return
        except Exception as e:  # arquivo corrompido, sem permissão etc.
            log.erro(traceback.format_exc())
            self.lb_planilha.setText(f"<span style='color:#b00'>Não foi possível ler a planilha: {e}</span>")
            return
        for chave, b in self.blocos.items():
            for desc, val in planilha_areas.linhas_tabela(b, self.sp_casas.value()):
                r = self.tb_areas.rowCount()
                self.tb_areas.insertRow(r)
                for c, t in enumerate((b["titulo"], desc, val)):
                    it = QTableWidgetItem(t)
                    if desc == "Total":
                        f = it.font()
                        f.setBold(True)
                        it.setFont(f)
                    self.tb_areas.setItem(r, c, it)
        self.lb_planilha.setText(f"Aba lida: <b>{aba}</b>. " + " ".join(self.avisos_planilha))
        config.definir("casas", self.sp_casas.value())

    # ------------------------------------------------------------ gerar
    def _dados(self):
        perfil = config.perfil_rt()
        dados = {
            "na_imovel": self.ed_imovel.currentText().strip(),
            "na_proprietario": self.ed_proprietario.currentText().strip(),
            "na_car": self.ed_car.text().strip(),
            "na_matricula": "",
            "na_municipio": self.ed_municipio.currentText().strip(),
            "na_uf": self.ed_uf.text().strip(),
            "na_elaboracao": self.ed_elaboracao.currentText().strip(),
            "na_data": self.ed_data.date().toString("dd/MM/yyyy"),
            "na_fonte": ", ".join(self._fontes()),
        }
        for var, (_rot, campo) in self.campos_extras.items():
            dados[var] = campo.text().strip()
        for var, _r, _p in identidade.VARIAVEIS_RT:
            dados[var] = perfil.get(var, "")
        return dados, perfil

    def _gerar(self):
        self._guardar_cfg_mapa()
        pp = self.painel_passivos
        if self._passivos_ativo and pp.combos_img and not pp.busca_feita() and pp.tarefa is None:
            r = QMessageBox.question(
                self, "Imagens de satélite",
                "As imagens de satélite ainda não foram buscadas.\n\nBuscar agora (cerca de 1 minuto) e gerar a "
                "planta em seguida?\n\nNão = gerar com as camadas marcadas em cada mapa.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                if pp.buscar(ao_terminar=self._gerar):
                    self.status.setText("Buscando as imagens; a planta será gerada ao terminar...")
                return
        if self._passivos_ativo and pp.tarefa is not None:
            _aviso(self, "Imagens de satélite", "Aguarde a busca de imagens terminar (ou cancele).")
            return
        if self._passivos_ativo:
            faltam = pp.faltando()
            if faltam:
                caixa = QMessageBox(self)
                caixa.setIcon(QMessageBox.Icon.Question)
                caixa.setWindowTitle("Legenda")
                caixa.setText("Estas camadas da legenda não foram encontradas no projeto:\n\n• " +
                              "\n• ".join(faltam) +
                              "\n\nVocê pode escolher a camada de cada uma (ou marcar outras camadas) na tabela "
                              "da legenda, ou gerar a planta sem elas.")
                b_escolher = caixa.addButton("Escolher camadas", QMessageBox.ButtonRole.RejectRole)
                caixa.addButton("Gerar sem elas", QMessageBox.ButtonRole.AcceptRole)
                caixa.exec()
                if caixa.clickedButton() is b_escolher:
                    self._ir_etapa(4)
                    pp.tb_leg.setFocus()
                    return
        if not self.ed_elaboracao.currentText().strip():
            nome, ok = QInputDialog.getText(self, "Elaboração", "Quem está elaborando esta planta?\n"
                                                                 "(nome como deve aparecer em 'Elaboração')")
            if not ok or not nome.strip():
                return
            self.ed_elaboracao.setCurrentText(nome.strip())
        self._preencher_municipio()  # o município vem da área do imóvel; não é pedido
        faltando = [r for r, c in (("Propriedade", self.ed_imovel.currentText()),
                                   ("Proprietário", self.ed_proprietario.currentText())) if not c.strip()]
        if faltando and QMessageBox.question(
                self, "Dados incompletos", "Faltam: " + ", ".join(faltando) + ".\nGerar assim mesmo? "
                "(você pode preencher depois em Projeto > Propriedades > Variáveis)") != QMessageBox.StandardButton.Yes:
            return
        imagens_mapas, legenda_itens = None, None
        if self._passivos_ativo:
            try:
                imagens_mapas, creditos = pp.imagens_escolhidas(self._progresso)
                legenda_itens = pp.itens_legenda()
            except Exception as e:
                log.erro(traceback.format_exc())
                _aviso(self, "Imagens de satélite", f"Não foi possível preparar as imagens: {e}")
                return
            if creditos:
                fontes = self._fontes()
                if len(imagens_mapas) >= len(pp.combos_img) and any("google" in f.lower() for f in fontes):
                    # as duas imagens vieram da busca automática: a fonte não é mais o Google Earth
                    primeira = self.linhas_fonte[0]
                    resto = [p.strip() for p in primeira.texto().split(",") if p.strip() and
                             "google" not in p.lower()]
                    primeira.campo.setCurrentText(", ".join(resto))
                    fontes = self._fontes()
                for c in creditos:
                    if c not in fontes:
                        self._add_fonte(c)
        dados, perfil = self._dados()
        config.lembrar_elaboracao(dados["na_elaboracao"])
        config.lembrar_fontes(self._fontes())
        config.definir("folha", self.cb_folha.currentText())
        config.definir("maiusculas_titulo", self.cb_maiusculas.isChecked())
        projeto = QgsProject.instance()
        t0 = time.time()
        self.b_gerar.setEnabled(False)
        self.abas.setEnabled(False)
        try:
            origem = self.cb_modelo.currentData()
            nome = f"{self._nome_modelo_curto()} - {dados['na_imovel'] or 'imóvel'}"
            layout, meta = modelos.abrir_modelo(projeto, origem, self.cb_folha.currentText(), self.corr,
                                                perfil.get("assinatura"), logo=config.logo_planta(), nome=nome)
            avisos = modelos.gerar_planta(projeto, layout, meta, dados, self.cfg_mapas, self.blocos,
                                          self.sp_casas.value(), self.corr, perfil.get("assinatura"),
                                          progresso=self._progresso, imagens=imagens_mapas,
                                          legenda_itens=legenda_itens, logo=config.logo_planta())
            builder.adicionar_ao_projeto(projeto, layout)
            self.layout_planta = layout
            avisos += self.avisos_planilha if self.blocos else []
            dt = time.time() - t0
            log.ok(f"Planta '{layout.name()}' gerada em {dt:.1f} s.")
            for a in avisos:
                log.aviso(a)
            self.status.setText(f"Planta '{layout.name()}' gerada em {dt:.1f} s." +
                                (f" {len(avisos)} aviso(s) - veja o painel de log, aba NorteAgro Layout."
                                 if avisos else ""))
            self.iface.openLayoutDesigner(layout)
        except Exception as e:
            log.erro(traceback.format_exc())
            _aviso(self, "Não foi possível gerar a planta", str(e))
        finally:
            self.b_gerar.setEnabled(True)
            self.abas.setEnabled(True)

    def _nome_modelo_curto(self):
        t = self.cb_modelo.currentText()
        return t.split(" (")[0]

    def _progresso(self, texto):
        self.status.setText(texto)
        QApplicationProcessar()

    def _layout_escolhido(self):
        gerente = QgsProject.instance().layoutManager()
        nomes = [l.name() for l in gerente.printLayouts()]
        if not nomes:
            _aviso(self, "Sem layout", "Gere uma planta (ou abra um projeto com layout) primeiro.")
            return None
        ultimo = _valido(self.layout_planta)
        padrao = nomes.index(ultimo.name()) if ultimo is not None and ultimo.name() in nomes else 0
        nome, ok = QInputDialog.getItem(self, "Layout", "Qual layout?", nomes, padrao, False)
        return gerente.layoutByName(nome) if ok else None

    def _salvar_como_modelo(self):
        layout = self._layout_escolhido()
        if layout is None:
            return
        nome, ok = QInputDialog.getText(self, "Salvar como modelo", "Nome do modelo:", text=layout.name())
        if not ok or not nome.strip():
            return
        try:
            destino = modelos.salvar_como_modelo(layout, nome.strip())
            self._carregar_modelos()
            self.status.setText(f"Modelo salvo em {destino} (sem as camadas e as áreas deste imóvel).")
        except PermissionError as e:
            _aviso(self, "Modelo não salvo", str(e))
        except Exception as e:
            log.erro(traceback.format_exc())
            _aviso(self, "Não foi possível salvar o modelo", str(e))

    def _exportar_pacote_planta(self):
        layout = self._layout_escolhido()
        if layout is None:
            return
        pasta = QFileDialog.getExistingDirectory(self, "Pasta de saída", config.valor("pasta_saida", ""))
        if not pasta:
            return
        config.definir("pasta_saida", pasta)
        destino = os.path.join(pasta, modelos._slug(layout.name()))
        try:
            r = builder.exportar_pacote(layout, destino, zipar=True)
            self.status.setText(f"Pacote gravado em {r['pasta']} (e .zip).")
        except PermissionError as e:
            _aviso(self, "Exportação bloqueada", str(e))
        except Exception as e:
            log.erro(traceback.format_exc())
            _aviso(self, "Falha na exportação", str(e))

    # =================================================================== ABA CONFIG
    def _aba_config(self):
        w = QWidget()
        v = QVBoxLayout(w)
        perfil = config.perfil_rt()
        g = _secao("Responsável técnico e identidade visual")
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        f.addRow(_dica("Estes dados, a assinatura e a logo entram sozinhos em toda planta gerada (nunca vêm da "
                       "imagem de referência)."))
        self.campos_rt = {}
        for var, rot, _p in identidade.VARIAVEIS_RT:
            e = QLineEdit(perfil.get(var, ""))
            f.addRow(rot + ":", e)
            self.campos_rt[var] = e
        self.fw_assinatura = QgsFileWidget()
        self.fw_assinatura.setFilter("Imagem (*.png *.jpg *.jpeg *.svg)")
        self.fw_assinatura.setFilePath(config.valor("rt/assinatura", "") or "")
        self.fw_assinatura.lineEdit().setPlaceholderText("escolha a imagem da assinatura do RT (opcional)")
        self.fw_assinatura.fileChanged.connect(lambda *_: self._previa_identidade())
        f.addRow("Assinatura:", self.fw_assinatura)
        self.fw_logo = QgsFileWidget()
        self.fw_logo.setFilter("Imagem (*.png *.jpg *.jpeg *.svg)")
        self.fw_logo.setFilePath(config.valor("logo", "") or "")
        self.fw_logo.lineEdit().setPlaceholderText("escolha a imagem da logo (opcional)")
        self.fw_logo.fileChanged.connect(lambda *_: self._previa_identidade())
        f.addRow("Logo:", self.fw_logo)
        hp = QHBoxLayout()
        self.lb_prev_assinatura = QLabel()
        self.lb_prev_logo = QLabel()
        for lb in (self.lb_prev_assinatura, self.lb_prev_logo):
            lb.setStyleSheet("background: #ffffff; border: 1px solid #dde3df; padding: 6px;")
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setMinimumHeight(64)
            hp.addWidget(lb)
        f.addRow("Prévia:", hp)
        b = QPushButton("Salvar")
        b.setObjectName("secundario")
        b.clicked.connect(self._salvar_rt)
        hb = QHBoxLayout()
        hb.addWidget(b)
        hb.addStretch()
        f.addRow("", hb)
        v.addWidget(g)
        self._previa_identidade()

        g = QgsCollapsibleGroupBox("Biblioteca de modelos e nomes de camadas")
        g.setCollapsed(True)
        g.setSaveCollapsedState(False)
        f = QFormLayout(g)
        self.fw_biblioteca = QgsFileWidget()
        self.fw_biblioteca.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.fw_biblioteca.setFilePath(modelos.pasta_biblioteca())
        self.fw_biblioteca.fileChanged.connect(lambda p: (modelos.definir_pasta_biblioteca(p),
                                                          self._carregar_modelos()))
        f.addRow("Pasta da biblioteca:", self.fw_biblioteca)
        self.fw_corr = QgsFileWidget()
        self.fw_corr.setFilter("CSV (*.csv)")
        self.fw_corr.setFilePath(self._caminho_correspondencia())
        self.fw_corr.fileChanged.connect(self._trocar_correspondencia)
        f.addRow("Tabela de nomes (CSV):", self.fw_corr)
        h = QHBoxLayout()
        b1 = QPushButton("Abrir tabela de nomes")
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._caminho_correspondencia())))
        b2 = QPushButton("Copiar tabela para a biblioteca (para editar)")
        b2.clicked.connect(self._copiar_correspondencia)
        h.addWidget(b1)
        h.addWidget(b2)
        f.addRow("", h)
        self.fw_python = QgsFileWidget()
        self.fw_python.setFilePath(config.valor("python_suporte", ""))
        self.fw_python.setFilter("python.exe (python.exe python python3)")
        self.fw_python.fileChanged.connect(lambda p: config.definir("python_suporte", p))
        f.addRow("Python de suporte (PDF/OCR, opcional):", self.fw_python)
        v.addWidget(g)

        v.addStretch()
        return w

    def _salvar_rt(self):
        perfil = {var: e.text().strip() for var, e in self.campos_rt.items()}
        perfil["assinatura"] = self.fw_assinatura.filePath()
        config.salvar_perfil_rt(perfil)
        config.definir("logo", self.fw_logo.filePath())
        self._previa_identidade()
        self.status.setText("Responsável técnico, assinatura e logo salvos.")

    def _previa_identidade(self):
        """Mostra a assinatura e a logo que vão para a planta (as escolhidas em Configurações)."""
        nome = self.campos_rt["na_responsavel"].text() if "na_responsavel" in self.campos_rt else ""
        ass = self.fw_assinatura.filePath() or config.assinatura_padrao(nome)
        logo = self.fw_logo.filePath()
        for lb, arq, vazio in ((self.lb_prev_assinatura, ass, "sem assinatura"), (self.lb_prev_logo, logo, "sem logo")):
            pix = QPixmap(arq) if arq and os.path.isfile(arq) else QPixmap()
            if pix.isNull():
                lb.setPixmap(QPixmap())
                lb.setText(vazio)
            else:
                lb.setPixmap(pix.scaled(260, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _caminho_correspondencia(self):
        p = config.valor("correspondencia", "")
        if p and os.path.isfile(p):
            return p
        bib = os.path.join(modelos.pasta_biblioteca(), "correspondencia_camadas.csv")
        return bib if os.path.isfile(bib) else os.path.join(PASTA_PLUGIN, "dados", "correspondencia_camadas.csv")

    def _trocar_correspondencia(self, p):
        config.definir("correspondencia", p)
        self.corr = Correspondencia.carregar(p)
        self.painel_mapa.corr = self.corr

    def _copiar_correspondencia(self):
        import shutil
        destino = os.path.join(modelos.pasta_biblioteca(), "correspondencia_camadas.csv")
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if not os.path.isfile(destino):
            shutil.copy2(os.path.join(PASTA_PLUGIN, "dados", "correspondencia_camadas.csv"), destino)
        self.fw_corr.setFilePath(destino)
        QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

def _valido(layout):
    """None se o layout foi apagado no Gerenciador de layouts (objeto C++ já excluído)."""
    if layout is None:
        return None
    try:
        from qgis.PyQt import sip
        if sip.isdeleted(layout):
            return None
        layout.name()
        return layout
    except (RuntimeError, ImportError):
        return None


def _textos_com_permitidos(layout, originais):
    """Textos completos de rótulos que contêm algum original que o usuário mandou manter."""
    if not originais:
        return []
    saida = []
    for _i, t in builder.textos_do_layout(layout):
        if any(o and o in t for o in originais):
            saida.append(t)
    return saida


def QApplicationProcessar():  # noqa: N802
    from qgis.PyQt.QtWidgets import QApplication
    QApplication.processEvents()
