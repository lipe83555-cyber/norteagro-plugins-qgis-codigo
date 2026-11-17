# -*- coding: utf-8 -*-
"""Vídeos da Ajuda (?) - a coluna "Vídeos deste assunto", ao lado do texto de cada assunto.

* Cada assunto da ajuda tem um LUGAR para o vídeo principal. A pessoa grava com o programa que quiser e clica em
  "Salvar vídeo no plugin...": o arquivo é copiado para a pasta de vídeos do plugin (sem limite de tamanho ou duração).
  "Apagar" apaga o arquivo dessa pasta. Não há gravador no plugin.
* "+ Mais um vídeo" acrescenta vídeos fora dos lugares: num assunto (embaixo do principal) ou em "Vídeos extras".
* "▶ Assistir" toca dentro do QGIS; se o formato não tocar aqui, abre no player do Windows.
* SENHA: salvar, trocar, editar e apagar vídeos pede a senha (uma vez por janela da Ajuda; mínimo de 8 caracteres;
  acesso.json danificado bloqueia em vez de voltar à senha de fábrica). "Mudar a senha..." só funciona com o arquivo
  IDENTIFICADOR (.naid). Senha e identificador ficam só como hash (PBKDF2-SHA256) em <plugin>/videos/acesso.json, que
  vai junto nas atualizações publicadas; sem esse arquivo vale a senha de fábrica (ACESSO_PADRAO).
* VÍDEOS PELA INTERNET (v0.7.5 / v0.32.5): os vídeos ficam FORA do plugin, em <perfil do QGIS>/norteagro_videos/
  <plugin> (atualizar o plugin não apaga nada). Quem publica roda 03_TESTES_E_FERRAMENTAS/publicar_repositorio.py: os
  vídeos vão para o GitHub da Norte Agro (em partes) junto com a lista (catalogo.json). Ao abrir o QGIS e a cada 2 horas,
  o plugin busca essa lista na internet (a cópia que vem dentro do plugin, em <plugin>/videos/catalogo.json, só vale sem
  internet), avisa na barra do QGIS e baixa em segundo plano só os vídeos que faltam; tira os publicados que saíram.
  Vídeo novo não precisa de versão nova do plugin. Vídeos salvos neste computador (de quem publica) nunca são mexidos.

Índice local: <pasta de vídeos>/videos.json -> {"versao": 2, "videos": [{"id", "assunto", "principal", "titulo",
"descricao", "arquivo", "tamanho", "adicionado", "sha256"?, "origem"?}]} ("origem": "publicado" = veio na atualização).

Este arquivo é IGUAL nos plugins norteagro_uso_solo (raiz) e norteagro_layout_ia (ui/).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import unicodedata
from datetime import datetime

from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea, QSlider, QStyle,
    QVBoxLayout, QWidget,
)

try:  # Qt Multimedia nem sempre vem no QGIS; sem ele o vídeo abre no player do Windows
    from qgis.PyQt.QtMultimedia import QMediaPlayer
    try:
        from qgis.PyQt.QtMultimediaWidgets import QVideoWidget
    except Exception:  # o qgis.PyQt não tem esse módulo em algumas versões
        try:
            from PyQt5.QtMultimediaWidgets import QVideoWidget
        except Exception:
            from PyQt6.QtMultimediaWidgets import QVideoWidget
    try:
        from qgis.PyQt.QtMultimedia import QAudioOutput  # Qt6
    except Exception:
        QAudioOutput = None
    TEM_PLAYER = True
except Exception:
    QMediaPlayer = QVideoWidget = QAudioOutput = None
    TEM_PLAYER = False

VERDE = "#46741F"
VERDE_CLARO = "#7DA63F"
EXTRAS = "_extras"
TITULO_EXTRAS = "Vídeos extras (fora dos assuntos)"
EXT_VIDEO = (".mp4", ".m4v", ".webm", ".mov", ".avi", ".mkv", ".wmv", ".mpg", ".mpeg", ".flv", ".3gp", ".ts")
FILTRO = "Vídeos (*.mp4 *.m4v *.webm *.mov *.avi *.mkv *.wmv *.mpg *.mpeg *.flv *.3gp *.ts);;Todos os arquivos (*.*)"
INDICE = "videos.json"
ACESSO = "acesso.json"
EXT_IDENTIFICADOR = "Identificador Norte Agro (*.naid);;Todos os arquivos (*.*)"
_ITERACOES = 200000
SENHA_MINIMA = 8
# senha de fábrica e identificador (só o hash; o texto não fica no plugin). Vale enquanto não existir videos/acesso.json
ACESSO_PADRAO = {
    "senha": {
        "sal": "cc0be76915c44886d8f1d562acb9182c",
        "hash": "04637742a086f41cf205bc0b03c6c21ed2cc4e01d1a7e09e8d91c75af81f13cc"
    },
    "identificador": {
        "sal": "0aa6f158953341bdff5ebe328b7eeb12",
        "hash": "e162b831d66a1142d55f0f46ce92d00301cb725b7927cede4c381303b542d011"
    },
}


def _raiz_plugin():
    """Pasta do plugin (a que tem metadata.txt), esteja este arquivo na raiz ou em ui/."""
    pasta = os.path.dirname(os.path.abspath(__file__))
    for _ in range(3):
        if os.path.isfile(os.path.join(pasta, "metadata.txt")):
            return pasta
        pasta = os.path.dirname(pasta)
    return os.path.dirname(os.path.abspath(__file__))


def _perfil_qgis():
    try:
        from qgis.core import QgsApplication
        pasta = QgsApplication.qgisSettingsDirPath()
        if pasta:
            return pasta
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".norteagro")


RAIZ_PLUGIN = _raiz_plugin()
NOME_PLUGIN = os.path.basename(RAIZ_PLUGIN)
# vai dentro do plugin (e nas atualizações): acesso.json (senha) e catalogo.json (vídeos publicados)
PASTA_PACOTE = os.path.join(RAIZ_PLUGIN, "videos")
# fica fora do plugin: a atualização do plugin não apaga os vídeos
PASTA_VIDEOS = os.path.normpath(os.path.join(_perfil_qgis(), "norteagro_videos", NOME_PLUGIN))
CATALOGO = "catalogo.json"
CATALOGO_ONLINE = "catalogo_online.json"   # última lista baixada da internet (em PASTA_VIDEOS)
REMOVIDOS = "removidos.json"
INTERVALO_CONFERENCIA_MS = 2 * 60 * 60 * 1000   # confere vídeos novos a cada 2 horas com o QGIS aberto


# ---------------------------------------------------------------- índice
def ler(pasta=PASTA_VIDEOS):
    """Lista de vídeos. O índice antigo (v0.5, roteiro de gravação) vira o novo: só ficam os que têm arquivo."""
    try:
        with open(os.path.join(pasta, INDICE), encoding="utf-8") as fp:
            dados = json.load(fp)
    except Exception:
        return []
    if isinstance(dados, list):
        dados = {"videos": dados}
    itens = [x for x in dados.get("videos", []) if isinstance(x, dict)]
    if dados.get("versao") == 2:
        return itens
    novos = []
    for x in itens:
        if x.get("arquivo") and os.path.isfile(os.path.join(pasta, x["arquivo"])):
            novos.append({"id": x.get("id") or _novo_id(EXTRAS, novos), "assunto": EXTRAS, "principal": False,
                          "titulo": x.get("titulo") or x["arquivo"], "descricao": x.get("descricao", ""),
                          "arquivo": x["arquivo"], "tamanho": _tamanho(os.path.join(pasta, x["arquivo"])),
                          "adicionado": x.get("adicionado", "")})
    try:
        gravar(novos, pasta)
    except Exception:
        pass
    return novos


def gravar(itens, pasta=PASTA_VIDEOS):
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, INDICE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump({"versao": 2, "videos": itens}, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(pasta, INDICE))


def _tamanho(caminho):
    try:
        return os.path.getsize(caminho)
    except Exception:
        return 0


def caminho(item, pasta=PASTA_VIDEOS):
    return os.path.normpath(os.path.join(pasta, item["arquivo"])) if item.get("arquivo") else ""


def tem_arquivo(item, pasta=PASTA_VIDEOS):
    return bool(item.get("arquivo")) and os.path.isfile(caminho(item, pasta))


def do_assunto(chave, itens=None, pasta=PASTA_VIDEOS):
    """(principal ou None, [extras]) do assunto."""
    itens = ler(pasta) if itens is None else itens
    deste = [x for x in itens if x.get("assunto") == chave]
    principal = next((x for x in deste if x.get("principal")), None)
    return principal, [x for x in deste if not x.get("principal")]


def assuntos_com_video(itens=None, pasta=PASTA_VIDEOS):
    itens = ler(pasta) if itens is None else itens
    return {x.get("assunto") for x in itens if tem_arquivo(x, pasta)}


def _slug(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:40] or "video"


def _novo_id(assunto, itens):
    usados = {x.get("id") for x in itens}
    n = 1
    while f"{assunto}__extra_{n}" in usados:
        n += 1
    return f"{assunto}__extra_{n}"


def _mb(n):
    if n < 1e6:
        return f"{max(1, round(n / 1e3))} KB"
    if n >= 1e9:
        return f"{n / 1e9:,.2f} GB".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{n / 1e6:,.1f} MB".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(ms):
    s = max(0, int(ms or 0) // 1000)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def copiar_com_andamento(origem, destino, parent=None):
    """Copia um arquivo de qualquer tamanho mostrando o andamento. False = cancelado ou falhou."""
    total = max(1, os.path.getsize(origem))
    prog = QProgressDialog("Copiando o vídeo...", "Cancelar", 0, 1000, parent)
    prog.setWindowTitle("Vídeos da ajuda")
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    prog.setMinimumDuration(300)
    feito = 0
    parcial = destino + ".parcial"
    try:
        with open(origem, "rb") as a, open(parcial, "wb") as b:
            while True:
                bloco = a.read(8 * 1024 * 1024)
                if not bloco:
                    break
                b.write(bloco)
                feito += len(bloco)
                prog.setValue(int(feito * 1000 / total))
                prog.setLabelText(f"Copiando o vídeo... {_mb(feito)} de {_mb(total)}")
                QApplication.processEvents()
                if prog.wasCanceled():
                    raise InterruptedError
        os.replace(parcial, destino)
        return True
    except InterruptedError:
        pass
    except Exception as exc:
        QMessageBox.warning(parent, "Vídeos da ajuda", f"Não foi possível copiar o vídeo:\n{exc}")
    finally:
        prog.close()
        if os.path.exists(parcial):
            try:
                os.remove(parcial)
            except Exception:
                pass
    return False


def _apagar(arquivo, pasta=PASTA_VIDEOS):
    """Apaga o arquivo do vídeo da pasta dos vídeos (e a pasta do assunto, se ficar vazia). True se apagou."""
    if not arquivo:
        return False
    alvo = os.path.normpath(os.path.join(pasta, arquivo))
    try:
        if os.path.isfile(alvo):
            os.remove(alvo)
    except Exception:
        return False
    sub = os.path.dirname(alvo)
    try:
        if os.path.normcase(sub) != os.path.normcase(os.path.normpath(pasta)) and os.path.isdir(sub) and not os.listdir(sub):
            os.rmdir(sub)
    except Exception:
        pass
    return not os.path.exists(alvo)


def nome_pasta(titulo):
    """Nome da pasta do assunto dentro de videos/ ("11. Calcular áreas" -> "Calcular áreas")."""
    t = re.sub(r"^\s*\d+\.\s*", "", str(titulo or "")).strip()
    t = re.sub(r'[\\/:*?"<>|]+', "-", t).strip(" .") or "Assunto"
    return t[:80]


def mostrar_na_pasta(caminho_arquivo):
    """Abre o Explorador do Windows com o arquivo selecionado (nos outros sistemas, só a pasta)."""
    alvo = os.path.normpath(caminho_arquivo)
    if os.name == "nt" and os.path.exists(alvo):
        try:
            import subprocess
            subprocess.Popen(f'explorer /select,"{alvo}"')
            return
        except Exception:
            pass
    pasta = alvo if os.path.isdir(alvo) else os.path.dirname(alvo)
    os.makedirs(pasta, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(pasta))


def bolinha(cor, tam=12):
    """Ícone redondo (verde = tem vídeo; cinza vazado = falta)."""
    pix = QPixmap(tam, tam)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if cor:
        p.setBrush(QColor(cor)); p.setPen(QColor(cor))
    else:
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QColor("#9CA3AF"))
    p.drawEllipse(1, 1, tam - 3, tam - 3)
    p.end()
    return QIcon(pix)


# ---------------------------------------------------------------- senha e identificador
def _hash(texto, sal_hex):
    return hashlib.pbkdf2_hmac("sha256", str(texto).encode("utf-8"), bytes.fromhex(sal_hex), _ITERACOES).hex()


def _par_valido(par):
    """{"sal", "hash"} com textos hexadecimais de tamanho certo."""
    try:
        return (isinstance(par, dict) and len(bytes.fromhex(par.get("sal", ""))) >= 16
                and len(bytes.fromhex(par.get("hash", ""))) == 32)
    except Exception:
        return False


def _ler_acesso(pasta=PASTA_PACOTE):
    """Senha e identificador. Sem acesso.json: os de fábrica. Com acesso.json danificado: None (fica bloqueado,
    não volta para a senha de fábrica; só "Mudar a senha..." com o identificador conserta)."""
    arquivo = os.path.join(pasta, ACESSO)
    if not os.path.exists(arquivo):
        return json.loads(json.dumps(ACESSO_PADRAO))
    try:
        with open(arquivo, encoding="utf-8") as fp:
            dados = json.load(fp)
        if isinstance(dados, dict) and _par_valido(dados.get("senha")) and _par_valido(dados.get("identificador")):
            return dados
    except Exception:
        pass
    return None


def _gravar_acesso(dados, pasta=PASTA_PACOTE):
    os.makedirs(pasta, exist_ok=True)
    tmp = os.path.join(pasta, ACESSO + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(dados, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(pasta, ACESSO))


def senha_confere(senha, pasta=PASTA_PACOTE):
    dados = _ler_acesso(pasta)
    if not senha or dados is None:
        return False
    return hmac.compare_digest(_hash(senha, dados["senha"]["sal"]), dados["senha"]["hash"])


def acesso_danificado(pasta=PASTA_PACOTE):
    return _ler_acesso(pasta) is None


def chave_do_identificador(arquivo):
    """Texto da linha "CHAVE:" do arquivo identificador ('' se não der para ler)."""
    try:
        with open(arquivo, "rb") as fp:
            texto = fp.read(65536).decode("utf-8", "ignore")
    except Exception:
        return ""
    m = re.search(r"CHAVE\s*:\s*([A-Za-z0-9_\-]{16,})", texto)
    return m.group(1) if m else ""


def identificador_confere(arquivo, pasta=PASTA_PACOTE):
    chave = chave_do_identificador(arquivo)
    if not chave:
        return False
    dados = _ler_acesso(pasta) or ACESSO_PADRAO   # acesso.json danificado: confere com o identificador de fábrica
    d = dados["identificador"]
    return hmac.compare_digest(_hash(chave, d["sal"]), d["hash"])


def trocar_senha(nova, pasta=PASTA_PACOTE):
    dados = _ler_acesso(pasta) or json.loads(json.dumps(ACESSO_PADRAO))   # danificado: refaz o arquivo
    sal = secrets.token_hex(16)
    dados["senha"] = {"sal": sal, "hash": _hash(nova, sal)}
    dados["alterada"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    _gravar_acesso(dados, pasta)


class DialogoSenha(QDialog):
    """Pede a senha (nova=True: senha nova digitada duas vezes)."""

    def __init__(self, parent=None, titulo="Senha dos vídeos", texto="", nova=False):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(420)
        self.nova = nova
        lay = QVBoxLayout(self)
        rot = QLabel(texto); rot.setWordWrap(True); lay.addWidget(rot)
        form = QFormLayout()
        self.campo = QLineEdit(); self.campo.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Senha nova:" if nova else "Senha:", self.campo)
        self.campo2 = None
        if nova:
            self.campo2 = QLineEdit(); self.campo2.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Repita a senha:", self.campo2)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Mudar a senha" if nova else "Liberar")
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.campo.setFocus()

    def _ok(self):
        if self.nova:
            if len(self.campo.text()) < SENHA_MINIMA:
                QMessageBox.warning(self, self.windowTitle(), f"A senha nova precisa ter pelo menos {SENHA_MINIMA} caracteres.")
                return
            if self.campo.text() != self.campo2.text():
                QMessageBox.warning(self, self.windowTitle(), "As duas senhas não são iguais. Digite de novo.")
                self.campo2.clear(); self.campo2.setFocus()
                return
        self.accept()

    def senha(self):
        return self.campo.text()


# ---------------------------------------------------------------- formulário
class FormularioVideo(QDialog):
    """Escolher o arquivo, o nome e para que serve (e, no vídeo extra, onde ele aparece)."""

    def __init__(self, parent=None, titulo_janela="Salvar vídeo no plugin", nome="", descricao="", assuntos=None,
                 assunto="", pedir_arquivo=True, pasta_de=None):
        super().__init__(parent)
        self.setWindowTitle(titulo_janela)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.arquivo = None
        if pedir_arquivo:
            linha = QHBoxLayout()
            self.arquivo = QLineEdit(); self.arquivo.setPlaceholderText("Escolha o arquivo do vídeo gravado")
            b = QPushButton("Escolher..."); b.clicked.connect(self._escolher)
            linha.addWidget(self.arquivo, 1); linha.addWidget(b)
            form.addRow("Arquivo:", linha)
        self.nome = QLineEdit(nome); self.nome.setPlaceholderText("Nome do vídeo")
        form.addRow("Nome:", self.nome)
        self.descricao = QPlainTextEdit(descricao); self.descricao.setPlaceholderText(
            "Para que serve: o que o vídeo mostra (aparece embaixo do nome)"); self.descricao.setFixedHeight(90)
        form.addRow("Para que serve:", self.descricao)
        self.assunto = None
        if assuntos:
            self.assunto = QComboBox()
            for chave, titulo in assuntos:
                self.assunto.addItem(titulo, chave)
            self.assunto.addItem(TITULO_EXTRAS, EXTRAS)
            i = self.assunto.findData(assunto or EXTRAS)
            self.assunto.setCurrentIndex(max(0, i))
            form.addRow("Aparece em:", self.assunto)
        lay.addLayout(form)
        self._pasta_de = pasta_de
        self.nota = QLabel(""); self.nota.setWordWrap(True); self.nota.setStyleSheet("color:#374151;")
        self.nota.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.nota)
        if self.assunto is not None:
            self.assunto.currentIndexChanged.connect(lambda _i: self._destino(assunto))
        self._destino(assunto)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar no plugin" if pedir_arquivo else "Salvar")
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if pedir_arquivo:
            self._escolher()

    def _destino(self, assunto_padrao=""):
        chave = self.assunto.currentData() if self.assunto is not None else assunto_padrao
        if self._pasta_de is None:
            self.nota.setText("O vídeo é copiado para a pasta dos vídeos. Sem limite de tamanho ou duração.")
            return
        self.nota.setText("Será salvo na pasta:\n" + self._pasta_de(chave)
                          + "\nSem limite de tamanho ou duração. O arquivo original continua onde você gravou. "
                          "Ele chega aos colegas quando você publicar os vídeos.")

    def _escolher(self):
        ini = os.path.dirname(self.arquivo.text()) if self.arquivo.text() else os.path.join(os.path.expanduser("~"), "Videos")
        arq, _ = QFileDialog.getOpenFileName(self, "Escolha o vídeo", ini, FILTRO)
        if arq:
            self.arquivo.setText(arq)
            if not self.nome.text().strip():
                self.nome.setText(os.path.splitext(os.path.basename(arq))[0])

    def _ok(self):
        if self.arquivo is not None and not os.path.isfile(self.arquivo.text().strip()):
            QMessageBox.warning(self, "Vídeos da ajuda", "Escolha o arquivo do vídeo.")
            return
        if not self.nome.text().strip():
            QMessageBox.warning(self, "Vídeos da ajuda", "Escreva o nome do vídeo.")
            return
        self.accept()

    def dados(self):
        return {"arquivo_origem": self.arquivo.text().strip() if self.arquivo is not None else "",
                "titulo": self.nome.text().strip(), "descricao": self.descricao.toPlainText().strip(),
                "assunto": self.assunto.currentData() if self.assunto is not None else None}


# ---------------------------------------------------------------- player
class PlayerVideo(QDialog):
    """Toca o vídeo dentro do QGIS. Se o formato não tocar aqui, abre no player do Windows."""

    def __init__(self, item, parent=None, pasta=PASTA_VIDEOS):
        super().__init__(parent)
        self.item = item
        self.arquivo = caminho(item, pasta)
        self._abriu_fora = False
        self.setWindowTitle(item.get("titulo") or "Vídeo")
        self.resize(960, 620)
        try:
            from .tamanho_tela import ajustar_a_tela
            ajustar_a_tela(self, "norteagro_videos/player")
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        self.tela = QVideoWidget(); self.tela.setStyleSheet("background:#000;"); self.tela.setMinimumSize(480, 270)
        lay.addWidget(self.tela, 1)
        self.aviso = QLabel(""); self.aviso.setWordWrap(True); self.aviso.setStyleSheet("color:#B45309;")
        self.aviso.setVisible(False); lay.addWidget(self.aviso)
        c = QHBoxLayout()
        self.b_play = QPushButton(); self.b_play.clicked.connect(self.tocar_pausar); c.addWidget(self.b_play)
        self.barra = QSlider(Qt.Orientation.Horizontal); self.barra.sliderMoved.connect(lambda ms: self.player.setPosition(int(ms)))
        c.addWidget(self.barra, 1)
        self.tempo = QLabel("0:00 / 0:00"); c.addWidget(self.tempo)
        b_cheia = QPushButton("Tela cheia"); b_cheia.clicked.connect(lambda: self.tela.setFullScreen(not self.tela.isFullScreen()))
        c.addWidget(b_cheia)
        b_fora = QPushButton("Abrir no player do Windows"); b_fora.clicked.connect(self.abrir_fora); c.addWidget(b_fora)
        lay.addLayout(c)
        self.player = QMediaPlayer(self)
        if QAudioOutput is not None and hasattr(self.player, "setAudioOutput"):
            self._audio = QAudioOutput(self); self.player.setAudioOutput(self._audio)
        self.player.setVideoOutput(self.tela)
        self.player.positionChanged.connect(self._posicao)
        self.player.durationChanged.connect(lambda ms: self.barra.setRange(0, int(ms)))
        for sinal in ("errorOccurred", "error"):
            try:
                getattr(self.player, sinal).connect(lambda *_: self._falhou())
                break
            except Exception:
                continue
        try:
            self.player.mediaStatusChanged.connect(self._status)
        except Exception:
            pass
        url = QUrl.fromLocalFile(self.arquivo)
        if hasattr(self.player, "setSource"):
            self.player.setSource(url)
        else:
            from qgis.PyQt.QtMultimedia import QMediaContent
            self.player.setMedia(QMediaContent(url))
        self._tocando = False
        self.tocar_pausar()

    def _icone(self):
        self.b_play.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaPause if self._tocando else QStyle.StandardPixmap.SP_MediaPlay))

    def tocar_pausar(self):
        if self._tocando:
            self.player.pause()
        else:
            self.player.play()
        self._tocando = not self._tocando
        self._icone()

    def _posicao(self, ms):
        if not self.barra.isSliderDown():
            self.barra.setValue(int(ms))
        self.tempo.setText(f"{_fmt(ms)} / {_fmt(self.player.duration())}")

    def _status(self, st):
        try:
            invalido = getattr(QMediaPlayer, "InvalidMedia", None) or QMediaPlayer.MediaStatus.InvalidMedia
            fim = getattr(QMediaPlayer, "EndOfMedia", None) or QMediaPlayer.MediaStatus.EndOfMedia
        except Exception:
            return
        if st == invalido:
            self._falhou()
        elif st == fim:
            self._tocando = False; self._icone()

    def _falhou(self):
        if self._abriu_fora:
            return
        self._abriu_fora = True
        # este formato não toca dentro do QGIS neste computador: abre no player do Windows e fecha a janela daqui
        self.abrir_fora()
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(0, self.close)

    def abrir_fora(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.arquivo))

    def keyPressEvent(self, ev):
        if self.tela.isFullScreen() and ev.key() == Qt.Key.Key_Escape:
            self.tela.setFullScreen(False); return
        if ev.key() == Qt.Key.Key_Space:
            self.tocar_pausar(); return
        super().keyPressEvent(ev)

    def closeEvent(self, ev):
        try:
            self.player.stop()
            if hasattr(self.player, "setSource"):
                self.player.setSource(QUrl())
            else:
                from qgis.PyQt.QtMultimedia import QMediaContent
                self.player.setMedia(QMediaContent())
        except Exception:
            pass
        super().closeEvent(ev)


_PLAYERS = []


def assistir(item, parent=None, pasta=PASTA_VIDEOS):
    if not tem_arquivo(item, pasta):
        QMessageBox.warning(parent, "Vídeos da ajuda", "O arquivo deste vídeo não está na pasta videos do plugin.")
        return None
    if not TEM_PLAYER:
        QDesktopServices.openUrl(QUrl.fromLocalFile(caminho(item, pasta)))
        return None
    dlg = PlayerVideo(item, parent, pasta)
    dlg.setWindowModality(Qt.WindowModality.NonModal)
    dlg.show()
    _PLAYERS.append(dlg)
    dlg.destroyed.connect(lambda *_: _PLAYERS.remove(dlg) if dlg in _PLAYERS else None)
    return dlg


def _fechar_players():
    """Fecha os players abertos (o Windows não deixa trocar/apagar um vídeo aberto)."""
    for d in list(_PLAYERS):
        try:
            d.close()
        except Exception:
            pass
    QApplication.processEvents()


# ---------------------------------------------------------------- vídeos publicados (chegam nas atualizações)
def _dentro(base, rel):
    """Caminho absoluto de `rel` dentro de `base`, ou '' se `rel` tentar sair da pasta."""
    rel = str(rel or "")
    if not rel or os.path.isabs(rel) or ":" in rel:
        return ""
    base_n = os.path.normpath(os.path.abspath(base))
    alvo = os.path.normpath(os.path.join(base_n, rel))
    if not os.path.normcase(alvo).startswith(os.path.normcase(base_n) + os.sep):
        return ""
    return alvo


def _remover_silencioso(arquivo):
    try:
        if arquivo and os.path.exists(arquivo):
            os.remove(arquivo)
    except Exception:
        pass


def _catalogo_valido(dados):
    return (isinstance(dados, dict) and isinstance(dados.get("videos"), list)
            and str(dados.get("base_url") or "").lower().startswith(("https://", "file:")))


def _ler_arquivo_catalogo(arquivo):
    try:
        with open(arquivo, encoding="utf-8") as fp:
            dados = json.load(fp)
        return dados if _catalogo_valido(dados) else {}
    except Exception:
        return {}


def ler_catalogo(pasta_pacote=PASTA_PACOTE, pasta=None):
    """Lista de vídeos publicados mais nova: a baixada da internet (em `pasta`) ou a que veio dentro do plugin.
    {} se não houver nenhuma."""
    interno = _ler_arquivo_catalogo(os.path.join(pasta_pacote, CATALOGO))
    online = _ler_arquivo_catalogo(os.path.join(pasta, CATALOGO_ONLINE)) if pasta else {}
    if online and (not interno or str(online.get("gerado") or "") >= str(interno.get("gerado") or "")):
        return online
    return interno


def _chave_item(item):
    return f"{item.get('id')}|{item.get('tamanho')}"


def _ler_removidos(pasta=PASTA_VIDEOS):
    try:
        with open(os.path.join(pasta, REMOVIDOS), encoding="utf-8") as fp:
            dados = json.load(fp)
        return set(dados) if isinstance(dados, list) else set()
    except Exception:
        return set()


def _marcar_removido(item, pasta=PASTA_VIDEOS):
    """Vídeo apagado à mão neste computador: a sincronização não o traz de volta."""
    try:
        r = _ler_removidos(pasta)
        r.add(_chave_item(item))
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, REMOVIDOS), "w", encoding="utf-8") as fp:
            json.dump(sorted(r), fp, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _migrar_pasta_antiga(pasta=PASTA_VIDEOS, antiga=PASTA_PACOTE):
    """Até a v0.7.3/v0.32.3 os vídeos ficavam dentro do plugin (a atualização apagava): passa para a pasta nova."""
    try:
        if os.path.normcase(os.path.abspath(pasta)) == os.path.normcase(os.path.abspath(antiga)):
            return
        velhos = [x for x in ler(antiga) if tem_arquivo(x, antiga)]
        if not velhos:
            return
        itens = ler(pasta)
        ja = {x.get("arquivo") for x in itens}
        for x in velhos:
            destino = _dentro(pasta, x.get("arquivo"))
            if x.get("arquivo") in ja or not destino:
                continue
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(caminho(x, antiga), destino)
            itens.append(dict(x))
        gravar(itens, pasta)
        os.replace(os.path.join(antiga, INDICE), os.path.join(antiga, INDICE + ".migrado"))
    except Exception:
        pass


def plano_sincronizacao(catalogo, pasta=PASTA_VIDEOS):
    """(baixar, tirar, atualizar): vídeos do catálogo que faltam aqui, os publicados que saíram do catálogo e os que só
    mudaram de nome/texto/lugar. Vídeos salvos neste computador (sem "origem": "publicado") nunca entram."""
    itens = ler(pasta)
    por_id = {x.get("id"): x for x in itens}
    removidos = _ler_removidos(pasta)
    ids_catalogo, baixar, atualizar = set(), [], []
    for c in catalogo.get("videos", []):
        if not isinstance(c, dict) or not c.get("id") or not _dentro(pasta, c.get("arquivo")) or not c.get("partes"):
            continue
        ids_catalogo.add(c["id"])
        local = por_id.get(c["id"])
        if local is not None and local.get("origem") != "publicado":
            continue
        if (local is not None and tem_arquivo(local, pasta) and local.get("sha256") == c.get("sha256")
                and _tamanho(caminho(local, pasta)) == c.get("tamanho")):
            if any(local.get(k) != c.get(k) for k in ("titulo", "descricao", "assunto", "principal")):
                atualizar.append(c)
            continue
        if _chave_item(c) in removidos:
            continue
        baixar.append(c)
    tirar = [x for x in itens if x.get("origem") == "publicado" and x.get("id") not in ids_catalogo]
    return baixar, tirar, atualizar


def _aplicar_tirar_atualizar(tirar, atualizar, pasta=PASTA_VIDEOS):
    itens = ler(pasta)
    if tirar:
        _fechar_players()
        ids = {x.get("id") for x in tirar}
        for x in tirar:
            _apagar(x.get("arquivo"), pasta)
        itens = [x for x in itens if not (x.get("origem") == "publicado" and x.get("id") in ids)]
    novos = {c["id"]: c for c in atualizar}
    for x in itens:
        c = novos.get(x.get("id"))
        if c is not None and x.get("origem") == "publicado":
            for k in ("titulo", "descricao", "assunto", "principal"):
                x[k] = c.get(k)
    gravar(itens, pasta)


def _authcfg():
    """Chave de acesso que o QGIS guarda para o repositório da Norte Agro ('' quando é público)."""
    try:
        from qgis.core import QgsSettings
        url = ""
        with open(os.path.join(RAIZ_PLUGIN, "repositorio_url.txt"), encoding="utf-8") as fp:
            for linha in fp:
                if linha.strip().lower().startswith("http"):
                    url = linha.strip()
                    break
        s = QgsSettings()
        s.beginGroup("app/plugin_repositories")
        try:
            for k in s.childGroups():
                if url and s.value(k + "/url", "", type=str) == url:
                    return s.value(k + "/authcfg", "", type=str) or ""
        finally:
            s.endGroup()
    except Exception:
        pass
    return ""


class _Avisos(QObject):
    terminou = pyqtSignal()


SINAL = _Avisos()
_SINC = {"tarefa": None, "busca": None, "relogio": None}
_PARTE_OK = re.compile(r"^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)*$")


def sincronizando():
    return _SINC.get("tarefa") is not None or _SINC.get("busca") is not None


def _nome_plugin():
    try:
        with open(os.path.join(RAIZ_PLUGIN, "metadata.txt"), encoding="utf-8") as fp:
            for linha in fp:
                if linha.lower().startswith("name="):
                    return linha.split("=", 1)[1].strip()
    except Exception:
        pass
    return NOME_PLUGIN


def _criar_tarefa(baixar, base_url, pasta, authcfg, tirados, avisar):
    from qgis.core import QgsTask

    class TarefaVideos(QgsTask):
        def __init__(self):
            super().__init__("Norte Agro: baixando os vídeos da Ajuda")
            self.baixar, self.base_url, self.pasta, self.authcfg = baixar, base_url, pasta, authcfg
            self.tirados, self.avisar = tirados, avisar
            self.prontos, self.erros = [], []

        def _parte(self, nome, tamanho):
            from qgis.core import QgsBlockingNetworkRequest
            from qgis.PyQt.QtNetwork import QNetworkRequest
            for _tentativa in range(3):
                if self.isCanceled():
                    raise InterruptedError
                req = QgsBlockingNetworkRequest()
                if self.authcfg:
                    req.setAuthCfg(self.authcfg)
                if int(req.get(QNetworkRequest(QUrl(self.base_url + nome)), True)) == 0:
                    conteudo = bytes(req.reply().content())
                    if tamanho is None or len(conteudo) == int(tamanho):
                        return conteudo
            raise IOError(f"não consegui baixar a parte {nome}")

        def run(self):
            total = max(1, sum(int(c.get("tamanho") or 0) for c in self.baixar))
            feito = 0
            for c in self.baixar:
                if self.isCanceled():
                    return False
                destino = _dentro(self.pasta, c["arquivo"])
                parcial = destino + ".baixando"
                try:
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    h, n = hashlib.sha256(), 0
                    with open(parcial, "wb") as fp:
                        for p in c["partes"]:
                            nome = str((p or {}).get("nome", ""))
                            if not _PARTE_OK.match(nome) or ".." in nome:
                                raise ValueError("lista de partes inválida")
                            conteudo = self._parte(nome, p.get("tamanho"))
                            fp.write(conteudo)
                            h.update(conteudo)
                            n += len(conteudo)
                            feito += len(conteudo)
                            self.setProgress(min(100.0, feito * 100.0 / total))
                    if n != int(c.get("tamanho") or -1) or (c.get("sha256") and h.hexdigest() != c["sha256"]):
                        raise IOError("o arquivo baixado não confere")
                    self.prontos.append((c, parcial, destino))
                except InterruptedError:
                    _remover_silencioso(parcial)
                    return False
                except Exception as exc:
                    _remover_silencioso(parcial)
                    self.erros.append(f"{c.get('titulo') or c.get('id')}: {exc}")
            return True

        def finished(self, resultado):
            _concluir(self)

    return TarefaVideos()


def _concluir(tarefa):
    """Na linha principal do QGIS: põe os vídeos baixados no lugar e no índice."""
    _SINC["tarefa"] = None
    novos = 0
    try:
        if tarefa.prontos:
            _fechar_players()
            itens = ler(tarefa.pasta)
            for c, parcial, destino in tarefa.prontos:
                try:
                    os.replace(parcial, destino)
                except Exception as exc:
                    _remover_silencioso(parcial)
                    tarefa.erros.append(f"{c.get('titulo') or c.get('id')}: {exc}")
                    continue
                antigo = next((x for x in itens if x.get("id") == c["id"]), None)
                if antigo is not None:
                    itens.remove(antigo)
                    velho = antigo.get("arquivo")
                    if (velho and os.path.normcase(velho) != os.path.normcase(c["arquivo"])
                            and not any(x.get("arquivo") == velho for x in itens)):
                        _apagar(velho, tarefa.pasta)
                novo = {k: c.get(k) for k in ("id", "assunto", "principal", "titulo", "descricao", "arquivo", "tamanho",
                                              "sha256")}
                novo.update({"origem": "publicado", "adicionado": datetime.now().strftime("%d/%m/%Y %H:%M")})
                itens.append(novo)
                novos += 1
            gravar(itens, tarefa.pasta)
    finally:
        SINAL.terminou.emit()
    if tarefa.avisar:
        partes = []
        if novos:
            partes.append(f"{novos} vídeo(s) novo(s) pronto(s)")
        if tarefa.tirados:
            partes.append(f"{tarefa.tirados} vídeo(s) saíram")
        if partes:
            _avisar(f"{_nome_plugin()} - vídeos da Ajuda atualizados: " + ", ".join(partes) + ". Veja em Ajuda (?).")
        if tarefa.erros:
            _avisar(f"{_nome_plugin()}: {len(tarefa.erros)} vídeo(s) da Ajuda não baixaram (sem internet?). O plugin tenta "
                    "de novo daqui a pouco, ou clique em \"Baixar agora\" na Ajuda.", aviso=True)


def _avisar(texto, aviso=False):
    try:
        from qgis.core import Qgis
        from qgis.utils import iface
        nivel = getattr(Qgis, "Warning" if aviso else "Success", None)
        if nivel is None:
            nivel = Qgis.MessageLevel.Warning if aviso else Qgis.MessageLevel.Success
        iface.messageBar().pushMessage("Norte Agro", texto, nivel, 10)
    except Exception:
        pass


def sincronizar(avisar=True, pasta=PASTA_VIDEOS, pasta_pacote=PASTA_PACOTE, manual=False):
    """Busca na internet a lista de vídeos publicados (sem internet, usa a última conhecida) e então tira os que saíram
    e baixa, em segundo plano, os que faltam. Devolve True se começou a buscar ou a baixar."""
    if sincronizando():
        return False
    if os.path.normcase(os.path.abspath(pasta)) == os.path.normcase(os.path.abspath(PASTA_VIDEOS)):
        _migrar_pasta_antiga(pasta, pasta_pacote)
    atual = ler_catalogo(pasta_pacote, pasta)
    url = str(atual.get("catalogo_url") or "")
    if not url.lower().startswith(("https://", "file:")):
        return _sincronizar_com(atual, avisar, pasta, manual)
    try:
        from qgis.core import QgsNetworkContentFetcher
        import time
        busca = QgsNetworkContentFetcher()
        _SINC["busca"] = busca

        def chegou():
            _SINC["busca"] = None
            online = None
            try:
                resposta = busca.reply()
                if resposta is not None and int(resposta.error()) == 0:
                    texto = busca.contentAsString()
                    if len(texto) < 5_000_000:
                        dados = json.loads(texto)
                        if _catalogo_valido(dados):
                            online = dados
            except Exception:
                online = None
            if online is None:   # sem internet: não tenta baixar vídeo agora
                if manual:
                    _avisar("Não consegui buscar a lista de vídeos (sem internet?). Tente de novo mais tarde.", aviso=True)
                SINAL.terminou.emit()
                return
            try:
                os.makedirs(pasta, exist_ok=True)
                tmp = os.path.join(pasta, CATALOGO_ONLINE + ".tmp")
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(online, fp, ensure_ascii=False)
                os.replace(tmp, os.path.join(pasta, CATALOGO_ONLINE))
            except Exception:
                pass
            _sincronizar_com(ler_catalogo(pasta_pacote, pasta) or online, avisar, pasta, manual)

        busca.finished.connect(chegou)
        separador = "&" if "?" in url else "?"
        busca.fetchContent(QUrl(f"{url}{separador}t={int(time.time() // 60)}"), _authcfg())
        SINAL.terminou.emit()
        return True
    except Exception:
        _SINC["busca"] = None
        return _sincronizar_com(atual, avisar, pasta, manual)


def _sincronizar_com(catalogo, avisar, pasta, manual=False):
    if not catalogo:
        if manual:
            _avisar("Esta versão do plugin não tem lista de vídeos publicados.")
        return False
    baixar, tirar, atualizar = plano_sincronizacao(catalogo, pasta)
    if tirar or atualizar:
        _aplicar_tirar_atualizar(tirar, atualizar, pasta)
        SINAL.terminou.emit()
    base = str(catalogo.get("base_url") or "")
    if not base.endswith("/"):
        base += "/"
    if not baixar or not base.lower().startswith(("https://", "file:")):
        if tirar and avisar:
            _avisar(f"{_nome_plugin()} - vídeos da Ajuda atualizados: {len(tirar)} vídeo(s) saíram.")
        elif manual and not tirar and not atualizar:
            _avisar("Os vídeos da Ajuda já estão em dia.")
        return False
    if avisar:
        total = sum(int(c.get("tamanho") or 0) for c in baixar)
        _avisar(f"{_nome_plugin()}: {len(baixar)} vídeo(s) novo(s) na Ajuda. Baixando em segundo plano ({_mb(total)}).")
    from qgis.core import QgsApplication
    tarefa = _criar_tarefa(baixar, base, pasta, _authcfg(), len(tirar), avisar)
    _SINC["tarefa"] = tarefa
    QgsApplication.taskManager().addTask(tarefa)
    SINAL.terminou.emit()
    return True


def iniciar_sincronizacao(atraso_ms=15000):
    """Chamado ao carregar o plugin: confere os vídeos depois que o QGIS terminar de abrir e a cada 2 horas."""
    def rodar():
        try:
            sincronizar()
        except Exception:
            pass
    QTimer.singleShot(atraso_ms, rodar)
    if _SINC.get("relogio") is None:
        relogio = QTimer()
        relogio.setInterval(INTERVALO_CONFERENCIA_MS)
        relogio.timeout.connect(rodar)
        relogio.start()
        _SINC["relogio"] = relogio


def parar_sincronizacao():
    relogio = _SINC.get("relogio")
    if relogio is not None:
        try:
            relogio.stop()
        except Exception:
            pass
        _SINC["relogio"] = None
    t = _SINC.get("tarefa")
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass


# ---------------------------------------------------------------- coluna "Vídeos deste assunto"
ESTILO_BOTAO = ("QPushButton{padding:4px 6px;border:1px solid #C9CEC0;border-radius:5px;background:#FFFFFF;}"
                "QPushButton:hover{border-color:#7DA63F;background:#F4F8EE;}")
ESTILO_PRINCIPAL = (f"QPushButton{{padding:6px 8px;border:none;border-radius:5px;background:{VERDE};color:white;"
                    f"font-weight:600;}} QPushButton:hover{{background:{VERDE_CLARO};}}")


def _botao(texto, principal=False, dica=""):
    b = QPushButton(texto)
    b.setStyleSheet(ESTILO_PRINCIPAL if principal else ESTILO_BOTAO)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if dica:
        b.setToolTip(dica)
    return b


class PainelVideos(QWidget):
    """Coluna da direita da Ajuda. `assuntos` = [(chave, título)]. Emite `alterado` quando um vídeo entra ou sai."""
    alterado = pyqtSignal()

    def __init__(self, assuntos, parent=None, pasta=PASTA_VIDEOS, raiz_plugin=RAIZ_PLUGIN, pasta_pacote=PASTA_PACOTE):
        super().__init__(parent)
        self.assuntos = list(assuntos)
        self.pasta = pasta
        self.raiz_plugin = raiz_plugin
        self.pasta_pacote = pasta_pacote   # senha (acesso.json) e lista dos vídeos publicados (catalogo.json)
        if os.path.normcase(os.path.abspath(pasta)) == os.path.normcase(os.path.abspath(PASTA_VIDEOS)):
            _migrar_pasta_antiga(pasta, pasta_pacote)
        self.chave = ""
        self.titulo = ""
        self._liberado = False   # senha certa nesta janela da Ajuda
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 0, 0, 0); lay.setSpacing(8)
        cab = QLabel("Vídeos deste assunto")
        cab.setStyleSheet(f"font-size:13pt; font-weight:700; color:{VERDE};")
        lay.addWidget(cab)
        self.nome_assunto = QLabel(""); self.nome_assunto.setWordWrap(True); self.nome_assunto.setStyleSheet("color:#374151;")
        lay.addWidget(self.nome_assunto)
        self.area = QScrollArea(); self.area.setWidgetResizable(True); self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conteudo = QWidget(); self.cl = QVBoxLayout(self.conteudo); self.cl.setContentsMargins(0, 0, 0, 0)
        self.cl.setSpacing(8)
        self.area.setWidget(self.conteudo)
        lay.addWidget(self.area, 1)
        self.b_mais = _botao("+ Mais um vídeo", dica="Acrescenta um vídeo fora dos lugares: neste assunto (embaixo do "
                                                    "principal) ou em Vídeos extras.")
        self.b_mais.clicked.connect(self.mais_um)
        lay.addWidget(self.b_mais)
        linha = QFrame(); linha.setFrameShape(QFrame.Shape.HLine); linha.setStyleSheet("color:#E5E7EB;"); lay.addWidget(linha)
        self.contagem = QLabel(""); self.contagem.setWordWrap(True); self.contagem.setStyleSheet("color:#6B7280;")
        lay.addWidget(self.contagem)
        rod = QHBoxLayout()
        b_pasta = _botao("Abrir a pasta", dica="Abre a pasta dos vídeos deste plugin (uma pasta para cada assunto).")
        b_pasta.clicked.connect(self.abrir_pasta)
        b_senha = _botao("Mudar a senha...", dica="Muda a senha de salvar/apagar vídeos. Precisa do arquivo "
                                                     "IDENTIFICADOR (.naid).")
        b_senha.clicked.connect(self.mudar_senha)
        rod.addWidget(b_pasta, 1); rod.addWidget(b_senha, 1)
        lay.addLayout(rod)
        SINAL.terminou.connect(self._sincronizou)

    def _sincronizou(self):
        try:
            if self.chave:
                self.mostrar(self.chave, self.titulo)
            self.alterado.emit()
        except RuntimeError:   # a janela da Ajuda já foi fechada
            pass

    def _baixar_agora(self):
        sincronizar(pasta=self.pasta, pasta_pacote=self.pasta_pacote, manual=True)
        self.mostrar(self.chave, self.titulo)

    # --- senha
    def _liberar(self, acao):
        """True se pode mexer nos vídeos. Pede a senha uma vez por janela da Ajuda."""
        if self._liberado:
            return True
        dlg = DialogoSenha(self.window(), "Senha dos vídeos",
                           f"Para {acao} é preciso a senha dos vídeos da Ajuda.")
        if not dlg.exec():
            return False
        if not senha_confere(dlg.senha(), self.pasta_pacote):
            if acesso_danificado(self.pasta_pacote):
                QMessageBox.warning(self.window(), "Senha dos vídeos",
                                    "O arquivo da senha (videos\\acesso.json) está danificado. Nada foi alterado.\n"
                                    "Use \"Mudar a senha...\" com o arquivo identificador para criar uma senha nova.")
            else:
                QMessageBox.warning(self.window(), "Senha dos vídeos", "Senha errada. Nada foi alterado.")
            return False
        self._liberado = True
        return True

    def mudar_senha(self):
        r = QMessageBox.information(
            self.window(), "Mudar a senha dos vídeos",
            "Para mudar a senha é preciso o arquivo IDENTIFICADOR (.naid).\n\nClique em OK e escolha o arquivo.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Ok:
            return
        arq, _ = QFileDialog.getOpenFileName(self.window(), "Escolha o arquivo identificador", os.path.expanduser("~"),
                                             EXT_IDENTIFICADOR)
        if not arq:
            return
        if not identificador_confere(arq, self.pasta_pacote):
            QMessageBox.warning(self.window(), "Mudar a senha dos vídeos",
                                "Este arquivo não é o identificador destes plugins. A senha NÃO foi mudada.")
            return
        dlg = DialogoSenha(self.window(), "Mudar a senha dos vídeos", "Identificador conferido. Digite a senha nova.", nova=True)
        if not dlg.exec():
            return
        try:
            trocar_senha(dlg.senha(), self.pasta_pacote)
        except Exception as exc:
            QMessageBox.warning(self.window(), "Mudar a senha dos vídeos", f"Não foi possível gravar a senha nova:\n{exc}")
            return
        self._liberado = True
        QMessageBox.information(self.window(), "Mudar a senha dos vídeos",
                                "Senha mudada neste plugin.\n\nOs colegas recebem a senha nova na próxima versão do "
                                "plugin publicada.\n"
                                "Atenção: o outro plugin (Uso do Solo / Layout) tem a senha dele; mude lá também.")

    # --- pastas
    def _titulo_de(self, chave):
        if chave == EXTRAS:
            return "Vídeos extras"
        return next((t for c, t in self.assuntos if c == chave), chave)

    def pasta_rel(self, chave):
        """Pasta do assunto, relativa a videos/ (ex.: "Calcular áreas")."""
        return nome_pasta(self._titulo_de(chave))

    def pasta_completa(self, chave):
        return os.path.join(self.pasta, self.pasta_rel(chave))

    # --- montagem
    def mostrar(self, chave, titulo):
        self.chave, self.titulo = chave, titulo
        self.nome_assunto.setText(titulo)
        while self.cl.count():
            w = self.cl.takeAt(0).widget()
            if w is not None:
                w.hide(); w.setParent(None); w.deleteLater()
        itens = ler(self.pasta)
        principal, extras = do_assunto(chave, itens, self.pasta)
        catalogo = ler_catalogo(self.pasta_pacote, self.pasta)
        faltam = [c for c in plano_sincronizacao(catalogo, self.pasta)[0] if c.get("assunto") == chave] if catalogo else []
        principal_faltando = next((c for c in faltam if c.get("principal")), None)
        if chave != EXTRAS:
            if principal is None and principal_faltando is not None:
                self.cl.addWidget(self._cartao_pendente(principal_faltando))
            else:
                self.cl.addWidget(self._cartao_principal(principal))
        elif not extras and not faltam:
            vazio = QLabel("Nenhum vídeo extra ainda. Use \"+ Mais um vídeo\" para acrescentar vídeos que não são de um "
                           "assunto só (ex.: um projeto completo do começo ao fim).")
            vazio.setWordWrap(True); vazio.setStyleSheet(self._estilo_vazio()); self.cl.addWidget(vazio)
        for x in extras:
            self.cl.addWidget(self._cartao_extra(x))
        ids_aqui = {x.get("id") for x in extras}
        for c in faltam:
            if not c.get("principal") and c.get("id") not in ids_aqui:
                self.cl.addWidget(self._cartao_pendente(c))
        self.cl.addStretch(1)
        feitos = assuntos_com_video(itens, self.pasta)
        n = sum(1 for c, _t in self.assuntos if c in feitos)
        extras_total = len([x for x in itens if not x.get("principal") and tem_arquivo(x, self.pasta)])
        self.contagem.setText(f"Assuntos com vídeo: {n} de {len(self.assuntos)}"
                              + (f"  ·  vídeos a mais: {extras_total}" if extras_total else "")
                              + ("\nConferindo/baixando os vídeos publicados..." if sincronizando() else ""))

    def _cartao_pendente(self, c):
        """Vídeo que veio na atualização e ainda não está neste computador."""
        f, v = self._cartao(False)
        t = QLabel("<b>%s</b>" % ("VÍDEO PRINCIPAL" if c.get("principal") else "VÍDEO A MAIS"))
        t.setStyleSheet("color:#6B7280; font-size:8pt;"); v.addWidget(t)
        n = QLabel(c.get("titulo") or ""); n.setWordWrap(True); n.setStyleSheet("font-weight:600;"); v.addWidget(n)
        if sincronizando():
            texto = f"Baixando este vídeo ({_mb(int(c.get('tamanho') or 0))}). Ele aparece aqui quando terminar."
        else:
            texto = (f"Este vídeo foi publicado e ainda não foi baixado neste computador "
                     f"({_mb(int(c.get('tamanho') or 0))}). Precisa de internet.")
        aviso = QLabel(texto); aviso.setWordWrap(True); aviso.setStyleSheet(self._estilo_vazio()); v.addWidget(aviso)
        if not sincronizando():
            b = _botao("Baixar agora", principal=True, dica="Busca e baixa os vídeos publicados que faltam neste computador.")
            b.clicked.connect(self._baixar_agora)
            v.addWidget(b)
        return f

    @staticmethod
    def _estilo_vazio():
        return "background:#F3F4F6;color:#4B5563;border:1px dashed #9CA3AF;border-radius:8px;padding:12px;"

    def _cartao(self, destaque):
        f = QFrame()
        f.setStyleSheet("QFrame#cartao{background:#FFFFFF;border:1px solid %s;border-radius:8px;}"
                        % ("#7DA63F" if destaque else "#E5E7EB"))
        f.setObjectName("cartao")
        v = QVBoxLayout(f); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(6)
        return f, v

    def _textos(self, v, item, rotulo):
        t = QLabel(f"<b>{rotulo}</b>"); t.setStyleSheet("color:#6B7280; font-size:8pt;"); v.addWidget(t)
        n = QLabel(item.get("titulo") or ""); n.setWordWrap(True); n.setStyleSheet("font-weight:600;"); v.addWidget(n)
        if item.get("descricao"):
            d = QLabel(item["descricao"]); d.setWordWrap(True); d.setStyleSheet("color:#374151;"); v.addWidget(d)
        rel = os.path.normpath(item.get("arquivo", ""))
        publicado = item.get("origem") == "publicado"
        if tem_arquivo(item, self.pasta):
            info = ("Veio na atualização" if publicado else "Salvo neste computador") + \
                   f": {rel}  ·  {_mb(_tamanho(caminho(item, self.pasta)))}"
        elif publicado:
            info = f"O arquivo {rel} sumiu: ele é baixado de novo (\"Baixar agora\" ou ao abrir o QGIS)"
        else:
            info = f"O arquivo não está mais em {rel} - salve o vídeo de novo"
        i = QLabel(info); i.setWordWrap(True); i.setStyleSheet("color:#6B7280; font-size:8pt;")
        i.setToolTip(caminho(item, self.pasta)); v.addWidget(i)

    def _cartao_principal(self, item):
        f, v = self._cartao(bool(item))
        if not item:
            t = QLabel("<b>VÍDEO PRINCIPAL</b>"); t.setStyleSheet("color:#6B7280; font-size:8pt;"); v.addWidget(t)
            vazio = QLabel("○  Este assunto ainda não tem vídeo.\nGrave com o seu programa e salve aqui: o vídeo vai para "
                           f"a pasta {self.pasta_rel(self.chave)} dos vídeos e chega aos colegas quando você "
                           "publicar os vídeos.")
            vazio.setWordWrap(True); vazio.setStyleSheet(self._estilo_vazio()); v.addWidget(vazio)
            b = _botao("Salvar vídeo no plugin...", principal=True,
                       dica="Escolha o vídeo gravado: ele é copiado para a pasta deste assunto, na pasta dos vídeos.")
            b.clicked.connect(lambda: self.anexar_principal(None))
            v.addWidget(b)
            return f
        self._textos(v, item, "● VÍDEO PRINCIPAL")
        b1 = _botao("▶  Assistir", principal=True); b1.clicked.connect(lambda: assistir(item, self.window(), self.pasta))
        v.addWidget(b1)
        h2 = QHBoxLayout(); h2.setSpacing(4)
        b2 = _botao("Trocar...", dica="Põe outro arquivo no lugar deste vídeo."); b2.clicked.connect(lambda: self.anexar_principal(item))
        b3 = _botao("Editar", dica="Muda o nome e o texto \"para que serve\"."); b3.clicked.connect(lambda: self.editar(item))
        b4 = _botao("Apagar", dica="Apaga o vídeo da pasta dos vídeos."); b4.clicked.connect(lambda: self.remover(item))
        for b in (b2, b3, b4):
            h2.addWidget(b, 1)
        v.addLayout(h2)
        b5 = _botao("Mostrar na pasta", dica="Abre o Explorador com o arquivo selecionado.")
        b5.clicked.connect(lambda: mostrar_na_pasta(caminho(item, self.pasta)))
        v.addWidget(b5)
        return f

    def _cartao_extra(self, item):
        f, v = self._cartao(False)
        self._textos(v, item, "VÍDEO A MAIS")
        b1 = _botao("▶  Assistir", principal=True); b1.clicked.connect(lambda: assistir(item, self.window(), self.pasta))
        v.addWidget(b1)
        h = QHBoxLayout(); h.setSpacing(4)
        b2 = _botao("Editar", dica="Muda o nome, o texto e onde o vídeo aparece."); b2.clicked.connect(lambda: self.editar(item, mudar_assunto=True))
        b3 = _botao("Apagar", dica="Apaga o vídeo da pasta dos vídeos."); b3.clicked.connect(lambda: self.remover(item))
        b4 = _botao("Pasta", dica="Abre o Explorador com o arquivo selecionado.")
        b4.clicked.connect(lambda: mostrar_na_pasta(caminho(item, self.pasta)))
        h.addWidget(b2, 1); h.addWidget(b3, 1); h.addWidget(b4, 1)
        v.addLayout(h)
        return f

    # --- ações
    def _guardar(self, origem, base, assunto):
        """Copia `origem` para videos/<pasta do assunto>/<base>.<ext>. Devolve o caminho relativo a videos/ ou ''."""
        sub = self.pasta_rel(assunto)
        pasta = os.path.join(self.pasta, sub)
        os.makedirs(pasta, exist_ok=True)
        ext = os.path.splitext(origem)[1].lower() or ".mp4"
        nome = base + ext
        destino = os.path.join(pasta, nome)
        if os.path.normcase(os.path.abspath(origem)) == os.path.normcase(os.path.abspath(destino)):
            return f"{sub}/{nome}"
        if os.path.exists(destino):
            n = 2
            while os.path.exists(os.path.join(pasta, f"{base}_{n}{ext}")):
                n += 1
            nome = f"{base}_{n}{ext}"; destino = os.path.join(pasta, nome)
        if copiar_com_andamento(origem, destino, self.window()):
            return f"{sub}/{nome}"
        try:
            if not os.listdir(pasta):
                os.rmdir(pasta)
        except Exception:
            pass
        return ""

    def anexar_principal(self, atual):
        if not self._liberar("trocar o vídeo" if atual else "salvar um vídeo"):
            return
        dlg = FormularioVideo(self.window(), "Trocar o vídeo" if atual else "Salvar vídeo no plugin",
                              nome=(atual or {}).get("titulo") or nome_pasta(self.titulo),
                              descricao=(atual or {}).get("descricao", ""), assunto=self.chave, pasta_de=self._mostra_pasta)
        if not dlg.exec():
            return
        d = dlg.dados()
        _fechar_players()
        nome = self._guardar(d["arquivo_origem"], _slug(self.chave), self.chave)
        if not nome:
            return
        itens = ler(self.pasta)
        antigo = next((x for x in itens if x.get("assunto") == self.chave and x.get("principal")), None)
        if antigo is not None:
            if antigo.get("arquivo") and antigo["arquivo"] != nome:
                _apagar(antigo["arquivo"], self.pasta)
            itens.remove(antigo)
        itens.append({"id": self.chave, "assunto": self.chave, "principal": True, "titulo": d["titulo"],
                      "descricao": d["descricao"], "arquivo": nome, "tamanho": _tamanho(caminho({"arquivo": nome}, self.pasta)),
                      "adicionado": datetime.now().strftime("%d/%m/%Y %H:%M")})
        gravar(itens, self.pasta)
        self.mostrar(self.chave, self.titulo); self.alterado.emit()

    def mais_um(self):
        if not self._liberar("adicionar um vídeo"):
            return
        dlg = FormularioVideo(self.window(), "Mais um vídeo", nome="", assuntos=self.assuntos,
                              assunto=self.chave if self.chave else EXTRAS, pasta_de=self._mostra_pasta)
        if not dlg.exec():
            return
        d = dlg.dados()
        assunto = d["assunto"] or EXTRAS
        itens = ler(self.pasta)
        novo_id = _novo_id(assunto, itens)
        nome = self._guardar(d["arquivo_origem"], _slug(d["titulo"]), assunto)
        if not nome:
            return
        itens.append({"id": novo_id, "assunto": assunto, "principal": False, "titulo": d["titulo"],
                      "descricao": d["descricao"], "arquivo": nome, "tamanho": _tamanho(caminho({"arquivo": nome}, self.pasta)),
                      "adicionado": datetime.now().strftime("%d/%m/%Y %H:%M")})
        gravar(itens, self.pasta)
        self.mostrar(self.chave, self.titulo); self.alterado.emit()

    def editar(self, item, mudar_assunto=False):
        if not self._liberar("editar o vídeo"):
            return
        dlg = FormularioVideo(self.window(), "Editar vídeo", nome=item.get("titulo", ""), descricao=item.get("descricao", ""),
                              assuntos=self.assuntos if mudar_assunto else None, assunto=item.get("assunto", ""),
                              pedir_arquivo=False)
        if not dlg.exec():
            return
        d = dlg.dados()
        itens = ler(self.pasta)
        for x in itens:
            if x.get("id") == item.get("id") and x.get("arquivo") == item.get("arquivo"):
                x["titulo"], x["descricao"] = d["titulo"], d["descricao"]
                if mudar_assunto and d["assunto"] and d["assunto"] != x.get("assunto"):
                    x["arquivo"] = self._mover(x.get("arquivo", ""), d["assunto"])
                    x["assunto"] = d["assunto"]
                    x["id"] = _novo_id(d["assunto"], itens)
        gravar(itens, self.pasta)
        self.mostrar(self.chave, self.titulo); self.alterado.emit()

    def _mostra_pasta(self, chave):
        return os.path.normpath(self.pasta_completa(chave or EXTRAS))

    def _mover(self, arquivo, assunto_novo):
        """Leva o arquivo para a pasta do outro assunto. Devolve o novo caminho relativo (ou o antigo, se não deu)."""
        if not arquivo:
            return arquivo
        _fechar_players()
        origem = caminho({"arquivo": arquivo}, self.pasta)
        sub = self.pasta_rel(assunto_novo)
        os.makedirs(os.path.join(self.pasta, sub), exist_ok=True)
        nome = os.path.basename(origem)
        base, ext = os.path.splitext(nome)
        destino = os.path.join(self.pasta, sub, nome); n = 2
        while os.path.exists(destino):
            nome = f"{base}_{n}{ext}"; destino = os.path.join(self.pasta, sub, nome); n += 1
        try:
            os.replace(origem, destino)
        except Exception as exc:
            QMessageBox.warning(self.window(), "Vídeos da ajuda", f"O vídeo não pôde mudar de pasta:\n{exc}")
            return arquivo
        velha = os.path.dirname(origem)
        try:
            if os.path.isdir(velha) and not os.listdir(velha) and os.path.normcase(velha) != os.path.normcase(self.pasta):
                os.rmdir(velha)
        except Exception:
            pass
        return f"{sub}/{nome}"

    def remover(self, item):
        if not self._liberar("apagar o vídeo"):
            return
        alvo = caminho(item, self.pasta)
        r = QMessageBox.question(self.window(), "Apagar vídeo",
                                 f"Apagar o vídeo \"{item.get('titulo')}\"?\n\nO arquivo será apagado da pasta dos vídeos:\n"
                                 f"{alvo}\n\nO arquivo original, onde você gravou, continua onde estava.")
        if r != QMessageBox.StandardButton.Yes:
            return
        _fechar_players()
        marca = dict(item)
        marca["tamanho"] = _tamanho(alvo) or item.get("tamanho")
        _marcar_removido(marca, self.pasta)
        itens = [x for x in ler(self.pasta) if not (x.get("id") == item.get("id") and x.get("arquivo") == item.get("arquivo"))]
        if item.get("arquivo") and not any(x.get("arquivo") == item["arquivo"] for x in itens):
            if not _apagar(item["arquivo"], self.pasta):
                QMessageBox.warning(self.window(), "Apagar vídeo",
                                    "O Windows não deixou apagar o arquivo agora (ele pode estar aberto em um player). "
                                    f"Feche o player e apague à mão:\n{alvo}")
        gravar(itens, self.pasta)
        self.mostrar(self.chave, self.titulo); self.alterado.emit()

    def abrir_pasta(self):
        os.makedirs(self.pasta, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.pasta))
