# -*- coding: utf-8 -*-
"""Tarefas em segundo plano (QgsTask): busca de imagens e funções demoradas.

A interface continua respondendo; o botão Cancelar chama task.cancel(), que é verificado
pelo transporte de rede (QgsFeedback) e entre as etapas da análise.
"""

import threading
import traceback

from qgis.core import QgsApplication, QgsFeedback, QgsTask
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core import imagens, log


class Sinais(QObject):
    progresso = pyqtSignal(str)
    terminou = pyqtSignal(object)
    falhou = pyqtSignal(str, object)


class TarefaImagens(QgsTask):
    """Busca as imagens de satélite (antiga e recente) do imóvel em segundo plano."""

    def __init__(self, retangulo, ano_antiga, ano_recente, tipos=("antiga", "recente")):
        super().__init__("NorteAgro: busca de imagens de satélite", QgsTask.Flag.CanCancel)
        self.ret, self.ano_antiga, self.ano_recente, self.tipos = retangulo, ano_antiga, ano_recente, tipos
        self.feedback = QgsFeedback()
        self.sinais = Sinais()
        self.resultado = None
        self.erro = None
        self._trava = threading.Lock()
        self._andamento = ("Iniciando a busca...", 0.0)

    def run(self):
        try:
            self.resultado = imagens.buscar(self.ret, self.ano_antiga, self.ano_recente, self.feedback,
                                            progresso=self._progresso, tipos=self.tipos)
            return True
        except imagens.Cancelado:
            self.erro = "Busca de imagens cancelada."
        except Exception as e:
            self.erro = f"Erro na busca de imagens: {e}"
            log.erro(traceback.format_exc())
        return False

    def _progresso(self, texto, frac=None):
        """Chamado pelas linhas paralelas da busca: só anota o andamento (nada de Qt aqui).
        A tela lê com andamento() pelo próprio relógio, na linha principal."""
        with self._trava:
            t, f = self._andamento
            self._andamento = (texto or t, f if frac is None else max(f, float(frac)))

    def andamento(self):
        with self._trava:
            return self._andamento

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def finished(self, ok):
        if ok and self.resultado is not None:
            self.sinais.terminou.emit(self.resultado)
        else:
            self.sinais.falhou.emit(self.erro or "Busca interrompida.", None)


class TarefaFuncao(QgsTask):
    """Roda funcao(feedback, progresso) em segundo plano; progresso(texto, fração 0-1)."""

    def __init__(self, titulo, funcao):
        super().__init__(titulo, QgsTask.Flag.CanCancel)
        self.funcao = funcao
        self.feedback = QgsFeedback()
        self.sinais = Sinais()
        self.resultado = None
        self.erro = None
        self._trava = threading.Lock()
        self._andamento = ("Iniciando a busca...", 0.0)

    def _progresso(self, texto, frac=None):
        """Chamado pelas linhas paralelas da busca: só anota o andamento (nada de Qt aqui).
        A tela lê com andamento() pelo próprio relógio, na linha principal."""
        with self._trava:
            t, f = self._andamento
            self._andamento = (texto or t, f if frac is None else max(f, float(frac)))

    def andamento(self):
        with self._trava:
            return self._andamento

    def run(self):
        try:
            self.resultado = self.funcao(self.feedback, self._progresso)
            return True
        except imagens.Cancelado:
            self.erro = "Busca cancelada."
        except Exception as e:
            self.erro = f"Erro na busca: {e}"
            log.erro(traceback.format_exc())
        return False

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def finished(self, ok):
        if ok and self.resultado is not None:
            self.sinais.terminou.emit(self.resultado)
        else:
            self.sinais.falhou.emit(self.erro or "Busca interrompida.", None)


def iniciar(tarefa):
    QgsApplication.taskManager().addTask(tarefa)
    return tarefa
