# -*- coding: utf-8 -*-
"""v3.9.5: lista de camadas de referência do escritório (não entram no cálculo)."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)
from qgis.core import QgsProject, QgsVectorLayer

from .estilo import (
    alertar, botao_principal, botao_secundario, cabecalho, confirmar, icone_tema,
    preparar_dialogo, secao, sucesso,
)
from .catalogo import (
    adicionar_referencia_escritorio, conflito_referencia_catalogo, indice_reconhecimento,
    referencias_escritorio, remover_referencia_escritorio,
)
from .reconhecimento import normalizar_chave


def _palavras(texto):
    return {x for x in normalizar_chave(texto).split("_") if x}


class DialogoReferencias(QDialog):
    """Abre a partir de qualquer tela do plugin; grava no catálogo do escritório."""

    def __init__(self, plugin, parent=None, nome_inicial=""):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin; self.alterou = False
        preparar_dialogo(self, "tela_referencias", "Norte Agro - Camadas de referência", (560, 460)); self.resize(640, 560)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho(
            "Camadas de referência",
            "Nomes que nunca entram no cálculo de áreas (municípios, UC, fitofisionomia, bases externas...). "
            "Valem para todos os usuários e todos os projetos.",
            os.path.join(os.path.dirname(__file__), "icon.png"),
        ))
        raiz.addWidget(secao("Adicionar"))
        linha = QHBoxLayout()
        self.nome = QLineEdit(nome_inicial or ""); self.nome.setPlaceholderText("Ex.: Fitofisionomia, Unidade de Conservação, Uso restrito")
        self.nome.setToolTip("Basta parte do nome: \"Fitofisionomia\" reconhece \"Fitofisionomia florestal 2008\", \"Fitofisionomia savânica\" etc.")
        self.nome.textChanged.connect(self._previa); self.nome.returnPressed.connect(self.adicionar)
        self.btn_add = botao_principal("+ Adicionar", self); self.btn_add.setIcon(icone_tema("/mActionAdd.svg")); self.btn_add.clicked.connect(self.adicionar)
        linha.addWidget(self.nome, 1); linha.addWidget(self.btn_add); raiz.addLayout(linha)
        self.previa = QLabel(); self.previa.setWordWrap(True); self.previa.setProperty("naSubtitle", True); raiz.addWidget(self.previa)
        raiz.addWidget(secao("Lista do escritório"))
        self.lista = QListWidget(); self.lista.itemSelectionChanged.connect(self._estado_botoes); raiz.addWidget(self.lista, 1)
        rod = QHBoxLayout()
        self.btn_rem = botao_secundario("Remover da lista", self); self.btn_rem.setIcon(icone_tema("/mActionRemove.svg")); self.btn_rem.clicked.connect(self.remover)
        rod.addWidget(self.btn_rem); rod.addStretch()
        fechar = botao_secundario("Fechar", self); fechar.clicked.connect(self.accept); rod.addWidget(fechar); raiz.addLayout(rod)
        self._carregar(); self._previa()

    def _carregar(self):
        self.lista.clear()
        for item in sorted(referencias_escritorio(forcar=True), key=lambda x: str(x.get("nome", "")).casefold()):
            texto = item.get("nome", "")
            detalhe = " - ".join(x for x in (item.get("autor", ""), item.get("data", "")) if x)
            it = QListWidgetItem(texto + (f"   ({detalhe})" if detalhe else "")); it.setData(Qt.ItemDataRole.UserRole, texto); self.lista.addItem(it)
        if not self.lista.count():
            it = QListWidgetItem("(nenhum nome cadastrado ainda)"); it.setFlags(Qt.ItemFlag.NoItemFlags); self.lista.addItem(it)
        self._estado_botoes()

    def _estado_botoes(self):
        item = self.lista.currentItem()
        self.btn_rem.setEnabled(bool(item and item.data(Qt.ItemDataRole.UserRole)))

    def camadas_afetadas(self, nome):
        palavras = _palavras(nome)
        if not palavras:
            return []
        saida = []
        for camada in QgsProject.instance().mapLayers().values():
            if not isinstance(camada, QgsVectorLayer) or camada.customProperty("norteagro/arquivo", ""):
                continue
            if palavras <= _palavras(camada.name()):
                saida.append(camada.name())
        return sorted(saida, key=str.casefold)

    def _previa(self):
        nome = self.nome.text().strip()
        if not nome:
            self.previa.setText("Digite um nome ou parte dele. A comparação ignora acentos e maiúsculas."); self.btn_add.setEnabled(False); return
        conflito = conflito_referencia_catalogo(nome)
        if conflito:
            self.previa.setText(f"Nome genérico demais: também faz parte de uma camada do catálogo ({conflito}). Use um nome mais específico.")
            self.btn_add.setEnabled(False); return
        afetadas = self.camadas_afetadas(nome)
        if afetadas:
            mais = f" e mais {len(afetadas) - 6}" if len(afetadas) > 6 else ""
            self.previa.setText("Neste projeto passam a ser referência: " + ", ".join(afetadas[:6]) + mais + ".")
        else:
            self.previa.setText("Nenhuma camada aberta neste projeto tem esse nome; ele valerá para os próximos projetos.")
        self.btn_add.setEnabled(True)

    def adicionar(self):
        nome = self.nome.text().strip()
        if not nome or not self.btn_add.isEnabled():
            return
        try:
            adicionar_referencia_escritorio(nome, indice_reconhecimento(QgsProject.instance()))
        except Exception as exc:
            alertar(self, "Camadas de referência", "Não foi possível adicionar o nome.", [str(exc)]); return
        self.alterou = True; self.nome.clear(); self._carregar()
        sucesso(self, "Camadas de referência", f"\"{nome}\" foi adicionado à lista (guardada dentro do plugin).")

    def remover(self):
        item = self.lista.currentItem()
        nome = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if not nome:
            return
        if not confirmar(self, "Camadas de referência", f"Remover \"{nome}\" da lista do escritório?", "Remover", destrutivo=True):
            return
        try:
            remover_referencia_escritorio(nome)
        except Exception as exc:
            alertar(self, "Camadas de referência", "Não foi possível remover o nome.", [str(exc)]); return
        self.alterou = True; self._carregar()


def abrir_referencias(plugin, parent=None, nome_inicial=""):
    dlg = DialogoReferencias(plugin, parent, nome_inicial)
    dlg.exec()
    return dlg.alterou
