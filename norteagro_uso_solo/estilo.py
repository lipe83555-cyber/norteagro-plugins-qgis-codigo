# -*- coding: utf-8 -*-
"""Identidade visual e componentes reutilizáveis do Norte Agro - Uso do Solo.

O estilo é aplicado somente aos diálogos do plugin. Nenhuma configuração global do
QGIS é alterada.
"""
import os

from qgis.PyQt.QtCore import QEvent, QObject, Qt, QSize
from qgis.PyQt.QtGui import QIcon, QPalette
from qgis.PyQt.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from qgis.core import QgsApplication, QgsSettings

PALETA = {
    "grafite": "#262621", "offwhite": "#FAF9F5", "verde": "#46741F",
    "folha": "#7DA63F", "marrom": "#6E5E4E", "borda": "#D9D6CC",
    "secao": "#FFFFFF", "hover": "#3B6219", "erro": "#B3261E",
    "alerta": "#A86A00", "info": "#2F5D8A", "folha_claro": "#E4EDD8",
}

_STATUS_CORES = {"Arquivo não encontrado":("#FBE4E2","#8F1D17"), 
    "OK": ("#E7F2DE", "#315B16"), "Vazia": ("#ECEBE7", "#5F5D57"),
    "Repetida": ("#FBE4E2", "#8F1D17"), "Já existe nesta pasta": ("#FFF2D6", "#865400"),
    "Criada": ("#E7F2DE", "#315B16"), "Criada (avulsa)": ("#E7F2DE", "#315B16"),
    "Não reconhecida": ("#FBE4E2", "#8F1D17"), "Semelhança": ("#FFF2D6", "#865400"),
    "Referência": ("#E3EEF8", "#244E78"), "Ignorada": ("#ECEBE7", "#5F5D57"),
    "CONFERIR": ("#FFF2D6", "#865400"), "VERIFICAR": ("#EEE7F8", "#5A3A83"),
    "ALERTA": ("#FBE4E2", "#8F1D17"), "SEM DADOS": ("#ECEBE7", "#5F5D57"),
}


def tema_escuro():
    try:
        return QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return False


