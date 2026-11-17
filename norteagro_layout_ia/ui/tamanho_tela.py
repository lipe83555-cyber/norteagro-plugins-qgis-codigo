# -*- coding: utf-8 -*-
"""Tamanho das janelas de acordo com a tela (monitor grande, notebook, escala do Windows 100% a 175%).

Regras (v3):
* A janela abre com o tamanho de projeto; em tela grande cresce até 25%. Em tela pequena NÃO encolhe o conteúdo:
  ela ocupa no máximo 94% da largura e 90% da altura da tela e fica centralizada.
* Se o conteúdo não cabe na tela (notebook, escala 125%/150%), a janela ganha barra de rolagem em vez de espremer
  ou cortar os campos e os botões.
* A janela já nasce no monitor onde está o QGIS. Com dois monitores de escalas diferentes (ex.: notebook em 150% e
  monitor em 100%), uma janela que nasce num e passa para o outro é encolhida/esticada pelo Windows.
* Nenhum resize() antes de abrir passa do tamanho da tela: no Windows, uma janela criada maior que a tela
  abre com tamanho distorcido (era o "fica estranho" no notebook 1366 x 768).
* O tamanho que a pessoa ajustar é lembrado para cada tamanho de tela; um tamanho lembrado que não cabe mais na
  tela é ignorado. Os tamanhos lembrados das versões antigas (que podiam estar ruins) não são mais usados.

Este arquivo é IGUAL nos três plugins (norteagro_uso_solo, norteagro_layout_ia/ui, norteagro_mapas_tematicos/ui).
"""
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QEvent, QObject, QSize, Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

REFERENCIA = (1920.0, 1040.0)   # área útil de uma tela Full HD com a barra de tarefas
VERSAO = "v3"                   # muda a chave: tamanhos lembrados das versões antigas são descartados
CRESCER_ATE = 1.25              # em tela grande a janela cresce até 25%
LARG_MAX, ALT_MAX = 0.94, 0.90  # parte da tela que a janela pode ocupar
BARRA_TITULO = 34               # a barra de título do Windows fica fora do tamanho da janela


def _enum(classe, grupo, nome):
    """Enum do Qt5 (QEvent.Show) ou do Qt6 (QEvent.Type.Show)."""
    try:
        return getattr(getattr(classe, grupo), nome)
    except AttributeError:
        return getattr(classe, nome)


EV_SHOW = _enum(QEvent, "Type", "Show")
EV_HIDE = _enum(QEvent, "Type", "Hide")
EV_POLISH = _enum(QEvent, "Type", "Polish")
SEM_MOLDURA = _enum(QFrame, "Shape", "NoFrame")
WA_CRIADO = _enum(Qt, "WidgetAttribute", "WA_WState_Created")
WA_REDIMENSIONADO = _enum(Qt, "WidgetAttribute", "WA_Resized")


def _tela(widget):
    """Tela onde está o QGIS (a janela abre no mesmo monitor)."""
    try:
        from qgis.utils import iface
        janela = iface.mainWindow().windowHandle() if iface is not None else None
        if janela is not None and janela.screen() is not None:
            return janela.screen()
    except Exception:
        pass
    try:
        pai = widget.parentWidget()
        if pai is not None and pai.window().windowHandle() is not None and pai.window().windowHandle().screen() is not None:
            return pai.window().windowHandle().screen()
    except Exception:
        pass
    try:
        if widget.windowHandle() is not None and widget.windowHandle().screen() is not None:
            return widget.windowHandle().screen()
    except Exception:
        pass
    return QGuiApplication.primaryScreen()


def _limites(widget):
    """(área útil da tela, largura máxima, altura máxima) para a janela."""
    g = _tela(widget).availableGeometry()
    return g, int(g.width() * LARG_MAX), int(g.height() * ALT_MAX) - BARRA_TITULO


def _envolver_em_rolagem(dialogo):
    """Põe todo o conteúdo da janela dentro de uma área com barra de rolagem. True se conseguiu."""
    if dialogo.property("naRolagem"):
        return True
    try:
        lay = dialogo.layout()
        if lay is None:
            return False
        conteudo = QWidget()
        conteudo.setObjectName("naConteudoRolagem")
        conteudo.setLayout(lay)            # o Qt tira o layout da janela e leva junto os campos
        if dialogo.layout() is not None:   # não soltou: deixa como estava
            return False
        area = QScrollArea(dialogo)
        area.setObjectName("naRolagem")
        area.setWidgetResizable(True)
        area.setFrameShape(SEM_MOLDURA)
        area.setStyleSheet("QScrollArea#naRolagem{background:transparent;border:none;}")
        area.setWidget(conteudo)
        conteudo.setAutoFillBackground(False)   # mantém o fundo da janela
        area.viewport().setAutoFillBackground(False)
        nova = QVBoxLayout(dialogo)
        nova.setContentsMargins(0, 0, 0, 0)
        nova.setSpacing(0)
        nova.addWidget(area)
        dialogo.setProperty("naRolagem", True)
        return True
    except Exception:
        return False


