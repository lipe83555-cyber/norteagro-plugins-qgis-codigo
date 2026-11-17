# -*- coding: utf-8 -*-
"""Cartão de andamento das buscas de imagem: título, porcentagem grande, barra fina, etapa atual e
tempo restante estimado. Usado na etapa "Mapas e imagens" e na área "Buscar imagem"."""

import time

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout

ESTILO_CARTAO = """
QFrame#cartao_busca { background: #FFFFFF; border: 1px solid #DCE6CF; border-radius: 10px; }
QFrame#cartao_busca[estado="aviso"] { background: #fff8ec; border: 1px solid #f0d6a8; }
QFrame#cartao_busca[estado="erro"] { background: #fdf1f0; border: 1px solid #efc4c0; }
QLabel#cartao_titulo { font-weight: 600; font-size: 10pt; color: #1F2A1B; background: transparent; }
QLabel#cartao_pct { font-size: 18pt; font-weight: 700; color: #46741F; background: transparent; }
QFrame#cartao_busca[estado="aviso"] QLabel#cartao_pct { color: #a15c00; }
QFrame#cartao_busca[estado="erro"] QLabel#cartao_pct { color: #b3261e; }
QLabel#cartao_etapa { color: #5f6b64; background: transparent; }
QLabel#cartao_tempo { color: #1F2A1B; font-weight: 600; background: transparent; }
QProgressBar#cartao_barra { background: #E8EEE1; border: none; border-radius: 4px; max-height: 8px;
                            min-height: 8px; }
QProgressBar#cartao_barra::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7DA63F,
                                   stop:1 #46741F); border-radius: 4px; }
QToolButton#cartao_cancelar { border: none; color: #b3261e; text-decoration: underline; background: transparent; }
"""


def tempo_txt(segundos):
    s = max(0, int(round(segundos)))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    return f"{m} min {s:02d} s"


