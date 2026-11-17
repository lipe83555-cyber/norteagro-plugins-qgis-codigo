# -*- coding: utf-8 -*-
"""Tela de escolha do fluxo principal do plugin."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .estilo import (
    botao_secundario, cabecalho, cartao_fluxo, configurar_caminho,
    icone_tema, preparar_dialogo,
)


class TelaEscolha(QDialog):
    """Não cria nem grava nada; apenas informa qual fluxo o usuário escolheu."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin
        self.modo = ""
        preparar_dialogo(self, "tela_escolha", "Norte Agro - Uso do Solo", (520, 500))
        self.resize(600, 580)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)
        raiz.setSpacing(12)
        raiz.addWidget(cabecalho(
            "Norte Agro - Uso do Solo",
            "Escolha o fluxo que deseja usar neste projeto.",
            os.path.join(os.path.dirname(__file__), "icon.png"),
        ))

        self.gerenciar = cartao_fluxo(
            "Criar / gerenciar camadas",
            "Cria a pasta do mapa e as camadas padrão.",
            icone_tema("/mActionAddLayer.svg", "/mIconVector.svg"), self,
        )
        self.gerenciar.clicked.connect(lambda: self._escolher("gerenciar"))
        self.gerenciar.setToolTip("Abrir a estrutura de uso do solo e gerenciar as camadas do mapa.")
        raiz.addWidget(self.gerenciar)

        self.avulsa = cartao_fluxo(
            "Criar camadas em uma pasta",
            "Escolha as camadas do catálogo e a pasta onde salvar.",
            icone_tema("/mActionNewVectorLayer.svg", "/mActionFileNew.svg"), self,
        )
        self.avulsa.clicked.connect(lambda: self._escolher("avulsa"))
        self.avulsa.setToolTip("Criar camadas do catálogo em uma pasta sem alterar a Pasta atual do projeto.")
        raiz.addWidget(self.avulsa)

        self.areas = cartao_fluxo(
            "Só calcular áreas",
            "Calcula as áreas das camadas abertas e gera a planilha, sem criar pastas.",
            icone_tema("/mActionCalculateField.svg", "/mActionSum.svg"), self,
        )
        self.areas.clicked.connect(lambda: self._escolher("areas"))
        self.areas.setToolTip("Abrir somente o cálculo de áreas usando as camadas já carregadas.")
        raiz.addWidget(self.areas)

        # v0.5.0: camadas da SEMAD (SIGA)
        self.semad = cartao_fluxo(
            "Camadas da SEMAD (SIGA)",
            "Murundus, APP de relevo e UC que existem no imóvel.",
            icone_tema("/mActionAddWfsLayer.svg", "/mActionAddOgrLayer.svg"), self,
        )
        self.semad.clicked.connect(lambda: self._escolher("semad"))
        self.semad.setToolTip("Consulta o SIGA da SEMAD-GO e coloca no mapa só o que existe no imóvel.")
        raiz.addWidget(self.semad)
        raiz.addStretch(1)

        rodape = QHBoxLayout()
        pasta, _ = plugin.memoria_basica()
        self.pasta_atual = QLabel("Pasta atual: não configurada")
        self.pasta_atual.setProperty("naSubtitle", True)
        self.pasta_atual.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if pasta and os.path.isdir(pasta):
            configurar_caminho(self.pasta_atual, f"Pasta atual: {pasta}", 80)
            self.pasta_atual.setToolTip(pasta)
        raiz.addWidget(self.pasta_atual)  # v3.9.12: linha própria, para o caminho não ser cortado pelos botões
        rodape.addStretch(1)
        referencias = botao_secundario("+ Referências", self)
        referencias.setIcon(icone_tema("/mActionAdd.svg"))
        referencias.setToolTip("Cadastrar nomes de camadas de referência (não entram no cálculo) para todo o escritório.")
        referencias.clicked.connect(self._referencias)
        rodape.addWidget(referencias)
        modelos_b = botao_secundario("Modelos", self)
        modelos_b.setIcon(icone_tema("/mActionOptions.svg", "/mActionPropertiesWidget.svg"))
        modelos_b.setToolTip("Modelos do escritório: estrutura de pastas com camadas, temas de cores e estilo da tabela.")
        modelos_b.clicked.connect(lambda: self.plugin.abrir_modelos(self))
        rodape.addWidget(modelos_b)
        ajuda_b = botao_secundario("? Ajuda", self)
        ajuda_b.setToolTip("Tutorial completo: como usar cada parte do plugin, com os vídeos de cada assunto.")
        ajuda_b.clicked.connect(lambda: __import__("norteagro_uso_solo.tela_ajuda", fromlist=["abrir_ajuda"]).abrir_ajuda(self, "comecar"))
        rodape.addWidget(ajuda_b)
        fechar = botao_secundario("Fechar", self)
        fechar.clicked.connect(self.reject)
        fechar.setToolTip("Fechar sem criar ou alterar nada.")
        rodape.addWidget(fechar)
        raiz.addLayout(rodape)

    def _referencias(self):
        from .tela_referencias import abrir_referencias
        abrir_referencias(self.plugin, self)

    def _escolher(self, modo):
        self.modo = modo
        self.accept()
