# -*- coding: utf-8 -*-
"""v3.9.6: tela única dos modelos do escritório.

Aba 1 - Estrutura de pastas: pastas/subpastas extras + camadas que o modelo cria + tema de cores.
Aba 2 - Temas de cores: guarda as cores atuais das camadas do projeto com um nome e aplica depois.
Aba 3 - Tabela: quadros, ordem, lado, títulos, nomes das linhas, cores, fonte, título, logo e colunas extras.
"""
from . import compat
import copy
import os
import re
import tempfile
from datetime import datetime

from qgis.PyQt.QtCore import QSize, Qt, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPen, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QMenu, QSizePolicy, QStyle, QLabel, QLineEdit, QListWidget, QListWidgetItem, QScrollArea, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import QgsProject, QgsSymbolLayerUtils
from qgis.gui import QgsColorButton

from . import modelos as M
from .compat import QShortcut
from .catalogo import EXPLICACAO_LUGAR, LUGARES_QUADRO
from .estilo import (
    alertar, botao_principal, botao_secundario, cabecalho, confirmar, preparar_dialogo, secao, sucesso,
)

TEXTO_LUGAR = {x[0]: x[1] for x in LUGARES_QUADRO}
TIPOS = {"P": "Polígono", "L": "Linha", "Pt": "Ponto"}


def _sub(texto):
    lb = QLabel(texto); lb.setWordWrap(True); lb.setProperty("naSubtitle", True)
    lb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum); return lb


def _altura(tabela, px):
    """A folha de estilo do plugin impõe min-height; a altura fixa precisa ir pelo próprio estilo."""
    tabela.setFixedHeight(px)
    tabela.setStyleSheet(f"QTableWidget {{ min-height:{px}px; max-height:{px}px; }}")


class _Aba(QWidget):
    """Lista de modelos à esquerda + editor à direita, com aviso de alterações não salvas."""
    TITULO_LISTA = "Modelos"

    def __init__(self, tela):
        super().__init__(tela); self.tela = tela; self.plugin = tela.plugin
        self.atual = None; self.nome_antigo = None; self._foto = None; self._carregando = False
        raiz = QHBoxLayout(self); raiz.setContentsMargins(0, 8, 0, 0); raiz.setSpacing(12)
        esq = QVBoxLayout(); raiz.addLayout(esq, 0)
        esq.addWidget(secao(self.TITULO_LISTA))
        self.lista = QListWidget(); self.lista.setMinimumWidth(220); self.lista.setMaximumWidth(280)
        self.lista.currentItemChanged.connect(self._trocar); esq.addWidget(self.lista, 1)
        self.botoes_lista = QHBoxLayout(); esq.addLayout(self.botoes_lista)
        self.dir = QVBoxLayout(); raiz.addLayout(self.dir, 1)

    # ----- a implementar nas abas
    def itens(self): return []
    def carregar(self, modelo): pass
    def coletar(self): return {}

    def preencher_lista(self, selecionar=None):
        self._carregando = True; self.lista.clear()
        for m in self.itens():
            it = QListWidgetItem(m["nome"] + ("  (fixo)" if m.get("fixo") else "")); it.setData(Qt.ItemDataRole.UserRole, m["nome"])
            if m.get("fixo"):
                f = it.font(); f.setItalic(True); it.setFont(f)
            self.lista.addItem(it)
        self._carregando = False
        alvo = selecionar or (self.atual or {}).get("nome")
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == alvo:
                self.lista.setCurrentRow(i); return
        if self.lista.count():
            self.lista.setCurrentRow(0)
        else:
            self.mostrar(None)

    def _alterado(self):
        try:
            return self.atual is not None and self._foto is not None and self.coletar() != self._foto
        except Exception:
            return False

    def pode_sair(self):
        if not self._alterado():
            return True
        return confirmar(self, "Alterações não salvas", f'Descartar as alterações em "{(self.atual or {}).get("nome", "")}"?', "Descartar")

    def _trocar(self, novo, antigo):
        if self._carregando:
            return
        if antigo is not None and not self.pode_sair():
            self._carregando = True; self.lista.setCurrentItem(antigo); self._carregando = False; return
        nome = novo.data(Qt.ItemDataRole.UserRole) if novo else None
        self.mostrar(next((copy.deepcopy(m) for m in self.itens() if m["nome"] == nome), None), nome)

    def mostrar(self, modelo, nome_antigo=None):
        self.atual = modelo; self.nome_antigo = nome_antigo
        self._carregando = True
        try:
            self.carregar(modelo)
        finally:
            self._carregando = False
        self._foto = self.coletar() if modelo is not None else None

    def novo_de(self, base, sufixo=""):
        if not self.pode_sair():
            return
        m = copy.deepcopy(base); m.pop("fixo", None); m.pop("autor", None); m.pop("data", None)
        nomes = {x["nome"].casefold() for x in self.itens()}
        nome = (base.get("nome", "Modelo") + sufixo) if sufixo else "Novo modelo"
        n, final = 2, nome
        while final.casefold() in nomes:
            final = f"{nome} {n}"; n += 1
        m["nome"] = final
        self._carregando = True; self.lista.clearSelection(); self.lista.setCurrentRow(-1); self._carregando = False
        self.mostrar(m, None); self._foto = {}  # novo: sempre conta como alterado até salvar

    def excluir(self, func):
        if not self.atual or self.atual.get("fixo"):
            return
        if self.nome_antigo is None:
            self.preencher_lista(); return
        if not confirmar(self, "Excluir modelo", f'Excluir "{self.nome_antigo}"?', "Excluir", destrutivo=True):
            return
        try:
            func(self.nome_antigo)
        except Exception as exc:
            alertar(self, "Excluir modelo", "Nada foi alterado.", str(exc)); return
        self.atual = None; self._foto = None; self.preencher_lista()

    def salvar(self, func):
        if not self.atual or self.atual.get("fixo"):
            return False
        dados = self.coletar()
        try:
            func(dados, self.nome_antigo)
        except Exception as exc:
            alertar(self, "Salvar modelo", "O modelo não foi salvo.", str(exc)); return False
        self._foto = None; self.atual = dados; self.preencher_lista(dados["nome"])
        sucesso(self, "Modelo salvo", f'"{dados["nome"]}" foi salvo no plugin.'); return True


# =========================================================== Estrutura de pastas
R_TIPO = Qt.ItemDataRole.UserRole + 1   # "mae", "pasta" (do usuário), "plugin" (shapefiles/kml/projetos), "camada"
R_MAPA = Qt.ItemDataRole.UserRole + 2   # True na pasta onde ficam shapefiles, kml e projetos


