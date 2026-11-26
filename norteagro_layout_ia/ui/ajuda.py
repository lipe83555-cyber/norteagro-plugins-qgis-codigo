# -*- coding: utf-8 -*-
"""Ajuda do plugin (botão "?" no cabeçalho). Abre no tópico da área/etapa em que a pessoa está.
v0.32.0: assuntos à esquerda, explicação no meio e, à direita, os vídeos de cada assunto (videos_ajuda.py)."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
    QWidget,
)

VERDE = "#46741F"


def _dica(t):
    return (f'<table width="100%" cellpadding="6"><tr><td style="background:#EEF4E6; border-left:4px solid {VERDE};">'
            f'<b>Dica:</b> {t}</td></tr></table>')


def _atencao(t):
    return ('<table width="100%" cellpadding="6"><tr><td style="background:#fff4e5; border-left:4px solid #c98a1a;">'
            f'<b>Atenção:</b> {t}</td></tr></table>')


TOPICOS = [
    ("inicio", "Visão geral: o que o plugin faz", f"""
<h2>Layout de plantas</h2>
<p>Monta a planta de <b>Uso do Solo</b> ou de <b>Passivos</b> pronta para imprimir, a partir das camadas do projeto,
da imagem de satélite e da planilha de áreas gerada pelo plugin <i>Criar camadas e calcular áreas</i>.</p>
<p>Abra por <b>Complementos &gt; Norte Agro Projetos &gt; Layout de plantas</b> (ou pelo ícone na barra).</p>
<h3>As três áreas (botões no alto)</h3>
<ul>
<li><b>Nova planta</b> - as 5 etapas da planta: 1 Modelo, 2 Dados do imóvel, 3 Tabelas, 4 Imagem, 5 Legenda.
Use <b>Próximo ›</b> e <b>‹ Voltar</b> ou clique direto na etapa; no fim, <b>Gerar planta</b>.</li>
<li><b>Buscar imagem</b> - só procurar e trazer uma imagem de satélite para o projeto.</li>
<li><b>Configurações</b> - responsável técnico, assinatura, logo, biblioteca de modelos e nomes das camadas.</li>
</ul>
<h3>Antes de começar</h3>
<ul>
<li>As camadas do imóvel abertas no projeto (de preferência criadas pelo <i>Criar camadas e calcular áreas</i>);</li>
<li>a planilha <b>Quadro de Áreas</b> (.xlsx) gerada por ele;</li>
<li>se quiser, o recibo do CAR e a certidão de matrícula em PDF.</li>
</ul>
{_dica("o <b>?</b> abre esta ajuda já no assunto da etapa em que você está. Ao lado de cada assunto ficam os vídeos dele.")}
"""),
    ("modelo", "Etapa 1 - Modelo e folha", f"""
<h2>Etapa 1 - Modelo e folha</h2>
<p>Escolha a planta e o tamanho da folha (A4, A3, A2 ou A1). Modelos salvos por você aparecem como <i>(biblioteca)</i>.</p>
<ul>
<li><b>Uso do Solo</b>: mapa grande com as tabelas no canto, coluna à direita com logo, localização do município,
legenda, parâmetros, dados, imóvel e responsável técnico.</li>
<li><b>Passivos</b>: dois mapas lado a lado - à esquerda a imagem de 2019 com as camadas de Uso do Solo e à direita a
imagem atual com as camadas de Passivos e Compensação, espelhados (legenda, tabelas e escala nos mesmos lugares).</li>
</ul>
<p>A frase embaixo da lista descreve o modelo escolhido.</p>
"""),
    ("dados", "Etapa 2 - Documentos e dados do imóvel", f"""
