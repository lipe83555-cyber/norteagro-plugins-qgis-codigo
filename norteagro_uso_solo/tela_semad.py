# -*- coding: utf-8 -*-
"""v0.5.0: tela "Camadas da SEMAD (SIGA)".

Toda vez que a tela abre (ou em "Verificar de novo") o plugin consulta o SIGA da SEMAD-GO e atualiza as camadas do
grupo "SEMAD - SIGA" do catálogo: murundus e APP de relevo só com a parte DENTRO do imóvel; Unidades de Conservação
INTEIRAS (as que sobrepõem o imóvel e as que estão perto), com nome e descrição. O que não existe no imóvel não é criado.
As mesmas camadas também podem ser criadas uma a uma em Criar / gerenciar camadas.
"""
import os

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)
from qgis.core import QgsSettings

from . import semad
from .estilo import botao_principal, botao_secundario, cabecalho, preparar_dialogo, secao

VERDE, CINZA, LARANJA = "#2E7D32", "#6B7280", "#B45309"


def auto_ligado():
    v = QgsSettings().value(semad.CHAVE_CONFIG_AUTO, True)
    return str(v).lower() not in ("false", "0", "no", "")


def verificar_em_silencio(plugin, progresso=None):
    """Usado ao abrir "Criar / gerenciar camadas": consulta e atualiza as camadas da SEMAD sem abrir janela; o resultado
    vai para a barra de mensagens do QGIS. Sem imóvel desenhado não faz nada. Devolve as linhas com dados."""
    resultados, problema = semad.gerar(plugin, None, progresso)
    if problema:
        return []
    tem = [l for r, l in zip(resultados, semad.resumo(resultados)) if r["situacao"] == "tem"]
    erros = [l for r, l in zip(resultados, semad.resumo(resultados)) if r["situacao"] == "erro"]
    try:
        from qgis.core import Qgis
        barra = plugin.iface.messageBar()
        if erros and not tem:
            barra.pushMessage("SEMAD (SIGA)", "Não foi possível consultar o SIGA agora: " + erros[0], Qgis.MessageLevel.Warning, 8)
        elif tem:
            barra.pushMessage("SEMAD (SIGA)", "No imóvel: " + " | ".join(tem), Qgis.MessageLevel.Info, 12)
        else:
            barra.pushMessage("SEMAD (SIGA)", "Nenhuma camada da SEMAD (murundus, APP de relevo, UC) no imóvel.",
                              Qgis.MessageLevel.Info, 6)
    except Exception:
        pass
    return tem