class ArvorePastas(QTreeWidget):
    """v0.0.0: árvore do modelo de pastas, a partir da pasta mãe (nome da fazenda). Cada subpasta tem uma linha
    ligando-a à pasta de cima, em quantos níveis o usuário quiser. As linhas são desenhadas aqui (não dependem do
    estilo do QGIS). Coluna 2: explicação curta das pastas especiais."""
    COR_LINHA = "#8C9A8C"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2); self.setHeaderHidden(True); self.setRootIsDecorated(False)
        self.setItemsExpandable(True); self.setExpandsOnDoubleClick(False)
        self.setIndentation(24); self.setUniformRowHeights(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setColumnWidth(0, 300); self.header().setStretchLastSection(True)

    def drawBranches(self, painter, rect, index):
        item = self.itemFromIndex(index)
        if item is None or item.parent() is None:
            return
        tem_depois = []   # do nível 1 até o item: o nó desse nível tem irmão abaixo?
        it = item
        while it.parent() is not None:
            pai = it.parent(); tem_depois.append(pai.indexOfChild(it) < pai.childCount() - 1); it = pai
        tem_depois.reverse()
        ind = self.indentation(); prof = len(tem_depois); meio = rect.center().y()
        painter.save(); pen = QPen(QColor(self.COR_LINHA)); pen.setWidth(1); painter.setPen(pen)
        for nivel, depois in enumerate(tem_depois, start=1):
            x = rect.left() + (nivel - 1) * ind + ind // 2
            if nivel < prof:
                if depois:
                    painter.drawLine(x, rect.top(), x, rect.bottom())
            else:
                painter.drawLine(x, rect.top(), x, rect.bottom() if depois else meio)
                painter.drawLine(x, meio, rect.left() + nivel * ind - 2, meio)
        painter.restore()


class AbaPastas(_Aba):
    TITULO_LISTA = "Modelos de pastas"

    def __init__(self, tela):
        super().__init__(tela)
        for texto, func in (("Novo", lambda: self.novo_de(M.modelo_pasta_vazio())), ("Duplicar", lambda: self.atual and self.novo_de(self.atual, " (cópia)")),
                            ("Excluir", lambda: self.excluir(M.remover_modelo_pasta))):
            b = botao_secundario(texto, self); b.clicked.connect(func); self.botoes_lista.addWidget(b)
        # v0.0.0: editor com rolagem (a árvore de pastas é alta); em telas grandes cabe tudo sem rolar
        self.rolar = QScrollArea(); self.rolar.setWidgetResizable(True); self.rolar.setFrameShape(QScrollArea.NoFrame)
        self.editor = QWidget(); self.rolar.setWidget(self.editor); ed = QVBoxLayout(self.editor); ed.setContentsMargins(0, 0, 8, 0)
        form = QFormLayout(); self.nome = QLineEdit(); form.addRow("Nome do modelo:", self.nome); ed.addLayout(form)
        ed.addWidget(secao("Pastas"))
        self.raiz = None
        self.pastas = ArvorePastas()
        self.pastas.setStyleSheet("QTreeWidget { min-height: 290px; }")  # a folha de estilo do plugin impõe min-height
        self.pastas.itemChanged.connect(self._pasta_renomeada)
        self.pastas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.pastas.customContextMenuRequested.connect(self._menu_pastas)
        atalho = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.pastas, self.remover_pasta); atalho.setContext(Qt.ShortcutContext.WidgetShortcut)
        ed.addWidget(self.pastas, 2)
        bp = QHBoxLayout()
        add = botao_secundario("+ Pasta mãe", self); add.clicked.connect(lambda *_: self.criar_mae())
        add.setToolTip("Cria uma ou mais pastas mãe (separe os nomes com ;). Pode ter quantas quiser.")
        sub = botao_secundario("+ Subpasta", self); sub.clicked.connect(lambda *_: self.adicionar_pasta(subpasta=True))
        sub.setToolTip("Cria uma ou mais pastas dentro da pasta selecionada (separe os nomes com ;).")
        ren = botao_secundario("Renomear", self); ren.clicked.connect(lambda *_: self.renomear_pasta()); ren.setToolTip("Também: F2 ou clique duplo.")
        rem = botao_secundario("Remover pasta", self); rem.clicked.connect(lambda *_: self.remover_pasta())
        rem.setToolTip("Remove a pasta selecionada e tudo o que estiver dentro dela (só no modelo). Também: tecla Delete.")
        mapa = botao_secundario("Pasta do mapa aqui", self); mapa.clicked.connect(lambda *_: self.definir_pasta_mapa())
        mapa.setToolTip("As camadas do QGIS (shapefiles) ficam na pasta selecionada.")
        mapa.setStyleSheet("QPushButton { min-width: 150px; }")
        for b in (add, sub, ren, rem, mapa): bp.addWidget(b)
        bp.addStretch(); ed.addLayout(bp)
        ed.addWidget(secao("Camadas que o modelo cria"))
        self.camadas = QTreeWidget(); self.camadas.setHeaderLabels(["Nome", "Tipo", "Grupo", "No Quadro de Áreas", "Origem"])
        self.camadas.setRootIsDecorated(False); self.camadas.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for col, larg in enumerate([210, 66, 110, 180, 70]): self.camadas.setColumnWidth(col, larg)
        self.camadas.header().setStretchLastSection(True); self.camadas.setIconSize(QSize(16, 16))
        ed.addWidget(self.camadas, 1)
        bc = QHBoxLayout()
        b1 = botao_secundario("+ Do catálogo...", self); b1.clicked.connect(self.adicionar_catalogo)
        b2 = botao_secundario("+ Nova camada...", self); b2.clicked.connect(self.adicionar_nova)
        b4 = botao_secundario("Editar camada...", self); b4.clicked.connect(self.editar_camada)
        b3 = botao_secundario("Remover", self); b3.clicked.connect(self.remover_camadas)
        self.camadas.itemDoubleClicked.connect(lambda *_: self.editar_camada())
        for b in (b1, b2, b4, b3): bc.addWidget(b)
        bc.addStretch(); ed.addLayout(bc)
        ft = QFormLayout(); self.tema = QComboBox(); ft.addRow("Tema de cores:", self.tema); ed.addLayout(ft)
        self.dir.addWidget(self.rolar, 1)
        self.aviso_fixo = _sub(""); self.dir.addWidget(self.aviso_fixo)
        rod = QHBoxLayout(); rod.addStretch()
        self.aplicar_btn = botao_secundario("Aplicar neste projeto", self); self.aplicar_btn.clicked.connect(self.aplicar)
        self.salvar_btn = botao_principal("Salvar modelo", self); self.salvar_btn.clicked.connect(lambda: self.salvar(M.salvar_modelo_pasta))
        rod.addWidget(self.aplicar_btn); rod.addWidget(self.salvar_btn); self.dir.addLayout(rod)
        self.preencher_lista()

    def itens(self):
        return M.modelos_pasta()

    def _temas(self, atual=""):
        self.tema.clear(); self.tema.addItem("Nenhum (cores padrão do catálogo)", "")
        for t in M.temas_cores():
            self.tema.addItem(t["nome"], t["nome"])
        if atual and self.tema.findData(atual) < 0:
            self.tema.addItem(f"{atual} (não existe mais)", atual)
        self.tema.setCurrentIndex(max(0, self.tema.findData(atual)))

    def _linha_camada(self, c):
        indice = self.plugin.indice_atual()
        if c.get("arquivo"):
            e = indice.get(c["arquivo"]) or {}
            vals = [e.get("nome") or c["arquivo"], TIPOS.get(e.get("tipo"), "-"), e.get("grupo", "-"),
                    "(do catálogo)" if not e.get("personalizada") else TEXTO_LUGAR.get(e.get("quadro") or "OUTRAS", ""),
                    "Catálogo" if e else "Não encontrada"]
        else:
            n = c["nova"]
            vals = [n["nome"], TIPOS.get(n["tipo"], "-"), n["grupo"], TEXTO_LUGAR.get(n["quadro"], "") if n["tipo"] == "P" else "Não entra", "Nova"]
        it = QTreeWidgetItem([str(v) for v in vals]); it.setData(0, Qt.ItemDataRole.UserRole, copy.deepcopy(c))
        it.setToolTip(3, vals[3])
        try:
            from .catalogo import simbolo_entrada
            base = dict(c["nova"]) if c.get("nova") else (indice.get(c["arquivo"]) or None)
            if base:
                it.setIcon(0, QgsSymbolLayerUtils.symbolPreviewIcon(simbolo_entrada(base), QSize(16, 16)))
        except Exception:
            pass
        self.camadas.addTopLevelItem(it)

    def carregar(self, m):
        self.editor.setVisible(m is not None)
        if m is None:
            return
        fixo = bool(m.get("fixo"))
        n = M.normalizar_modelo_pasta(m)
        self.nome.setText(m["nome"]); self._montar_pastas(n["pastas"], n["pasta_mapa"])
        self.camadas.clear()
        for c in n["camadas"]:
            self._linha_camada(c)
        self._temas(m.get("tema_cores", "")); self._atualizar_previa()
        self.editor.setEnabled(not fixo); self.salvar_btn.setEnabled(not fixo)
        self.aviso_fixo.setText("Modelo fixo do plugin (pastas de sempre). Use Novo para começar do zero ou Duplicar para partir dele." if fixo else
                                (f"Salvo por {m.get('autor')} em {m.get('data')}." if m.get("autor") else "Modelo ainda não salvo."))

    def coletar(self):
        if self.atual is None:
            return {}
        return {"nome": self.nome.text().strip(), "pastas": self.caminhos_pastas(),
                "camadas": [self.camadas.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(self.camadas.topLevelItemCount())],
                "tema_cores": str(self.tema.currentData() or ""),
                "formato_pastas": 2, "pasta_mapa": self.pasta_mapa()}

    def _atualizar_previa(self, *_):
        """Atualiza a coluna de explicações da árvore."""
        self._atualizar_textos()

    def editar_camada(self):
        it = self.camadas.currentItem()
        if not it:
            alertar(self, "Editar camada", "Selecione uma camada da lista."); return
        c = it.data(0, Qt.ItemDataRole.UserRole)
        if c.get("arquivo"):
            alertar(self, "Editar camada", "Esta camada vem do catálogo do escritório: o tipo, o grupo e o estilo dela são os do catálogo.",
                    ["Para mudar o lugar no quadro de uma camada personalizada, use Criar/gerenciar camadas > botão direito > Lugar no Quadro de Áreas."])
            return
        from .tela_nova_camada import TelaNovaCamada
        dlg = TelaNovaCamada(self.plugin, self, somente_definicao=True, inicial=c["nova"])
        if not compat.aceito(dlg.exec()) or not dlg.entrada_resultado:
            return
        n = M._camada_modelo({"nova": dlg.entrada_resultado})
        if not n:
            return
        if n["nova"]["arquivo"] != c["nova"]["arquivo"] and self._ja_tem(n["nova"]["arquivo"]):
            alertar(self, "Editar camada", "Já existe outra camada com esse nome no modelo."); return
        pos = self.camadas.indexOfTopLevelItem(it); self.camadas.takeTopLevelItem(pos)
        self._linha_camada(n); novo = self.camadas.takeTopLevelItem(self.camadas.topLevelItemCount() - 1)
        self.camadas.insertTopLevelItem(pos, novo); self.camadas.setCurrentItem(novo); self._atualizar_previa()

    # ----- árvore de pastas (v0.0.0, formato 2)
    # Topo fixo = o local escolhido em Configurar pasta ("Criar dentro de"). Dentro dele: quantas pastas mãe a pessoa
    # quiser, cada uma com as subpastas que quiser. O modelo grava os caminhos a partir do local (só as pastas finais;
    # as de cima são criadas junto) e "pasta_mapa", a pasta onde o plugin grava as camadas.
    BASE = "Local escolhido ao criar a estrutura"
    DICAS = {"shapefiles": "camadas do QGIS (se faltar, o plugin cria sozinho)", "kml": "cópia KML automática de cada camada",
             "projetos": "lugar sugerido para salvar o projeto do QGIS (.qgz)"}
    COR_MAPA = "#46741F"

    @staticmethod
    def _tipo(it):
        return it.data(0, R_TIPO) if it is not None else None

    def _icone(self, it, tipo=QStyle.StandardPixmap.SP_DirIcon):
        cache = self.__dict__.setdefault("_cache_icones", {})   # um ícone por tipo, reaproveitado em todas as pastas
        if tipo not in cache:
            cache[tipo] = self.style().standardIcon(tipo)
        it.setIcon(0, cache[tipo])

    def _novo_no(self, pai, nome):
        it = QTreeWidgetItem([nome, ""]); it.setData(0, Qt.ItemDataRole.UserRole, nome); it.setData(0, R_TIPO, "pasta")
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable); self._icone(it)
        pai.addChild(it); return it

    def _montar_pastas(self, caminhos, mapa=""):
        self.pastas.blockSignals(True); self.pastas.setUpdatesEnabled(False)
        try:
            self.pastas.clear()
            self.raiz = QTreeWidgetItem([self.BASE, ""]); self.raiz.setData(0, R_TIPO, "base")
            self.raiz.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable); self._icone(self.raiz, QStyle.StandardPixmap.SP_DriveHDIcon)
            f = self.raiz.font(0); f.setItalic(True); self.raiz.setFont(0, f)
            self.raiz.setToolTip(0, "É a pasta que você escolhe em Configurar pasta do mapa (Criar dentro de). As pastas mãe são criadas dentro dela.")
            for c in caminhos:   # monta fora da tela (rápido mesmo com centenas de pastas) e só depois mostra
                self._garantir_caminho(c)
            (self._garantir_caminho(mapa) if mapa else self.raiz).setData(0, R_MAPA, True)
            self.pastas.addTopLevelItem(self.raiz)
        finally:
            self.pastas.blockSignals(False)
        try:
            self._atualizar_textos()
        finally:
            self.pastas.setUpdatesEnabled(True)

    def _filhos_usuario(self, no):
        return [no.child(i) for i in range(no.childCount()) if self._tipo(no.child(i)) == "pasta"]

    def _filho(self, pai, nome):
        for f in self._filhos_usuario(pai):
            if f.text(0).strip().casefold() == nome.strip().casefold():
                return f
        return None

    def _garantir_caminho(self, caminho):
        no = self.raiz
        for parte in [p.strip() for p in re.split(r"[\\/]+", str(caminho or "")) if p.strip()]:
            no = self._filho(no, parte) or self._novo_no(no, parte)
        return no

    def _achar_caminho(self, caminho):
        no = self.raiz
        for parte in [p for p in str(caminho or "").split("/") if p]:
            no = self._filho(no, parte) if no is not None else None
        return no

    @staticmethod
    def _caminho(it):
        partes = []
        while it is not None and it.parent() is not None:
            partes.append(it.text(0).strip()); it = it.parent()
        return "/".join(reversed(partes))

    def _todos(self, no=None):
        no = no or self.raiz
        if no is None:
            return []
        saida = [no]
        for i in range(no.childCount()):
            saida += self._todos(no.child(i))
        return saida

    def no_mapa(self):
        if self.raiz is None:
            return None
        return next((it for it in self._todos() if it.data(0, R_MAPA)), self.raiz)

    def pasta_mapa(self):
        return self._caminho(self.no_mapa()) if self.raiz is not None else ""

    def caminhos_pastas(self):
        """Caminhos das pastas finais (as de cima são criadas junto)."""
        saida = []
        def visitar(no):
            for f in self._filhos_usuario(no):
                if self._filhos_usuario(f):
                    visitar(f)
                elif self._caminho(f):
                    saida.append(self._caminho(f))
        if self.raiz is not None:
            visitar(self.raiz)
        return saida

    def _contar(self, no):
        return sum(1 + self._contar(f) for f in self._filhos_usuario(no))

    def _atualizar_textos(self):
        """Coluna da direita: o que é cada pasta (pasta mãe, pasta do mapa e as pastas que o plugin usa)."""
        if getattr(self, "raiz", None) is None:
            return
        self.pastas.blockSignals(True)
        try:
            mapa = self.no_mapa(); caminho_mapa = self._caminho(mapa)
            for it in self._todos():
                txt = ""
                if self._tipo(it) == "pasta" and it.parent() is not None and it.parent().parent() is None:
                    txt = "pasta mãe"
                    it.setToolTip(0, "Pasta mãe. Ao criar a estrutura (Configurar pasta do mapa), dá para trocar o nome dela, por exemplo pelo nome da fazenda.")
                if it.data(0, R_MAPA):
                    txt = "pasta mãe e pasta do mapa (camadas do QGIS)" if txt else "pasta do mapa: as camadas do QGIS ficam aqui"
                elif self._tipo(it) == "pasta" and it.parent() is not None and self._caminho(it.parent()) == caminho_mapa \
                        and it.text(0).strip().casefold() in self.DICAS:
                    txt = self.DICAS[it.text(0).strip().casefold()]
                it.setText(1, txt)
                it.setForeground(1, QColor(self.COR_MAPA if it.data(0, R_MAPA) else "#7A7A7A"))
            self.pastas.expandAll()
        finally:
            self.pastas.blockSignals(False)

    @staticmethod
    def _nomes(texto):
        return [x.strip() for x in str(texto or "").split(";") if x.strip()]

    def _criar_em(self, pai, titulo, rotulo):
        """Pede um ou mais nomes (separados por ;) e cria dentro de `pai`. Devolve os itens criados."""
        texto, ok = QInputDialog.getText(self, titulo, rotulo)
        if not ok:
            return []
        onde = self._caminho(pai); mapa = self.pasta_mapa(); criados, problemas = [], []
        self.pastas.setUpdatesEnabled(False)
        try:
            self._criar_nomes(texto, onde, mapa, criados, problemas)
        finally:
            self.pastas.setUpdatesEnabled(True)
        if problemas:
            alertar(self, titulo, "Algumas pastas não foram criadas.", problemas)
        return criados

    def _criar_nomes(self, texto, onde, mapa, criados, problemas):
        for nome in self._nomes(texto):
            try:
                limpa = M.limpar_subpasta((onde + "/" if onde else "") + nome, mapa)
            except ValueError as exc:
                problemas.append(str(exc)); continue
            if not limpa or self._achar_caminho(limpa) is not None:
                problemas.append(f'A pasta "{limpa or nome}" já existe no modelo.'); continue
            self.pastas.blockSignals(True)
            try:
                criados.append(self._garantir_caminho(limpa))
            finally:
                self.pastas.blockSignals(False)

    def criar_mae(self):
        if self.raiz is None:
            return
        sem_maes = not self._filhos_usuario(self.raiz)
        criados = self._criar_em(self.raiz, "Nova pasta mãe",
                                 "Nome da pasta mãe (para criar várias de uma vez, separe os nomes com ;):")
        if not criados:
            return
        maes = [c if c.parent() is not None and c.parent().parent() is None else None for c in criados]
        primeira = next((m for m in maes if m is not None), criados[0])
        if sem_maes and self.no_mapa().parent() is None:
            # primeira pasta mãe: as camadas passam a ficar nela (dá para mudar com Pasta do mapa aqui)
            self.raiz.setData(0, R_MAPA, None); primeira.setData(0, R_MAPA, True)
        self._atualizar_textos(); self.pastas.setCurrentItem(primeira)

    def adicionar_pasta(self, subpasta=True):
        if self.raiz is None:
            return
        pai = self.pastas.currentItem() if subpasta else None
        if pai is None:
            maes = self._filhos_usuario(self.raiz)
            if len(maes) != 1:
                alertar(self, "Nova subpasta", "Selecione na árvore a pasta onde as subpastas vão ficar." if maes
                        else "Crie primeiro uma pasta mãe (botão + Pasta mãe)."); return
            pai = maes[0]
        if self._tipo(pai) == "base":
            self.criar_mae(); return
        onde = self._caminho(pai)
        criados = self._criar_em(pai, "Nova subpasta",
                                 f'Subpasta dentro de "{onde}".\nPara criar várias de uma vez, separe os nomes com ;\n'
                                 'Para criar uma dentro da outra, use / (ex.: CAR/2026).\n\nNome:')
        if criados:
            self._atualizar_textos(); self.pastas.setCurrentItem(pai)   # continua na mesma pasta: fica fácil criar outras

    def definir_pasta_mapa(self):
        it = self.pastas.currentItem()
        if it is None:
            alertar(self, "Pasta do mapa", "Selecione na árvore a pasta onde devem ficar as camadas do QGIS."); return
        caminho = self._caminho(it)
        try:
            for f in self._caminhos_abaixo(it):
                M.limpar_subpasta(f, caminho)
        except ValueError as exc:
            alertar(self, "Pasta do mapa", str(exc)); return
        for x in self._todos():
            x.setData(0, R_MAPA, None)
        it.setData(0, R_MAPA, True); self._atualizar_textos(); self.pastas.setCurrentItem(it)

    def _caminhos_abaixo(self, no):
        return [self._caminho(x) for x in self._todos(no)[1:] if self._tipo(x) == "pasta"]

    def renomear_pasta(self):
        it = self.pastas.currentItem()
        if it is None:
            alertar(self, "Renomear pasta", "Selecione a pasta que quer renomear."); return
        if self._tipo(it) != "pasta":
            alertar(self, "Renomear pasta", "Esta é a pasta escolhida em Configurar pasta do mapa; ela não tem nome no modelo."); return
        self.pastas.editItem(it, 0)

    def _pasta_renomeada(self, it, col=0):
        if self._carregando or it is None or col != 0 or self._tipo(it) != "pasta":
            return
        antigo = str(it.data(0, Qt.ItemDataRole.UserRole) or ""); novo = it.text(0).strip()
        if novo == antigo:
            return
        erro = None
        if not novo or re.search(r"[\\/]", novo):
            erro = 'Use só o nome da pasta, sem / ou \\. Para criar uma pasta dentro dela, selecione-a e clique em "+ Subpasta".'
        elif any(it.parent().indexOfChild(f) != it.parent().indexOfChild(it) and f.text(0).strip().casefold() == novo.casefold()
                 for f in self._filhos_usuario(it.parent())):
            erro = f'Já existe uma pasta "{novo}" nesse mesmo lugar.'
        else:
            try:
                mapa = self.pasta_mapa()
                for c in [self._caminho(it)] + self._caminhos_abaixo(it):
                    M.limpar_subpasta(c, mapa)
            except ValueError as exc:
                erro = str(exc)
        self.pastas.blockSignals(True)
        try:
            if erro:
                it.setText(0, antigo)
            else:
                it.setText(0, novo); it.setData(0, Qt.ItemDataRole.UserRole, novo)
        finally:
            self.pastas.blockSignals(False)
        if erro:
            alertar(self, "Renomear pasta", erro)
        self._atualizar_textos()

    def remover_pasta(self):
        it = self.pastas.currentItem()
        if it is None:
            alertar(self, "Remover pasta", "Selecione na árvore a pasta que quer remover."); return
        if self._tipo(it) != "pasta":
            alertar(self, "Remover pasta", "Esta é a pasta escolhida em Configurar pasta do mapa; selecione uma pasta criada por você."); return
        n = self._contar(it); tinha_mapa = any(x.data(0, R_MAPA) for x in self._todos(it))
        if n or tinha_mapa:
            frase = f'Remover "{it.text(0)}"' + (f" e a(s) {n} pasta(s) dentro dela?" if n else "?")
            detalhes = ["As camadas do QGIS (pasta do mapa) estavam nela; escolha outra pasta com Pasta do mapa aqui."] if tinha_mapa else None
            if not confirmar(self, "Remover pasta", frase, "Remover", destrutivo=True, detalhes=detalhes):
                return
        pai = it.parent(); pai.removeChild(it)
        if tinha_mapa:
            self.raiz.setData(0, R_MAPA, True)
        self._atualizar_textos(); self.pastas.setCurrentItem(pai)

    def _menu_pastas(self, pos):
        it = self.pastas.itemAt(pos)
        if it is not None:
            self.pastas.setCurrentItem(it)
        menu = QMenu(self)
        menu.addAction("+ Pasta mãe", self.criar_mae)
        if it is not None and self._tipo(it) == "pasta":
            menu.addAction("+ Subpasta aqui", lambda: self.adicionar_pasta(subpasta=True))
            menu.addAction("Renomear (F2)", self.renomear_pasta)
            menu.addAction("Remover pasta (Delete)", self.remover_pasta)
        if it is not None:
            menu.addSeparator(); menu.addAction("Pasta do mapa aqui (camadas do QGIS)", self.definir_pasta_mapa)
        menu.exec(self.pastas.viewport().mapToGlobal(pos))

    def _ja_tem(self, chave):
        for i in range(self.camadas.topLevelItemCount()):
            c = self.camadas.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            if (c.get("arquivo") or c.get("nova", {}).get("arquivo")) == chave:
                return True
        return False

    def adicionar_catalogo(self):
        dlg = QDialog(self); preparar_dialogo(dlg, "modelo_do_catalogo", "Norte Agro - Camadas do catálogo", (520, 520))
        lay = QVBoxLayout(dlg); lay.addWidget(_sub("Marque as camadas do catálogo que o modelo deve criar."))
        arvore = QTreeWidget(); arvore.setHeaderHidden(True); lay.addWidget(arvore, 1)
        for grupo, itens in self.plugin.catalogo_atual().items():
            if not itens:
                continue
            g = QTreeWidgetItem([grupo]); g.setFlags(g.flags() & ~Qt.ItemFlag.ItemIsUserCheckable); arvore.addTopLevelItem(g)
            for e in itens:
                it = QTreeWidgetItem([f'{e["nome"]}  ({TIPOS.get(e.get("tipo"), "-")})']); it.setData(0, Qt.ItemDataRole.UserRole, e["arquivo"])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if self._ja_tem(e["arquivo"]) else Qt.CheckState.Unchecked)
                if self._ja_tem(e["arquivo"]): it.setDisabled(True)
                g.addChild(it)
            g.setExpanded(True)
        bt = QHBoxLayout(); bt.addStretch(); c = botao_secundario("Fechar", dlg); o = botao_principal("Adicionar", dlg)
        c.clicked.connect(dlg.reject); o.clicked.connect(dlg.accept); bt.addWidget(c); bt.addWidget(o); lay.addLayout(bt)
        if not compat.aceito(dlg.exec()):
            return
        for i in range(arvore.topLevelItemCount()):
            g = arvore.topLevelItem(i)
            for j in range(g.childCount()):
                it = g.child(j); arq = it.data(0, Qt.ItemDataRole.UserRole)
                if it.checkState(0) == Qt.CheckState.Checked and not self._ja_tem(arq):
                    self._linha_camada({"arquivo": arq})
        self._atualizar_previa()

    def adicionar_nova(self):
        from .tela_nova_camada import TelaNovaCamada
        dlg = TelaNovaCamada(self.plugin, self, somente_definicao=True)
        if not compat.aceito(dlg.exec()) or not dlg.entrada_resultado:
            return
        n = M._camada_modelo({"nova": dlg.entrada_resultado})
        if not n:
            return
        if self._ja_tem(n["nova"]["arquivo"]):
            alertar(self, "Nova camada", "Essa camada já está no modelo."); return
        self._linha_camada(n); self._atualizar_previa()

    def remover_camadas(self):
        for it in self.camadas.selectedItems():
            self.camadas.takeTopLevelItem(self.camadas.indexOfTopLevelItem(it))
        self._atualizar_previa()

    def aplicar(self):
        if self.atual is None:
            return
        pasta, _ = self.plugin.memoria_basica()
        if not pasta or not os.path.isdir(pasta):
            alertar(self, "Aplicar modelo", "Configure a pasta do mapa primeiro (Criar/gerenciar camadas)."); return
        m = self.coletar() if not self.atual.get("fixo") else self.atual
        qtd = len(M.normalizar_modelo_pasta(m)["camadas"])
        if not confirmar(self, "Aplicar modelo", f'Aplicar "{m["nome"]}" em {pasta}?',
                         "Aplicar", detalhes=["Cria as pastas que faltarem.", f"Cria ou carrega {qtd} camada(s); nada existente é apagado ou sobrescrito.",
                                              "Aplica o tema de cores, se houver."]):
            return
        try:
            resumo = self.plugin.aplicar_modelo_pasta(m)
        except Exception as exc:
            alertar(self, "Aplicar modelo", "O modelo não foi aplicado.", str(exc)); return
        (alertar if (resumo["falhas"] or resumo.get("ausentes")) else sucesso)(self, "Modelo aplicado", f'"{m["nome"]}" aplicado neste projeto.',
                                                   self.plugin.texto_resumo_modelo(resumo) or ["Tudo já existia."])