def _qss_claro():
    p = PALETA
    return f"""
    QDialog {{ background:{p['offwhite']}; color:{p['grafite']}; font-family:"Segoe UI"; }}
    QWidget {{ font-size:9pt; }}
    QLabel[naTitle="true"] {{ font-size:14pt; font-weight:700; color:{p['grafite']}; }}
    QLabel[naSubtitle="true"] {{ color:{p['marrom']}; }}
    QLabel[naAlertText="true"] {{ color:{p['erro']}; font-weight:600; }}
    QLabel[naSection="true"] {{ font-weight:700; color:{p['verde']}; padding-top:4px; }}
    QFrame[naSeparator="true"] {{ background:{p['borda']}; border:none; min-height:1px; max-height:1px; }}
    QPushButton[naCardButton="true"] {{ text-align:left; min-height:68px; padding:12px 16px; background:{p['secao']}; border:1px solid {p['borda']}; border-left:4px solid {p['folha']}; border-radius:10px; font-weight:600; font-size:10pt; }}
    QPushButton[naCardButton="true"]:hover {{ border-color:{p['folha']}; border-left:4px solid {p['verde']}; background:#F3F7ED; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit {{ background:{p['secao']}; color:{p['grafite']}; border:1px solid {p['borda']}; border-radius:6px; min-height:28px; selection-background-color:{p['verde']}; selection-color:white; }}
    QLineEdit, QComboBox {{ padding:0 8px; }}
    QTreeWidget, QTableWidget, QListWidget {{ border-radius:8px; alternate-background-color:#FAFAF6; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTreeWidget:focus, QTableWidget:focus, QListWidget:focus {{ border:1px solid {p['verde']}; }}
    QComboBox::drop-down {{ border:none; width:22px; }}
    QComboBox QAbstractItemView {{ background:{p['secao']}; border:1px solid {p['borda']}; selection-background-color:{p['folha_claro']}; selection-color:{p['grafite']}; outline:0; }}
    QPushButton, QToolButton {{ min-height:28px; min-width:96px; padding:0 12px; border:1px solid {p['borda']}; border-radius:6px; background:{p['secao']}; color:{p['grafite']}; }}
    QPushButton:hover, QToolButton:hover {{ border-color:{p['folha']}; background:#F3F7ED; }}
    QPushButton:pressed, QToolButton:pressed {{ background:{p['folha_claro']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color:#A09D94; background:#F3F2EE; border-color:#E6E3DA; }}
    QPushButton[naRole="primary"] {{ background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #538529,stop:1 {p['verde']}); border:1px solid {p['hover']}; color:white; font-weight:700; padding:0 16px; }}
    QPushButton[naRole="primary"]:hover {{ background:{p['hover']}; border-color:{p['hover']}; }}
    QPushButton[naRole="primary"]:pressed {{ background:#2F5514; }}
    QPushButton[naRole="danger"] {{ color:{p['erro']}; border-color:{p['erro']}; background:{p['secao']}; }}
    QPushButton[naRole="danger"]:hover {{ background:#FBE4E2; }}
    QToolButton[naIconOnly="true"], QPushButton[naIconOnly="true"] {{ min-width:28px; max-width:30px; padding:0; }}
    QLabel[naPending="true"] {{ background:#FFF7E6; color:#6D4B00; border:1px solid #E6C36A; border-radius:8px; padding:8px 10px; }}
    QWidget[naAltRow="true"] {{ background:#F7F6F1; border-radius:6px; }}
    QHeaderView::section {{ background:#F2F1EC; color:{p['grafite']}; border:0; border-bottom:1px solid {p['borda']}; padding:6px 8px; font-weight:700; }}
    QTreeWidget::item, QTableWidget::item {{ min-height:30px; }}
    QTreeWidget::item:hover, QTableWidget::item:hover {{ background:#F3F7ED; }}
    QTreeWidget::item:selected, QTableWidget::item:selected {{ background:{p['folha_claro']}; color:{p['grafite']}; }}
    QProgressBar {{ border:none; border-radius:5px; text-align:center; background:#E8EEE1; min-height:10px; max-height:14px; color:{p['grafite']}; }}
    QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {p['folha']},stop:1 {p['verde']}); border-radius:5px; }}
    QTabWidget::pane {{ border:1px solid {p['borda']}; border-radius:8px; background:{p['secao']}; top:-1px; }}
    QTabBar::tab {{ background:transparent; color:#55604F; padding:8px 18px; min-width:120px; border:none; border-bottom:3px solid transparent; font-weight:600; }}
    QTabBar::tab:hover {{ color:{p['verde']}; }}
    QTabBar::tab:selected {{ color:{p['verde']}; border-bottom:3px solid {p['verde']}; }}
    QGroupBox {{ background:{p['secao']}; border:1px solid {p['borda']}; border-radius:10px; margin-top:14px; padding:12px 10px 8px 10px; font-weight:700; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 6px; color:{p['verde']}; }}
    QMenu {{ background:{p['secao']}; border:1px solid {p['borda']}; border-radius:8px; padding:4px; }}
    QMenu::item {{ padding:6px 22px 6px 14px; border-radius:5px; }}
    QMenu::item:selected {{ background:{p['folha_claro']}; color:{p['grafite']}; }}
    QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:#CFCBBE; border-radius:4px; min-height:30px; }}
    QScrollBar::handle:vertical:hover {{ background:{p['folha']}; }}
    QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
    QScrollBar::handle:horizontal {{ background:#CFCBBE; border-radius:4px; min-width:30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width:0px; height:0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
    QToolTip {{ background:{p['grafite']}; color:white; border:none; padding:5px 8px; }}
    """