<h2>Etapa 2 - Documentos e dados do imóvel</h2>
<h3>Documentos do imóvel (opcional)</h3>
<ol>
<li><b>Adicionar PDF...</b> - escolha o recibo do CAR (SIGCAR ou SICAR) e/ou a certidão de matrícula. O botão ao lado tira um PDF da lista.</li>
<li><b>Ler documentos</b> - preenche Propriedade, Proprietário, CAR e Município. Campos em amarelo foram lidos com menos certeza: confira.</li>
</ol>
<p>Matrícula digitalizada (só imagem) não tem texto: digite os dados ou use o OCR opcional ({'<a href="#biblioteca">Configurações avançadas</a>'}).</p>
<h3>Dados do imóvel</h3>
<ul>
<li><b>Propriedade</b>, <b>Proprietário</b> (com vários proprietários, o plugin sugere "PRIMEIRO NOME e outros"; a lista aparece na seta), <b>CAR</b>, <b>Município</b> e <b>Estado</b>.</li>
<li><b>Iniciais maiúsculas no nome do proprietário</b> - escreve "Maria da Silva" em vez de "MARIA DA SILVA".</li>
</ul>
{_dica("o município é achado sozinho pela posição do imóvel (camada Área do Imóvel): não precisa escrever. Se quiser, dá para trocar no campo.")}
"""),
    ("tabelas", "Etapa 3 - Dados de projeto e planilha de áreas", f"""
<h2>Etapa 3 - Dados de projeto e planilha de áreas</h2>
<h3>Dados de projeto</h3>
<ul>
<li><b>Elaboração</b> - seu nome como sai na planta (o plugin lembra os últimos usados).</li>
<li><b>Data</b> - hoje, de fábrica.</li>
<li><b>Fonte</b> - "Google Earth, SICAR" de fábrica; o botão <b>+</b> acrescenta outras (ex.: Imagem Planet, Levantamento topográfico).</li>
</ul>
<h3>Quadro de áreas</h3>
<p>Em <b>Planilha</b>, escolha o .xlsx <b>Quadro de Áreas</b> gerado pelo <i>Criar camadas e calcular áreas</i>. A tabela mostra
cada quadro, a descrição e os hectares; <b>Casas decimais</b> muda quantas casas saem na planta (4 de fábrica). Sem planilha,
as tabelas ficam com os campos para preencher à mão.</p>
<p>O total de cada quadro é a soma das linhas; se não bater com o total gravado na planilha, aparece aviso.</p>
{_atencao("se aparecer “fórmula sem resultado salvo”, abra a planilha no Excel, salve e escolha de novo.")}
"""),
    ("imagem", "Etapa 4 - Mapas e imagens de satélite", f"""
<h2>Etapa 4 - Mapas e imagens de satélite</h2>
<p>O plugin procura a imagem de satélite em cores reais com a melhor qualidade: <b>Esri Wayback</b> (alta resolução)
e <b>Sentinel-2</b> (10 m, sem nuvem sobre o imóvel). Uso do Solo: a mais recente do ano. Passivos: a mais recente de
2019 à esquerda e a mais recente do ano à direita.</p>
<ol>
<li>Confira a camada do imóvel usada para procurar (achada pelo nome: AREA_DO_IMOVEL...).</li>
<li>Clique em <b>Buscar imagens</b>. O cartão mostra a porcentagem e o tempo que falta.</li>
<li>Na lista de cada mapa (<b>Imagem antiga</b> / <b>Imagem recente</b>) dá para trocar a imagem escolhida. A data vai sozinha para o quadro branco de cada mapa.</li>
</ol>
<h3>Textos escritos nos mapas</h3>
<p>Os textos que aparecem em cima de cada mapa (ex.: a data da imagem). Dá para corrigir aqui antes de gerar.</p>
{_dica("a mesma busca repetida na sessão é instantânea (fica guardada por 1 hora). Para mexer nas camadas, no SRC ou no enquadramento de um mapa, veja " + '<a href="#mapas">Personalizar cada mapa</a>' + ".")}
"""),
    ("mapas", "Personalizar cada mapa", f"""
<h2>Personalizar cada mapa</h2>
<p>Opcional, no fim da etapa 4 (grupo recolhido <b>Personalizar cada mapa</b>). Sem mexer aqui, o plugin escolhe as camadas
visíveis do projeto e enquadra o imóvel sozinho.</p>
<ol>
<li>Em <b>Mapa</b>, escolha qual mapa do modelo vai ajustar (principal, localização, esquerdo/direito na de Passivos).</li>
<li><b>Camadas</b> - marque as que aparecem neste mapa. A ordem de desenho segue o painel de camadas; imagens ficam sempre embaixo.</li>
<li><b>SRC</b> - <i>Automático (SIRGAS 2000 / UTM do fuso do imóvel)</i> ou outro.</li>
<li><b>Enquadramento</b> - ajustar à camada (com margem), extensão manual (desenhar no mapa ou usar a vista atual), município,
estado ou Brasil (mapa de localização), tema do projeto, ou igual ao outro mapa.</li>
</ol>
<p>O mapa de localização usa a camada de municípios do projeto (ou a malha de Goiás que vem com o plugin), com o município em
verde e os vizinhos em cinza. A camada do projeto não é alterada.</p>
"""),
    ("legenda", "Etapa 5 - Legenda", f"""