# =========================================================== Temas de cores
class AbaCores(_Aba):
    TITULO_LISTA = "Temas de cores"

    def __init__(self, tela):
        self._estilos = {}; self._nomes = {}  # antes de montar a tela: os botões podem ser usados sem tema aberto
        super().__init__(tela)
        b = botao_secundario("+ Novo tema com as cores do projeto", self); b.clicked.connect(self.novo_tema); self.botoes_lista.addWidget(b)
        self.botoes_lista2 = QHBoxLayout(); self.lista.parentWidget()
        self.layout().itemAt(0).layout().addLayout(self.botoes_lista2)
        b2 = botao_secundario("Excluir", self); b2.clicked.connect(lambda: self.excluir(M.remover_tema_cores)); self.botoes_lista2.addWidget(b2)
        self.dir.addWidget(_sub("Pinte as camadas no QGIS (Propriedades da camada > Simbologia: cor única, categorizado, graduado...) "
                                "e guarde aqui como tema. Vale para qualquer camada do projeto: as do plugin, as criadas do jeito normal "
                                "no QGIS e as trazidas de outro projeto. Depois aplique o tema em qualquer projeto ou escolha-o num modelo de pastas."))
        self.editor = QWidget(); ed = QVBoxLayout(self.editor); ed.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout(); self.nome = QLineEdit(); form.addRow("Nome do tema:", self.nome); ed.addLayout(form)
        ed.addWidget(secao("Cores guardadas"))
        self.tabela = QTreeWidget(); self.tabela.setHeaderLabels(["Camada", "Estilo"]); self.tabela.setRootIsDecorated(False)
        self.tabela.setColumnWidth(0, 300); self.tabela.setIconSize(QSize(20, 20)); self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        ed.addWidget(self.tabela, 1)
        bt = QHBoxLayout(); tirar = botao_secundario("Remover camada do tema", self); tirar.clicked.connect(self.remover_camadas)
        tirar.setToolTip("O tema deixa de mudar a cor dessas camadas."); bt.addWidget(tirar); bt.addStretch(); ed.addLayout(bt)
        self.gravar_qml = QCheckBox("Ao aplicar, gravar também no estilo (.qml) de cada camada"); self.gravar_qml.setChecked(True)
        self.gravar_qml.setToolTip("Assim a cor continua a mesma quando a camada for carregada de novo ou padronizada.")
        ed.addWidget(self.gravar_qml)
        self.dir.addWidget(self.editor, 1)
        self.vazio = _sub("Nenhum tema ainda. Pinte as camadas do projeto e clique em \"+ Novo tema com as cores do projeto\".")
        self.dir.addWidget(self.vazio); self.dir.addStretch(0)
        rod = QHBoxLayout(); rod.addStretch()
        self.atualizar_btn = botao_secundario("Atualizar com as cores do projeto", self)
        self.atualizar_btn.setToolTip("Pega de novo as cores das camadas que já estão no tema."); self.atualizar_btn.clicked.connect(self.atualizar_do_projeto)
        self.aplicar_btn = botao_secundario("Aplicar neste projeto", self); self.aplicar_btn.clicked.connect(self.aplicar)
        self.salvar_btn = botao_principal("Salvar tema", self); self.salvar_btn.clicked.connect(lambda: self.salvar(lambda d, a: M.salvar_tema_cores(d["nome"], d["estilos"], a, d.get("nomes"))))
        for b in (self.atualizar_btn, self.aplicar_btn, self.salvar_btn): rod.addWidget(b)
        self.dir.addLayout(rod)
        self.preencher_lista()

    def itens(self):
        return M.temas_cores()

    def carregar(self, m):
        self.editor.setVisible(m is not None)
        if hasattr(self, "vazio"): self.vazio.setVisible(m is None)
        for b in (self.atualizar_btn, self.aplicar_btn, self.salvar_btn): b.setEnabled(m is not None)
        if m is None:
            return
        self.nome.setText(m["nome"]); self._estilos = dict(m.get("estilos") or {}); self._nomes = dict(m.get("nomes") or {}); self._mostrar_estilos()

    def _mostrar_estilos(self):
        self.tabela.clear(); indice = self.plugin.indice_atual(); nomes = getattr(self, "_nomes", {})

        def rotulo(chave):
            if str(chave).startswith(M.PREFIXO_NOME):
                return str(nomes.get(chave) or chave[len(M.PREFIXO_NOME):])
            return str((indice.get(chave) or {}).get("nome") or chave)
        for arq in sorted(self._estilos, key=lambda a: rotulo(a).casefold()):
            it = QTreeWidgetItem([rotulo(arq), ""]); it.setData(0, Qt.ItemDataRole.UserRole, arq)
            try:
                r = M.renderer_de_xml(self._estilos[arq]); simbolos = r.symbols(__import__("qgis.core", fromlist=["QgsRenderContext"]).QgsRenderContext()) if r else []
                if simbolos:
                    it.setIcon(1, QgsSymbolLayerUtils.symbolPreviewIcon(simbolos[0], QSize(20, 20)))
                    it.setText(1, r.type().replace("singleSymbol", "cor única").replace("categorizedSymbol", f"categorizado ({len(simbolos)})").replace("graduatedSymbol", f"graduado ({len(simbolos)})"))
            except Exception:
                it.setText(1, "estilo ilegível")
            self.tabela.addTopLevelItem(it)

    def coletar(self):
        if self.atual is None:
            return {}
        estilos = dict(getattr(self, "_estilos", {}))
        nomes = {k: v for k, v in getattr(self, "_nomes", {}).items() if k in estilos}
        return {"nome": self.nome.text().strip(), "estilos": estilos, "nomes": nomes}

    def remover_camadas(self):
        for it in self.tabela.selectedItems():
            self._estilos.pop(it.data(0, Qt.ItemDataRole.UserRole), None)
        self._mostrar_estilos()

    def novo_tema(self):
        nomes = {}; estilos = M.capturar_tema(QgsProject.instance(), nomes=nomes)
        if not estilos:
            alertar(self, "Novo tema", "Não há camadas vetoriais neste projeto para guardar as cores.",
                    "Abra ou crie as camadas no QGIS (pode ser de qualquer jeito: pelo plugin, pelo QGIS ou de outro projeto) e tente de novo."); return
        self.novo_de({"nome": "Novo tema", "estilos": estilos, "nomes": nomes})
        sucesso(self, "Cores capturadas", f"{len(estilos)} camada(s) do projeto. Dê um nome e clique em Salvar tema.")

    def atualizar_do_projeto(self):
        """Atualiza só as camadas que já estão no tema (para incluir outras, use Novo tema ou Adicionar)."""
        projeto = QgsProject.instance(); camadas = M.camadas_vetoriais(projeto)
        if not camadas:
            alertar(self, "Atualizar tema", "Não há camadas vetoriais neste projeto."); return
        if not hasattr(self, "_nomes"): self._nomes = {}
        if not self._estilos:
            nomes = {}; self._estilos.update(M.capturar_tema(projeto, camadas, nomes=nomes)); self._nomes.update(nomes)
            self._mostrar_estilos(); return
        # cada camada pode bater com o tema pela linha do catálogo ou pelo nome; a primeira que bate vale
        todos = M.capturar_tema(projeto, camadas)  # já prefere a camada da pasta do mapa quando há duas iguais
        atualizadas = {k: v for k, v in todos.items() if k in self._estilos}
        for c, chave in M.camadas_do_tema({"estilos": self._estilos}, projeto, camadas):
            if chave in atualizadas:
                continue
            nomes = {}; est = M.capturar_tema(projeto, [c], nomes=nomes)
            if est:
                atualizadas[chave] = next(iter(est.values()))
                if chave.startswith(M.PREFIXO_NOME): self._nomes[chave] = c.name()
        if not atualizadas:
            alertar(self, "Atualizar tema", "Nenhuma camada deste tema está aberta no projeto."); return
        self._estilos.update(atualizadas)
        self._mostrar_estilos()

    def aplicar(self):
        if self.atual is None:
            return
        alvo = [c for c, _k in M.camadas_do_tema(self.coletar(), QgsProject.instance())]
        if not alvo:
            alertar(self, "Aplicar tema", "Nenhuma camada deste projeto tem cor guardada neste tema."); return
        det = [f"Muda a cor de {len(alvo)} camada(s) deste projeto."]
        if self.gravar_qml.isChecked():
            det.append("Também regrava o estilo (.qml) dessas camadas na pasta delas, para a cor valer quando forem abertas de novo.")
        det.append("O desenho das camadas não é alterado.")
        if not confirmar(self, "Aplicar tema", f'Aplicar o tema "{self.nome.text()}" neste projeto?', "Aplicar", detalhes=det):
            return
        try:
            aplicadas, sem, erros = M.aplicar_tema(self.coletar(), QgsProject.instance(), gravar_qml=self.gravar_qml.isChecked(), camadas=alvo)
        except Exception as exc:
            alertar(self, "Aplicar tema", "O tema não foi aplicado.", str(exc)); return
        det = [f"Aplicado em {len(aplicadas)} camada(s)."] + erros
        (alertar if erros else sucesso)(self, "Tema aplicado", f'"{self.nome.text()}" aplicado neste projeto.', det)