def _qss_escuro():
    p = PALETA
    return f"""
    QDialog {{ background:palette(window); color:palette(window-text); }}
    QWidget {{ font-size:9pt; }}
    QLabel[naTitle="true"] {{ font-size:12pt; font-weight:600; color:palette(window-text); }}
    QLabel[naSubtitle="true"] {{ color:palette(mid); }}
    QLabel[naAlertText="true"] {{ color:#FF8A80; font-weight:600; }}
    QLabel[naSection="true"] {{ font-weight:600; color:palette(window-text); padding-top:2px; }}
    QFrame[naSeparator="true"] {{ background:palette(mid); min-height:1px; max-height:1px; }}
    QPushButton[naCardButton="true"] {{ text-align:left; min-height:64px; padding:10px 14px; border:1px solid palette(mid); border-radius:4px; font-weight:600; }}
    QLineEdit, QComboBox, QSpinBox, QTreeWidget, QTableWidget {{ min-height:28px; border-radius:4px; }}
    QPushButton, QToolButton {{ min-height:28px; min-width:96px; padding:0 10px; border-radius:4px; }}
    QPushButton[naRole="primary"] {{ background:{p['verde']}; border:1px solid {p['verde']}; color:white; font-weight:600; }}
    QPushButton[naRole="primary"]:hover {{ background:{p['hover']}; }}
    QPushButton[naRole="danger"] {{ color:#FF8A80; border:1px solid #FF8A80; }}
    QToolButton[naIconOnly="true"], QPushButton[naIconOnly="true"] {{ min-width:28px; max-width:30px; padding:0; }}
    QLabel[naPending="true"] {{ background:rgba(168,106,0,50); border:1px solid {p['alerta']}; border-radius:4px; padding:8px; }}
    QWidget[naAltRow="true"] {{ background:rgba(255,255,255,10); border-radius:3px; }}
    QProgressBar::chunk {{ background:{p['folha']}; }}
    """


def folha_estilo():
    return _qss_escuro() if tema_escuro() else _qss_claro()


def _chave_geometria(tela):
    return f"NorteAgro/UsoSolo/{tela}/geometria"


class _FiltroAjuda(QObject):
    """v3.9.12: o "?" da barra de título (Windows) abre a ajuda do plugin no assunto da tela."""
    def eventFilter(self, obj, evento):
        if evento.type() == QEvent.Type.EnterWhatsThisMode:
            from qgis.PyQt.QtWidgets import QApplication, QWhatsThis
            # Só a janela onde o "?" foi clicado responde (o Qt avisa todas as janelas abertas).
            if obj is QApplication.activeWindow() or obj is QApplication.activeModalWidget():
                QWhatsThis.leaveWhatsThisMode()
                from .tela_ajuda import abrir_ajuda
                abrir_ajuda(obj)
                return True
        return False


def abrir_ajuda_da_janela(widget):
    from .tela_ajuda import abrir_ajuda
    janela = widget.window() if widget is not None else None
    return abrir_ajuda(janela)


def preparar_dialogo(dialogo, tela, titulo=None, minimo=(480, 300)):
    dialogo.setProperty("naTela", tela)
    if tela != "tela_ajuda" and not dialogo.property("naAjudaHook"):
        dialogo.setProperty("naAjudaHook", True)
        dialogo.setWindowFlags(dialogo.windowFlags() | Qt.WindowType.WindowContextHelpButtonHint)
        dialogo._filtro_ajuda = _FiltroAjuda(dialogo); dialogo.installEventFilter(dialogo._filtro_ajuda)
    if titulo:
        dialogo.setWindowTitle(titulo)
    dialogo.setStyleSheet(folha_estilo())
    dialogo.setMinimumSize(*minimo)
    dialogo.setSizeGripEnabled(True)
    # tamanho proporcional à tela (PC ou notebook) e lembrado por tamanho de tela (tamanho_tela.py)
    from .tamanho_tela import ajustar_a_tela
    ajustar_a_tela(dialogo, _chave_geometria(tela))
    return dialogo


def _salvar_geometria(dialogo, chave):
    try:
        QgsSettings().setValue(chave, dialogo.saveGeometry())
    except Exception:
        pass


