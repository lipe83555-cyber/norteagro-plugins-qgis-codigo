# -*- coding: utf-8 -*-
"""Imagens de satélite e legenda padrão (etapas "Mapas e imagens" e "Legenda" da aba Planta).

- Acha a camada do imóvel (tabela de correspondência) e busca em segundo plano, para cada mapa, a imagem
  mais recente do ano pedido com a melhor qualidade em cores reais (Passivos: 2019 à esquerda e o ano atual
  à direita; Uso do Solo: ano atual no mapa principal).
- Cada mapa tem uma lista de imagens para escolher; a data da escolhida vai para o quadro branco do mapa.
- Legenda: itens padrão do modelo, cada um com a camada do projeto; a pessoa marca, desmarca, troca a
  camada, renomeia, acrescenta, remove ou reordena itens. A escolha fica salva para as próximas plantas.

A classe não é um widget de tela: ela monta duas páginas (`pagina_imagens` e `pagina_legenda`) que a
janela coloca nas etapas certas.
"""

from ..core import compat
import json
import os
import time
from datetime import date

from qgis.core import QgsApplication, QgsLayerTree, QgsMapLayer, QgsMapLayerProxyModel, QgsProject
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                                 QHeaderView, QLabel, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                                 QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .. import builder
from ..modelos import legenda_escolhivel, legendas_do_meta
from ..core import config, imagens, log
from ..core.correspondencia import chave as chave_nome
from .andamento import CartaoAndamento, tempo_txt
from .tarefas import TarefaImagens, iniciar

GRUPO_IMAGENS = "NorteAgro - Imagens de satélite"
SEM_IMAGEM = "Sem imagem automática (usar as camadas marcadas no mapa)"
NOMES_MAPA = {"mapa_esquerdo": "Mapa esquerdo", "mapa_direito": "Mapa direito", "mapa_principal": "Mapa principal"}


def _estilo_nome(nome):
    """'Área Suprimida antes de 2019' -> 'Área suprimida antes de 2019' (siglas como APP e RL ficam)."""
    palavras = (nome or "").split(" ")
    saida = []
    for i, p in enumerate(palavras):
        if len(p) > 1 and p.isupper():
            saida.append(p)
        elif i == 0:
            saida.append(p[:1].upper() + p[1:].lower())
        else:
            saida.append(p.lower())
    return " ".join(saida)


def _secao(titulo):
    g = QGroupBox(titulo)
    g.setObjectName("secao")
    return g


def _dica(texto):
    lb = QLabel(texto)
    lb.setObjectName("dica")
    lb.setWordWrap(True)
    return lb


