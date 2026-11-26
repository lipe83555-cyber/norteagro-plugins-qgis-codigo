# -*- coding: utf-8 -*-
"""Ponto de entrada do plugin no QGIS."""

import os

from qgis.PyQt.QtGui import QIcon
from .core.compat import QAction

from .core import log

# grupo de menu compartilhado com o plugin "Criar camadas e calcular áreas" (norteagro_uso_solo)
MENU = "&Norte Agro Projetos"


class NorteAgroLayoutIA:
    def __init__(self, iface):
        self.iface = iface
        self.acao = None
        self.dialogo = None

    def initGui(self):  # noqa: N802
        try:  # cadastra o repositório da Norte Agro no QGIS (aviso de atualização e instalação pelo nome)
            from .repositorio_norteagro import avisar_se_precisa_acesso, registrar_repositorio
            registrar_repositorio()
            avisar_se_precisa_acesso(self.iface)
        except Exception:
            pass
        try:  # v0.32.7: tira o responsável técnico e a assinatura que vinham de fábrica nas versões antigas
            from .core import config
            if config.limpar_rt_antigo():
                self.iface.messageBar().pushInfo(
                    "Layout de plantas", "O responsável técnico e a assinatura que vinham de fábrica foram retirados. "
                    "Preencha os seus em Configurações.")
        except Exception as e:  # nunca impede o plugin de carregar
            log.aviso(f"Limpeza do responsável técnico antigo não concluída: {e}")
        try:  # vídeos da Ajuda que vieram na atualização: baixa em segundo plano os que faltam
            from .ui.videos_ajuda import iniciar_sincronizacao
            iniciar_sincronizacao()
        except Exception:
            pass
        icone = QIcon(os.path.join(os.path.dirname(__file__), "assets", "icon.png"))
        self.acao = QAction(icone, "Layout de plantas", self.iface.mainWindow())
        self.acao.setToolTip("Norte Agro Projetos: layout de plantas (Uso do Solo e Passivos)")
        self.acao.setObjectName("norteagro_layout_ia")
        self.acao.triggered.connect(self.abrir)
        self.iface.addPluginToMenu(MENU, self.acao)
        self.iface.addToolBarIcon(self.acao)
        # processos de leitura de imagem que versões antigas deixavam abertos (em segundo plano)
        import threading
        from .core import gdal_processo
        threading.Thread(target=gdal_processo.limpar_orfaos, daemon=True).start()

    def unload(self):
        try:
            from .ui.videos_ajuda import parar_sincronizacao
            parar_sincronizacao()
        except Exception:
            pass
        if self.dialogo is not None:
            for t in (getattr(self.dialogo, "tarefa", None), getattr(self.dialogo, "_tarefa_download", None),
                      getattr(self.dialogo, "_tarefa_imagens", None), getattr(self.dialogo, "_tarefa_ia", None),
                      getattr(getattr(self.dialogo, "painel_passivos", None), "tarefa", None),
                      getattr(getattr(self.dialogo, "pagina_imagem", None), "tarefa", None)):
                try:
                    if t is not None:
                        t.cancel()
                except RuntimeError:
                    pass
        if self.acao:
            self.iface.removePluginMenu(MENU, self.acao)
            self.iface.removeToolBarIcon(self.acao)
        if self.dialogo:
            self.dialogo.close()
            self.dialogo.deleteLater()
            self.dialogo = None

    def reiniciar(self):
        """'Limpar tudo': troca a janela por uma nova, como se o plugin tivesse acabado de abrir."""
        antiga = self.dialogo
        geometria = antiga.saveGeometry() if antiga is not None else None
        self.dialogo = None
        if antiga is not None:
            try:
                antiga.cancelar_tarefas()  # tarefa terminando depois avisaria uma janela que não existe mais
            except (AttributeError, RuntimeError):
                pass
            antiga.close()  # closeEvent solta a ferramenta de desenhar do mapa
            antiga.deleteLater()
        self.abrir()
        if geometria is not None and self.dialogo is not None:
            self.dialogo.restoreGeometry(geometria)
            self.dialogo.status.setText("Tudo limpo. Pronto para uma nova planta.")

    def abrir(self):
        try:
            if self.dialogo is None:
                from .ui.dialog import DialogoPrincipal
                self.dialogo = DialogoPrincipal(self.iface)
                self.dialogo.ao_reiniciar = self.reiniciar
            self.dialogo.show()
            self.dialogo.raise_()
            self.dialogo.activateWindow()
        except Exception as e:  # mostra o erro em português e registra o detalhe
            import traceback
            log.erro(traceback.format_exc())
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self.iface.mainWindow(), "NorteAgro Layout",
                                 f"Não foi possível abrir o plugin: {e}\n\nDetalhes no painel de log, aba "
                                 f"'NorteAgro Layout'.")