class CartaoAndamento(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cartao_busca")
        self.setStyleSheet(ESTILO_CARTAO)
        self.setVisible(False)
        self.ao_progresso = None  # (texto) -> repete o andamento em outro lugar (barra de status)
        self.ao_cancelar = None
        self.tarefa = None
        self._t0 = 0.0
        self._pct = 0.0
        self._fim_previsto = None
        self._etapa = ""
        self._relogio = QTimer(self)
        self._relogio.setInterval(500)
        self._relogio.timeout.connect(self._atualizar)

        cv = QVBoxLayout(self)
        cv.setContentsMargins(14, 10, 14, 10)
        cv.setSpacing(6)
        topo = QHBoxLayout()
        self.lb_titulo = QLabel("")
        self.lb_titulo.setObjectName("cartao_titulo")
        self.lb_pct = QLabel("0%")
        self.lb_pct.setObjectName("cartao_pct")
        topo.addWidget(self.lb_titulo)
        topo.addStretch()
        topo.addWidget(self.lb_pct)
        cv.addLayout(topo)
        self.barra = QProgressBar()
        self.barra.setObjectName("cartao_barra")
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        cv.addWidget(self.barra)
        base = QHBoxLayout()
        self.lb_etapa = QLabel("")
        self.lb_etapa.setObjectName("cartao_etapa")
        self.lb_etapa.setWordWrap(True)
        self.lb_tempo = QLabel("")
        self.lb_tempo.setObjectName("cartao_tempo")
        self.b_cancelar = QToolButton()
        self.b_cancelar.setObjectName("cartao_cancelar")
        self.b_cancelar.setText("Cancelar")
        self.b_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_cancelar.clicked.connect(self._cancelar)
        base.addWidget(self.lb_etapa, 1)
        base.addWidget(self.lb_tempo, 0, Qt.AlignmentFlag.AlignTop)
        base.addSpacing(10)
        base.addWidget(self.b_cancelar, 0, Qt.AlignmentFlag.AlignTop)
        cv.addLayout(base)

    # ------------------------------------------------------------ ciclo
    def iniciar(self, tarefa, titulo="Buscando imagens de satélite"):
        """Liga o cartão à tarefa (QgsTask com sinais.progresso(texto) e progressChanged(%))."""
        self.tarefa = tarefa
        self._t0 = time.time()
        self._pct = 0.0
        self._fim_previsto = None
        self._etapa = "Iniciando a busca..."
        self._estado("", titulo)
        self.b_cancelar.setVisible(True)
        self.setVisible(True)
        self._atualizar()
        self._relogio.start()

    def decorrido(self):
        return time.time() - self._t0

    def concluir(self, titulo, detalhe="", aviso=False):
        self._parar()
        self.barra.setValue(1000)
        self.lb_pct.setText("✓")
        self._estado("aviso" if aviso else "", titulo)
        self.lb_etapa.setText(detalhe)
        self.lb_tempo.setText("")

    def falhar(self, erro):
        self._parar()
        self.lb_pct.setText("✕")
        self._estado("erro", "A busca não terminou")
        self.lb_etapa.setText(erro)
        self.lb_tempo.setText("")
        if self.ao_progresso:
            self.ao_progresso(erro)

    def _parar(self):
        self._relogio.stop()
        self.tarefa = None
        self.b_cancelar.setVisible(False)

    def _cancelar(self):
        if self.tarefa is not None:
            self.lb_etapa.setText("Cancelando...")
            self.tarefa.cancel()
        if self.ao_cancelar:
            self.ao_cancelar()

    # ------------------------------------------------------------ andamento
    def _etapa_mudou(self, texto):
        self._etapa = texto
        self._atualizar()

    def _pct_mudou(self, pct):
        self._pct = max(self._pct, float(pct))  # nunca volta para trás
        decorrido = self.decorrido()
        if self._pct >= 4 and decorrido >= 1.5:
            previsto = self._t0 + decorrido * 100.0 / self._pct
            # suaviza a previsão para o número não pular a cada consulta
            self._fim_previsto = previsto if self._fim_previsto is None else 0.6 * self._fim_previsto + 0.4 * previsto
        self._atualizar()

    def _atualizar(self):
        if self.tarefa is None:
            return
        # lê o andamento anotado pela busca (linha principal; nenhum sinal vem de outras linhas)
        try:
            texto, frac = self.tarefa.andamento()
        except (AttributeError, RuntimeError):
            texto, frac = self._etapa, self._pct / 100.0
        self._etapa = texto
        pct = max(self._pct, frac * 100.0)
        if pct != self._pct:
            self._pct = pct
            decorrido = self.decorrido()
            if self._pct >= 4 and decorrido >= 1.5:
                previsto = self._t0 + decorrido * 100.0 / self._pct
                self._fim_previsto = previsto if self._fim_previsto is None else \
                    0.6 * self._fim_previsto + 0.4 * previsto
            try:
                self.tarefa.setProgress(self._pct)  # barra de tarefas do QGIS (linha principal)
            except RuntimeError:
                pass
        self.barra.setValue(int(self._pct * 10))
        self.lb_pct.setText(f"{self._pct:.0f}%")
        self.lb_etapa.setText(self._etapa)
        if self._fim_previsto is None:
            tempo = "calculando o tempo..."
        else:
            resta = self._fim_previsto - time.time()
            tempo = "quase pronto" if resta <= 2 else f"faltam ~{tempo_txt(resta)}"
        self.lb_tempo.setText(tempo)
        if self.ao_progresso:
            self.ao_progresso(f"Buscando imagens de satélite  ·  {self._pct:.0f}%  ·  {tempo}")

    def _estado(self, estado, titulo):
        self.setProperty("estado", estado)
        for w in (self, self.lb_pct, self.lb_titulo):
            w.style().unpolish(w)
            w.style().polish(w)
        self.lb_titulo.setText(titulo)
