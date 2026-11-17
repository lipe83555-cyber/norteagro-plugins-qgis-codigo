# -*- coding: utf-8 -*-
"""Renomeação segura da pasta do mapa, sem manter wrappers de camadas entre ações."""
import gc
import os
import re
import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout
from qgis.core import QgsExpressionContextUtils, QgsProject, QgsVectorLayer, QgsWkbTypes
from .estilo import alertar, botao_principal, botao_secundario, cabecalho, configurar_caminho, preparar_dialogo, secao, sucesso


class DialogoRenomearPasta(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin = plugin
        pasta, _ = plugin.memoria_basica(); self.pasta_antiga = os.path.abspath(pasta)
        preparar_dialogo(self,"renomear_pasta","Norte Agro - Renomear pasta",(480,180)); self.resize(560,220)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16,16,16,16); raiz.setSpacing(12)
        raiz.addWidget(cabecalho("Renomear pasta", "Altere somente o nome da Pasta do Mapa. As fontes das camadas serão reapontadas com segurança."))
        raiz.addWidget(secao("Novo nome")); raiz.addWidget(QLabel("Nome da pasta do mapa:"))
        self.nome = QLineEdit(os.path.basename(self.pasta_antiga)); self.nome.setToolTip("Não use caracteres inválidos do Windows e não termine com ponto."); raiz.addWidget(self.nome)
        self.destino = QLabel(); self.destino.setProperty("naSubtitle", True); raiz.addWidget(self.destino)
        self.nome.textChanged.connect(self.atualizar); botoes = QHBoxLayout(); botoes.addStretch()
        cancelar = botao_secundario("Fechar", self); cancelar.clicked.connect(self.reject); ok = botao_principal("Renomear", self); ok.clicked.connect(self.executar)
        botoes.addWidget(cancelar); botoes.addWidget(ok); raiz.addLayout(botoes); self.atualizar()

    def atualizar(self):
        configurar_caminho(self.destino, os.path.join(os.path.dirname(self.pasta_antiga), self.nome.text().strip()), 70)

    @staticmethod
    def nome_valido(nome):
        nome = nome.strip()
        return bool(nome) and not bool(re.search(r'[\\/:*?"<>|]', nome)) and not nome.endswith(".")

    def executar(self):
        novo_nome = self.nome.text().strip()
        if not self.nome_valido(novo_nome):
            alertar(self, "Nome inválido", 'Não use \\ / : * ? " < > |, não deixe vazio e não termine com ponto.'); return
        nova = os.path.join(os.path.dirname(self.pasta_antiga), novo_nome)
        if os.path.normcase(nova) == os.path.normcase(self.pasta_antiga):
            self.accept(); return
        if os.path.exists(nova):
            alertar(self, "Pasta já existente", "Já existe uma pasta com esse nome."); return
        if renomear_pasta(self.plugin, self.pasta_antiga, nova, self):
            self.pasta_antiga = nova; self.accept()


def _fonte_partes(camada):
    try:
        bruto = str(camada.dataProvider().dataSourceUri() or "") if camada.dataProvider() else str(camada.source() or "")
    except Exception:
        bruto = str(camada.source() or "")
    caminho = bruto.split("|", 1)[0]
    sufixo = bruto[len(caminho):]
    return os.path.abspath(caminho), sufixo


def _dentro(caminho, pasta):
    try:
        a = os.path.normcase(os.path.abspath(caminho)); b = os.path.normcase(os.path.abspath(pasta))
        return os.path.commonpath([a, b]) == b
    except Exception:
        return False


def _soltar_camadas(projeto, dados):
    """Troca temporariamente OGR por memory; resolve a camada pelo id a cada iteração."""
    for dado in dados:
        camada = projeto.mapLayer(dado["layer_id"])
        if camada is None:
            continue
        # v3.9.4: reloadData() faz o QGIS fechar as conexões OGR guardadas em cache.
        # Sem isso o .shp/.dbf continuava aberto ~60 s depois de soltar a camada e o
        # Windows negava a renomeação (WinError 5/32).
        try:
            if camada.providerType() == "ogr" and camada.dataProvider() is not None:
                camada.dataProvider().reloadData()
        except Exception:
            pass
        uri = QgsWkbTypes.displayString(camada.wkbType())
        auth = camada.crs().authid()
        if auth:
            uri += "?crs=" + auth
        camada.setDataSource(uri, dado["nome"], "memory", False)
        if not camada.isValid():
            raise RuntimeError(f"Não foi possível liberar a camada {dado['nome']}.")
    QApplication.processEvents(); gc.collect()


def _reapontar(projeto, dados, pasta_base):
    for dado in dados:
        camada = projeto.mapLayer(dado["layer_id"])
        if camada is None:
            continue
        fonte = os.path.join(pasta_base, dado["relativo"]) + dado["sufixo"]
        camada.setDataSource(fonte, dado["nome"], dado["provider"], False)
        if not camada.isValid():
            raise RuntimeError(f"A camada {dado['nome']} não pôde ser reapontada para {fonte}.")
        if dado["renderer"]:
            camada.setRenderer(dado["renderer"].clone())
        # Se uma avulsa estava dentro da pasta renomeada, atualiza somente a raiz KML gravada nela.
        kml_dir = dado.get("kml_dir", "")
        if kml_dir and _dentro(kml_dir, dado["pasta_antiga"]):
            novo_kml = os.path.join(pasta_base, os.path.relpath(kml_dir, dado["pasta_antiga"]))
            camada.setCustomProperty("norteagro/kml_dir", os.path.abspath(novo_kml))
        camada.triggerRepaint()