# =========================================================== Tabela
class AbaTabela(_Aba):
    TITULO_LISTA = "Modelos de tabela"

    def __init__(self, tela):
        super().__init__(tela)
        for texto, func in (("Novo", lambda: self.novo_de(M.modelo_tabela_padrao())), ("Duplicar", lambda: self.atual and self.novo_de(self.atual, " (cópia)")),
                            ("Excluir", lambda: self.excluir(M.remover_modelo_tabela))):
            b = botao_secundario(texto, self); b.clicked.connect(func); self.botoes_lista.addWidget(b)
        rolar = QScrollArea(); rolar.setWidgetResizable(True); self.editor = QWidget(); rolar.setWidget(self.editor)
        ed = QVBoxLayout(self.editor); ed.setContentsMargins(0, 0, 8, 0)
        form = QFormLayout(); self.nome = QLineEdit(); form.addRow("Nome do modelo:", self.nome)
        self.titulo = QLineEdit(); self.titulo.setToolTip("Campos: {imovel}, {data}, {metodo}, {src}")
        form.addRow("Título da planilha:", self.titulo); form.addRow("", _sub("Pode usar {imovel}, {data}, {metodo} e {src}.")); ed.addLayout(form)
        ed.addWidget(secao("Quadros (ordem, lado e título)"))
        self.quadros = QTableWidget(0, 3); self.quadros.setHorizontalHeaderLabels(["Mostrar", "Título", "Lado"])
        self.quadros.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); self.quadros.setColumnWidth(0, 70); self.quadros.setColumnWidth(2, 110)
        self.quadros.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.quadros.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quadros.verticalHeader().setVisible(False); self.quadros.verticalHeader().setDefaultSectionSize(30)
        _altura(self.quadros, 30 * len(M.QUADROS_TABELA) + 34); ed.addWidget(self.quadros)
        bq = QHBoxLayout(); sobe = botao_secundario("Subir", self); desce = botao_secundario("Descer", self)
        sobe.clicked.connect(lambda: self._mover(-1)); desce.clicked.connect(lambda: self._mover(1)); bq.addWidget(sobe); bq.addWidget(desce); bq.addStretch()
        ed.addLayout(bq)
        ed.addWidget(secao("Nomes das linhas"))
        ed.addWidget(_sub("Deixe em branco para manter o nome original. Linhas que vêm do nome da camada também podem ser renomeadas: use + Outra linha."))
        self.linhas = QTableWidget(0, 2); self.linhas.setHorizontalHeaderLabels(["Nome original", "Nome na planilha"])
        self.linhas.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.linhas.verticalHeader().setVisible(False)
        self.linhas.verticalHeader().setDefaultSectionSize(28); _altura(self.linhas, 28 * 10 + 34); ed.addWidget(self.linhas)
        bl = QHBoxLayout(); outra = botao_secundario("+ Outra linha", self); outra.clicked.connect(self._outra_linha); bl.addWidget(outra); bl.addStretch(); ed.addLayout(bl)
        ed.addWidget(secao("Aparência"))
        fa = QFormLayout(); self.fonte = QFontComboBox(); self.tamanho = QSpinBox(); self.tamanho.setRange(7, 16)
        fa.addRow("Fonte:", self.fonte); fa.addRow("Tamanho:", self.tamanho)
        self.cores = {}
        for chave, rotulo in M.ROTULOS_CORES:
            b = QgsColorButton(); b.setAllowOpacity(False); b.setShowNoColor(False); b.setMinimumWidth(120); self.cores[chave] = b; fa.addRow(rotulo + ":", b)
        ed.addLayout(fa)
        ed.addWidget(secao("Logo"))
        hl = QHBoxLayout(); self.logo_prev = QLabel("Sem logo"); self.logo_prev.setFixedHeight(56); self.logo_prev.setMinimumWidth(160)
        el = botao_secundario("Escolher imagem...", self); el.clicked.connect(self._escolher_logo); rl = botao_secundario("Remover", self); rl.clicked.connect(lambda: self._definir_logo(""))
        hl.addWidget(self.logo_prev); hl.addWidget(el); hl.addWidget(rl); hl.addStretch(); ed.addLayout(hl)
        ed.addWidget(secao("Colunas extras"))
        self.col_m2 = QCheckBox("Área em m² ao lado dos hectares"); self.col_pct = QCheckBox("% da Área Total do Imóvel")
        ed.addWidget(self.col_m2); ed.addWidget(self.col_pct); ed.addStretch()
        self.dir.addWidget(rolar, 1)
        self.aviso_fixo = _sub(""); self.dir.addWidget(self.aviso_fixo)
        rod = QHBoxLayout(); rod.addStretch()
        ex = botao_secundario("Ver exemplo no Excel", self); ex.clicked.connect(self.exemplo)
        self.salvar_btn = botao_principal("Salvar modelo", self); self.salvar_btn.clicked.connect(lambda: self.salvar(M.salvar_modelo_tabela))
        rod.addWidget(ex); rod.addWidget(self.salvar_btn); self.dir.addLayout(rod)
        self._logo = ""
        self.preencher_lista()

    def itens(self):
        return M.modelos_tabela()

    def _linha_quadro(self, q, linha=None):
        r = self.quadros.rowCount() if linha is None else linha
        self.quadros.insertRow(r)
        vis = QTableWidgetItem(); vis.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        vis.setCheckState(Qt.CheckState.Checked if q["visivel"] else Qt.CheckState.Unchecked); vis.setData(Qt.ItemDataRole.UserRole, q["id"]); self.quadros.setItem(r, 0, vis)
        tit = QTableWidgetItem(q["titulo"]); tit.setToolTip(f"Original: {M.TITULO_PADRAO_QUADRO[q['id']]}"); self.quadros.setItem(r, 1, tit)
        lado = QComboBox(); lado.addItem("Esquerda", "E"); lado.addItem("Direita", "D"); lado.setCurrentIndex(1 if q["lado"] == "D" else 0)
        self.quadros.setCellWidget(r, 2, lado)

    def _quadros_lidos(self):
        out = []
        for r in range(self.quadros.rowCount()):
            vis = self.quadros.item(r, 0); tit = self.quadros.item(r, 1); lado = self.quadros.cellWidget(r, 2)
            out.append({"id": vis.data(Qt.ItemDataRole.UserRole), "titulo": (tit.text() if tit else "").strip() or M.TITULO_PADRAO_QUADRO[vis.data(Qt.ItemDataRole.UserRole)],
                        "lado": lado.currentData() if lado else "E", "visivel": vis.checkState() == Qt.CheckState.Checked})
        return out

    def _mover(self, passo):
        r = self.quadros.currentRow(); alvo = r + passo
        if r < 0 or alvo < 0 or alvo >= self.quadros.rowCount():
            return
        qs = self._quadros_lidos(); qs[r], qs[alvo] = qs[alvo], qs[r]
        self.quadros.setRowCount(0)
        for q in qs: self._linha_quadro(q)
        self.quadros.selectRow(alvo)

    def _linha_nome(self, original, novo=""):
        r = self.linhas.rowCount(); self.linhas.insertRow(r)
        o = QTableWidgetItem(original); o.setFlags(o.flags() & ~Qt.ItemFlag.ItemIsEditable); self.linhas.setItem(r, 0, o)
        self.linhas.setItem(r, 1, QTableWidgetItem(novo))

    def _outra_linha(self):
        texto, ok = QInputDialog.getText(self, "Outra linha", "Nome original da linha (como aparece hoje na planilha):")
        if ok and texto.strip():
            self._linha_nome(texto.strip()); self.linhas.scrollToBottom()

    def _definir_logo(self, b64):
        self._logo = b64 or ""
        if self._logo:
            pix = QPixmap(); pix.loadFromData(__import__("base64").b64decode(self._logo)); self.logo_prev.setPixmap(pix.scaledToHeight(52, Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_prev.clear(); self.logo_prev.setText("Sem logo")

    def _escolher_logo(self):
        arq, _ = QFileDialog.getOpenFileName(self, "Logo da planilha", os.path.expanduser("~"), "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if not arq:
            return
        try:
            self._definir_logo(M.logo_de_arquivo(arq))
        except Exception as exc:
            alertar(self, "Logo", "A imagem não pôde ser usada.", str(exc))

    def carregar(self, m):
        self.editor.setVisible(m is not None)
        if m is None:
            return
        m = M.normalizar_modelo_tabela(m) if not m.get("fixo") else m
        fixo = bool(m.get("fixo"))
        self.nome.setText(m["nome"]); self.titulo.setText(m["titulo_planilha"])
        self.quadros.setRowCount(0)
        for q in m["quadros"]: self._linha_quadro(q)
        self.linhas.setRowCount(0)
        originais = list(M.LINHAS_PADRAO) + [k for k in m["linhas"] if k not in M.LINHAS_PADRAO]
        for o in originais: self._linha_nome(o, m["linhas"].get(o, ""))
        self.fonte.setCurrentFont(QFont(m["fonte"])); self.tamanho.setValue(int(m["tamanho"]))
        for k, b in self.cores.items(): b.setColor(QColor(m["cores"][k]))
        self._definir_logo(m.get("logo_png", ""))
        self.col_m2.setChecked(m["colunas"]["m2"]); self.col_pct.setChecked(m["colunas"]["pct"])
        self.editor.setEnabled(not fixo); self.salvar_btn.setEnabled(not fixo)
        self.aviso_fixo.setText("Modelo fixo do plugin (a planilha de sempre). Use Duplicar para criar um seu." if fixo else
                                (f"Salvo por {m.get('autor')} em {m.get('data')}." if m.get("autor") else "Modelo ainda não salvo."))

    def coletar(self):
        if self.atual is None:
            return {}
        linhas = {}
        for r in range(self.linhas.rowCount()):
            o = self.linhas.item(r, 0).text().strip(); n = (self.linhas.item(r, 1).text() if self.linhas.item(r, 1) else "").strip()
            if o and n and n != o: linhas[o] = n
        return {"nome": self.nome.text().strip(), "quadros": self._quadros_lidos(), "linhas": linhas,
                "cores": {k: b.color().name().upper() for k, b in self.cores.items()},
                "fonte": self.fonte.currentFont().family(), "tamanho": self.tamanho.value(),
                "titulo_planilha": self.titulo.text().strip() or M.TITULO_PLANILHA_PADRAO, "logo_png": self._logo,
                "colunas": {"m2": self.col_m2.isChecked(), "pct": self.col_pct.isChecked()}}

    def exemplo(self, abrir=True):
        from .planilha import gerar_planilha
        modelo = self.coletar() if self.atual is not None and not self.atual.get("fixo") else (self.atual or M.modelo_tabela_padrao())
        caminho = os.path.join(tempfile.gettempdir(), f"EXEMPLO_QUADRO_{datetime.now().strftime('%H%M%S')}.xlsx")
        try:
            gerar_planilha(caminho, dados_exemplo(), modelo)
        except Exception as exc:
            alertar(self, "Exemplo", "Não foi possível gerar o exemplo.", str(exc)); return ""
        if abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(caminho))
        return caminho


def dados_exemplo():
    """Valores fictícios coerentes (fecham) só para ver o visual do modelo."""
    v = {"AREA_DO_IMOVEL": 100.0, "AREA_DE_VEGETACAO": 55.0, "AREA_CONSOLIDADA": 30.0, "AREA_SUPRIMIDA_ANTES_2019": 10.0,
         "AREA_SUPRIMIDA_DEPOIS_2019": 5.0, "RESERVA_LEGAL": 20.0, "APP_TOTAL": 8.0, "APP_PRESERVADA": 6.0, "APP_CONSOLIDADA": 1.5,
         "APP_ANTROPIZADA_ANTES_2019": 0.5, "APP_ANTROPIZADA_APOS_2019": 0.0, "SUPRESSAO_PASSIVEL_ANTES_2019": 7.5,
         "SUPRESSAO_PASSIVEL_DEPOIS_2019": 4.0, "HIDROGRAFIA": 1.2, "COMPENSACAO_DANOS": 2.0, "COMPENSACAO_FLORESTAL": 1.0, "AREA_RECOMPOSICAO": 0.5}
    vq = dict(v); vq.update({"RL_SUP_ANTES": 2.0, "RL_SUP_APOS": 1.0, "FORA_RL_APP": 29.0})
    return {"imovel_nome": "FAZENDA EXEMPLO", "metodo": "Elipsoidal (GRS80, vértices a cada 10 m)", "densificacao_m": 10.0, "srid": "EPSG:31982",
            "gerado_em": datetime.now(), "valores": v, "valores_quadro": vq,
            "especiais": {"reserva_suprimida_antes": 2.0, "reserva_suprimida_apos": 1.0, "area_fora_rl_app": 29.0},
            "fechamento": {"area_sem_classificacao": 0.0}, "fechamento_linhas": [
                {"descricao": "Área Antropizada não Consolidada", "arquivos": ["AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019"], "area": 15.0},
                {"descricao": "Área Consolidada", "arquivos": ["AREA_CONSOLIDADA"], "area": 30.0},
                {"descricao": "Área de Vegetação Nativa", "arquivos": ["AREA_DE_VEGETACAO"], "area": 55.0}],
            "hidro": [{"descricao": "Barramento 1 - PARTE 1", "area": 0.8}], "outras": [{"arquivo": "", "nome": "Área de Pastagem", "area": 3.0}],
            "linhas_personalizadas": {}, "nomes_catalogo": {}, "todas": [], "conferencias": [], "avisos": [], "problemas_detalhados": []}


class TelaModelos(QDialog):
    def __init__(self, plugin, parent=None, aba=0):
        super().__init__(parent or plugin.iface.mainWindow()); self.plugin = plugin
        preparar_dialogo(self, "tela_modelos", "Norte Agro - Modelos do escritório", (900, 640))
        try:  # v0.0.0: maior quando a tela permite (árvore de pastas e seus botões)
            from qgis.PyQt.QtWidgets import QApplication
            geo = QApplication.primaryScreen().availableGeometry(); larg, alt = geo.width() - 80, geo.height() - 60
        except Exception:
            larg, alt = 1040, 760
        self.resize(max(1040, min(1200, larg)), max(700, min(920, alt)))
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho("Modelos do escritório", "Estrutura de pastas com camadas, temas de cores e o estilo da tabela. Ficam guardados dentro do próprio plugin.",
                                 os.path.join(os.path.dirname(__file__), "icon.png")))
        self.abas = QTabWidget(); raiz.addWidget(self.abas, 1)
        self.pastas = AbaPastas(self); self.cores = AbaCores(self); self.tabela = AbaTabela(self)
        self.abas.addTab(self.pastas, "Estrutura de pastas"); self.abas.addTab(self.cores, "Temas de cores"); self.abas.addTab(self.tabela, "Tabela")
        self.abas.setCurrentIndex(max(0, min(2, int(aba or 0))))
        rod = QHBoxLayout(); rod.addWidget(_sub(f"Guardado dentro do plugin: {M.caminho_modelos()}"), 1)
        fechar = botao_secundario("Fechar", self); fechar.clicked.connect(self.reject); rod.addWidget(fechar); raiz.addLayout(rod)

    def topico_ajuda(self):
        return ("modelos_pastas", "temas", "modelos_tabela")[max(0, self.abas.currentIndex())]

    def reject(self):
        for aba in (self.pastas, self.cores, self.tabela):
            if not aba.pode_sair():
                self.abas.setCurrentWidget(aba); return
        super().reject()