class PainelPassivos(QObject):
    def __init__(self, iface, corr, definir_data, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.corr = corr
        self.definir_data = definir_data  # (variavel, texto) -> preenche o campo da data
        self.projeto = QgsProject.instance()
        self.meta = {}
        self.resultado = None
        self.tarefa = None
        self.ao_terminar_busca = None
        self.combos_img = {}  # id_mapa -> (QComboBox, cfg)
        self.cfgs_leg = []  # legendas do modelo escolhidas na tela (Passivos: uma por mapa)
        self._estados = []  # por legenda: {"grupo": caminho, "linhas": [itens]}
        self._ativa = 0
        self._grupos = {}
        self._t0 = 0.0
        self._montar_imagens()
        self._montar_legenda()

    # ================================================================ páginas
    def _montar_imagens(self):
        self.pagina_imagens = g = _secao("Imagem de satélite")
        v = QVBoxLayout(g)
        v.addWidget(_dica("Em cada mapa entra a imagem mais recente do ano pedido, com a melhor qualidade em cores "
                          "reais: alta resolução (Esri Wayback, 0,3–0,5 m) quando houver naquele ano; senão "
                          "Sentinel-2 (10 m) sem nuvem sobre o imóvel."))
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cb_imovel = QgsMapLayerComboBox()
        self.cb_imovel.setFilters(compat.FILTRO_POLIGONO)
        self.cb_imovel.setAllowEmptyLayer(True)
        self.cb_imovel.setToolTip("Polígono usado para procurar as imagens (achado pelo nome: AREA_DO_IMOVEL...).")
        f.addRow("Área do imóvel:", self.cb_imovel)
        h = QHBoxLayout()
        self.sp_ano_antiga = QSpinBox()
        self.sp_ano_antiga.setRange(2010, 2100)
        self.sp_ano_antiga.setValue(2019)
        self.sp_ano_antiga.setToolTip("Mapa esquerdo: a imagem mais recente deste ano.")
        self.sp_ano = QSpinBox()
        self.sp_ano.setRange(2015, 2100)
        self.sp_ano.setValue(date.today().year)
        self.sp_ano.setToolTip("A imagem mais recente deste ano, sem nuvens sobre o imóvel.")
        self.lb_ano_antiga = QLabel("Imagem antiga:")
        self.lb_ano_recente = QLabel("Imagem recente:")
        h.addWidget(self.lb_ano_antiga)
        h.addWidget(self.sp_ano_antiga)
        h.addSpacing(18)
        h.addWidget(self.lb_ano_recente)
        h.addWidget(self.sp_ano)
        h.addStretch()
        f.addRow("Anos:", h)
        self.form_img = f
        v.addLayout(f)
        h = QHBoxLayout()
        self.b_buscar = QPushButton("Buscar imagens")
        self.b_buscar.setObjectName("secundario")
        self.b_buscar.clicked.connect(lambda: self.buscar())
        h.addWidget(self.b_buscar)
        h.addStretch()
        v.addLayout(h)
        self.lb_busca = _dica("Leva cerca de 15 segundos. Se você gerar a planta sem buscar, o plugin pergunta.")
        v.addWidget(self.lb_busca)

        # ---- cartão de andamento: título e % grandes, barra fina, etapa atual e tempo restante
        self.cartao = CartaoAndamento()
        v.addWidget(self.cartao)

    def _montar_legenda(self):
        self.pagina_legenda = w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        # modelos com mais de uma legenda (Passivos: mapa da esquerda e mapa da direita)
        self.linha_qual = QWidget()
        h = QHBoxLayout(self.linha_qual)
        h.setContentsMargins(0, 0, 0, 0)
        lb = QLabel("Legenda do:")
        lb.setStyleSheet("font-weight: 600")
        h.addWidget(lb)
        self.cb_qual = QComboBox()
        self.cb_qual.setMinimumContentsLength(30)
        self.cb_qual.setToolTip("Cada mapa tem a sua legenda; escolha qual editar.")
        self.cb_qual.currentIndexChanged.connect(self._trocar_legenda)
        h.addWidget(self.cb_qual, 1)
        v.addWidget(self.linha_qual)
        self.linha_qual.setVisible(False)
        h = QHBoxLayout()
        h.addWidget(QLabel("Camadas da legenda vêm do grupo:"))
        self.cb_grupo = QComboBox()
        self.cb_grupo.setMinimumContentsLength(30)
        self.cb_grupo.setToolTip("Grupo do painel de camadas cujas camadas viram itens da legenda.")
        self.cb_grupo.currentIndexChanged.connect(lambda *_: self._grupo_mudou())
        h.addWidget(self.cb_grupo, 1)
        b = QToolButton()
        b.setText("↻ Recarregar")
        b.setToolTip("Relê os grupos e as camadas do projeto")
        b.clicked.connect(self._recarregar_grupos)
        h.addWidget(b)
        v.addLayout(h)
        self.tb_leg = QTableWidget(0, 3)
        self.tb_leg.setHorizontalHeaderLabels(["", "Nome na legenda", "Camada do projeto"])
        cab = self.tb_leg.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tb_leg.verticalHeader().setVisible(False)
        self.tb_leg.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tb_leg.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tb_leg.setAlternatingRowColors(True)
        self.tb_leg.setMinimumHeight(260)
        v.addWidget(self.tb_leg, 1)
        h = QHBoxLayout()
        self.botoes_leg = []
        for texto, acao, dica in (("Adicionar", self._adicionar_linha, "Acrescenta outra camada à legenda"),
                                  ("Remover", self._remover_linha, "Tira o item selecionado da legenda"),
                                  ("▲", lambda: self._mover(-1), "Sobe o item selecionado"),
                                  ("▼", lambda: self._mover(1), "Desce o item selecionado")):
            b = QToolButton()
            b.setText(texto)
            b.setToolTip(dica)
            b.clicked.connect(acao)
            h.addWidget(b)
            self.botoes_leg.append(b)
        h.addStretch()
        b = QToolButton()
        b.setText("Marcar todas")
        b.clicked.connect(lambda: self._marcar_todas(True))
        h.addWidget(b)
        self.botoes_leg.append(b)
        b = QToolButton()
        b.setText("Desmarcar todas")
        b.clicked.connect(lambda: self._marcar_todas(False))
        h.addWidget(b)
        self.botoes_leg.append(b)
        v.addLayout(h)
        self.lb_leg = _dica("")
        v.addWidget(self.lb_leg)

    # ================================================================ modelo
    def configurar(self, meta):
        self.meta = meta or {}
        self.resultado = None
        tipos = {c.get("tipo") for c in (self.meta.get("imagens") or {}).values()}
        for wdg in (self.lb_ano_antiga, self.sp_ano_antiga):
            wdg.setVisible("antiga" in tipos)
        imovel = builder.camada_imovel(self.projeto, self.corr)
        if imovel is not None:
            self.cb_imovel.setLayer(imovel)
        for _ident, (cb, _cfg) in list(self.combos_img.items()):
            self.form_img.removeRow(cb)
        self.combos_img = {}
        for ident, cfg in (self.meta.get("imagens") or {}).items():
            cb = QComboBox()
            cb.setMinimumContentsLength(40)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.currentIndexChanged.connect(lambda _i, k=ident: self._imagem_mudou(k))
            self.form_img.addRow(f"{NOMES_MAPA.get(ident, ident)}:", cb)
            self.combos_img[ident] = (cb, cfg)
        self._preencher_combos()
        config.definir(self._chave_cfg(), "")  # versões antigas guardavam a legenda; agora vem sempre do grupo
        self.cfgs_leg = [c for c in legendas_do_meta(self.meta) if legenda_escolhivel(c)]
        self._ativa = 0
        self.cb_qual.blockSignals(True)
        self.cb_qual.clear()
        for c in self.cfgs_leg:
            self.cb_qual.addItem(c.get("nome") or c.get("id"), c.get("id"))
        self.cb_qual.blockSignals(False)
        self.linha_qual.setVisible(len(self.cfgs_leg) > 1)
        self._recarregar_grupos()

    def tem_imagens(self):
        return bool(self.meta.get("imagens"))

    def tem_legenda(self):
        return bool(self.cfgs_leg)

    # ================================================================ imagens
    def ret_imovel(self):
        cam = self.cb_imovel.currentLayer()
        if cam is None or cam.extent().isEmpty():
            return None
        return imagens.area_imovel(cam, self.projeto)

    def buscar(self, ao_terminar=None):
        if self.tarefa is not None:
            return False
        ret = self.ret_imovel()
        if ret is None:
            self._mensagem("Escolha a camada da área do imóvel para buscar as imagens.", "erro")
            return False
        self.ao_terminar_busca = ao_terminar
        tipos = tuple(sorted({c.get("tipo") for c in (self.meta.get("imagens") or {}).values()}))
        self.tarefa = TarefaImagens(ret, self.sp_ano_antiga.value(), self.sp_ano.value(), tipos)
        self.tarefa.sinais.terminou.connect(self._busca_ok)
        self.tarefa.sinais.falhou.connect(self._busca_falhou)
        self.b_buscar.setEnabled(False)
        self.lb_busca.setVisible(False)
        self.cartao.iniciar(self.tarefa)
        iniciar(self.tarefa)
        return True

    def cancelar(self):
        if self.tarefa is not None:
            self.tarefa.cancel()

    def _mensagem(self, texto, tipo=""):
        cores = {"erro": "#b3261e", "ok": "#46741F", "aviso": "#a15c00"}
        self.lb_busca.setStyleSheet(f"color: {cores[tipo]}" if tipo in cores else "")
        self.lb_busca.setText(texto)

    @property
    def ao_progresso(self):
        return self.cartao.ao_progresso

    @ao_progresso.setter
    def ao_progresso(self, funcao):
        self.cartao.ao_progresso = funcao

    def _fim(self):
        self.tarefa = None
        self.b_buscar.setEnabled(True)

    def _busca_ok(self, resultado):
        dur = tempo_txt(self.cartao.decorrido())
        self._fim()
        self.resultado = resultado
        self._preencher_combos()
        avisos = resultado.get("avisos") or []
        for a in avisos:
            log.aviso(a)
        self.cartao.concluir(f"Imagens encontradas em {dur}",
                             "A melhor de cada mapa já está escolhida; troque na lista se quiser." +
                             "".join("\n• " + a for a in avisos), aviso=bool(avisos))
        self.b_buscar.setText("Buscar de novo")
        if self.ao_progresso:
            self.ao_progresso(f"Imagens de satélite encontradas em {dur}.")
        acao, self.ao_terminar_busca = self.ao_terminar_busca, None
        if acao:
            acao()

    def _busca_falhou(self, erro, _parcial):
        self._fim()
        self.ao_terminar_busca = None
        self.cartao.falhar(erro)

    def busca_feita(self):
        return self.resultado is not None

    def _preencher_combos(self):
        rasters = [c for c, _v in builder.camadas_projeto(self.projeto) if c.type() == compat.CAMADA_RASTER]
        for ident, (cb, cfg) in self.combos_img.items():
            atual = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cands = (self.resultado or {}).get(cfg.get("tipo")) or []
            for c in cands:
                cb.addItem(c["descricao"], {"cand": c})
            if rasters:
                cb.insertSeparator(cb.count())
                for r in rasters:
                    cb.addItem(f"Camada do projeto: {r.name()}", {"camada": r.id()})
            cb.addItem(SEM_IMAGEM, None)
            idx = 0 if cands else cb.count() - 1
            if atual is not None and not cands:
                for i in range(cb.count()):
                    if cb.itemData(i) == atual:
                        idx = i
            cb.setCurrentIndex(idx)
            cb.blockSignals(False)
            self._imagem_mudou(ident)

    def _imagem_mudou(self, ident):
        cb, cfg = self.combos_img[ident]
        d = cb.currentData()
        cand = None
        if d and d.get("cand"):
            cand = d["cand"]
        elif d and d.get("camada"):
            cam = self.projeto.mapLayer(d["camada"])
            cand = imagens.candidata_da_camada(cam) if cam else None
        if cand and cfg.get("variavel"):
            self.definir_data(cfg["variavel"], imagens.data_extenso(cand["data"]))

    def imagens_escolhidas(self, progresso=lambda t: None):
        """{id_mapa: camada} criando (uma vez) as camadas das imagens escolhidas; e os créditos das fontes."""
        saida, creditos = {}, []
        ret = self.ret_imovel()
        for ident, (cb, _cfg) in self.combos_img.items():
            d = cb.currentData()
            if not d:
                continue
            if d.get("camada"):
                cam = self.projeto.mapLayer(d["camada"])
                if cam is not None:
                    saida[ident] = cam
                    c = imagens.candidata_da_camada(cam)
                    if c and c.get("credito"):
                        creditos.append(c["credito"])
                continue
            c = d["cand"]
            cam = self._camada_existente(c)
            if cam is None:
                progresso(f"Preparando a imagem de {imagens.data_br(c['data'])}...")
                cam = imagens.criar_camada(c, ret, self._pasta_imagens())
                self._adicionar_ao_projeto(cam)
            saida[ident] = cam
            creditos.append(c["credito"])
        return saida, list(dict.fromkeys(creditos))

    def _camada_existente(self, c):
        for cam in self.projeto.mapLayers().values():
            o = imagens.candidata_da_camada(cam)
            if o and o.get("fonte") == c["fonte"] and o.get("data") == c["data"] and \
                    o.get("num") == c.get("num") and o.get("id") == c.get("id"):
                return cam
        return None

    def _pasta_imagens(self):
        arq = self.projeto.fileName()
        if arq:
            return os.path.join(os.path.dirname(arq), "imagens_satelite")
        return os.path.join(QgsApplication.qgisSettingsDirPath(), "norteagro_imagens")

    def _adicionar_ao_projeto(self, cam):
        raiz = self.projeto.layerTreeRoot()
        grupo = raiz.findGroup(GRUPO_IMAGENS) or raiz.addGroup(GRUPO_IMAGENS)
        self.projeto.addMapLayer(cam, False)
        no = grupo.addLayer(cam)
        no.setItemVisibilityChecked(False)  # aparece só nos mapas da planta; marque para ver na tela
        grupo.setExpanded(False)

    # ================================================================ legenda
    def _chave_cfg(self):
        return f"legenda/{self.meta.get('id', 'modelo')}"

    # ---- de onde vêm as camadas da legenda
    def _grupos_projeto(self):
        """[(caminho, nó do grupo)] de todos os grupos do painel de camadas (menos os de apoio do plugin)."""
        saida = []

        def andar(g, pref):
            for c in g.children():
                if QgsLayerTree.isGroup(c):
                    caminho = f"{pref} / {c.name().strip()}" if pref else c.name().strip()
                    if c.name() not in (GRUPO_IMAGENS, builder.GRUPO_APOIO):
                        saida.append((caminho, c))
                    andar(c, caminho)

        andar(self.projeto.layerTreeRoot(), "")
        return saida

    def _cfg(self):
        return self.cfgs_leg[self._ativa] if self.cfgs_leg and self._ativa < len(self.cfgs_leg) else {}

    def _rotulo_padrao(self, cfg):
        nomes = {"USODOSOLO": "Uso do Solo", "PASSIVO": "Passivos"}
        alvo = ", ".join(nomes.get(chave_nome(t), t) for t in cfg.get("grupo") or [])
        return f"Padrão do escritório (camadas de '{alvo}' pela tabela de nomes)" if alvo else \
            "Padrão do modelo"

    def _grupo_padrao(self, cfg):
        """Grupo do painel de camadas com o nome do modelo ('Uso do Solo', 'Passivos'); '' se não houver."""
        tokens = [chave_nome(t) for t in cfg.get("grupo") or []]
        for caminho in self._grupos:
            nome = chave_nome(caminho.split(" / ")[-1])
            if any(t and t in nome for t in tokens):
                return caminho
        return ""

    def _itens_de(self, cfg, caminho):
        """Itens (já ordenados no padrão) de uma legenda, vindos do grupo escolhido ou do padrão do escritório."""
        no = self._grupos.get(caminho) if caminho else None
        if no is not None:
            itens = [{"nome": (self.corr.nome_legenda(c.name()) if self.corr else None) or c.name(),
                      "chave": c.id(), "usar": True, "padrao": False, "camada": c}
                     for c in self._camadas_do_grupo(no)]
        else:
            itens = self._itens_padrao(cfg)
        for it in itens:
            if it.get("camada") is None and it.get("chave"):
                it["camada"] = builder.achar_camada(self.projeto, it["chave"], self.corr)
        excluir = set(cfg.get("excluir") or [])
        if excluir and self.corr:
            def chave_do(it):
                cam = it.get("camada")
                item = self.corr.procurar(cam.name() if cam is not None else it.get("chave", ""))
                return item["arquivo"] if item else it.get("chave")
            itens = [it for it in itens if chave_do(it) not in excluir]
        return self._ordenar(itens, cfg)

    def _recarregar_grupos(self):
        """Relê os grupos do projeto e refaz todas as legendas (cada uma com o grupo do seu modelo)."""
        self._grupos = dict(self._grupos_projeto())
        self._estados = []
        for cfg in self.cfgs_leg:
            g = self._grupo_padrao(cfg)
            self._estados.append({"grupo": g, "linhas": self._itens_de(cfg, g)})
        self._mostrar(self._ativa if self._ativa < len(self._estados) else 0)

    def _mostrar(self, i):
        """Põe na tela a legenda i."""
        self._ativa = i
        self.tb_leg.setRowCount(0)
        self.cb_grupo.blockSignals(True)
        self.cb_grupo.clear()
        if not self.cfgs_leg:
            self.cb_grupo.blockSignals(False)
            self._resumo_legenda()
            return
        cfg, est = self.cfgs_leg[i], self._estados[i]
        self.cb_grupo.addItem(self._rotulo_padrao(cfg), "")
        for caminho in self._grupos:
            self.cb_grupo.addItem(f"Grupo: {caminho}", caminho)
        self.cb_grupo.setCurrentIndex(max(0, self.cb_grupo.findData(est["grupo"])))
        self.cb_grupo.blockSignals(False)
        self.cb_qual.blockSignals(True)
        self.cb_qual.setCurrentIndex(i)
        self.cb_qual.blockSignals(False)
        self._carregar_de_linhas(est["linhas"])

    def _guardar(self):
        """Guarda o que está na tabela na legenda ativa."""
        if self.cfgs_leg and self._ativa < len(self._estados):
            self._estados[self._ativa] = {"grupo": self.cb_grupo.currentData() or "", "linhas": self._linhas()}

    def _trocar_legenda(self, i):
        if i < 0 or i >= len(self.cfgs_leg) or i == self._ativa:
            return
        self._guardar()
        self._mostrar(i)

    def _grupo_mudou(self):
        if not self.cfgs_leg:
            return
        caminho = self.cb_grupo.currentData() or ""
        self._estados[self._ativa] = {"grupo": caminho, "linhas": self._itens_de(self._cfg(), caminho)}
        self._carregar_de_linhas(self._estados[self._ativa]["linhas"])

    def _carregar_legenda(self, itens=None):
        """Recarrega a legenda ativa a partir do grupo escolhido (ou mostra os itens dados)."""
        if itens is None:
            self._grupo_mudou()
        else:
            self._carregar_de_linhas(itens)

    def _camadas_do_grupo(self, no):
        saida = []
        for n in no.findLayers():
            c = n.layer()
            if c is None or c.type() != compat.CAMADA_VETOR:
                continue
            if self.corr and self.corr.papel(c.name()) in ("municipio", "estado", "brasil"):
                continue
            if c not in saida:
                saida.append(c)
        return saida

    def _itens_padrao(self, cfg):
        """Sem grupo no projeto: itens padrão do modelo e as camadas que a tabela de nomes põe no grupo do
        modelo (Uso do Solo / Passivos), sem repetir camada nem nome."""
        tokens = [chave_nome(t) for t in cfg.get("grupo") or []]
        itens = []
        if tokens and self.corr:
            for c, _vis in builder.camadas_projeto(self.projeto):
                if c.type() != compat.CAMADA_VETOR:
                    continue
                item = self.corr.procurar(c.name())
                if item and any(t in chave_nome(item.get("grupo", "")) for t in tokens):
                    itens.append({"nome": item["nome_legenda"], "chave": c.id(), "usar": True, "padrao": False,
                                  "camada": c})
        padrao, usadas = [], set()
        for n, k in cfg.get("padrao") or []:
            cam = builder.achar_camada(self.projeto, k, self.corr) if self.corr else None
            if cam is not None and cam.id() in usadas:
                continue
            if cam is not None:
                usadas.add(cam.id())
            padrao.append({"nome": n, "chave": k, "usar": True, "padrao": True, "camada": cam})
        nomes = {chave_nome(p["nome"]) for p in padrao}
        for it in itens:
            # camadas repetidas no projeto (mesmo nome de legenda) entram uma vez só
            if it["camada"].id() not in usadas and chave_nome(it["nome"]) not in nomes:
                usadas.add(it["camada"].id())
                nomes.add(chave_nome(it["nome"]))
                padrao.append(it)
        return padrao

    def _ordenar(self, itens, cfg):
        """Ordem e nomes do padrão do modelo (ordem). Camadas que não estão no padrão entram logo depois do
        item 'extras_apos' (Uso do Solo: entre Reserva legal e APP total), na ordem do painel de camadas."""
        ordem = cfg.get("ordem") or []
        if not ordem or not self.corr:
            return itens
        chaves = [k for _n, k in ordem]
        nomes = {k: n for n, k in ordem}
        apos = cfg.get("extras_apos")
        pos_extra = chaves.index(apos) + 0.5 if apos in chaves else len(chaves)
        chaveados = []
        for idx, it in enumerate(itens):
            cam = it.get("camada")
            item = self.corr.procurar(cam.name() if cam is not None else it.get("chave", ""))
            k = item["arquivo"] if item else None
            if k in nomes:
                it = dict(it, nome=nomes[k])
                pos = chaves.index(k)
            else:
                pos = pos_extra
                it = dict(it, nome=_estilo_nome(it.get("nome", "")))
            chaveados.append((pos, idx, it))
        return [it for _p, _i, it in sorted(chaveados, key=lambda t: (t[0], t[1]))]

    def _marcar_todas(self, valor):
        for r in range(self.tb_leg.rowCount()):
            if self.tb_leg.cellWidget(r, 2).currentLayer() is not None:
                self.tb_leg.item(r, 0).setCheckState(Qt.CheckState.Checked if valor else Qt.CheckState.Unchecked)
        self._resumo_legenda()

    def _linha(self, nome, chave, usar=True, padrao=False, camada=None):
        r = self.tb_leg.rowCount()
        self.tb_leg.insertRow(r)
        cam = camada or (builder.achar_camada(self.projeto, chave, self.corr) if chave else None)
        ck = QTableWidgetItem()
        ck.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        ck.setCheckState(Qt.CheckState.Checked if (usar and cam is not None) else Qt.CheckState.Unchecked)
        ck.setToolTip("Marque para o item entrar na legenda")
        ck.setData(Qt.ItemDataRole.UserRole, {"chave": chave, "padrao": padrao})
        self.tb_leg.setItem(r, 0, ck)
        self.tb_leg.setItem(r, 1, QTableWidgetItem(nome))
        cb = QgsMapLayerComboBox()
        cb.setFilters(compat.FILTRO_VETOR)
        cb.setAllowEmptyLayer(True, "— não encontrada (escolha a camada) —")
        cb.setLayer(cam)
        cb.layerChanged.connect(lambda c, item=ck: self._camada_mudou(item, c))
        self.tb_leg.setCellWidget(r, 2, cb)
        self._pintar(r)

    def _camada_mudou(self, item, camada):
        r = self.tb_leg.row(item)
        if camada is not None:
            item.setCheckState(Qt.CheckState.Checked)
            if not self.tb_leg.item(r, 1).text().strip():
                self.tb_leg.item(r, 1).setText(self.corr.nome_legenda(camada.name()) or camada.name())
        self._pintar(r)
        self._resumo_legenda()

    def _pintar(self, r):
        cb = self.tb_leg.cellWidget(r, 2)
        falta = cb is not None and cb.currentLayer() is None
        self.tb_leg.item(r, 1).setForeground(QColor("#b3261e") if falta else QColor("#1f2d24"))

    def _adicionar_linha(self):
        self._linha("", "", True, False)
        self.tb_leg.scrollToBottom()
        self.tb_leg.selectRow(self.tb_leg.rowCount() - 1)
        self._resumo_legenda()

    def _remover_linha(self):
        for r in sorted({i.row() for i in self.tb_leg.selectedIndexes()}, reverse=True):
            self.tb_leg.removeRow(r)
        self._resumo_legenda()

    def _mover(self, passo):
        sel = sorted({i.row() for i in self.tb_leg.selectedIndexes()})
        if len(sel) != 1:
            return
        r = sel[0]
        alvo = r + passo
        if not 0 <= alvo < self.tb_leg.rowCount():
            return
        itens = self._linhas()
        itens[r], itens[alvo] = itens[alvo], itens[r]
        self._carregar_de_linhas(itens)
        self.tb_leg.selectRow(alvo)

    def _linhas(self):
        saida = []
        for r in range(self.tb_leg.rowCount()):
            dado = self.tb_leg.item(r, 0).data(Qt.ItemDataRole.UserRole) or {}
            cam = self.tb_leg.cellWidget(r, 2).currentLayer()
            saida.append({"nome": self.tb_leg.item(r, 1).text().strip(), "camada": cam,
                          "usar": self.tb_leg.item(r, 0).checkState() == Qt.CheckState.Checked,
                          "chave": dado.get("chave") or (cam.name() if cam else ""), "padrao": dado.get("padrao")})
        return saida

    def _carregar_de_linhas(self, linhas):
        self.tb_leg.setRowCount(0)
        for it in linhas:
            self._linha(it.get("nome", ""), it.get("chave", ""), it.get("usar", True), it.get("padrao", False),
                        it.get("camada"))
        self._resumo_legenda()

    def _resumo_legenda(self):
        faltam = self._faltam_em(self._linhas())
        if faltam:
            self.lb_leg.setStyleSheet("color: #b3261e")
            self.lb_leg.setText("Não encontradas no projeto: " + ", ".join(faltam) +
                                ". Escolha a camada na coluna da direita, ou remova o item para ele ficar fora "
                                "da legenda.")
        else:
            self.lb_leg.setStyleSheet("color: #46741F")
            n = sum(1 for l in self._linhas() if l["usar"])
            if n:
                self.lb_leg.setText(f"{n} item(ns) marcado(s) para esta legenda.")
            else:
                self.lb_leg.setStyleSheet("color: #a15c00")
                self.lb_leg.setText("Nenhuma camada marcada: esta legenda sairá vazia. Escolha o grupo "
                                    "acima ou adicione camadas.")

    @staticmethod
    def _faltam_em(linhas):
        return [l.get("nome") or "(item sem nome)" for l in linhas
                if l.get("camada") is None and (l.get("padrao") or l.get("usar", True))]

    def faltando(self):
        """Itens da legenda (de todas as legendas do modelo) sem camada no projeto."""
        if not self.tem_legenda():
            return []
        self._guardar()
        saida = []
        for cfg, est in zip(self.cfgs_leg, self._estados):
            for nome in self._faltam_em(est["linhas"]):
                saida.append(f"{nome} ({cfg.get('nome')})" if len(self.cfgs_leg) > 1 else nome)
        return saida

    def itens_legenda(self):
        """{id da legenda: [(camada, nome)]} marcados, na ordem da tabela.
        None quando o modelo não tem legenda escolhida na tela (legenda automática do modelo)."""
        if not self.tem_legenda():
            return None
        self._guardar()
        return {cfg["id"]: [(l["camada"], l.get("nome") or l["camada"].name()) for l in est["linhas"]
                            if l.get("usar", True) and l.get("camada") is not None]
                for cfg, est in zip(self.cfgs_leg, self._estados)}