def icone_tema(*nomes):
    for nome in nomes:
        try:
            icone = QgsApplication.getThemeIcon(nome)
            if not icone.isNull():
                return icone
        except Exception:
            pass
    return QIcon()


def cabecalho(titulo, descricao="", icone_plugin="", ajuda=True):
    w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,4); l.setSpacing(12)
    ico = QLabel(); ico.setFixedSize(34,34)
    if icone_plugin and os.path.isfile(icone_plugin):
        ico.setPixmap(QIcon(icone_plugin).pixmap(QSize(30,30)))
    else:
        ico.setPixmap(icone_tema("/mIconLayer.svg", "/mActionMapTips.svg").pixmap(QSize(28,28)))
    textos = QVBoxLayout(); textos.setSpacing(2)
    t = QLabel(titulo); t.setProperty("naTitle", True); textos.addWidget(t)
    if descricao:
        d = QLabel(descricao); d.setProperty("naSubtitle", True); d.setWordWrap(True); textos.addWidget(d)
    l.addWidget(ico,0,Qt.AlignmentFlag.AlignTop); l.addLayout(textos,1)
    if ajuda:
        # v3.9.12: "?" visível no cabeçalho de toda janela do plugin.
        from qgis.PyQt.QtWidgets import QToolButton
        b = QToolButton(w); b.setText("?"); b.setToolTip("Ajuda: como esta tela funciona"); b.setFixedSize(22, 22)
        b.setCursor(Qt.CursorShape.PointingHandCursor); b.setAutoRaise(True)
        b.setStyleSheet(
            "QToolButton { font-family:'Segoe UI'; font-weight:600; font-size:12px; color:white; background:#46741F;"
            " border:none; border-radius:11px; min-width:22px; max-width:22px; min-height:22px; max-height:22px; padding:0px; }"
            " QToolButton:hover { background:#7DA63F; } QToolButton:pressed { background:#3A5F19; }")
        b.clicked.connect(lambda _=False, bb=b: abrir_ajuda_da_janela(bb))
        l.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
    return w


def secao(titulo):
    w=QWidget(); l=QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(4)
    t=QLabel(titulo); t.setProperty("naSection", True)
    linha=QFrame(); linha.setFrameShape(QFrame.Shape.NoFrame); linha.setFixedHeight(1); linha.setProperty("naSeparator", True)
    l.addWidget(t); l.addWidget(linha); return w


def cartao_fluxo(titulo, descricao, icone=None, parent=None):
    b=QPushButton(f"{titulo}\n{descricao}", parent); b.setProperty("naCardButton", True)
    if icone is not None and not icone.isNull():
        b.setIcon(icone); b.setIconSize(QSize(24,24))
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed); return b


def botao_principal(texto, parent=None):
    b=QPushButton(texto,parent); b.setProperty("naRole","primary"); b.setDefault(True); b.setAutoDefault(True); return b


def botao_secundario(texto, parent=None):
    b=QPushButton(texto,parent); b.setProperty("naRole","secondary"); return b


def botao_destrutivo(texto, parent=None):
    b=QPushButton(texto,parent); b.setProperty("naRole","danger"); return b


def botao_icone(icone, tooltip, parent=None):
    b=QToolButton(parent); b.setIcon(icone); b.setIconSize(QSize(18,18)); b.setToolTip(tooltip); b.setProperty("naIconOnly",True); return b


def aplicar_selo(label, texto):
    texto=str(texto or ""); label.setText(texto)
    bg,fg=_STATUS_CORES.get(texto,("#ECEBE7","#5F5D57"))
    if tema_escuro():
        label.setStyleSheet(f"QLabel{{padding:2px 7px;border-radius:8px;border:1px solid {fg};color:palette(window-text);}}")
    else:
        label.setStyleSheet(f"QLabel{{padding:2px 7px;border-radius:8px;background:{bg};color:{fg};font-weight:600;}}")
    label.setToolTip(texto)