<h2>Etapa 5 - Legenda</h2>
<p>A legenda vem do grupo de camadas do modelo (<b>Uso do Solo</b> ou <b>Passivos</b>), na ordem padrão do escritório.
Camadas a mais entram entre <i>Reserva legal</i> e <i>APP total</i>.</p>
<ul>
<li><b>Camadas da legenda vêm do grupo</b> - escolha o grupo do painel de camadas; o botão ao lado relê os grupos.</li>
<li>Marque/desmarque, troque a camada, renomeie, suba/desça ou adicione itens livremente.</li>
<li>Passivos: escolha em <b>Legenda do:</b> qual mapa editar (esquerda = Uso do Solo, direita = Passivos). Cada mapa
mostra só as camadas da sua legenda (e a imagem).</li>
<li>A legenda se ajusta ao espaço: uma coluna quando cabe, duas quando o espaço é pouco, centralizada. Os nomes seguem a
tabela de nomes (<a href="#biblioteca">ver</a>).</li>
</ul>
"""),
    ("gerar", "Gerar a planta e os botões do rodapé", f"""
<h2>Gerar a planta</h2>
<p><b>Gerar planta</b> monta o layout com tudo no lugar: mapas, coordenadas, legenda, tabelas, barra de escala (presa
no canto do mapa, com fundo branco discreto), seta do norte, mapa de localização com o município destacado, logo e
assinatura do responsável técnico. O layout abre no editor e fica em Projeto &gt; Gerenciador de layouts; exporte o PDF
pelo próprio editor do QGIS.</p>
{_atencao("nada fica em cima do imóvel: legenda e tabelas diminuem e, se preciso, o mapa afasta para a próxima escala redonda.")}
<h3>Automático na planta</h3>
<ul>
<li>Textos variáveis são variáveis do projeto (<code>@na_imovel</code>, <code>@na_proprietario</code>, <code>@na_car</code>...): trocou em Projeto &gt; Propriedades &gt; Variáveis, o layout atualiza.</li>
<li>Parâmetros cartográficos (projeção, datum, meridiano central, fuso), escala e folha calculados sozinhos.</li>
</ul>
<h3>Botões do rodapé</h3>
<ul>
<li><b>Cancelar processo</b> - para a busca em andamento e volta para a etapa 1 (mantém o que já foi preenchido).</li>
<li><b>Limpar tudo</b> - apaga o que foi preenchido (documentos, dados, planilha, imagens, legenda): o plugin fica como recém-aberto.</li>
<li><b>Mais opções ▾ &gt; Salvar layout como modelo...</b> - grava o layout na biblioteca, sem as camadas e os dados do imóvel atual.</li>
<li><b>Mais opções ▾ &gt; Exportar pacote (QPT + prévia)...</b> - grava o modelo em arquivo (.qpt, prévia e .zip) para mandar a alguém.</li>
</ul>
"""),
    ("buscar", "Buscar imagem (sem gerar planta)", f"""
<h2>Buscar imagem</h2>
<p>Só procura uma imagem de satélite e põe no projeto, sem gerar planta.</p>
<ol>
<li><b>Área</b> - a área de uma <b>Camada</b> ou a <b>Área visível no mapa do QGIS</b>.</li>
<li><b>Data da imagem</b> - <b>Mais recente</b> ou <b>Escolher período</b> (de / até).</li>
<li><b>Buscar imagem</b> - aparecem as imagens encontradas, com os mesmos critérios de qualidade das plantas.</li>
<li><b>Adicionar ao projeto</b> - a imagem entra no grupo <i>NorteAgro - Imagens de satélite</i>.</li>
</ol>
"""),
    ("config", "Configurações: responsável técnico", f"""
<h2>Configurações: responsável técnico</h2>
<p><b>Nome</b>, <b>Título</b>, <b>Registro</b> (CREA) e <b>Empresa</b>, a imagem da <b>Assinatura</b> e a <b>Logo</b>. Entram
sozinhos em toda planta. A assinatura e a logo são opcionais: escolha as imagens aqui; a <b>Prévia</b> mostra como ficam.
Clique em <b>Salvar</b>.</p>
"""),
    ("biblioteca", "Configurações avançadas", f"""
