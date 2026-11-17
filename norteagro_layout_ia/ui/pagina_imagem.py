# -*- coding: utf-8 -*-
"""Área "Buscar imagem": só procurar e adicionar uma imagem de satélite ao projeto, sem gerar planta.

Mesmos critérios das plantas: cores reais, melhor qualidade primeiro (alta resolução do Esri Wayback
quando houver) e, empatando, a mais recente; cenas Sentinel-2 só contam sem nuvem sobre a área.
  - Mais recente: a imagem mais recente do ano atual (ou do anterior, se ainda não houver).
  - Período: imagens capturadas entre as datas escolhidas.
"""

from ..core import compat
import os
from datetime import date, timedelta

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMapLayerProxyModel,
                       QgsProject)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (QAbstractItemView, QButtonGroup, QDateEdit, QFormLayout, QGroupBox, QHBoxLayout,
                                 QHeaderView, QLabel, QPushButton, QRadioButton, QScrollArea, QFrame,
                                 QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import builder
from ..core import imagens, log
from .andamento import CartaoAndamento, tempo_txt
from .tarefas import TarefaFuncao, iniciar

GRUPO_IMAGENS = "NorteAgro - Imagens de satélite"


def _secao(titulo):
    g = QGroupBox(titulo)
    g.setObjectName("secao")
    return g


def _dica(texto):
    lb = QLabel(texto)
    lb.setObjectName("dica")
    lb.setWordWrap(True)
    return lb


class PaginaImagem(QWidget):
    def __init__(self, iface, corr, status=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.corr = corr
        self.status = status or (lambda t: None)
        self.projeto = QgsProject.instance()
        self.tarefa = None
        self.resultado = []
        self._ret = None

        conteudo = QWidget()
        v = QVBoxLayout(conteudo)
        v.setContentsMargins(4, 8, 8, 4)
        t = QLabel("Buscar imagem de satélite")
        t.setObjectName("titulo_pagina")
        v.addWidget(t)
        v.addWidget(_dica("Encontra a imagem em cores reais com a melhor qualidade disponível para a área e a "
                          "adiciona ao projeto, sem gerar planta. Mesmos critérios das plantas: alta resolução "
                          "(Esri Wayback, 0,3–0,5 m) quando houver; senão Sentinel-2 (10 m) sem nuvem sobre a área."))

        # ---- área
        ga = _secao("Área")
        fa = QVBoxLayout(ga)
        self.rb_camada = QRadioButton("Camada:")
        self.rb_vista = QRadioButton("Área visível no mapa do QGIS")
        self.grupo_area = QButtonGroup(self)
        self.grupo_area.addButton(self.rb_camada)
        self.grupo_area.addButton(self.rb_vista)
        self.rb_camada.setChecked(True)
        self.cb_camada = QgsMapLayerComboBox()
        self.cb_camada.setFilters(compat.FILTRO_POLIGONO)
        self.cb_camada.setAllowEmptyLayer(True)
        imovel = builder.camada_imovel(self.projeto, corr)
        if imovel is not None:
            self.cb_camada.setLayer(imovel)
        h = QHBoxLayout()
        h.addWidget(self.rb_camada)
        h.addWidget(self.cb_camada, 1)
        fa.addLayout(h)
        fa.addWidget(self.rb_vista)
        self.rb_camada.toggled.connect(self.cb_camada.setEnabled)

        # ---- data
        gd = _secao("Data da imagem")
        fd = QVBoxLayout(gd)
        self.rb_recente = QRadioButton("Mais recente (a melhor imagem mais recente disponível)")
        self.rb_periodo = QRadioButton("Escolher período:")
        self.grupo_data = QButtonGroup(self)
        self.grupo_data.addButton(self.rb_recente)
        self.grupo_data.addButton(self.rb_periodo)
        self.rb_recente.setChecked(True)
        hoje = QDate.currentDate()
        self.ed_de = QDateEdit(hoje.addYears(-1))
        self.ed_ate = QDateEdit(hoje)
        for ed in (self.ed_de, self.ed_ate):
            ed.setDisplayFormat("dd/MM/yyyy")
            ed.setCalendarPopup(True)
            ed.setMaximumDate(hoje)
            ed.setMinimumDate(QDate(2010, 1, 1))
            ed.setEnabled(False)
        self.rb_periodo.toggled.connect(lambda on: [e.setEnabled(on) for e in (self.ed_de, self.ed_ate)])
        fd.addWidget(self.rb_recente)
        h = QHBoxLayout()
        h.addWidget(self.rb_periodo)
        h.addSpacing(6)
        h.addWidget(QLabel("de"))
        h.addWidget(self.ed_de)
        h.addWidget(QLabel("até"))
        h.addWidget(self.ed_ate)
        h.addStretch()
        fd.addLayout(h)
        atalhos = QHBoxLayout()
        atalhos.addSpacing(24)
        for rotulo, ano in (("2019", 2019), ("Ano passado", hoje.year() - 1), ("Este ano", hoje.year())):
            b = QPushButton(rotulo)
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton { color: #46741F; text-decoration: underline; border: none; padding: 0 6px; }")
            b.clicked.connect(lambda _c=False, a=ano: self._ano(a))
            atalhos.addWidget(b)
        atalhos.addStretch()
        fd.addLayout(atalhos)

        # ---- buscar + andamento
        hb = QHBoxLayout()
        self.b_buscar = QPushButton("Buscar imagem")
        self.b_buscar.setObjectName("primario")
        self.b_buscar.clicked.connect(self.buscar)
        hb.addWidget(self.b_buscar)
        hb.addStretch()
        self.cartao = CartaoAndamento()
        self.cartao.ao_progresso = self.status

        # ---- resultados
        gr = _secao("Imagens encontradas")
        fr = QVBoxLayout(gr)
        self.lb_rec = _dica("Faça uma busca para ver as opções. A recomendada vem marcada com ★.")
        fr.addWidget(self.lb_rec)
        self.tb = QTableWidget(0, 5)
        self.tb.setHorizontalHeaderLabels(["", "Data", "Fonte", "Qualidade", "Nuvens na área"])
        cab = self.tb.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        cab.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tb.setAlternatingRowColors(True)
        self.tb.setMinimumHeight(200)
        self.tb.doubleClicked.connect(lambda *_: self.adicionar())
        fr.addWidget(self.tb)
        ha = QHBoxLayout()
        ha.addStretch()
        self.b_adicionar = QPushButton("Adicionar ao projeto")
        self.b_adicionar.setObjectName("secundario")
        self.b_adicionar.setEnabled(False)
        self.b_adicionar.clicked.connect(self.adicionar)
        ha.addWidget(self.b_adicionar)
        fr.addLayout(ha)

        for w in (ga, gd):
            v.addWidget(w)
        v.addLayout(hb)
        v.addWidget(self.cartao)
        v.addWidget(gr)
        v.addStretch()
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(conteudo)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sa)

    # ------------------------------------------------------------ área e datas
    def _ano(self, ano):
        self.rb_periodo.setChecked(True)
        hoje = QDate.currentDate()
        self.ed_de.setDate(QDate(ano, 1, 1))
        self.ed_ate.setDate(min(QDate(ano, 12, 31), hoje))

    def _retangulo(self):
        if self.rb_vista.isChecked():
            canvas = self.iface.mapCanvas()
            ct = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(),
                                        QgsCoordinateReferenceSystem("EPSG:4326"), self.projeto)
            return ct.transformBoundingBox(canvas.extent())
        cam = self.cb_camada.currentLayer()
        if cam is None or cam.extent().isEmpty():
            return None
        return imagens.area_imovel(cam, self.projeto)

    # ------------------------------------------------------------ busca
    def buscar(self):
        if self.tarefa is not None:
            return
        ret = self._retangulo()
        if ret is None:
            self.lb_rec.setText("Escolha a camada da área (ou use a área visível no mapa).")
            self.lb_rec.setStyleSheet("color: #b3261e")
            return
        if ret.width() > 0.5 or ret.height() > 0.5:
            self.lb_rec.setText("A área é grande demais para buscar imagem (mais de ~50 km). Aproxime o mapa ou "
                                "use a camada do imóvel.")
            self.lb_rec.setStyleSheet("color: #b3261e")
            return
        self._ret = ret
        if self.rb_recente.isChecked():
            inicio = fim = None
        else:
            a, b = self.ed_de.date(), self.ed_ate.date()
            inicio, fim = date(a.year(), a.month(), a.day()), date(b.year(), b.month(), b.day())
            if inicio > fim:
                inicio, fim = fim, inicio
        self.tarefa = TarefaFuncao("NorteAgro: busca de imagem de satélite",
                                   lambda feedback, progresso: imagens.buscar_periodo(ret, inicio, fim, feedback,
                                                                                      progresso))
        self.tarefa.sinais.terminou.connect(self._ok)
        self.tarefa.sinais.falhou.connect(self._falhou)
        self.b_buscar.setEnabled(False)
        self.b_adicionar.setEnabled(False)
        self.cartao.iniciar(self.tarefa, "Buscando imagem de satélite")
        iniciar(self.tarefa)

    def cancelar(self):
        if self.tarefa is not None:
            self.tarefa.cancel()

    def _ok(self, resultado):
        dur = tempo_txt(self.cartao.decorrido())
        self.tarefa = None
        self.b_buscar.setEnabled(True)
        self.resultado = resultado.get("imagens") or []
        avisos = resultado.get("avisos") or []
        for a in avisos:
            log.aviso(a)
        self._preencher()
        n = len(self.resultado)
        self.cartao.concluir(f"{n} imagem(ns) encontrada(s) em {dur}",
                             "Selecione na lista e clique em Adicionar ao projeto (ou dê dois cliques)." +
                             "".join("\n• " + a for a in avisos), aviso=bool(avisos) or not n)
        self.status(f"Busca de imagem concluída em {dur}.")

    def _falhou(self, erro, _parcial):
        self.tarefa = None
        self.b_buscar.setEnabled(True)
        self.cartao.falhar(erro)

    def _preencher(self):
        self.tb.setRowCount(0)
        negrito = QFont()
        negrito.setBold(True)
        for i, c in enumerate(self.resultado):
            r = self.tb.rowCount()
            self.tb.insertRow(r)
            alta = c["fonte"] == "wayback"
            r_ = c.get("resolucao")
            res = "?" if not r_ else (f"{r_:.0f} m" if r_ >= 1 else f"{r_:.2f} m".replace(".", ","))
            fonte = "Esri Wayback" + (f" ({c.get('provedor')} {c.get('sensor')})".replace(" )", ")")
                                      if c.get("provedor") else "") if alta else "Sentinel-2 (ESA)"
            nuv = "—" if c.get("nuvens") is None else f"{c['nuvens']:.0f}%"
            celulas = ["★" if i == 0 else "", imagens.data_br(c["data"]), fonte,
                       ("Alta · " if alta else "Média · ") + res, nuv]
            for k, txt in enumerate(celulas):
                it = QTableWidgetItem(txt)
                if i == 0:
                    it.setFont(negrito)
                if k == 0:
                    it.setForeground(QColor("#46741F"))
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if k == 4 and not imagens.limpa(c):
                    it.setForeground(QColor("#b3261e"))
                self.tb.setItem(r, k, it)
        if self.resultado:
            self.tb.selectRow(0)
            c = self.resultado[0]
            self.lb_rec.setText(f"Recomendada: {c['descricao']}")
            self.lb_rec.setStyleSheet("color: #1f2d24")
        else:
            self.lb_rec.setText("Nenhuma imagem encontrada para essa área e período.")
            self.lb_rec.setStyleSheet("color: #b3261e")
        self.b_adicionar.setEnabled(bool(self.resultado))

    # ------------------------------------------------------------ adicionar
    def _pasta(self):
        arq = self.projeto.fileName()
        if arq:
            return os.path.join(os.path.dirname(arq), "imagens_satelite")
        return os.path.join(QgsApplication.qgisSettingsDirPath(), "norteagro_imagens")

    def adicionar(self):
        linhas = {i.row() for i in self.tb.selectedIndexes()}
        if not linhas or self._ret is None:
            return
        c = self.resultado[min(linhas)]
        self.status(f"Preparando a imagem de {imagens.data_br(c['data'])}...")
        try:
            cam = imagens.criar_camada(c, self._ret, self._pasta())
        except Exception as e:
            self.cartao.falhar(f"Não foi possível adicionar a imagem: {e}")
            return
        raiz = self.projeto.layerTreeRoot()
        grupo = raiz.findGroup(GRUPO_IMAGENS) or raiz.addGroup(GRUPO_IMAGENS)
        self.projeto.addMapLayer(cam, False)
        grupo.insertLayer(0, cam)
        # imagem embaixo de tudo: o grupo vai para o fim do painel de camadas
        if raiz.children() and raiz.children()[-1] is not grupo:
            clone = grupo.clone()
            raiz.addChildNode(clone)
            raiz.removeChildNode(grupo)
        canvas = self.iface.mapCanvas()
        ct = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), canvas.mapSettings().destinationCrs(),
                                    self.projeto)
        canvas.setExtent(ct.transformBoundingBox(self._ret).buffered(0))
        canvas.zoomByFactor(1.15)
        canvas.refresh()
        self.status(f"Imagem de {imagens.data_br(c['data'])} adicionada ao projeto (grupo '{GRUPO_IMAGENS}').")