def _renomear_com_espera(antiga, nova, limite_s=20.0):
    """Tenta renomear por alguns segundos: Google Drive, antivírus ou o QGIS podem
    segurar um arquivo por instantes logo após as camadas serem soltas."""
    inicio = time.time(); ultimo = None
    while True:
        try:
            os.rename(antiga, nova)
            return
        except OSError as exc:
            ultimo = exc
            if time.time() - inicio >= limite_s:
                raise ultimo
            QApplication.processEvents(); gc.collect(); time.sleep(0.5)


def renomear_pasta(plugin, antiga, nova, parent=None):
    """Renomeia a pasta do mapa; avulsas externas saem do projeto, mas seus arquivos ficam intactos."""
    projeto = QgsProject.instance(); parent = parent or plugin.iface.mainWindow()
    if not plugin.garantir_projeto_salvo(parent):
        alertar(parent, "Projeto não salvo", "Salve o projeto antes de renomear a pasta."); return False

    dados = []; avulsas_externas = []
    for camada in list(projeto.mapLayers().values()):
        if not isinstance(camada, QgsVectorLayer):
            continue
        caminho, sufixo = _fonte_partes(camada)
        if not _dentro(caminho, antiga):
            if str(camada.customProperty("norteagro/avulsa", "") or "") == "1":
                avulsas_externas.append(camada.id())
            continue
        if camada.isEditable() and camada.isModified():
            alertar(parent, "Edições não salvas", f"A camada {camada.name()} possui edições não salvas. Salve ou reverta as edições antes de renomear a pasta.")
            return False
        if camada.isEditable():
            camada.rollBack()
        dados.append({
            "layer_id": camada.id(), "nome": camada.name(), "provider": camada.providerType(),
            "relativo": os.path.relpath(caminho, antiga), "sufixo": sufixo,
            "renderer": camada.renderer().clone() if camada.renderer() else None,
            "kml_dir": str(camada.customProperty("norteagro/kml_dir", "") or ""),
            "pasta_antiga": antiga,
        })

    arquivo_projeto = os.path.abspath(projeto.fileName()) if projeto.fileName() else ""
    qgz_rel = os.path.relpath(arquivo_projeto, antiga) if arquivo_projeto and _dentro(arquivo_projeto, antiga) else ""
    plugin.kml.desconectar_todos(); renomeou = False
    try:
        # Regra das avulsas externas: saem do projeto, mas nada é movido/apagado fora da pasta do mapa.
        for layer_id in avulsas_externas:
            if projeto.mapLayer(layer_id) is not None:
                projeto.removeMapLayer(layer_id)
        QApplication.processEvents()
        try:
            plugin.iface.mapCanvas().stopRendering()
        except Exception:
            pass
        _soltar_camadas(projeto, dados)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            _renomear_com_espera(antiga, nova)
        finally:
            QApplication.restoreOverrideCursor()
        renomeou = True
        _reapontar(projeto, dados, nova)
        QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_pasta", os.path.abspath(nova)); projeto.setDirty(True)
        if qgz_rel:
            novo_qgz = os.path.join(nova, qgz_rel)
            if not projeto.write(novo_qgz):
                raise RuntimeError("A pasta foi renomeada, mas o projeto .qgz não pôde ser salvo no novo caminho.")
        elif projeto.fileName() and not projeto.write():
            raise RuntimeError("A pasta foi renomeada, mas o projeto QGIS não pôde ser salvo.")
        plugin.kml.reconectar()
        sucesso(parent, "Pasta renomeada", "A pasta foi renomeada com sucesso.", [nova])
        return True
    except Exception as exc:
        plugin.log(f"Falha ao renomear pasta: {exc}")
        try:
            if renomeou and os.path.isdir(nova):
                try:
                    _soltar_camadas(projeto, dados)
                except Exception:
                    pass
                _renomear_com_espera(nova, antiga)
            _reapontar(projeto, dados, antiga)
            QgsExpressionContextUtils.setProjectVariable(projeto, "norteagro_pasta", os.path.abspath(antiga)); projeto.setDirty(True)
            if qgz_rel and os.path.isfile(os.path.join(antiga, qgz_rel)):
                projeto.write(os.path.join(antiga, qgz_rel))
        except Exception as restaurar:
            plugin.log(f"Falha adicional ao restaurar após renomeação: {restaurar}")
        plugin.kml.reconectar()
        alertar(
            parent, "Não foi possível renomear a pasta",
            "As camadas foram reapontadas para o caminho antigo sempre que possível. Feche o Google Drive ou outros programas que estejam usando essa pasta e tente novamente.",
            [f"Erro: {exc}"]
        )
        return False