class AjusteTela(QObject):
    def __init__(self, dialogo, chave):
        super().__init__(dialogo)
        self.d = dialogo
        self.chave = chave
        self.feito = False
        self.rolagem_vista = False
        self.base = None   # tamanho de projeto (o último resize() antes de abrir)

    # --- antes de abrir
    def limitar(self, tamanho):
        """Tamanho que não passa da tela (o Windows distorce janelas criadas maiores que a tela)."""
        try:
            _g, lim_w, lim_h = _limites(self.d)
            return QSize(min(tamanho.width(), lim_w), min(tamanho.height(), lim_h))
        except Exception:
            return tamanho

    def pre_posicionar(self):
        """Antes de abrir: põe a janela no centro do monitor do QGIS, para ela nascer nele."""
        try:
            g, _w, _h = _limites(self.d)
            t = self.d.size()
            self._mover(g.x() + max(0, (g.width() - t.width()) // 2),
                        g.y() + max(0, (g.height() - t.height() - BARRA_TITULO) // 2))
        except Exception:
            pass

    def conferir_rolagem(self):
        """Se o conteúdo não cabe na tela, barra de rolagem. Devolve o mínimo de que o conteúdo precisa (ou None)."""
        lay = self.d.layout()
        if lay is None or self.d.property("naRolagem"):
            return None
        try:
            precisa = lay.totalMinimumSize()
        except Exception:
            return None
        _g, lim_w, lim_h = _limites(self.d)
        if precisa.width() > lim_w or precisa.height() > lim_h:
            if _envolver_em_rolagem(self.d):
                return None
        return precisa

    # --- eventos
    def _nome_chave(self, g):
        return f"{self.chave}/{VERSAO}/{g.width()}x{g.height()}"

    def eventFilter(self, obj, evento):
        if obj is self.d:
            tipo = evento.type()
            if tipo == EV_POLISH and not self.rolagem_vista and self.d.testAttribute(WA_CRIADO):
                # abrindo: a janela já existe no Windows, mas o conteúdo ainda não esticou a janela
                self.rolagem_vista = True
                try:
                    self.conferir_rolagem()
                except Exception:
                    pass
            elif tipo == EV_SHOW and not self.feito:
                self.feito = True
                try:
                    self.aplicar()
                except Exception:
                    pass
            elif tipo == EV_HIDE and self.feito:
                try:
                    g, _w, _h = _limites(self.d)
                    QgsSettings().setValue(self._nome_chave(g), self.d.saveGeometry())
                except Exception:
                    pass
        return False

    def aplicar(self):
        d = self.d
        g, lim_w, lim_h = _limites(d)
        base = self.base or d.size()

        # 1) o conteúdo cabe na tela? se não, barra de rolagem (nada fica espremido ou cortado)
        precisa = self.conferir_rolagem()

        # 2) tamanho mínimo: o que o conteúdo precisa, mas nunca maior que a tela
        mw, mh = d.minimumWidth(), d.minimumHeight()
        if d.property("naRolagem"):
            mw, mh = min(mw, 480), min(mh, 320)
        elif precisa is not None:
            mw, mh = max(mw, precisa.width()), max(mh, precisa.height())
        d.setMinimumSize(min(mw, lim_w), min(mh, lim_h))

        # 3) tamanho que a pessoa deixou da última vez nesta tela (só se ainda couber)
        try:
            bruto = QgsSettings().value(self._nome_chave(g))
            if bruto and d.restoreGeometry(bruto):
                r = d.geometry()
                if r.width() <= lim_w and r.height() <= lim_h + BARRA_TITULO and g.contains(r.center()):
                    self._dentro_da_tela(g)
                    return
        except Exception:
            pass

        # 4) tamanho de projeto; em tela grande cresce um pouco; nunca passa do limite da tela
        f = max(1.0, min(CRESCER_ATE, min(g.width() / REFERENCIA[0], g.height() / REFERENCIA[1])))
        w = min(max(int(base.width() * f), d.minimumWidth()), lim_w)
        h = min(max(int(base.height() * f), d.minimumHeight()), lim_h)
        d.resize(w, h)
        d.move(g.x() + (g.width() - w) // 2, g.y() + max(0, (g.height() - h - BARRA_TITULO) // 2))

    def _dentro_da_tela(self, g):
        """Puxa a janela para dentro da tela se uma parte ficou para fora (ex.: monitor desligado)."""
        r = self.d.geometry()
        x = min(max(r.x(), g.x()), g.x() + g.width() - r.width())
        y = min(max(r.y(), g.y() + BARRA_TITULO), g.y() + g.height() - r.height())
        if (x, y) != (r.x(), r.y()):
            self.d.setGeometry(x, y, r.width(), r.height())


def ajustar_a_tela(dialogo, chave):
    """Liga o ajuste automático. Pode ser chamado antes ou depois do resize() de projeto da janela."""
    if dialogo.property("naAjusteTela"):
        return
    dialogo.setProperty("naAjusteTela", True)
    aj = AjusteTela(dialogo, chave)
    dialogo._ajuste_tela = aj
    dialogo.installEventFilter(aj)
    original = dialogo.resize
    aj._mover = dialogo.move
    if dialogo.testAttribute(WA_REDIMENSIONADO):   # o resize() de projeto veio antes desta chamada
        aj.base = QSize(dialogo.size())
        original(aj.limitar(dialogo.size()))
    aj.pre_posicionar()

    def resize(*args):
        try:
            tamanho = QSize(args[0]) if len(args) == 1 else QSize(int(args[0]), int(args[1]))
        except Exception:
            return original(*args)
        if not aj.feito:   # antes de abrir: guarda o tamanho de projeto e não deixa passar da tela
            aj.base = QSize(tamanho)
            original(aj.limitar(tamanho))
            aj.pre_posicionar()
            return None
        return original(tamanho)

    dialogo.resize = resize