<h2>Configurações avançadas</h2>
<p>No grupo recolhido <b>Biblioteca de modelos e nomes de camadas</b> (aba Configurações):</p>
<ul>
<li><b>Pasta da biblioteca</b> - onde ficam os modelos salvos com "Salvar layout como modelo" (pode ser uma pasta de rede ou do Drive, para o escritório todo).</li>
<li><b>Tabela de nomes (CSV)</b> - liga o nome do arquivo da camada ao nome que sai na legenda. <b>Abrir tabela de nomes</b> mostra a tabela;
<b>Copiar tabela para a biblioteca</b> cria uma cópia para editar (ex.: acrescentar uma camada nova). Colunas: <code>arquivo;nome_legenda;apelidos;papel;grupo</code>.</li>
<li><b>Python de suporte (PDF/OCR)</b> - só para PDF que o QGIS não abre e para ler documento digitalizado: rode
<code>support\\Preparar_PDF_Windows.cmd</code> ou <code>support\\Instalar_OCR_Windows.cmd</code> (pasta do plugin) e informe aqui o caminho mostrado no fim.</li>
</ul>
"""),
    ("videos", "Vídeos da ajuda: como salvar e apagar", f"""
<h2>Vídeos da ajuda</h2>
<p>Cada assunto desta ajuda tem um <b>lugar para vídeo</b>, na coluna da direita, ao lado do texto. Grave com o programa que
preferir e salve aqui. Na lista, <b>●</b> verde = já tem vídeo; <b>○</b> = falta. Marque <b>Mostrar só os que faltam vídeo</b>
para ver o que ainda falta gravar.</p>
<ol>
<li>Clique no assunto e em <b>Salvar vídeo no plugin...</b>; escolha o arquivo, confira o nome e escreva para que serve.</li>
<li><b>Salvar no plugin</b> copia o vídeo para a <b>pasta dos vídeos</b> deste plugin, numa pasta só daquele assunto.
Sem limite de tamanho ou duração; o original continua onde você gravou.</li>
</ol>
<p><b>▶ Assistir</b> toca o vídeo (se o formato não tocar dentro do QGIS, abre no player do Windows). <b>Trocar...</b> e
<b>Editar</b> mudam o vídeo do assunto; <b>Mostrar na pasta</b> abre o Explorador com o arquivo selecionado.</p>
<p><b>Apagar</b> tira o vídeo da ajuda e <b>apaga o arquivo da pasta dos vídeos</b> (pergunta antes e mostra o caminho).</p>
<p><b>+ Mais um vídeo</b> acrescenta vídeos fora dos lugares: num assunto (embaixo do principal) ou em <b>Vídeos extras</b>.
Os vídeos chegam aos colegas <b>pela internet</b>: quando quem cuida dos plugins publica vídeos, o QGIS de cada um
avisa e baixa sozinho, em segundo plano, só os que ainda não tem (e tira os que saíram); confere ao abrir e a cada 2 horas.
Eles ficam numa pasta do QGIS fora do plugin, então atualizar não apaga nenhum vídeo.</p>
{_atencao("salvar, trocar, editar e apagar vídeos pede a senha dos vídeos. Assistir não pede.")}
"""),
]

HTML_EXTRAS = """
<h2>Vídeos extras</h2>
<p>Vídeos que não são de um assunto só - por exemplo, uma planta completa do começo ao fim. Use <b>+ Mais um vídeo</b>
(na coluna da direita) e escolha <b>Vídeos extras</b> em "Aparece em".</p>
"""


def assuntos_numerados():
    return [(chave, f"{n}. {nome}") for n, (chave, nome, _h) in enumerate(TOPICOS, 1)]


class DialogoAjuda(QDialog):
    def __init__(self, parent=None, topico="inicio"):
        super().__init__(parent)
        from .videos_ajuda import EXTRAS, TITULO_EXTRAS, PainelVideos
        self._extras = EXTRAS
        self.setWindowTitle("Ajuda - Layout de plantas")
        self.resize(1300, 720)
        from .tamanho_tela import ajustar_a_tela
        ajustar_a_tela(self, "norteagro_layout_ia/ajuda_v2")
        v = QVBoxLayout(self)
        div = QSplitter(Qt.Orientation.Horizontal)
        esq = QWidget(); le = QVBoxLayout(esq); le.setContentsMargins(0, 0, 0, 0)
        self.so_faltam = QCheckBox("Mostrar só os que faltam vídeo")
        self.so_faltam.toggled.connect(lambda _v: self._filtrar())
        le.addWidget(self.so_faltam)
        self.lista = QListWidget()
        self.lista.setWordWrap(True)
        self.lista.setStyleSheet(f"QListWidget::item {{ padding: 6px; }} QListWidget::item:selected "
                                 f"{{ background: {VERDE}; color: white; }}")
        le.addWidget(self.lista, 1)
        legenda = QLabel("● tem vídeo   ○ falta vídeo"); legenda.setStyleSheet("color:#6B7280;"); le.addWidget(legenda)
        div.addWidget(esq)
        self.texto = QTextBrowser()
        self.texto.setOpenLinks(False)
        self.texto.anchorClicked.connect(self._link)
        self.texto.document().setDefaultStyleSheet(
            f"h2 {{ color: {VERDE}; }} body {{ font-size: 10pt; }} li {{ margin-bottom: 4px; }}")
        div.addWidget(self.texto)
        self.numerados = assuntos_numerados()
        self.videos = PainelVideos(self.numerados, self)
        self.videos.alterado.connect(self._marcar)
        div.addWidget(self.videos)
        div.setStretchFactor(0, 0); div.setStretchFactor(1, 1); div.setStretchFactor(2, 0)
        div.setSizes([300, 640, 360])
        v.addWidget(div, 1)
        for chave, nome in self.numerados + [(EXTRAS, TITULO_EXTRAS)]:
            it = QListWidgetItem(nome); it.setData(Qt.ItemDataRole.UserRole, chave); self.lista.addItem(it)
        self.lista.currentItemChanged.connect(self._mostrar)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._marcar()
        self.abrir(topico)

    def _html(self, chave):
        if chave == self._extras:
            return HTML_EXTRAS
        return next((h for c, _n, h in TOPICOS if c == chave), "")

    def _marcar(self):
        from .videos_ajuda import assuntos_com_video, bolinha, ler
        itens = ler()
        feitos = assuntos_com_video(itens)
        cheio, vazio = bolinha(VERDE), bolinha("")
        for i in range(self.lista.count()):
            it = self.lista.item(i); chave = it.data(Qt.ItemDataRole.UserRole)
            if chave == self._extras:
                tem = any(x.get("assunto") == self._extras for x in itens)
            else:
                tem = chave in feitos
            it.setIcon(cheio if tem else vazio)
        if self.so_faltam.isChecked():
            self._filtrar()

    def abrir(self, chave):
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == chave:
                self.lista.item(i).setHidden(False); self.lista.setCurrentRow(i); return
        self.lista.setCurrentRow(0)

    def _mostrar(self, item, _antigo=None):
        if not item:
            return
        chave = item.data(Qt.ItemDataRole.UserRole)
        self.texto.setHtml(self._html(chave))
        self.videos.mostrar(chave, item.text())

    def _link(self, url):
        alvo = url.fragment() or url.toString().lstrip("#")
        if alvo.startswith("http"):
            from qgis.PyQt.QtGui import QDesktopServices
            QDesktopServices.openUrl(url); return
        if alvo:
            self.so_faltam.setChecked(False); self.abrir(alvo)

    def _filtrar(self):
        from .videos_ajuda import assuntos_com_video
        feitos = assuntos_com_video() if self.so_faltam.isChecked() else set()
        primeiro = None
        for i in range(self.lista.count()):
            it = self.lista.item(i); chave = it.data(Qt.ItemDataRole.UserRole)
            esconder = self.so_faltam.isChecked() and (chave in feitos or chave == self._extras)
            it.setHidden(esconder)
            if not esconder and primeiro is None:
                primeiro = i
        if primeiro is not None and (self.lista.currentRow() < 0 or self.lista.currentItem().isHidden()):
            self.lista.setCurrentRow(primeiro)


def abrir_ajuda(parent=None, topico="inicio"):
    d = DialogoAjuda(parent, topico)
    d.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    d.show()
    return d
