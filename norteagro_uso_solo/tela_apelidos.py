# -*- coding: utf-8 -*-
"""v0.1.1: Nomes que o plugin não reconhece -> em que linha do Quadro de Áreas a camada entra.

A usuária escreve o nome da camada como ele vem (de outro escritório, do cliente, da DAI...) e escolhe o
destino. O nome vira um apelido: no cálculo, a camada passa a ser tratada como a camada padrão escolhida.
Vale para todo o escritório (catálogo compartilhado) ou só para este projeto.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QStandardItem
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)
from qgis.core import QgsProject, QgsVectorLayer

from .estilo import (
    alertar, botao_principal, botao_secundario, cabecalho, configurar_alerta_texto, confirmar, icone_tema,
    preparar_dialogo, secao, sucesso,
)
from .catalogo import (
    QUADRO_DO_LUGAR, apelidos_escritorio, apelidos_manuais_projeto,
    indice_reconhecimento, lugar_quadro, remover_apelido_escritorio, salvar_apelido_escritorio,
    salvar_apelidos_manuais_projeto,
)
from .reconhecimento import chaves_texto, normalizar_chave

# Onde cada camada padrão aparece no Quadro de Áreas (títulos padrão do modelo de tabela).
_Q_IMOVEL = "Áreas Totais do Imóvel"
_Q_PASSIVOS = "Passivos ambientais"
_Q_REMAN = "Áreas Remanescentes"
_Q_ANTES = "Área antropizada antes de 2019"
_Q_APP = "Área de Preservação Permanente"
_Q_APOS = "Área antropizada após 2019"
_Q_HIDRO = "Área Hidrográfica"
_Q_COMP = "Área Total de Compensação"
_Q_OUTRAS = "Outras camadas"
_Q_CONTA = "Usada nas contas e conferências (sem linha própria)"
_Q_LISTA = "Só na aba Todas as camadas"

ORDEM_QUADROS = [_Q_IMOVEL, _Q_PASSIVOS, _Q_REMAN, _Q_ANTES, _Q_APP, _Q_APOS, _Q_HIDRO, _Q_COMP, _Q_OUTRAS,
                 _Q_CONTA, _Q_LISTA]

QUADRO_FIXO = {
    "AREA_DO_IMOVEL": (_Q_IMOVEL, "Área Total do Imóvel (conferência do quadro)"),
    "AREA_CONSOLIDADA": (_Q_IMOVEL, "Área Consolidada"),
    "AREA_DE_VEGETACAO": (_Q_IMOVEL, "Área de Vegetação Nativa"),
    "AREA_SUPRIMIDA_ANTES_2019": (_Q_PASSIVOS, "Área Suprimida antes de 2019 (também soma na Área Antropizada não Consolidada)"),
    "AREA_SUPRIMIDA_DEPOIS_2019": (_Q_PASSIVOS, "Área Suprimida depois de 2019 (também soma na Área Antropizada não Consolidada)"),
    "RESERVA_LEGAL": (_Q_REMAN, "Área de Reserva Legal"),
    "APP_PRESERVADA": (_Q_APP, "APP Preservada"),
    "APP_CONSOLIDADA": (_Q_APP, "APP Consolidada"),
    "APP_ANTROPIZADA_ANTES_2019": (_Q_ANTES, "APP Suprimida antes de 2019 (também soma na APP Suprimida)"),
    "SUPRESSAO_PASSIVEL_ANTES_2019": (_Q_ANTES, "Supressão em Área Passível antes de 2019"),
    "APP_ANTROPIZADA_APOS_2019": (_Q_APOS, "APP Suprimida depois de 2019 (também soma na APP Suprimida)"),
    "SUPRESSAO_PASSIVEL_DEPOIS_2019": (_Q_APOS, "Supressão em Área Passível após 2019"),
    "RESERVA_SUPRIMIDA": (_Q_ANTES, "Reserva Legal Suprimida (divide em antes/após 2019 pela supressão)"),
    "HIDROGRAFIA": (_Q_HIDRO, "Hidrografia"),
    "BARRAGEM": (_Q_HIDRO, "Barramento (uma linha por feição)"),
    "CACIMBA": (_Q_HIDRO, "Cacimba (uma linha por feição)"),
    "TANQUE": (_Q_HIDRO, "Tanque (uma linha por feição)"),
    "LAGOA_NATURAL": (_Q_HIDRO, "Lagoa Natural (uma linha por feição)"),
    "COMPENSACAO_DANOS": (_Q_COMP, "Área de Compensação por Danos"),
    "COMPENSACAO_FLORESTAL": (_Q_COMP, "Área de Compensação Florestal"),
    "AREA_RECOMPOSICAO": (_Q_COMP, "Área de Recomposição"),
    "APP_TOTAL": (_Q_CONTA, "APP Total (fecha o quadro de APP)"),
    "APP_SUPRIMIDA": (_Q_CONTA, "APP Suprimida (conferência: antes + depois de 2019)"),
    "AREA_SUPRIMIDA": (_Q_CONTA, "Área Suprimida (conferência)"),
    "RESERVA_PRESERVADA": (_Q_CONTA, "Reserva Legal Preservada (conferência)"),
    "RESERVA_CONSOLIDADA": (_Q_CONTA, "Reserva Legal Consolidada (conferência)"),
    "SUPRESSAO_PASSIVEL_TOTAL": (_Q_CONTA, "Supressão em Área Passível total (conferência)"),
}


def onde_na_tabela(arquivo, entrada):
    """(quadro, descrição da linha) de uma camada do catálogo."""
    if arquivo in QUADRO_FIXO:
        return QUADRO_FIXO[arquivo]
    if entrada and entrada.get("personalizada"):
        cod = lugar_quadro(entrada)
        quadro = QUADRO_DO_LUGAR.get(cod, "")
        if cod == "IMOVEL":
            return _Q_IMOVEL, str(entrada.get("nome") or arquivo)
        if quadro:
            return quadro, str(entrada.get("nome") or arquivo)
    return _Q_LISTA, str((entrada or {}).get("nome") or arquivo)


def destinos_ordenados(indice):
    """[(quadro, [(arquivo, nome, linha), ...]), ...] na ordem do Quadro de Áreas."""
    grupos = {}
    for arquivo, entrada in indice.items():
        if str(entrada.get("tipo") or "P") != "P" and arquivo not in QUADRO_FIXO:
            quadro = _Q_LISTA
            linha = str(entrada.get("nome") or arquivo)
        else:
            quadro, linha = onde_na_tabela(arquivo, entrada)
        grupos.setdefault(quadro, []).append((arquivo, str(entrada.get("nome") or arquivo), linha))
    saida = []
    for quadro in ORDEM_QUADROS + sorted(q for q in grupos if q not in ORDEM_QUADROS):
        if quadro in grupos:
            saida.append((quadro, sorted(grupos[quadro], key=lambda x: x[1].casefold())))
    return saida


def preencher_combo_destinos(combo, indice, antes=None, depois=None):
    """Combo agrupado por quadro da tabela (títulos em negrito, não selecionáveis).
    antes/depois: [(texto, dado)] extras no início/fim (ex.: Automático, Ignorar, Referência)."""
    combo.clear()
    for texto, dado in antes or []:
        combo.addItem(texto, dado)
    modelo = combo.model()
    for quadro, itens in destinos_ordenados(indice):
        titulo = QStandardItem(f"— {quadro} —")
        fonte = QFont(); fonte.setBold(True); titulo.setFont(fonte)
        titulo.setFlags(Qt.ItemFlag.NoItemFlags); titulo.setData(None, Qt.ItemDataRole.UserRole)
        modelo.appendRow(titulo)
        for arquivo, nome, linha in itens:
            combo.addItem("    " + nome, arquivo)
            dica = f"Quadro: {quadro}\nLinha: {linha}\nARQUIVO: {arquivo}"
            combo.setItemData(combo.count() - 1, dica, Qt.ItemDataRole.ToolTipRole)
    for texto, dado in depois or []:
        combo.addItem(texto, dado)


def _textos_camada(camada):
    from .areas import _textos_camada as textos
    try:
        return textos(camada)
    except Exception:
        return [camada.name()]


class DialogoApelidos(QDialog):
    """Lista de nomes ensinados ao plugin. Abre de Calcular áreas e de Ferramentas."""

    def __init__(self, plugin, parent=None, nome_inicial="", destino_inicial=""):
        super().__init__(parent or plugin.iface.mainWindow())
        self.plugin = plugin; self.alterou = False
        self.projeto = QgsProject.instance()
        preparar_dialogo(self, "tela_apelidos", "Norte Agro - Nomes não reconhecidos", (640, 520)); self.resize(820, 680)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho(
            "Nomes não reconhecidos",
            "Escreva o nome da camada que o plugin não reconhece e escolha em qual linha da tabela ela entra. "
            "Daí em diante o cálculo trata essa camada como a camada padrão escolhida.",
            os.path.join(os.path.dirname(__file__), "icon.png"),
        ))
        raiz.addWidget(secao("Ensinar um nome"))
        l1 = QHBoxLayout(); l1.addWidget(QLabel("Nome da camada:"))
        self.nome = QLineEdit(nome_inicial or "")
        self.nome.setPlaceholderText("Ex.: APP Antropizada até 2008, Mata nativa cliente, RL averbada")
        self.nome.setToolTip("Escreva o nome como ele vem na camada (no QGIS ou no arquivo .shp). Maiúsculas, acentos, "
                             "_ e - não importam.")
        self.nome.textChanged.connect(self._previa); l1.addWidget(self.nome, 1)
        self.btn_projeto = QPushButton("Camadas deste projeto"); self.btn_projeto.setToolTip("Escolher o nome de uma camada aberta no projeto.")
        self.menu_projeto = QMenu(self.btn_projeto); self.btn_projeto.setMenu(self.menu_projeto)
        self.menu_projeto.aboutToShow.connect(self._montar_menu_projeto); l1.addWidget(self.btn_projeto)
        raiz.addLayout(l1)

        l2 = QHBoxLayout(); l2.addWidget(QLabel("Entra na tabela como:"))
        self.destino = QComboBox(); self.destino.setMinimumWidth(360); self.destino.setMaxVisibleItems(24)
        self.destino.currentIndexChanged.connect(self._previa); l2.addWidget(self.destino, 1); raiz.addLayout(l2)
        self.onde = QLabel(); self.onde.setProperty("naSubtitle", True); self.onde.setWordWrap(True); raiz.addWidget(self.onde)

        l3 = QHBoxLayout(); l3.addWidget(QLabel("Vale para:"))
        self.r_escritorio = QRadioButton("Todos os projetos")
        self.r_projeto = QRadioButton("Só este projeto")
        self.r_projeto.setToolTip("Grava a escolha nas camadas abertas neste projeto que têm esse nome (fica salvo no .qgz).")
        grupo = QButtonGroup(self); grupo.addButton(self.r_escritorio); grupo.addButton(self.r_projeto)
        self.r_escritorio.setChecked(True); self.r_escritorio.toggled.connect(self._previa)
        l3.addWidget(self.r_escritorio); l3.addWidget(self.r_projeto); l3.addStretch(); raiz.addLayout(l3)

        l4 = QHBoxLayout()
        self.previa = QLabel(); self.previa.setWordWrap(True); self.previa.setProperty("naSubtitle", True); l4.addWidget(self.previa, 1)
        self.btn_salvar = botao_principal("Salvar nome", self); self.btn_salvar.setIcon(icone_tema("/mActionAdd.svg"))
        self.btn_salvar.clicked.connect(self.salvar); self.nome.returnPressed.connect(self.salvar); l4.addWidget(self.btn_salvar)
        raiz.addLayout(l4)

        raiz.addWidget(secao("Nomes já ensinados"))
        self.lista = QTreeWidget(); self.lista.setColumnCount(4)
        self.lista.setHeaderLabels(["Nome da camada", "Entra como", "Quadro da tabela", "Vale para"])
        self.lista.setRootIsDecorated(False); self.lista.setAlternatingRowColors(True)
        cab = self.lista.header(); cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3): cab.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.lista.itemSelectionChanged.connect(self._estado_botoes)
        self.lista.itemDoubleClicked.connect(self._editar_item); raiz.addWidget(self.lista, 1)
        rod = QHBoxLayout()
        self.btn_rem = botao_secundario("Remover da lista", self); self.btn_rem.setIcon(icone_tema("/mActionRemove.svg"))
        self.btn_rem.clicked.connect(self.remover); rod.addWidget(self.btn_rem)
        dica = QLabel("Dois cliques num nome para trocar o destino."); dica.setProperty("naSubtitle", True); rod.addWidget(dica)
        rod.addStretch()
        fechar = botao_secundario("Fechar", self); fechar.clicked.connect(self.accept); rod.addWidget(fechar); raiz.addLayout(rod)

        self._recarregar_indice()
        if destino_inicial:
            i = self.destino.findData(destino_inicial)
            if i >= 0: self.destino.setCurrentIndex(i)
        self._situacao(); self._carregar(); self._previa()

    # ------------------------------------------------------------ dados
    def _recarregar_indice(self):
        atual = self.destino.currentData() if self.destino.count() else None
        self.indice = indice_reconhecimento(self.projeto)
        preencher_combo_destinos(self.destino, self.indice, antes=[("Escolha a camada padrão / linha da tabela...", "")])
        i = self.destino.findData(atual) if atual else -1
        self.destino.setCurrentIndex(i if i >= 0 else 0)

    def _situacao(self):
        """v0.2.0: o catálogo fica dentro do plugin; não há mais aviso de Drive."""
        return

    def _camadas_vetoriais(self):
        return [c for c in self.projeto.mapLayers().values()
                if isinstance(c, QgsVectorLayer) and str(c.customProperty("norteagro/conferencia", "") or "") != "1"]

    def _reconhecimento_atual(self):
        try:
            from .areas import prever_reconhecimentos
            camadas = self._camadas_vetoriais()
            prev, _ = prever_reconhecimentos(camadas, "", self.indice, apelidos_manuais_projeto(self.projeto), {})
            return camadas, prev
        except Exception:
            return [], {}

    def _montar_menu_projeto(self):
        self.menu_projeto.clear()
        camadas, prev = self._reconhecimento_atual()
        if not camadas:
            a = self.menu_projeto.addAction("(nenhuma camada vetorial no projeto)"); a.setEnabled(False); return
        def rotulo(c):
            r = prev.get(c.id(), {})
            if r.get("referencia"): return "referência"
            if r.get("ignorar"): return "ignorada"
            if not r.get("arquivo"): return "NÃO RECONHECIDA"
            nome = self.indice.get(r["arquivo"], {}).get("nome", r["arquivo"])
            return ("parecida com " if r.get("via") == "semelhança" else "") + nome
        problemas = [c for c in camadas if not prev.get(c.id(), {}).get("arquivo") or prev.get(c.id(), {}).get("via") == "semelhança"]
        outras = [c for c in camadas if c not in problemas and not str(c.customProperty("norteagro/arquivo", "") or "")]
        for titulo, lista in (("Não reconhecidas / incertas", problemas), ("Outras camadas", outras)):
            if not lista: continue
            t = self.menu_projeto.addAction(titulo); t.setEnabled(False)
            for c in sorted(lista, key=lambda x: x.name().casefold()):
                a = self.menu_projeto.addAction(f"{c.name()}   ({rotulo(c)})")
                a.triggered.connect(lambda _=False, n=c.name(): self.nome.setText(n))

    def _carregar(self):
        self.lista.clear()
        nomes = {a: e.get("nome", a) for a, e in self.indice.items()}
        for apelido, arquivo in sorted(apelidos_escritorio(forcar=True).items(), key=lambda kv: kv[0].casefold()):
            quadro, _ = onde_na_tabela(arquivo, self.indice.get(arquivo, {}))
            it = QTreeWidgetItem([apelido, nomes.get(arquivo, arquivo), quadro, "Todos os projetos"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("escritorio", apelido, arquivo))
            if arquivo not in self.indice:
                it.setText(1, f"{arquivo} (camada não existe mais no catálogo)")
                for c in range(4): it.setForeground(c, QBrush(QColor("#B00020")))
            self.lista.addTopLevelItem(it)
        camadas = {}
        for c in self._camadas_vetoriais():
            try:
                from .areas import chave_manual_camada
                camadas[chave_manual_camada(c)] = c.name()
            except Exception:
                pass
        for chave, arquivo in sorted(apelidos_manuais_projeto(self.projeto).items()):
            nome = camadas.get(chave) or os.path.splitext(os.path.basename(chave))[0] or chave
            if arquivo == "__IGNORAR__": entra, quadro = "Ignorar no cálculo", "-"
            elif arquivo == "__REFERENCIA__": entra, quadro = "Referência (não calcular)", "-"
            else:
                entra = nomes.get(arquivo, arquivo); quadro, _ = onde_na_tabela(arquivo, self.indice.get(arquivo, {}))
            it = QTreeWidgetItem([nome, entra, quadro, "Este projeto"])
            it.setToolTip(0, chave); it.setData(0, Qt.ItemDataRole.UserRole, ("projeto", chave, arquivo)); self.lista.addTopLevelItem(it)
        if not self.lista.topLevelItemCount():
            it = QTreeWidgetItem(["(nenhum nome ensinado ainda)", "", "", ""]); it.setFlags(Qt.ItemFlag.NoItemFlags); self.lista.addTopLevelItem(it)
        self._estado_botoes()

    def _estado_botoes(self):
        it = self.lista.currentItem()
        self.btn_rem.setEnabled(bool(it and it.data(0, Qt.ItemDataRole.UserRole)))

    def _editar_item(self, it, _col=0):
        dado = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        if not dado: return
        escopo, chave, arquivo = dado
        if escopo == "escritorio":
            self.nome.setText(chave); self.r_escritorio.setChecked(True)
        else:
            self.nome.setText(it.text(0)); self.r_projeto.setChecked(True)
        i = self.destino.findData(arquivo)
        if i >= 0: self.destino.setCurrentIndex(i)
        self.nome.setFocus()

    # ------------------------------------------------------------ prévia
    def _camadas_com_nome(self, nome):
        chaves = set(chaves_texto(nome))
        if not chaves: return []
        saida = []
        for c in self._camadas_vetoriais():
            if str(c.customProperty("norteagro/arquivo", "") or ""): continue
            textos = _textos_camada(c)[:2]  # nome no QGIS e nome do arquivo
            if any(set(chaves_texto(t)) & chaves for t in textos):
                saida.append(c)
        return saida

    def _previa(self, *_):
        arquivo = str(self.destino.currentData() or "")
        if arquivo:
            quadro, linha = onde_na_tabela(arquivo, self.indice.get(arquivo, {}))
            self.onde.setText(f"Na tabela: quadro <b>{quadro}</b> → linha <b>{linha}</b>.")
        else:
            self.onde.setText("Os destinos estão agrupados pelo quadro da tabela onde a linha aparece.")
        nome = self.nome.text().strip()
        if not nome or not normalizar_chave(nome):
            self.previa.setText("Digite o nome ou escolha uma camada do projeto."); self.btn_salvar.setEnabled(False); return
        if not arquivo:
            self.previa.setText("Escolha em qual linha da tabela essa camada entra."); self.btn_salvar.setEnabled(False); return
        afetadas = self._camadas_com_nome(nome)
        _, prev = self._reconhecimento_atual() if afetadas else ([], {})
        partes = []
        chave = normalizar_chave(nome)
        canon = {}
        for arq, ent in self.indice.items():
            for k in chaves_texto(arq) + chaves_texto(ent.get("nome", "")):
                canon.setdefault(k, arq)
        if canon.get(chave) == arquivo:
            partes.append("Esse nome já é reconhecido automaticamente como essa camada.")
        elif canon.get(chave):
            partes.append(f"Atenção: hoje esse nome é a camada padrão \"{self.indice[canon[chave]].get('nome')}\"; o nome ensinado passa na frente.")
        if afetadas:
            mudam = [c.name() for c in afetadas if prev.get(c.id(), {}).get("arquivo") != arquivo]
            if mudam:
                mais = f" e mais {len(mudam) - 5}" if len(mudam) > 5 else ""
                partes.append("Neste projeto passam a entrar assim: " + ", ".join(mudam[:5]) + mais + ".")
            else:
                partes.append("As camadas deste projeto com esse nome já entram assim.")
        elif self.r_projeto.isChecked():
            partes.append("Nenhuma camada aberta neste projeto tem esse nome - para \"Só este projeto\" a camada precisa estar aberta.")
        else:
            partes.append("Nenhuma camada aberta tem esse nome agora; vale para os próximos projetos.")
        self.previa.setText(" ".join(partes))
        self.btn_salvar.setEnabled(not (self.r_projeto.isChecked() and not afetadas))

    # ------------------------------------------------------------ ações
    def salvar(self):
        if not self.btn_salvar.isEnabled(): return
        nome = self.nome.text().strip(); arquivo = str(self.destino.currentData() or "")
        entrada = self.indice.get(arquivo, {}); destino_nome = entrada.get("nome", arquivo)
        quadro, _ = onde_na_tabela(arquivo, entrada)
        if self.r_projeto.isChecked():
            from .areas import chave_manual_camada
            dados = apelidos_manuais_projeto(self.projeto)
            camadas = self._camadas_com_nome(nome)
            for c in camadas:
                dados[chave_manual_camada(c)] = arquivo
            salvar_apelidos_manuais_projeto(self.projeto, dados)
            self.alterou = True; self._carregar(); self._previa()
            sucesso(self, "Nome salvo", f"{len(camadas)} camada(s) deste projeto passam a entrar como \"{destino_nome}\" ({quadro}).",
                    ["Fica gravado no projeto: salve o projeto (.qgz) para manter."])
            return
        if entrada.get("origem") in ("projeto", "camada"):
            alertar(self, "Nomes não reconhecidos",
                    f"\"{destino_nome}\" é uma camada personalizada só deste projeto; os outros projetos não a conhecem.",
                    ["Marque \"Só este projeto\" ou catalogue a camada no escritório primeiro (Criar e gerenciar camadas)."])
            return
        try:
            salvar_apelido_escritorio(nome, arquivo, self.indice)
        except Exception as exc:
            self.plugin.log(f"Falha ao salvar nome não reconhecido: {exc}")
            alertar(self, "Nomes não reconhecidos", "Não foi possível salvar o nome.", [str(exc)]); return
        self.alterou = True
        self.nome.clear(); self._carregar(); self._previa()
        sucesso(self, "Nome salvo",
                f"\"{nome}\" agora entra como \"{destino_nome}\" ({quadro}).",
                ["Fica guardado dentro do plugin e vale para todos os projetos."])

    def remover(self):
        it = self.lista.currentItem(); dado = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        if not dado: return
        escopo, chave, _arquivo = dado
        if not confirmar(self, "Nomes não reconhecidos", f"Remover \"{it.text(0)}\" da lista?", "Remover", destrutivo=True):
            return
        try:
            if escopo == "escritorio":
                remover_apelido_escritorio(chave)
            else:
                dados = apelidos_manuais_projeto(self.projeto); dados.pop(chave, None)
                salvar_apelidos_manuais_projeto(self.projeto, dados)
        except Exception as exc:
            alertar(self, "Nomes não reconhecidos", "Não foi possível remover o nome.", [str(exc)]); return
        self.alterou = True; self._situacao(); self._carregar(); self._previa()


def abrir_apelidos(plugin, parent=None, nome_inicial="", destino_inicial=""):
    dlg = DialogoApelidos(plugin, parent, nome_inicial, destino_inicial)
    dlg.exec()
    return dlg.alterou
