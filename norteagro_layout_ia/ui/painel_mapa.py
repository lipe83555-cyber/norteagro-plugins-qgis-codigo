# -*- coding: utf-8 -*-
"""Painel de configuração de um mapa (Fase 1): camadas, SRC e enquadramento independentes."""

from ..core import compat
from qgis.core import QgsCoordinateReferenceSystem, QgsMapLayer, QgsMapLayerProxyModel, QgsProject
from qgis.gui import QgsMapLayerComboBox, QgsMapToolExtent, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                                 QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import builder

MODOS = [
    ("camada", "Ajustar à camada"),
    ("manual", "Extensão manual (desenhar no mapa)"),
    ("municipio", "Localização - município inteiro"),
    ("estado", "Localização - estado"),
    ("brasil", "Localização - Brasil"),
    ("tema", "Seguir um tema do projeto"),
    ("projeto", "Todas as camadas marcadas"),
]


class PainelMapa(QWidget):
    alterado = pyqtSignal()

    def __init__(self, iface, corr, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.corr = corr
        self.projeto = QgsProject.instance()
        self._extensao_manual = None
        self._ferramenta = None
        self._ferramenta_anterior = None
        self._modos_extra = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.rotulo_papel = QLabel("")
        self.rotulo_papel.setStyleSheet("font-weight: bold")
        lay.addWidget(self.rotulo_papel)

        lay.addWidget(QLabel("Camadas deste mapa (marque as que aparecem):"))
        self.lista = QListWidget()
        self.lista.setMinimumHeight(110)
        self.lista.itemChanged.connect(lambda *_: self.alterado.emit())
        lay.addWidget(self.lista)
        botoes = QHBoxLayout()
        b_sugerir = QPushButton("Sugerir camadas")
        b_sugerir.setToolTip("Marca as camadas visíveis do projeto adequadas ao papel deste mapa.")
        b_sugerir.clicked.connect(self.sugerir)
        b_nenhuma = QPushButton("Desmarcar todas")
        b_nenhuma.clicked.connect(lambda: self._marcar_todas(False))
        botoes.addWidget(b_sugerir)
        botoes.addWidget(b_nenhuma)
        botoes.addStretch()
        lay.addLayout(botoes)

        form = QFormLayout()
        self.crs_modo = QComboBox()
        self.crs_modo.addItem("Automático (SIRGAS 2000 / UTM do fuso do imóvel)", "auto")
        self.crs_modo.addItem("SRC do projeto", "projeto")
        self.crs_modo.addItem("SIRGAS 2000 geográfico (EPSG:4674)", "EPSG:4674")
        self.crs_modo.addItem("Escolher...", "escolher")
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setCrs(self.projeto.crs() if self.projeto.crs().isValid()
                               else QgsCoordinateReferenceSystem("EPSG:31982"))
        self.crs_widget.setEnabled(False)
        self.crs_modo.currentIndexChanged.connect(lambda *_: self.crs_widget.setEnabled(
            self.crs_modo.currentData() == "escolher"))
        form.addRow("SRC:", self.crs_modo)
        form.addRow("", self.crs_widget)

        self.modo = QComboBox()
        for k, rot in MODOS:
            self.modo.addItem(rot, k)
        self.modo.currentIndexChanged.connect(self._modo_mudou)
        form.addRow("Enquadramento:", self.modo)

        self.camada_ext = QgsMapLayerComboBox()
        self.camada_ext.setFilters(compat.FILTRO_VETOR)
        self.camada_ext.setAllowEmptyLayer(True)
        form.addRow("Camada:", self.camada_ext)

        self.margem = QSpinBox()
        self.margem.setRange(0, 200)
        self.margem.setSuffix(" %")
        self.margem.setValue(10)
        form.addRow("Margem:", self.margem)

        self.tema = QComboBox()
        form.addRow("Tema:", self.tema)

        self.camada_mun = QgsMapLayerComboBox()
        self.camada_mun.setFilters(compat.FILTRO_POLIGONO)
        self.camada_mun.setAllowEmptyLayer(True)
        self.camada_mun.setToolTip("Vazio = usa a malha de municípios de Goiás que acompanha o plugin (IBGE).")
        form.addRow("Municípios:", self.camada_mun)

        manual = QHBoxLayout()
        self.b_desenhar = QPushButton("Desenhar no mapa")
        self.b_desenhar.clicked.connect(self.desenhar)
        self.b_canvas = QPushButton("Usar a vista atual")
        self.b_canvas.clicked.connect(self.usar_vista)
        self.info_manual = QLabel("")
        manual.addWidget(self.b_desenhar)
        manual.addWidget(self.b_canvas)
        manual.addWidget(self.info_manual, 1)
        form.addRow("Extensão:", manual)

        self.grade = QCheckBox("Coordenadas na moldura")
        form.addRow("", self.grade)
        lay.addLayout(form)
        self.atualizar_camadas()
        self._modo_mudou()

    # ------------------------------------------------------------ camadas
    def atualizar_camadas(self, marcadas=None):
        marcadas = set(marcadas if marcadas is not None else self.camadas_marcadas())
        self.lista.blockSignals(True)
        self.lista.clear()
        apoio = {c.id() for c in builder._camadas_do_grupo_apoio(self.projeto)}
        for c, _vis in builder.camadas_projeto(self.projeto):
            if c.id() in apoio:
                continue
            nome_leg = self.corr.nome_legenda(c.name()) if self.corr else None
            texto = c.name() + (f"   (legenda: {nome_leg})" if nome_leg and nome_leg != c.name() else "")
            it = QListWidgetItem(texto)
            it.setData(Qt.ItemDataRole.UserRole, c.id())
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c.id() in marcadas else Qt.CheckState.Unchecked)
            self.lista.addItem(it)
        self.lista.blockSignals(False)
        self.tema.clear()
        self.tema.addItem("")
        self.tema.addItems(self.projeto.mapThemeCollection().mapThemes())

    def camadas_marcadas(self):
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.CheckState.Checked]

    def _marcar_todas(self, valor):
        for i in range(self.lista.count()):
            self.lista.item(i).setCheckState(Qt.CheckState.Checked if valor else Qt.CheckState.Unchecked)

    def sugerir(self):
        papel = getattr(self, "_papel", "principal")
        ids = {c.id() for c in builder.camadas_padrao(self.projeto, papel, self.corr)}
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)

    # ------------------------------------------------------------ modos
    def definir_modos_extra(self, extras):
        """extras = [("igual:mapa_esquerdo", "Igual ao mapa esquerdo")]"""
        for k, _ in self._modos_extra:
            idx = self.modo.findData(k)
            if idx >= 0:
                self.modo.removeItem(idx)
        self._modos_extra = list(extras)
        for k, rot in extras:
            self.modo.addItem(rot, k)

    def _modo_mudou(self, *_):
        m = self.modo.currentData() or ""
        self.camada_ext.setEnabled(m == "camada" or m in ("estado", "brasil"))
        self.margem.setEnabled(m not in ("manual", "tema") and not m.startswith("igual:"))
        self.tema.setEnabled(m == "tema")
        self.camada_mun.setEnabled(m == "municipio" or m == "estado")
        for b in (self.b_desenhar, self.b_canvas):
            b.setEnabled(m == "manual")
        self.alterado.emit()

    def usar_vista(self):
        c = self.iface.mapCanvas()
        r = c.extent()
        self._extensao_manual = ([r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()],
                                 c.mapSettings().destinationCrs().authid())
        self.info_manual.setText("vista atual do mapa")
        self.alterado.emit()

    def soltar_ferramenta(self):
        """Tira do mapa a ferramenta de desenhar a extensão (se ainda estiver ativa). Tem de ser chamada antes de a
        janela ser destruída: senão o mapa do QGIS fica apontando para uma ferramenta que não existe mais e o QGIS
        fecha na próxima vez que mexer no mapa (ex.: ao abrir outro projeto)."""
        ferr, self._ferramenta = self._ferramenta, None
        if ferr is None:
            return
        try:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is ferr or canvas.mapTool() == ferr:
                anterior = self._ferramenta_anterior
                if anterior is not None:
                    canvas.setMapTool(anterior)
                else:
                    canvas.unsetMapTool(ferr)
        except (RuntimeError, AttributeError):
            pass
        self._ferramenta_anterior = None

    def desenhar(self):
        canvas = self.iface.mapCanvas()
        self.soltar_ferramenta()
        self._ferramenta_anterior = canvas.mapTool()
        self._ferramenta = QgsMapToolExtent(canvas)
        self._ferramenta.extentChanged.connect(self._extensao_desenhada)
        canvas.setMapTool(self._ferramenta)
        self.info_manual.setText("arraste um retângulo no mapa do QGIS...")
        self.window().showMinimized()

    def _extensao_desenhada(self, r):
        canvas = self.iface.mapCanvas()
        if r is not None and not r.isEmpty():
            self._extensao_manual = ([r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()],
                                     canvas.mapSettings().destinationCrs().authid())
            self.info_manual.setText("extensão desenhada")
        self.soltar_ferramenta()
        self.window().showNormal()
        self.window().raise_()
        self.alterado.emit()

    # ------------------------------------------------------------ cfg
    def carregar(self, cfg, papel="principal", titulo=""):
        self._papel = papel
        self.rotulo_papel.setText(titulo or papel)
        cfg = dict(cfg or {})
        ids = []
        for n in cfg.get("layers") or []:
            c = builder.achar_camada(self.projeto, n, self.corr)
            if c:
                ids.append(c.id())
        if not ids:
            ids = [c.id() for c in builder.camadas_padrao(self.projeto, papel, self.corr)]
        self.atualizar_camadas(ids)
        crs = cfg.get("crs") or ("EPSG:4674" if papel == "localizacao" else "auto")
        idx = self.crs_modo.findData(crs)
        if idx >= 0:
            self.crs_modo.setCurrentIndex(idx)
        elif str(crs).startswith("igual:"):
            self.crs_modo.setCurrentIndex(0)
        else:
            self.crs_modo.setCurrentIndex(self.crs_modo.findData("escolher"))
            self.crs_widget.setCrs(QgsCoordinateReferenceSystem(crs))
        modo = cfg.get("extent_mode") or ("municipio" if papel == "localizacao" else "camada")
        idx = self.modo.findData(modo)
        self.modo.setCurrentIndex(max(0, idx))
        self.margem.setValue(int(round(float(cfg.get("margin", 0.04 if papel == "localizacao" else 0.10)) * 100)))
        cam = builder.achar_camada(self.projeto, cfg.get("extent_layer"), self.corr) or \
            builder.camada_imovel(self.projeto, self.corr)
        self.camada_ext.setLayer(cam)
        mun = builder.achar_camada(self.projeto, (cfg.get("municipio") or {}).get("layer"), self.corr)
        if mun is None:
            mun = next((c for c, _ in builder.camadas_projeto(self.projeto)
                        if builder.papel_camada(c, self.corr) == "municipio"), None)
        self.camada_mun.setLayer(mun)
        if cfg.get("theme"):
            self.tema.setCurrentText(cfg["theme"])
        self.grade.setChecked(bool(cfg.get("grid", papel == "principal")))
        if cfg.get("manual_extent"):
            self._extensao_manual = (cfg["manual_extent"], cfg.get("manual_crs", ""))
            self.info_manual.setText("extensão definida")
        self._modo_mudou()

    def cfg(self):
        modo = self.modo.currentData() or "camada"
        crs_m = self.crs_modo.currentData()
        if crs_m == "projeto":
            crs = self.projeto.crs().authid()
        elif crs_m == "escolher":
            crs = self.crs_widget.crs().authid()
        else:
            crs = crs_m
        cfg = {"layers": self.camadas_marcadas(), "crs": crs, "extent_mode": modo,
               "margin": self.margem.value() / 100.0, "grid": self.grade.isChecked(), "role": self._papel_cfg()}
        cam = self.camada_ext.currentLayer()
        if cam is not None:
            cfg["extent_layer"] = cam.id()
        if modo == "tema" and self.tema.currentText():
            cfg["theme"] = self.tema.currentText()
        mun = self.camada_mun.currentLayer()
        if mun is not None:
            cfg["municipio"] = {"layer": mun.id()}
        if modo == "manual" and self._extensao_manual:
            cfg["manual_extent"], cfg["manual_crs"] = self._extensao_manual
            cfg["_origem_usuario"] = True
        if modo.startswith("igual:") and crs_m == "auto":
            cfg["crs"] = modo
        return cfg

    def _papel_cfg(self):
        return getattr(self, "_papel", "principal")