class TelaSemad(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.resultados = []
        preparar_dialogo(self, "tela_semad", "Norte Agro - Camadas da SEMAD (SIGA)", (760, 560))
        self.resize(980, 700)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho(
            "Camadas da SEMAD (SIGA)",
            "Toda vez que esta tela abre, o plugin consulta o SIGA da SEMAD-GO pelo limite da Área Total do Imóvel. "
            "Os murundus vão para a camada Murundus do grupo Uso do Solo (criada sozinha quando o imóvel tem murundus; "
            "desenho feito à mão nela não é substituído). APP de relevo (declividade, borda de chapada, topo de morro) "
            "fica só com a parte DENTRO do imóvel, no grupo \"SEMAD - SIGA\". Unidades de Conservação vêm INTEIRAS - "
            "as que sobrepõem o imóvel e as que estão perto - com nome e descrição. O que não existe no imóvel não é criado.",
            os.path.join(os.path.dirname(__file__), "icon.png")))
        self.info = QLabel(); self.info.setWordWrap(True); self.info.setProperty("naSubtitle", True)
        raiz.addWidget(self.info)
        self.gerar_imovel = botao_secundario("Gerar a Área Total do Imóvel", self)
        self.gerar_imovel.clicked.connect(self._gerar_imovel); self.gerar_imovel.setVisible(False)
        linha_im = QHBoxLayout(); linha_im.addWidget(self.gerar_imovel); linha_im.addStretch(1); raiz.addLayout(linha_im)

        raiz.addWidget(secao("Camadas"))
        self.automaticas = [semad.config_camada(a) for a in semad.AUTOMATICAS]
        self.tabela = QTableWidget(len(self.automaticas), 3)
        self.tabela.setHorizontalHeaderLabels(["Camada", "Como entra", "No imóvel"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        cab = self.tabela.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i, c in enumerate(self.automaticas):
            nome = semad.nome_camada(plugin, c["arquivo"])
            if c.get("uso_do_solo"):
                nome += " (grupo Uso do Solo)"
            it = QTableWidgetItem(nome); it.setToolTip(semad.EXPLICACAO[c["arquivo"]])
            self.tabela.setItem(i, 0, it)
            self.tabela.setItem(i, 1, QTableWidgetItem("só a parte dentro do imóvel" if c["recortar"]
                                                       else "inteiras (no imóvel e perto)"))
            self.tabela.setItem(i, 2, QTableWidgetItem("-"))
        raiz.addWidget(self.tabela, 2)

        raiz.addWidget(secao("Unidades de Conservação encontradas"))
        self.ucs = QTableWidget(0, 5)
        self.ucs.setHorizontalHeaderLabels(["Nome", "Sobrepõe o imóvel", "Dentro do imóvel (ha)", "Distância (km)", "Descrição"])
        self.ucs.verticalHeader().setVisible(False)
        self.ucs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        cab = self.ucs.horizontalHeader()
        for col in range(4):
            cab.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        raiz.addWidget(self.ucs, 2)

        self.progresso = QProgressBar(); self.progresso.setVisible(False); raiz.addWidget(self.progresso)
        opc = QHBoxLayout()
        opc.addWidget(QLabel("Unidades de Conservação perto do imóvel: até"))
        self.raio = QDoubleSpinBox(); self.raio.setRange(0, 200); self.raio.setDecimals(0); self.raio.setSuffix(" km")
        self.raio.setValue(semad.raio_uc_km()); self.raio.setToolTip("0 km = só as que sobrepõem o imóvel")
        self.raio.valueChanged.connect(lambda v: semad.definir_raio_uc_km(v))
        opc.addWidget(self.raio); opc.addSpacing(18)
        self.auto = QCheckBox("Verificar sozinho sempre que abrir \"Criar / gerenciar camadas\"")
        self.auto.setChecked(auto_ligado())
        self.auto.toggled.connect(lambda v: QgsSettings().setValue(semad.CHAVE_CONFIG_AUTO, bool(v)))
        opc.addWidget(self.auto); opc.addStretch(1)
        raiz.addLayout(opc)
        nota = QLabel("Fonte: GeoServer do SIGA (siga.meioambiente.go.gov.br). APP de relevo e UC ficam no grupo "
                      f"\"{semad.GRUPO}\" e na pasta shapefiles do mapa; são referência e não entram no cálculo de áreas. "
                      "Os murundus ficam na camada Murundus do Uso do Solo e entram no Quadro de Áreas. "
                      "Passe o mouse sobre uma UC no mapa (Dicas de mapa) para ver a descrição.")
        nota.setWordWrap(True); nota.setProperty("naSubtitle", True); raiz.addWidget(nota)

        rod = QHBoxLayout(); rod.addStretch(1)
        fechar = botao_secundario("Fechar", self); fechar.clicked.connect(self.accept)
        self.botao = botao_principal("Verificar de novo", self); self.botao.clicked.connect(self.verificar)
        rod.addWidget(fechar); rod.addWidget(self.botao); raiz.addLayout(rod)
        QTimer.singleShot(150, self.verificar)  # "toda vez": a consulta começa ao abrir

    def _linha(self, i, texto, cor):
        it = QTableWidgetItem(texto); it.setForeground(QBrush(QColor(cor))); it.setToolTip(texto)
        self.tabela.setItem(i, 2, it)

    def _gerar_imovel(self):
        ok, acao, erro = self.plugin.criar_ou_carregar("AREA_DO_IMOVEL")
        if not ok:
            self.info.setText("Não foi possível criar a Área Total do Imóvel: " + str(erro))
            return
        camada = self.plugin.camada_plugin("AREA_DO_IMOVEL")
        try:
            if camada is not None:
                self.plugin.iface.setActiveLayer(camada)
        except Exception:
            pass
        self.info.setText("Área Total do Imóvel " + ("criada" if acao == "criada" else "carregada") + ". Desenhe (ou "
                          "cole) o limite do imóvel, salve a edição e clique em \"Verificar de novo\".")
        self.gerar_imovel.setVisible(False)

    def _mostrar_ucs(self):
        self.ucs.setRowCount(0)
        res = next((r for r in self.resultados if r["arquivo"] == "SEMAD_UC"), None)
        if not res or not res["feicoes"]:
            return
        for _, a in res["feicoes"]:
            i = self.ucs.rowCount(); self.ucs.insertRow(i)
            valores = [a["nome"], a["sobrepoe"], f"{a['dentro_ha']:.4f}".replace(".", ","),
                       f"{a['dist_km']:.2f}".replace(".", ","), a["descricao"]]
            for col, v in enumerate(valores):
                it = QTableWidgetItem(str(v)); it.setToolTip(str(v))
                if a["sobrepoe"] == "Sim":
                    it.setForeground(QBrush(QColor(VERDE)))
                self.ucs.setItem(i, col, it)

    def verificar(self):
        pasta, _ = self.plugin.memoria_basica()
        self.gerar_imovel.setVisible(False)
        problema = semad.problema_imovel(self.plugin)
        if problema:
            self.info.setText(semad.texto_problema_imovel(problema))
            self.gerar_imovel.setVisible(problema == "sem_imovel")
            for i in range(len(self.automaticas)):
                self._linha(i, "-", CINZA)
            self.ucs.setRowCount(0)
            return
        base_info = (("Pasta do mapa: " + pasta) if pasta and os.path.isdir(pasta) else
                     "Sem pasta do mapa: as camadas ficam temporárias (somem ao fechar o projeto).")
        self.info.setText(base_info)
        self.botao.setEnabled(False); self.progresso.setVisible(True); self.progresso.setRange(0, len(self.automaticas))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        for i in range(len(self.automaticas)):
            self._linha(i, "aguardando...", CINZA)

        def andamento(i, total, texto):
            self.progresso.setValue(i); self.progresso.setFormat(texto)
            if i < total:
                self._linha(i, "consultando o SIGA...", CINZA)
            QApplication.processEvents()
        try:
            self.resultados, problema = semad.gerar(self.plugin, None, andamento)
        finally:
            QApplication.restoreOverrideCursor(); self.progresso.setVisible(False); self.botao.setEnabled(True)
        if problema:
            self.info.setText(semad.texto_problema_imovel(problema)); return
        for i, res in enumerate(self.resultados):
            cor = VERDE if res["situacao"] == "tem" else (LARANJA if res["situacao"] == "erro" else CINZA)
            self._linha(i, semad.linha_resultado(res), cor)
        self._mostrar_ucs()
        tem = sum(1 for r in self.resultados if r["situacao"] == "tem")
        falhas = sum(1 for r in self.resultados if r["situacao"] == "erro")
        imovel = self.resultados[0].get("imovel", "") if self.resultados else ""
        self.info.setText(f"Imóvel: {imovel}   ·   Resultado: {tem} camada(s) com dados"
                          + (f", {falhas} sem resposta do SIGA (tente de novo)" if falhas else "")
                          + "   ·   " + base_info)
        try:
            self.plugin.iface.mapCanvas().refresh()
        except Exception:
            pass
