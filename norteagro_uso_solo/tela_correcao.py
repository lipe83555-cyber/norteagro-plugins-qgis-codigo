# -*- coding: utf-8 -*-
"""v0.3.0: tela "Conferir e corrigir camadas", aberta pelo Calcular áreas antes do cálculo.

Mostra o que o plugin vai corrigir sozinho e pergunta, em cada sobreposição larga (conflito de classificação),
qual camada cede a área - como a ferramenta de sobreposição do Bússola SIGCAR.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QSizePolicy, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)
from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject

from .correcao import _texto_area
from .estilo import botao_principal, botao_secundario, cabecalho, preparar_dialogo, secao

COR_GRAVE = "#B45309"
COR_INFO = "#6B7280"


def _sub(texto):
    lb = QLabel(texto); lb.setWordWrap(True); lb.setProperty("naSubtitle", True)
    lb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    return lb


class TelaCorrecao(QDialog):
    def __init__(self, plugin, correcao, relatorio, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin; self.correcao = correcao; self.relatorio = relatorio; self.decisao = None
        self._combos = {}; self._geoms_lista = []
        preparar_dialogo(self, "tela_correcao", "Norte Agro - Conferir e corrigir camadas", (760, 520))
        self.resize(1040, 720)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho(
            "Conferir e corrigir camadas",
            "Antes de calcular, o plugin conferiu o desenho. Corrigindo, as camadas ficam certas e o Quadro de Áreas "
            "bate exatamente com o que está desenhado.", os.path.join(os.path.dirname(__file__), "icon.png")))

        probs = relatorio.get("problemas", []); confl = relatorio.get("conflitos", [])
        n_auto = sum(1 for p in probs if p["acao"] == "auto")
        n_info = sum(1 for p in probs if p["acao"] == "info")
        n_grave = sum(1 for p in probs if p.get("grave"))
        partes = [f"{n_auto} correção(ões) automática(s)"]
        if confl:
            partes.append(f"{len(confl)} decisão(ões) técnica(s) para você")
        if n_info:
            partes.append(f"{n_info} aviso(s)")
        resumo = QLabel(" · ".join(partes) + (f"  —  {n_grave} item(ns) em laranja merecem um olhar antes" if n_grave else ""))
        f = resumo.font(); f.setBold(True); resumo.setFont(f); raiz.addWidget(resumo)

        if confl:
            raiz.addWidget(secao("Decisões técnicas"))
            raiz.addWidget(_sub(
                "O plugin não decide sozinho o que depende de avaliação técnica. Sobreposição larga (a mesma terra "
                "desenhada como duas coisas): escolha a camada que vai PERDER o pedaço. Recorte grande no limite: escolha "
                "se recorta ou se deixa como está (às vezes quem está errado é o limite). A sugestão segue as regras do "
                "cálculo."))
            self.tabela = QTableWidget(len(confl), 5)
            self.tabela.setHorizontalHeaderLabels(["Quadro", "Situação", "Área", "Decisão", ""])
            self.tabela.verticalHeader().setVisible(False)
            cab = self.tabela.horizontalHeader()
            cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents); cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            cab.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents); cab.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            cab.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            for i, k in enumerate(confl):
                self.tabela.setItem(i, 0, QTableWidgetItem(k["quadro"]))
                if k.get("opcoes"):
                    texto = k.get("descricao", "")
                    opcoes = list(k["opcoes"])
                else:
                    texto = f"Sobreposição: {k['nome_a']}  ×  {k['nome_b']}  ({k['pecas']} mancha(s))"
                    outro = k["a"] if k["sugestao"] == k["b"] else k["b"]
                    nomes = {k["a"]: k["nome_a"], k["b"]: k["nome_b"]}
                    opcoes = [(arq, "Tirar de " + nomes[arq]) for arq in (k["sugestao"], outro)]
                it_txt = QTableWidgetItem(texto); it_txt.setToolTip(texto); self.tabela.setItem(i, 1, it_txt)
                self.tabela.setItem(i, 2, QTableWidgetItem(_texto_area(k["area_m2"]) if k.get("area_m2") else "-"))
                cb = QComboBox()
                opcoes.sort(key=lambda o: o[0] != k["sugestao"])
                for valor, rotulo in opcoes:
                    cb.addItem(rotulo + ("  (sugerido)" if valor == k["sugestao"] else ""), valor)
                i_cede = cb.findData(k.get("cede") or k["sugestao"])
                cb.setCurrentIndex(max(0, i_cede))
                self.tabela.setCellWidget(i, 3, cb); self._combos[k["id"]] = cb
                ver = botao_secundario("Ver no mapa", self); ver.clicked.connect(lambda _c=False, g=k["geom"]: self._zoom(g))
                ver.setEnabled(k.get("geom") is not None)
                self.tabela.setCellWidget(i, 4, ver)
            self.tabela.setMaximumHeight(min(60 + 34 * len(confl), 240)); raiz.addWidget(self.tabela)

        raiz.addWidget(secao("O que será corrigido"))
        self.lista = QTreeWidget(); self.lista.setColumnCount(4)
        self.lista.setHeaderLabels(["Camada", "Problema", "Tamanho", "O que acontece"])
        self.lista.setRootIsDecorated(False); self.lista.setAlternatingRowColors(True)
        cab = self.lista.header(); cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); cab.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        acoes = {"auto": "corrige sozinho", "escolha": "conforme a decisão acima", "info": "só aviso (corrija à mão)"}
        ordem = {"escolha": 0, "auto": 1, "info": 2}
        for p in sorted(probs, key=lambda x: (not x.get("grave"), ordem.get(x["acao"], 3))):
            tam = []
            if p.get("area_m2"):
                tam.append(_texto_area(p["area_m2"]))
            texto = p["titulo"] + (f" — {p['detalhe']}" if p.get("detalhe") else "")
            it = QTreeWidgetItem([p.get("camada") or "-", texto, " ".join(tam), acoes.get(p["acao"], p["acao"])])
            it.setToolTip(1, texto)
            it.setData(0, Qt.ItemDataRole.UserRole, len(self._geoms_lista)); self._geoms_lista.append(p.get("geom"))
            if p.get("grave"):
                for c in range(4): it.setForeground(c, QBrush(QColor(COR_GRAVE)))
            elif p["acao"] == "info":
                for c in range(4): it.setForeground(c, QBrush(QColor(COR_INFO)))
            self.lista.addTopLevelItem(it)
        self.lista.itemDoubleClicked.connect(lambda it, _c: self._zoom(self._geoms_lista[int(it.data(0, Qt.ItemDataRole.UserRole))]))
        raiz.addWidget(self.lista, 1)
        raiz.addWidget(_sub(
            "Dois cliques numa linha mostram o lugar no mapa. Antes de alterar, o plugin guarda uma cópia de cada camada "
            "na pasta _backup ao lado dela. A hidrografia pode passar do limite do imóvel; todas as outras camadas são "
            "recortadas no limite."))

        rod = QHBoxLayout(); rod.addStretch()
        cancelar = botao_secundario("Cancelar", self); cancelar.clicked.connect(self.reject)
        sem = botao_secundario("Calcular sem corrigir", self); sem.clicked.connect(lambda: self._fim("sem"))
        sem.setToolTip("Calcula como antes: as camadas não são alteradas e o quadro desconsidera os problemas em memória.")
        corrigir = botao_principal("Corrigir as camadas e calcular", self); corrigir.clicked.connect(lambda: self._fim("corrigir"))
        corrigir.setEnabled(bool(relatorio.get("corrigir")))
        for b in (cancelar, sem, corrigir): rod.addWidget(b)
        raiz.addLayout(rod)

    def topico_ajuda(self):
        return "correcao"

    def _fim(self, decisao):
        self.decisao = decisao; self.accept()

    def escolhas(self):
        return {ident: cb.currentData() for ident, cb in self._combos.items()}

    def _zoom(self, geom):
        if geom is None:
            return
        try:
            canvas = self.plugin.iface.mapCanvas()
            g = QgsGeometry(geom)
            destino = canvas.mapSettings().destinationCrs()
            if destino != self.correcao.alvo:
                g.transform(QgsCoordinateTransform(self.correcao.alvo, destino, QgsProject.instance().transformContext()))
            caixa = g.boundingBox()
            caixa.grow(max(caixa.width(), caixa.height(), 20.0) * 0.6)
            canvas.setExtent(caixa); canvas.refresh()
            canvas.flashGeometries([g], destino)
        except Exception as exc:
            self.plugin.log(f"Zoom da correção: {exc}")