class PainelPendencias(QLabel):
    def __init__(self,parent=None):
        super().__init__(parent); self.setProperty("naPending",True); self.setWordWrap(True); self.setVisible(False)
    def definir(self,itens):
        itens=[str(x).strip() for x in itens if str(x).strip()]
        if not itens:
            self.clear(); self.setVisible(False); return
        self.setText("Pendências:\n" + "\n".join(f"- {x}" for x in itens)); self.setVisible(True)


def encurtar_caminho(caminho, largura=72):
    texto=str(caminho or "")
    if len(texto)<=largura: return texto
    metade=max(10,(largura-5)//2); return texto[:metade]+"..."+texto[-metade:]


def configurar_caminho(label,caminho,largura=72):
    caminho=str(caminho or ""); label.setText(encurtar_caminho(caminho,largura)); label.setToolTip(caminho); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); return label


def configurar_alerta_texto(label):
    """Marca um QLabel como texto de alerta sem espalhar QSS pelas telas."""
    label.setProperty("naAlertText", True); label.setWordWrap(True)
    return label


def _mensagem(parent,titulo,frase,detalhes=None,icon=QMessageBox.Icon.Information):
    box=QMessageBox(parent); box.setStyleSheet(folha_estilo()); box.setWindowTitle(titulo); box.setIcon(icon); box.setText(str(frase))
    if detalhes:
        if isinstance(detalhes,(list,tuple)): detalhes="\n".join(f"- {x}" for x in detalhes)
        box.setDetailedText(str(detalhes))
    box.setStandardButtons(QMessageBox.StandardButton.Ok); box.exec(); return box


def informar(parent,titulo,frase,detalhes=None): return _mensagem(parent,titulo,frase,detalhes,QMessageBox.Icon.Information)
def sucesso(parent,titulo,frase,detalhes=None): return _mensagem(parent,titulo,frase,detalhes,QMessageBox.Icon.Information)
def alertar(parent,titulo,frase,detalhes=None): return _mensagem(parent,titulo,frase,detalhes,QMessageBox.Icon.Warning)
def erro(parent,titulo,frase,detalhes=None): return _mensagem(parent,titulo,frase,detalhes,QMessageBox.Icon.Critical)


def confirmar(parent,titulo,frase,acao="Continuar",cancelar="Cancelar",destrutivo=False,detalhes=None):
    box=QMessageBox(parent); box.setStyleSheet(folha_estilo()); box.setWindowTitle(titulo); box.setIcon(QMessageBox.Icon.Warning if destrutivo else QMessageBox.Icon.Question); box.setText(str(frase))
    if detalhes:
        box.setDetailedText("\n".join(str(x) for x in detalhes) if isinstance(detalhes,(list,tuple)) else str(detalhes))
    sim=box.addButton(acao,QMessageBox.ButtonRole.DestructiveRole if destrutivo else QMessageBox.ButtonRole.AcceptRole); nao=box.addButton(cancelar,QMessageBox.ButtonRole.RejectRole); box.setDefaultButton(nao); box.exec(); return box.clickedButton() is sim


def dialogo_acoes(parent,titulo,frase,detalhes=None,acoes=None,nivel="info",padrao=None):
    box=QMessageBox(parent); box.setStyleSheet(folha_estilo()); box.setWindowTitle(titulo)
    box.setIcon({"info":QMessageBox.Icon.Information,"sucesso":QMessageBox.Icon.Information,"alerta":QMessageBox.Icon.Warning,"erro":QMessageBox.Icon.Critical}.get(nivel,QMessageBox.Icon.Information)); box.setText(str(frase))
    if detalhes:
        if isinstance(detalhes,(list,tuple)): detalhes="\n".join(str(x) for x in detalhes)
        box.setDetailedText(str(detalhes))
    botoes={}
    for texto_botao,papel in list(acoes or [("Continuar",QMessageBox.ButtonRole.AcceptRole)]):
        botoes[texto_botao]=box.addButton(texto_botao,papel)
    if padrao in botoes: box.setDefaultButton(botoes[padrao])
    box.exec()
    for texto_botao,botao in botoes.items():
        if box.clickedButton() is botao: return texto_botao
    return ""
