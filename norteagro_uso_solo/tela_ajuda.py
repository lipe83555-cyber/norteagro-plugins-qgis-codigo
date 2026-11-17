# -*- coding: utf-8 -*-
"""v3.9.12: tutorial do plugin. Abre pelo "?" de qualquer janela (já no assunto da tela) ou pelo
botão Ajuda da tela inicial. Assuntos à esquerda, explicação no meio, busca e links entre assuntos.
v0.6.0: à direita, os vídeos de cada assunto (videos_ajuda.py) - um lugar por assunto + vídeos a mais."""
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
    QWidget,
)

CSS = """
<style>
h2 { color:#46741F; margin-bottom:4px; }
h3 { color:#262621; margin-top:14px; margin-bottom:2px; }
p, li { line-height:135%; }
.dica { background:#EEF4E6; border-left:4px solid #7DA63F; padding:6px; }
.cuidado { background:#FFF4E5; border-left:4px solid #C98A1A; padding:6px; }
code { background:#F0F0EB; }
td { padding:3px 8px; border-bottom:1px solid #DDD; }
</style>
"""


def _dica(t): return f'<table width="100%" cellpadding="6"><tr><td style="background:#EEF4E6; border-left:4px solid #7DA63F;"><b>Dica:</b> {t}</td></tr></table>'
def _cuidado(t): return f'<table width="100%" cellpadding="6"><tr><td style="background:#FFF4E5; border-left:4px solid #C98A1A;"><b>Atenção:</b> {t}</td></tr></table>'
def _ir(topico, texto): return f'<a href="#{topico}">{texto}</a>'


TOPICOS = [
("comecar", "Começando: o que o plugin faz", f"""
<h2>Começando</h2>
<p>O <b>Norte Agro - Uso do Solo</b> organiza o mapa de uso do solo do imóvel: cria as pastas e as camadas padronizadas
(com nome, estilo e KML certos), reconhece camadas que vieram de outros lugares, calcula as áreas sem contar nada duas vezes
e gera a planilha <b>Quadro de Áreas</b> no Excel, com as conferências de desenho.</p>
<p>Ele é aberto por <b>Complementos &gt; Norte Agro Projetos &gt; Criar camadas e calcular áreas</b> ou pelo ícone verde na barra de ferramentas do QGIS.</p>
<h3>Passo a passo de um projeto novo</h3>
<ol>
<li>Abra o plugin e escolha <b>Criar / gerenciar camadas</b>.</li>
<li>Na primeira vez, aparece {_ir("configurar_pasta","Configurar pasta do mapa")}: escolha o modelo de pastas, onde criar, o nome de cada pasta mãe (ex.: o nome da fazenda) e o SRC (22S ou 23S). Clique em <b>Criar estrutura</b> e salve o projeto (.qgz) quando ele pedir.</li>
<li>Na tela {_ir("gerenciar","Criar / gerenciar camadas")}, marque as camadas que vai usar e clique em <b>Criar selecionadas</b>. Elas entram no QGIS já com nome, grupo e estilo.</li>
<li>Desenhe normalmente no QGIS (ligue a edição, desenhe, salve). A cada salvamento o plugin grava a cópia em {_ir("kml","KML")} sozinho.</li>
<li>Se precisar de uma camada que não existe no catálogo, use {_ir("nova_camada","+ Nova camada")} e escolha em qual quadro da planilha ela entra.</li>
<li>Quando terminar, clique em <b>Calcular áreas</b>, confira a lista e clique em <b>Calcular e gerar planilha</b> ({_ir("calcular","como calcular")}).</li>
<li>Abra a planilha e leia a aba <b>Observações</b> antes de entregar ({_ir("planilha","entendendo a planilha")}).</li>
</ol>
<h3>Os quatro caminhos da tela inicial</h3>
<table>
<tr><td><b>Criar / gerenciar camadas</b></td><td>O caminho normal: pasta do mapa + camadas padrão + cálculo.</td></tr>
<tr><td><b>Criar camadas em uma pasta</b></td><td>Cria camadas do catálogo em qualquer pasta, sem mudar a pasta do projeto ({_ir("avulsa","ver")}).</td></tr>
<tr><td><b>Só calcular áreas</b></td><td>Calcula as camadas que já estão abertas (inclusive de cliente) e gera a planilha, sem criar nada.</td></tr>
<tr><td><b>Camadas da SEMAD (SIGA)</b></td><td>Traz do SIGA os murundus, as APP de relevo e as Unidades de Conservação do imóvel ({_ir("semad","ver")}).</td></tr>
</table>
{_dica("em qualquer janela do plugin, clique no <b>?</b> (no canto do título ou do cabeçalho) para abrir esta ajuda já no assunto daquela tela. Ao lado de cada assunto ficam os <b>vídeos</b> dele (" + _ir("videos","como salvar") + ").")}
"""),

("tela_inicial", "Tela inicial do plugin", f"""
<h2>Tela inicial do plugin</h2>
<p>É a primeira janela ao clicar em <b>Criar camadas e calcular áreas</b>. Ela não cria nem grava nada: só escolhe o caminho.</p>
<ul>
<li><b>Criar / gerenciar camadas</b> - abre {_ir("gerenciar","Criar / gerenciar camadas")} (se o projeto ainda não tem pasta do mapa, antes abre {_ir("configurar_pasta","Configurar pasta do mapa")}).</li>
<li><b>Criar camadas em uma pasta</b> - abre {_ir("avulsa","Criar camadas em uma pasta")}.</li>
<li><b>Só calcular áreas</b> - abre {_ir("calcular","Calcular áreas")} direto.</li>
<li><b>Camadas da SEMAD (SIGA)</b> - abre {_ir("semad","Camadas da SEMAD")}.</li>
</ul>
<h3>Rodapé</h3>
<ul>
<li><b>Pasta atual</b> - mostra a pasta do mapa deste projeto (ou "não configurada").</li>
<li><b>+ Referências</b> - lista de nomes de camadas que são só consulta ({_ir("referencias","ver")}).</li>
<li><b>Modelos</b> - modelos do escritório: pastas, temas de cores e tabela ({_ir("modelos_pastas","ver")}).</li>
<li><b>? Ajuda</b> - este tutorial, com os vídeos de cada assunto.</li>
<li><b>Fechar</b> - fecha sem criar nada.</li>
</ul>
"""),

("configurar_pasta", "Configurar a pasta do mapa", f"""
<h2>Configurar pasta do mapa</h2>
<p>Cria as pastas do projeto a partir de um modelo e diz ao plugin onde ficam as camadas. O plugin lembra isso dentro do projeto (.qgz).</p>
<ol>
<li><b>1. Modelo de pastas</b> - escolha o modelo ({_ir("modelos_pastas","como criar um modelo")}). A linha abaixo resume as pastas e as camadas. <b>Modelos...</b> abre a tela para criar ou editar modelos.</li>
<li><b>2. Onde criar</b> - em <b>Criar dentro de</b>, clique em <b>Escolher...</b> e selecione a pasta onde tudo vai ser criado (por exemplo, a pasta dos clientes).</li>
<li><b>3. Nomes das pastas mãe</b> - aparece um campo para cada pasta mãe do modelo, já com o nome que ela tem no modelo. Troque pelo nome deste projeto (ex.: <i>Fazenda Norte</i>). A marcada com <i>(camadas)</i> é a que guarda as camadas do QGIS; <b>Camadas do QGIS em</b> mostra o caminho completo.</li>
<li><b>4. SRC</b> - EPSG:31982 (UTM 22S) ou EPSG:31983 (UTM 23S). É o sistema das camadas criadas.</li>
<li>Clique em <b>Criar estrutura</b>. Se o projeto ainda não foi salvo, o plugin oferece salvar o .qgz (na pasta <i>projetos</i>, se o modelo tiver essa pasta).</li>
</ol>
{_dica("se a pasta já existe, o plugin pergunta se quer usar a existente. Nada é apagado nem sobrescrito.")}
<h3>Estrutura criada</h3>
<p>Com o modelo padrão: a pasta mãe (<i>MAPA USO DO SOLO</i> ou o nome que você der) com <code>shapefiles</code>, <code>kml</code>, <code>projetos</code>, <code>layout</code> e <code>plantas pdf</code>. Com um modelo seu, a árvore que você montou ({_ir("modelos_pastas","modelos de pastas")}).
Cada camada fica numa subpasta com o nome dela dentro de <code>shapefiles</code> (ex.: <code>shapefiles\\Área de Reserva Legal\\RESERVA_LEGAL.shp</code>) e a cópia KML no mesmo nome dentro de <code>kml</code>.</p>
"""),

("gerenciar", "Criar / gerenciar camadas", f"""
<h2>Criar / gerenciar camadas</h2>
<p>Tela principal para montar o mapa. No topo aparecem a pasta do mapa e o SRC do projeto.</p>
<h3>Barra de cima</h3>
<table>
<tr><td><b>Pasta: Trocar</b></td><td>Escolhe outra pasta do mapa para este projeto ({_ir("pasta_renomear","ver")}).</td></tr>
<tr><td><b>Pasta: Renomear</b></td><td>Renomeia a pasta do mapa no disco e reaponta as camadas ({_ir("pasta_renomear","ver")}).</td></tr>
<tr><td><b>Grupos: Criar</b></td><td>Cria um grupo novo neste projeto (só no QGIS, nenhuma pasta é criada).</td></tr>
<tr><td><b>Grupos: Apagar</b></td><td>Apaga um grupo criado no projeto e as camadas dele (os arquivos vão para <code>_apagados</code>). Grupos padrão não podem ser apagados.</td></tr>
<tr><td><b>Catálogo: Adicionar / Remover / Restaurar</b></td><td>Gerencia o catálogo do escritório ({_ir("catalogo","ver")}).</td></tr>
<tr><td><b>Ferramentas</b></td><td>Ajustar nomes no QGIS, Voltar nomes de arquivo, Exportar KML ({_ir("kml","ver")}), + Camadas de referência ({_ir("referencias","ver")}), Nomes não reconhecidos ({_ir("apelidos","ver")}), Modelos ({_ir("modelos_pastas","ver")}), Criar camadas em uma pasta ({_ir("avulsa","ver")}) e Camadas da SEMAD ({_ir("semad","ver")}).</td></tr>
</table>
<h3>Lista de camadas</h3>
<p>As camadas do catálogo aparecem por grupo, com o tipo (polígono, linha, ponto) e a <b>Situação</b>:</p>
<ul>
<li><b>Nova</b> - ainda não existe na pasta do mapa.</li>
<li><b>Criada</b> - existe e está carregada no projeto.</li>
<li><b>Criada - não carregada</b> - o arquivo existe, mas não está no projeto (criar de novo só carrega, não apaga nada).</li>
<li><b>Nova - consulta o SIGA</b> - camadas do grupo SEMAD - SIGA e a Murundus do Uso do Solo: ao criar, o plugin busca os dados na hora ({_ir("semad","ver")}).</li>
</ul>
<p>Use <b>Buscar camada...</b> para filtrar e <b>Selecionar todos</b> para marcar tudo. Clicar numa camada marca só ela; clicar no grupo marca o grupo.</p>
<p><b>Botão direito</b> numa camada: <b>Mudar cor padrão...</b> ({_ir("cor_padrao","ver")}), <b>Substituir...</b> ({_ir("substituir","ver")}) e, nas camadas personalizadas, <b>Lugar no Quadro de Áreas...</b> ({_ir("nova_camada","ver")}). <b>Dois cliques</b> numa camada também mudam a cor padrão.</p>
<h3>Rodapé</h3>
<ul>
<li><b>+ Nova camada</b> - cria uma camada com nome novo ({_ir("nova_camada","ver")}).</li>
<li><b>SEMAD</b> - abre a tela das camadas da SEMAD ({_ir("semad","ver")}).</li>
<li><b>Calcular áreas</b> - abre o cálculo ({_ir("calcular","ver")}).</li>
<li><b>Criar selecionadas</b> - cria (ou carrega, se já existir) as camadas marcadas. Nunca sobrescreve um arquivo existente.</li>
</ul>
<h3>Ajustar / Voltar nomes</h3>
<p><b>Ajustar nomes no QGIS</b> troca o nome que aparece no painel de camadas (ex.: 00_RESERVA_LEGAL vira Área de Reserva Legal). <b>Voltar nomes de arquivo</b> desfaz. Nenhum dos dois mexe em arquivos.</p>
"""),

("kml", "Desenhar, salvar e a cópia KML", f"""
<h2>Desenhar, salvar e a cópia KML</h2>
<p>Depois de criar as camadas, desenhe normalmente no QGIS: selecione a camada, ligue a edição (lápis), desenhe e <b>salve</b>. O plugin não muda o jeito de desenhar.</p>
<p>Com a pasta <b>kml</b> ligada no modelo (padrão), cada vez que uma camada é salva, padronizada ou substituída o plugin grava uma cópia em KML (EPSG:4326, com a simbologia) em <code>kml\\&lt;pasta da camada&gt;\\ARQUIVO.kml</code>.</p>
<ul>
<li><b>Ferramentas &gt; Exportar KML</b> - grava na hora o KML das camadas selecionadas no painel (ou de todas do plugin, se nenhuma estiver selecionada). Funciona mesmo com a cópia automática desligada.</li>
<li>KML antigo solto na pasta é guardado em <code>kml\\_antigos\\data</code>, nunca apagado.</li>
<li>Camadas criadas em "Criar camadas em uma pasta" têm a pasta KML delas.</li>
</ul>
"""),

("nova_camada", "Nova camada e lugar no Quadro de Áreas", f"""
<h2>Nova camada (nome novo)</h2>
<p>Para camadas que não existem no catálogo (ex.: Área de Pastagem, Área Embargada, Pivô Central).</p>
<ol>
<li><b>Nome</b> - o nome que vai aparecer no QGIS e na planilha. O <b>Arquivo gerado</b> mostra o nome técnico (sem acento, com _).</li>
<li><b>Tipo</b> - Polígono, Linha ou Ponto.</li>
<li><b>Grupo</b> - grupo do painel de camadas (ou <b>Novo grupo...</b>).</li>
<li><b>No Quadro de Áreas</b> - onde ela entra na planilha (veja a tabela abaixo). A frase embaixo explica cada opção.</li>
<li><b>Estilo</b> - <b>Editar estilo</b> abre o editor de símbolo do QGIS; <b>Copiar de outra camada</b> usa o estilo de uma camada aberta.</li>
<li><b>Criar camada</b>. No fim o plugin pergunta se quer <b>catalogar</b>: Sim = vale para todo o escritório; Não = só neste projeto.</li>
</ol>
<h3>Opções de "No Quadro de Áreas"</h3>
<table>
<tr><td><b>Áreas Totais do Imóvel</b></td><td>Vira uma classe de uso do solo e entra na soma que fecha com a Área Total do Imóvel. Se sobrepuser uma classe padrão, a área fica com a classe padrão e a sobreposição é avisada.</td></tr>
<tr><td><b>Passivos ambientais / Área Hidrográfica / Área Total de Compensação</b></td><td>Vira uma linha a mais nesse quadro. A parte que já está em outra linha do mesmo quadro é descontada (sem contar duas vezes).</td></tr>
<tr><td><b>Outras camadas</b></td><td>Quadro próprio no fim da planilha, sem total.</td></tr>
<tr><td><b>Não entra no Quadro de Áreas</b></td><td>Só aparece na aba Todas as camadas.</td></tr>
</table>
<p>Linhas e pontos não têm área: ficam sempre fora dos quadros (aparecem em Todas as camadas).</p>
{_dica("para mudar depois, clique com o botão direito na camada em Criar / gerenciar camadas e escolha <b>Lugar no Quadro de Áreas</b>.")}
"""),

("catalogo", "Catálogo do escritório", f"""
<h2>Catálogo do escritório</h2>
<p>É a lista de camadas padrão do plugin. Fica dentro do próprio plugin (pasta <code>dados</code>), com uma cópia de segurança no perfil do QGIS: ao atualizar o plugin, nada se perde.</p>
<ul>
<li><b>Catálogo: Adicionar</b> - publica uma camada aberta no QGIS como camada do catálogo: escolha a camada, o nome, o grupo e o lugar no Quadro de Áreas. O estilo é copiado da camada.</li>
<li><b>Catálogo: Remover</b> - tira a camada da lista de todos (nenhum arquivo é apagado; se ela existe neste projeto, continua aqui como camada do projeto).</li>
<li><b>Catálogo: Restaurar</b> - traz de volta camadas removidas.</li>
<li><b>Cor padrão</b> de cada camada - {_ir("cor_padrao","ver")}.</li>
</ul>
{_cuidado("o catálogo é compartilhado. Se duas pessoas gravarem ao mesmo tempo, o plugin espera alguns segundos e avisa; nada se perde.")}
"""),

("cor_padrao", "Cor padrão das camadas", f"""
<h2>Cor padrão das camadas</h2>
<p>Cada camada do catálogo nasce com uma cor (estilo). Dá para trocar essa cor para <b>todo o escritório</b>.</p>
<ol>
<li>Em {_ir("gerenciar","Criar / gerenciar camadas")}, dê <b>dois cliques</b> na camada (ou botão direito &gt; <b>Mudar cor padrão...</b>).</li>
<li>Abre o editor de símbolo do QGIS: escolha cor, contorno, hachura, transparência e clique em OK.</li>
<li>O plugin grava a cor nova no catálogo e pergunta se quer aplicar também na camada deste projeto (a cor vai junto para o .qml da camada).</li>
</ol>
<p>As próximas camadas criadas já vêm com a cor nova. Para desfazer: botão direito &gt; <b>Voltar à cor original do plugin</b> (aparece só nas camadas com cor trocada).</p>
{_dica("para guardar as cores de várias camadas de uma vez e reaplicar em outros projetos, use os " + _ir("temas","temas de cores") + ".")}
"""),

("semad", "Camadas da SEMAD (SIGA)", f"""
<h2>Camadas da SEMAD (SIGA)</h2>
<p>O plugin consulta o <b>SIGA</b> da SEMAD-GO (siga.meioambiente.go.gov.br) pelo limite da <b>Área Total do Imóvel</b>.</p>
<ul>
<li><b>Murundus → camada Murundus do grupo Uso do Solo</b>: os campos de murundus da SEMAD (versão convalidada) que estão dentro do imóvel vão direto para a camada <b>Murundus</b> do Uso do Solo, a mesma do catálogo do escritório. Ela é <b>criada sozinha</b> quando o imóvel tem murundus (ao abrir Criar / gerenciar camadas, na tela da SEMAD ou ao criar o grupo Uso do Solo); sem murundus no imóvel, ela não é criada. Ela <b>entra no Quadro de Áreas</b> (em Outras camadas). Se você desenhou ou ajustou murundus à mão nessa camada, o plugin <b>não substitui</b> o seu desenho; se ela só tem dados do SIGA, a consulta nova troca o conteúdo (com cópia de segurança em <code>_backup</code>).</li>
<li><b>Só a parte dentro do imóvel</b> (o resto é descartado), no grupo <b>SEMAD - SIGA</b>: APP de Declividade, APP de Borda de Chapada, APP de Topo de Morro. O mapeamento original de murundus de 2020 (antes da convalidação) continua no catálogo desse grupo, mas só é criado se você marcar.</li>
<li><b>Inteiras</b>: Unidades de Conservação (estaduais, federais, municipais e RPPN) - as que <b>sobrepõem</b> o imóvel e as que estão <b>perto</b> (até 10 km; muda na tela da SEMAD). Cada UC traz <code>nome</code>, <code>categoria</code>, <code>grupo</code>, <code>esfera</code>, <code>criacao</code>, <code>descricao</code>, <code>sobrepoe</code> (Sim/Não), <code>dentro_ha</code> (quanto do imóvel ela cobre) e <code>dist_km</code>. O nome aparece como rótulo no mapa e a descrição nas Dicas de mapa.</li>
</ul>
<h3>Duas formas de gerar</h3>
<ol>
<li><b>Uma a uma, no catálogo</b>: em Criar / gerenciar camadas, marque a camada (no grupo SEMAD - SIGA, ou a Murundus no Uso do Solo) e clique em Criar. O plugin consulta o SIGA naquela hora e grava só o que há no imóvel. Criar de novo atualiza. Criando o grupo Uso do Solo inteiro com o imóvel ainda sem desenho, a Murundus fica para depois e é criada sozinha quando o limite estiver desenhado.</li>
<li><b>Todas de uma vez</b>: tela <b>Camadas da SEMAD</b> (tela inicial ou botão SEMAD de Criar / gerenciar camadas). Ela também lista as UC encontradas com nome e descrição.</li>
</ol>
<p><b>Precisa do imóvel</b>: se a Área Total do Imóvel ainda não existe, o plugin pede para gerá-la primeiro; se ela está sem desenho, pede para desenhar o limite. Isso vale também para as UC (é o imóvel que diz quais sobrepõem), mas a UC <b>não é recortada</b>.</p>
<p>Camada que não tem nada no imóvel <b>não é criada</b> (e a de uma consulta anterior sai do grupo SEMAD - SIGA; a Murundus do Uso do Solo nunca é apagada pelo plugin). A consulta é feita <b>toda vez</b>, e também sozinha ao abrir Criar / gerenciar camadas (dá para desligar na tela da SEMAD).</p>
<p>As do grupo SEMAD - SIGA são <b>referência</b>: não entram no cálculo de áreas nem na correção. A Murundus do Uso do Solo entra no cálculo como as outras camadas do Uso do Solo. Projetos antigos que tinham a camada à parte "Campos de Murundus (SEMAD)" perdem essa camada na primeira consulta: os dados passam para a Murundus.</p>
{_cuidado("se o SIGA não responder (sem internet ou serviço fora do ar), a linha fica laranja e a camada da consulta anterior continua no mapa. Clique em Verificar de novo.")}
{_dica("Uso Restrito (declividade 25° a 45°) não existe no SIGA; ele está na base de relevo do CAR (Serviço Florestal), que é um arquivo único de 1,2 GB para todo o estado.")}
"""),

("avulsa", "Criar camadas em uma pasta", f"""
<h2>Criar camadas em uma pasta</h2>
<p>Cria camadas do catálogo (ou personalizadas) em qualquer pasta, <b>sem mudar a pasta do mapa do projeto</b>. Útil para entregar camadas soltas ou montar algo fora da estrutura.</p>
<ol>
<li>Em <b>Camadas</b>, escolha cada camada digitando o nome, o ARQUIVO ou um apelido. <b>+ Adicionar camada</b> cria outra linha; <b>Remover linhas vazias</b> limpa as não usadas. A opção <b>+ Camada personalizada...</b> cria uma com nome novo.</li>
<li>Em <b>Destino</b>, escolha a <b>Pasta de destino</b> e o <b>SRC</b>. A <b>Pasta do KML</b> é sugerida sozinha (<b>Alterar...</b> para mudar).</li>
<li>Clique em <b>Criar</b>. Camadas que já existem na pasta são só carregadas, nunca sobrescritas.</li>
</ol>
<p>Selos de cada linha: <b>OK</b>, <b>Vazia</b>, <b>Repetida</b> (bloqueia) e <b>Já existe nesta pasta</b>.</p>
{_dica("Enter vai para a próxima linha; Ctrl+Enter cria.")}
"""),

("calcular", "Calcular áreas", f"""
<h2>Calcular áreas</h2>
<p>Lista todas as camadas abertas no projeto, mostra como cada uma foi reconhecida e gera a planilha. <b>O cálculo nunca altera as camadas nem os arquivos</b>: limpeza, correções e recortes acontecem só em memória.</p>
<h3>Lista de camadas</h3>
<table>
<tr><td><b>✓</b></td><td>Marque as camadas que entram no cálculo.</td></tr>
<tr><td><b>Reconhecer como</b></td><td>Como o plugin entendeu a camada. Se estiver errado, escolha a classe certa na lista (vale só para este projeto).</td></tr>
<tr><td><b>Situação</b></td><td>Reconhecida, <b>Semelhança</b> (reconhecida por nome parecido - confira), <b>Referência</b> (só consulta, fora do quadro), <b>Não reconhecida</b>, <b>Arquivo não encontrado</b> (o arquivo sumiu do computador).</td></tr>
<tr><td><b>Ações</b></td><td><b>Criar camada padrão com este conteúdo</b> ({_ir("padronizar","padronizar")}), <b>Ensinar este nome</b> ({_ir("apelidos","ver")}) ou <b>Remover camada</b>.</td></tr>
</table>
<p>Botões da lista: <b>Nomes não reconhecidos...</b> (escreva o nome que o plugin não reconhece e escolha em qual linha da tabela ele entra - {_ir("apelidos","ver")}),
<b>Padronizar todas as reconhecidas</b> e <b>+ Referência</b> ({_ir("referencias","ver")}).</p>
<h3>Conferir e corrigir antes de calcular</h3>
<p>A opção <b>Conferir e corrigir as camadas antes de calcular</b> (marcada de fábrica) faz o plugin arrumar o desenho antes do cálculo: sobreposição, parte fora do imóvel, frestas e geometria ({_ir("correcao","ver")}). Desmarcada, ele calcula sem tocar nas camadas e só aponta os problemas ({_ir("problemas","ver")}).</p>
<h3>Método e SRC</h3>
<ul>
<li><b>Elipsoidal (GRS80, vértices a cada 10 m)</b> - recomendado; é o método usado nas entregas.</li>
<li><b>Plano UTM</b> - área plana na projeção.</li>
<li>O SRC do cálculo vem do projeto; escolha 22S ou 23S se ele pedir.</li>
</ul>
<h3>Saída</h3>
<ul>
<li><b>Planilha</b> - onde salvar o .xlsx (<b>Escolher...</b> para mudar).</li>
<li><b>Modelo da tabela</b> - visual da planilha ({_ir("modelos_tabela","ver")}). O último usado fica lembrado. <b>Modelos...</b> abre a tela de modelos.</li>
</ul>
<p>Clique em <b>Calcular e gerar planilha</b>. Depois, <b>Salvar novamente</b> grava outra cópia sem recalcular, e <b>Ver no mapa</b> mostra onde ficaram os problemas que o plugin não corrige sozinho (ex.: área sem classificação). Para ler o resultado, veja {_ir("planilha","Entendendo a planilha")}.</p>
{_cuidado("se aparecer <b>Arquivo não encontrado</b>, a camada está quebrada no projeto: ela fica desmarcada e não entra no cálculo.")}
"""),

("correcao", "Conferir e corrigir camadas", f"""
<h2>Conferir e corrigir camadas</h2>
<p>Ao clicar em <b>Calcular</b>, o plugin confere o desenho e abre a tela <b>Conferir e corrigir camadas</b> quando acha problema. Corrigindo, as camadas ficam certas e cada linha do Quadro de Áreas bate com o que está desenhado.</p>
<h3>O que ele corrige sozinho</h3>
<ul>
<li><b>Fora do imóvel</b>: toda camada é recortada no limite do imóvel. Só a <b>hidrografia</b> (rio, nascente, barramento, cacimba, tanque, lagoa, vereda) pode passar do limite; no quadro conta só a parte de dentro. Feição inteira fora é apagada.</li>
<li><b>Faixa fina de sobreposição</b> (menos de 1 m de largura) entre camadas que dividem o mesmo todo: é erro de traçado; sai da camada de menor prioridade.</li>
<li><b>Fora da classe-mãe</b>: APP Preservada/Consolidada/Suprimida fora da APP Total, APP Suprimida fora da Área Suprimida do período, Supressão Passível fora da Área Suprimida.</li>
<li><b>Frestas</b> entre classes: toda faixa sem classe onde não cabe um círculo de 2 m (de qualquer comprimento), ou menor que 1 m², é somada à classe vizinha de maior divisa. Dentro da Área Suprimida a fresta vai pela definição: dentro da RL vira RL Suprimida; fora da RL e da APP vira Supressão em Área Passível.</li>
<li><b>APP Suprimida fora da Área Suprimida</b>: a APP Suprimida é Área Suprimida do mesmo período; o pedaço que faltava é somado à Área Suprimida (a APP não é alterada).</li>
<li><b>Passível dentro da RL ou da APP Total</b> (regra P3) e <b>RL Suprimida fora da Reserva Legal</b> (regra P2): saem da camada errada.</li>
<li><b>Camadas personalizadas</b> do quadro do imóvel, de Passivos, Hidrográfica e Compensação entram na correção com as mesmas regras do cálculo.</li>
<li><b>Geometria</b>: registros sem geometria, geometria inválida, lascas soltas, feições repetidas e feições da mesma camada uma por cima da outra.</li>
<li><b>Quadros que somam camadas</b> (Área Hidrográfica, Compensação): a mesma área em duas camadas contaria duas vezes.</li>
</ul>
<h3>Decisões técnicas</h3>
<p>O que depende de avaliação técnica o plugin <b>pergunta</b>, não decide sozinho:</p>
<ul>
<li><b>Sobreposição larga</b> (1 m ou mais) é conflito de classificação: a mesma terra desenhada como duas coisas. Você escolhe a camada que vai perder o pedaço. Água (rio, lagoa, barragem...) não é perguntada: ela sempre fica na linha Hidrografia.</li>
<li><b>Recorte grande no limite do imóvel</b> (mais de 1.000 m², ou feição inteira fora): recortar no limite ou não mexer, porque às vezes quem está errado é o limite do imóvel.</li>
<li><b>Subclasse com pedaço grande fora da classe-mãe</b> (ex.: Supressão em Área Passível fora da Área Suprimida): recortar ou não mexer (falta desenhar a classe-mãe ali).</li>
<li><b>Camadas repetidas</b> (a mesma classe em dois arquivos, ex.: SHP e KML do DAI): qual vale. A outra fica fora da correção e do cálculo.</li>
<li><b>Área sem classificação</b>: somar à classe vizinha ou deixar para desenhar depois.</li>
</ul>
<p><b>Camadas que a correção não altera:</b> as de APP (APP Total, Preservada, Consolidada, Suprimida, Suprimida antes e depois de 2019) e as camadas de total da supressão (Área Suprimida e Supressão em Área Passível). Cada uma é calculada sozinha, do jeito que foi desenhada; no quadro, a linha APP Suprimida é a camada APP Suprimida e o Total é a camada APP Total.</p>
<p><b>Barragem ou rio feito em área suprimida</b> continua como Área Suprimida (é passivo); a água só ganha da Consolidada e da Vegetação.</p>
<p><b>RL Suprimida dentro da APP Suprimida</b> é permitido (a Reserva Legal pode conter APP): as duas camadas ficam; no quadro da Área antropizada a área conta uma vez só, na APP, e a conferência não acusa diferença.</p>
<p><b>Uma régua só (v0.5.0):</b> a correção e o cálculo usam exatamente as mesmas regras e a mesma conta (exata, sem arredondar o desenho). Depois de corrigir, o Quadro de Áreas bate com o desenho e uma nova correção não acha mais nada.</p>
<p>A sugestão segue as regras do cálculo. <b>Ver no mapa</b> mostra o lugar. Faixas finas, frestas e recortes pequenos são erro de traçado e o plugin corrige sozinho.</p>
<h3>Segurança</h3>
<p>Antes de alterar, cada camada ganha uma cópia em <code>_backup</code> ao lado do arquivo. Linhas em laranja merecem um olhar (recorte grande, feição apagada). <b>Calcular sem corrigir</b> faz o cálculo como antes, sem tocar nas camadas.</p>
{_dica("ideias trazidas da ferramenta de sobreposição do app Bússola SIGCAR.")}
"""),

("problemas", "Sobreposições e problemas de desenho", f"""
<h2>Sobreposições e problemas de desenho</h2>
<p>Com <b>Conferir e corrigir as camadas antes de calcular</b> marcado (padrão), o plugin corrige o desenho antes do cálculo ({_ir("correcao","ver")}). Sem essa opção ele calcula certo mesmo com problemas, ajustando só em memória, e aponta onde corrigir.</p>
<h3>Situações</h3>
<table>
<tr><td><b>OK</b></td><td>Sem problema.</td></tr>
<tr><td><b>AJUSTADO</b></td><td>O quadro foi ajustado (sobreposição, fresta ou parte fora) para não contar nada duas vezes. Corrija o desenho quando puder.</td></tr>
<tr><td><b>ALERTA</b></td><td>Erro de desenho que muda valores: corrigir antes de entregar.</td></tr>
<tr><td><b>CONFERIR</b></td><td>Pode estar certo, mas precisa de olho técnico.</td></tr>
<tr><td><b>VERIFICAR</b></td><td>Situação permitida que pede confirmação (ex.: Reserva Legal sobre área consolidada).</td></tr>
<tr><td><b>SEM DADOS</b></td><td>Falta uma camada para fazer a verificação.</td></tr>
</table>
<h3>Ajustes no quadro (T1 a T4)</h3>
<ul>
<li><b>T1 sobreposição</b> - a área fica com a classe de maior prioridade (ex.: suprimida antes de consolidada antes de vegetação).</li>
<li><b>T2 fora do todo</b> - parte de uma subclasse fora da classe-mãe não entra.</li>
<li><b>T3 lasca/fresta</b> - frestas muito finas são somadas à classe vizinha.</li>
<li><b>T4 sem classificação</b> - lacuna real vira a linha "Área sem classificação".</li>
</ul>
<h3>Regras de conferência</h3>
<ul>
<li><b>R1 a R9</b> - somas que devem fechar (ex.: Imóvel = Vegetação + Consolidada + Suprimidas; APP Total = subclasses de APP).</li>
<li><b>P1 a P6</b> - posição (ex.: subclasses de APP dentro da APP Total; Reserva Legal Suprimida dentro da RL).</li>
<li><b>G1 a G4</b> - geometria (nulos, fora do imóvel, sobreposição na hidrografia, camada sem SRC ou SRC trocado).</li>
<li><b>A6 / A7</b> - camadas duplicadas e arquivo não encontrado.</li>
</ul>
<h3>Ver no mapa</h3>
<p>O plugin não cria camada de erros: com a correção ligada ele já arruma o desenho sozinho. O que sobrar (o que ele não tem como adivinhar, ex.: área sem classificação) aparece na lista depois do cálculo; <b>Ver no mapa</b> aproxima e faz esses pontos piscarem no mapa. As coordenadas E/N ficam na aba Observações da planilha.</p>
"""),

("planilha", "Entendendo a planilha", f"""
<h2>Entendendo a planilha</h2>
<h3>Abas</h3>
<table>
<tr><td><b>Quadro de Áreas</b></td><td>Só os resultados, em quadros lado a lado (Imóvel, Passivos, Remanescentes, Antropizada antes/após 2019, APP, Hidrografia, Compensação e Outras camadas).</td></tr>
<tr><td><b>Observações</b></td><td>Todos os problemas encontrados, por quadro: situação, tamanho, onde (coordenadas E/N) e <b>como resolver</b>.</td></tr>
<tr><td><b>Todas as camadas</b></td><td>Cada camada calculada: área bruta, fora do imóvel, área considerada, ajuste topológico, área no quadro, comprimento, registros sem geometria e como foi reconhecida.</td></tr>
<tr><td><b>Conferências</b></td><td>Todas as verificações feitas, em seções, com filtro.</td></tr>
</table>
<h3>As áreas</h3>
<ul>
<li><b>Área bruta</b> - o que está desenhado.</li>
<li><b>Fora do imóvel</b> - parte desenhada fora da Área Total do Imóvel (não entra).</li>
<li><b>Área considerada</b> - desenho limpo e recortado no imóvel.</li>
<li><b>Área no quadro</b> - considerada depois de resolver sobreposições e frestas (o valor que vai para o quadro).</li>
</ul>
<h3>Linhas especiais</h3>
<ul>
<li><b>Área sem classificação</b> - parte do imóvel (ou do quadro) sem nenhuma classe desenhada.</li>
<li><b>Diferença</b> - só aparece se o total não bater com a camada de referência (ex.: Área Total do Imóvel).</li>
</ul>
{_dica("os totais são fórmulas do Excel e os valores fecham exatamente com 4 casas. A aparência pode ser mudada com " + _ir('modelos_tabela','Modelos de tabela') + ".")}
"""),

("reconhecimento", "Como o plugin reconhece as camadas", f"""
<h2>Como o plugin reconhece as camadas</h2>
<p>Camadas criadas pelo plugin são reconhecidas sempre. Camadas de cliente ou antigas são reconhecidas pelo nome, nesta ordem:</p>
<ol>
<li>lista de {_ir("referencias","referências")} do escritório (vira Referência);</li>
<li>marca do próprio plugin na camada;</li>
<li>escolha manual feita em "Reconhecer como" neste projeto;</li>
<li>apelidos do escritório;</li>
<li>nome do arquivo, da pasta e da camada (ignora acentos, maiúsculas, "00_", "cópia", erros de digitação comuns, sinônimos como antropizada/suprimida, após/depois);</li>
<li>semelhança (marcada como <b>Semelhança</b> - confira).</li>
</ol>
<p>Exemplos: <code>reserva_legall</code> → Área de Reserva Legal; <code>REMANESCENTE DE VEGETAÇÃO NATIVA</code> → Área de Vegetação Nativa; <code>supresso_em_rea_passvel_aps_2019</code> → Supressão em Área Passível após 2019.</p>
<p>Se um nome sempre vem diferente, ensine o plugin em {_ir("apelidos","Nomes não reconhecidos")}.</p>
<p>Os nomes, referências e cores ficam guardados dentro do próprio plugin (pasta <code>dados</code>). Não depende do Google Drive.</p>
{_dica("camadas de compensação nunca são confundidas com supressão, e nomes ambíguos (ex.: 'área consolidada em APP') não são adivinhados.")}
"""),

("apelidos", "Nomes não reconhecidos (ensinar um nome)", f"""
<h2>Nomes não reconhecidos</h2>
<p>Quando uma camada sempre vem com um nome que o plugin não entende (ex.: "MATA NATIVA CLIENTE X"), ensine uma vez e ele passa a reconhecer.</p>
<h3>Onde abrir</h3>
<ul>
<li>Calcular áreas &gt; <b>Nomes não reconhecidos...</b>;</li>
<li>Calcular áreas &gt; botão <b>Ações</b> da camada &gt; <b>Ensinar este nome (escolher a linha da tabela)...</b> (já vem com o nome preenchido);</li>
<li>Criar / gerenciar camadas &gt; <b>Ferramentas &gt; Nomes não reconhecidos (linha da tabela)...</b></li>
</ul>
<h3>Passo a passo</h3>
<ol>
<li>Digite o nome como ele vem, ou escolha em <b>Camadas deste projeto</b>.</li>
<li>Em <b>Entra na tabela como</b>, escolha a linha certa. As opções estão agrupadas pelo quadro do Quadro de Áreas; embaixo aparece em qual quadro e linha ela vai cair.</li>
<li>Escolha <b>Todos os projetos</b> (vale para o escritório inteiro) ou <b>Só este projeto</b>.</li>
<li><b>Salvar nome</b>. Para desfazer, selecione na lista e clique em <b>Remover da lista</b>.</li>
</ol>
<p>Um nome ensinado vale antes das regras automáticas, inclusive do filtro de referência (ex.: nomes com "Limite" ou "Município").</p>
{_dica("para só uma vez, neste projeto, basta trocar o <b>Reconhecer como</b> da camada em " + _ir("calcular","Calcular áreas") + ".")}
"""),

("referencias", "Camadas de referência", f"""
<h2>Camadas de referência</h2>
<p>São camadas só de consulta (fitofisionomia, unidade de conservação, limites, bases externas): aparecem em <b>Todas as camadas</b>, mas <b>não entram no Quadro de Áreas</b>.</p>
<p>O plugin já trata como referência limites municipais (os 246 de Goiás), SICAR, SIGEF, INCRA, IBGE, serviços web e camadas muito maiores que o imóvel.</p>
<h3>Cadastrar um nome para todo o escritório</h3>
<ol>
<li>Clique em <b>+ Referências</b> (tela inicial), <b>+ Referência</b> (Calcular áreas) ou <b>Ferramentas &gt; + Camadas de referência...</b>.</li>
<li>Digite o nome ou parte dele (ex.: Fitofisionomia). A prévia mostra quais camadas abertas serão afetadas.</li>
<li>Clique em <b>+ Adicionar</b>. Para desfazer, selecione na lista e clique em <b>Remover da lista</b>.</li>
</ol>
<p>A comparação ignora acentos, maiúsculas e palavras a mais: "Fitofisionomia" pega "Fitofisionomia florestal 2008".</p>
{_cuidado("nomes genéricos que tirariam camadas do cálculo (APP, área, reserva legal...) são recusados. Uma camada com nome exato do catálogo continua sendo a classe dela.")}
"""),

("padronizar", "Padronizar camadas de cliente", f"""
<h2>Padronizar camadas</h2>
<p>Transforma uma camada de cliente (com nome e pasta quaisquer) na camada padrão do mapa, com o conteúdo dela.</p>
<ol>
<li>Em Calcular áreas, no botão <b>Ações</b> da camada, escolha <b>Criar camada padrão com este conteúdo</b> (ou use <b>Padronizar todas as reconhecidas</b>).</li>
<li>Confira a <b>Camada padrão</b> de destino e se quer corrigir geometrias.</li>
<li>Se a camada padrão já existir, o plugin mostra quantas feições e hectares tem antes e depois e pede confirmação. O conteúdo antigo vai para <code>_backup</code>.</li>
<li>No fim, escolha se a original fica, sai do projeto ou (se estiver dentro da pasta do mapa) vai para <code>_apagados</code>.</li>
</ol>
<p>O arquivo original do cliente nunca é renomeado, apagado ou alterado. Registros sem geometria não são copiados. O tipo precisa ser igual (polígono → polígono).</p>
"""),

("substituir", "Substituir o conteúdo de uma camada", f"""
<h2>Substituir conteúdo</h2>
<p>Troca as feições de uma camada padrão pelas de outra camada, mantendo arquivo, grupo, estilo e KML.</p>
<ol>
<li>Botão direito na camada em Criar / gerenciar camadas &gt; <b>Substituir...</b></li>
<li><b>Destino</b> - a camada padrão. <b>Origem</b> - a camada com o desenho novo. A tela mostra feições e hectares de cada uma.</li>
<li>Opções: <b>Corrigir geometrias antes</b> (recomendado) e <b>Remover a camada de origem do projeto depois</b> (o arquivo dela não é apagado).</li>
<li><b>Substituir</b> - um backup do conteúdo antigo é criado em <code>_backup</code> antes de gravar.</li>
</ol>
<p>Só aceita o mesmo tipo (polígono por polígono, linha por linha, ponto por ponto).</p>
"""),

("modelos_pastas", "Modelos: estrutura de pastas", f"""
<h2>Modelos de estrutura de pastas</h2>
<p>Um modelo é a "receita" das pastas de um projeto: você monta uma vez e o plugin cria tudo sozinho em cada projeto novo.
Pode ter quantas pastas mãe quiser, cada uma com as subpastas que quiser, em quantos níveis quiser.</p>
<h3>Passo a passo: criar um modelo do zero</h3>
<ol>
<li>Abra <b>Modelos</b> (na tela inicial do plugin, em <b>Ferramentas &gt; Modelos</b> ou no botão <b>Modelos...</b> de Configurar pasta) e fique na aba <b>Estrutura de pastas</b>.</li>
<li>Clique em <b>Novo</b> e escreva o <b>Nome do modelo</b> (ex.: <i>Licenciamento completo</i>). A árvore começa só com <i>Local escolhido ao criar a estrutura</i>: é a pasta que você escolhe depois, na hora de usar o modelo.</li>
<li>Clique em <b>+ Pasta mãe</b> e digite o nome. Para criar várias de uma vez, separe os nomes com <b>;</b> (ex.: <code>Fazenda; Documentos do cliente; Fotos</code>).</li>
<li>Clique numa pasta da árvore para selecioná-la e clique em <b>+ Subpasta</b>. Digite um nome, ou vários separados por <b>;</b> (ex.: <code>01 Documentos; 02 Mapas; 03 Licenças</code>). A pasta continua selecionada: é só clicar em <b>+ Subpasta</b> de novo para criar mais nela.</li>
<li>Para descer um nível, selecione a subpasta e clique em <b>+ Subpasta</b> outra vez. Atalho: use <b>/</b> para criar uma dentro da outra de uma vez (ex.: <code>CAR/2026</code>). Não tem limite de níveis; uma linha liga cada pasta à pasta de cima.</li>
<li>Escolha onde ficam as camadas do QGIS: selecione a pasta (ex.: <i>02 Mapas</i>) e clique em <b>Pasta do mapa aqui</b>. Ela aparece em verde, na coluna da direita, como <i>pasta do mapa</i>. Ao criar a primeira pasta mãe, o plugin já marca ela; mude quando quiser.</li>
<li>Dentro da pasta do mapa, crie se quiser as pastas que o plugin sabe usar:
<ul>
<li><code>kml</code> - liga a cópia KML automática de cada camada (sem ela, o KML só sai por <b>Ferramentas &gt; Exportar KML</b>);</li>
<li><code>projetos</code> - lugar sugerido para salvar o projeto do QGIS (.qgz);</li>
<li><code>shapefiles</code> - onde ficam as camadas. Se você não criar, o plugin cria sozinho quando a primeira camada for criada.</li>
</ul></li>
<li>(Opcional) Em <b>Camadas que o modelo cria</b>, use <b>+ Do catálogo...</b> ou <b>+ Nova camada...</b>. Em <b>Tema de cores</b>, escolha um {_ir("temas","tema")}.</li>
<li>Clique em <b>Salvar modelo</b>. Ele fica disponível para todo o escritório.</li>
</ol>
<h3>Exemplo</h3>
<pre>Local escolhido ao criar a estrutura
├── Fazenda Norte          pasta mãe
│   ├── 01 Documentos
│   │   ├── CAR
│   │   │   └── 2026
│   │   └── Matrícula
│   ├── 02 Mapas           pasta do mapa (camadas do QGIS)
│   │   ├── kml
│   │   ├── projetos
│   │   └── layout
│   └── 03 Licenças
└── Fotos                  pasta mãe</pre>
<p>Para montar isso: <b>+ Pasta mãe</b> com <code>Fazenda Norte; Fotos</code> &rarr; selecione <i>Fazenda Norte</i> e <b>+ Subpasta</b> com <code>01 Documentos; 02 Mapas; 03 Licenças</code> &rarr;
selecione <i>01 Documentos</i> e <b>+ Subpasta</b> com <code>CAR/2026; Matrícula</code> &rarr; selecione <i>02 Mapas</i>, <b>+ Subpasta</b> com <code>kml; projetos; layout</code> e clique em <b>Pasta do mapa aqui</b>.</p>
<h3>Arrumar a árvore</h3>
<ul>
<li><b>Renomear</b> - selecione e clique em Renomear, aperte <b>F2</b> ou clique duas vezes no nome.</li>
<li><b>Remover pasta</b> - tira a pasta e tudo o que estiver dentro dela, só do modelo (nada é apagado do disco). Atalho: tecla <b>Delete</b>.</li>
<li><b>Botão direito</b> em qualquer pasta mostra as mesmas opções.</li>
</ul>
<h3>Usar o modelo</h3>
<p>Em {_ir("configurar_pasta","Configurar pasta do mapa")}: escolha o modelo, o lugar (<b>Criar dentro de</b>) e confira o nome de cada pasta mãe (troque, por exemplo, pelo nome da fazenda).
Num projeto já configurado, <b>Aplicar neste projeto</b> cria só o que falta; nada é apagado nem sobrescrito.</p>
{_dica("o modelo Padrão Norte Agro é fixo: para partir dele, selecione-o e clique em Duplicar. Os modelos ficam no arquivo modelos_norteagro.json, ao lado do catálogo.")}
"""),

("temas", "Modelos: temas de cores", f"""
<h2>Temas de cores</h2>
<p>Um tema guarda o estilo de cada camada do plugin para reaplicar em outros projetos.</p>
<ol>
<li>Pinte as camadas no QGIS (Propriedades da camada &gt; Simbologia): cor única, categorizado, graduado, ponto, linha ou polígono.</li>
<li>Em <b>Modelos &gt; Temas de cores</b>, clique em <b>+ Novo tema com as cores do projeto</b>.</li>
<li>Se quiser, selecione camadas e clique em <b>Remover camada do tema</b> para deixar só as que interessam.</li>
<li>Dê um nome e clique em <b>Salvar tema</b>.</li>
</ol>
<h3>Usar o tema</h3>
<ul>
<li><b>Aplicar neste projeto</b> - pede confirmação dizendo quantas camadas mudam. Com <b>gravar também no estilo (.qml)</b> marcado, a cor continua ao reabrir a camada.</li>
<li>Escolher o tema num {_ir("modelos_pastas","modelo de pastas")} - as camadas já nascem com as cores.</li>
<li><b>Atualizar com as cores do projeto</b> - pega de novo as cores das camadas que já estão no tema.</li>
</ul>
<p>O tema guarda por tipo de camada (Reserva Legal, APP...). Se uma camada for de outro tipo geométrico (ponto em vez de polígono), ela é pulada e o motivo é avisado.</p>
{_dica("o QGIS tem o conta-gotas <b>Amostrar cor</b> na janela de cor: dá para pegar uma cor de um print aberto na tela.")}
"""),

("modelos_tabela", "Modelos: visual da planilha", f"""
<h2>Modelos de tabela</h2>
<p>Mudam a aparência do Quadro de Áreas sem mudar nenhum valor. O <b>Padrão Norte Agro</b> é a planilha de sempre.</p>
<ol>
<li>Em <b>Modelos &gt; Tabela</b>, clique em <b>Duplicar</b> no padrão (ou <b>Novo</b>).</li>
<li><b>Título da planilha</b> - pode usar <code>{{imovel}}</code>, <code>{{data}}</code>, <code>{{metodo}}</code> e <code>{{src}}</code>.</li>
<li><b>Quadros</b> - marque <b>Mostrar</b>, mude o <b>Título</b>, escolha o <b>Lado</b> (esquerda/direita) e a ordem com <b>Subir</b>/<b>Descer</b>.</li>
<li><b>Nomes das linhas</b> - escreva o nome novo ao lado do original. <b>+ Outra linha</b> para renomear linhas de camadas personalizadas.</li>
<li><b>Aparência</b> - fonte, tamanho e cores dos títulos e cabeçalhos.</li>
<li><b>Logo</b> - <b>Escolher imagem...</b> (aparece no canto do título).</li>
<li><b>Colunas extras</b> - área em m² e % da Área Total do Imóvel.</li>
<li><b>Ver exemplo no Excel</b> mostra o resultado com números de exemplo. <b>Salvar modelo</b>.</li>
</ol>
<p>Escolha o modelo em Calcular áreas &gt; <b>Modelo da tabela</b>.</p>
"""),

("pasta_renomear", "Pasta do mapa (trocar e renomear) e grupos", f"""
<h2>Trocar e renomear a pasta do mapa</h2>
<ul>
<li><b>Trocar</b> - aponta o projeto para outra pasta do mapa (abre {_ir("configurar_pasta","Configurar pasta do mapa")}).</li>
<li><b>Renomear</b> - muda o nome da pasta do mapa no disco. O plugin solta os arquivos, renomeia, reaponta todas as camadas e <b>salva o projeto</b> com o caminho novo. Se o Google Drive ou o antivírus estiver segurando algum arquivo, ele tenta por alguns segundos.</li>
</ul>
<h3>Grupos</h3>
<ul>
<li><b>Criar</b> - grupo novo só neste projeto.</li>
<li><b>Apagar</b> - mostra a lista do que será removido e pede confirmação. Camadas da pasta do mapa vão para <code>_apagados\\data</code> (não são apagadas de vez); camadas de fora só saem do projeto. O projeto é salvo em seguida.</li>
</ul>
"""),

("seguranca", "Segurança: o que o plugin nunca faz", f"""
<h2>Segurança dos dados</h2>
<ul>
<li>O cálculo em si <b>nunca</b> altera camadas. Só a <b>correção das camadas</b> (antes do cálculo, com sua confirmação) altera o desenho, e sempre com cópia em <code>_backup</code>.</li>
<li>Criar <b>nunca</b> sobrescreve uma camada existente.</li>
<li>Substituir e padronizar sempre fazem <b>backup</b> em <code>_backup</code> antes.</li>
<li>Apagar move para <code>_apagados</code>; nada é apagado de vez.</li>
<li>Arquivos de fora da pasta do mapa (de cliente) nunca são movidos ou apagados.</li>
<li>Mudar nomes de exibição não muda nomes de arquivo nem pastas existentes.</li>
<li>Catálogo e modelos do escritório têm trava contra gravação simultânea, e o arquivo de modelos não é sobrescrito se estiver ilegível.</li>
</ul>
"""),

("duvidas", "Perguntas frequentes", f"""
<h2>Perguntas frequentes</h2>
<h3>A camada do cliente não foi reconhecida.</h3>
<p>Em Calcular áreas, escolha a classe em <b>Reconhecer como</b>. Se o nome vai se repetir, clique em <b>Nomes não reconhecidos...</b> e escolha a linha da tabela.</p>
<h3>Uma camada que é só consulta entrou no cálculo.</h3>
<p>Cadastre o nome em {_ir("referencias","Camadas de referência")} ou desmarque a camada na lista.</p>
<h3>O total do imóvel não fechou / apareceu "Área sem classificação".</h3>
<p>Existe parte do imóvel sem classe desenhada. A aba Observações mostra onde (E/N). Desenhe a classe correta ali.</p>
<h3>Apareceu AJUSTADO ou T1.</h3>
<p>Duas classes se sobrepõem. O quadro já está certo (sem contar duas vezes), mas corrija o desenho com Vetor &gt; Geoprocessamento &gt; Diferença.</p>
<h3>Preciso de uma classe que não existe.</h3>
<p>Use {_ir("nova_camada","+ Nova camada")} e escolha o lugar no Quadro de Áreas.</p>
<h3>Quero outra estrutura de pastas ou outro visual de planilha.</h3>
<p>Veja {_ir("modelos_pastas","Modelos de pastas")} e {_ir("modelos_tabela","Modelos de tabela")}.</p>
<h3>Como monto as minhas próprias pastas (várias pastas mãe, subpastas dentro de subpastas)?</h3>
<p>Em <b>Modelos &gt; Estrutura de pastas</b>, clique em <b>Novo</b>, crie as pastas mãe com <b>+ Pasta mãe</b> e as de dentro com <b>+ Subpasta</b>. O passo a passo completo, com exemplo, está em {_ir("modelos_pastas","Modelos: estrutura de pastas")}.</p>
<h3>A planilha não salvou ("Planilha em uso").</h3>
<p>Ela está aberta no Excel. Feche e clique em <b>Salvar novamente</b>.</p>
<h3>"Arquivo não encontrado".</h3>
<p>O arquivo da camada foi movido ou apagado no computador. Recarregue a camada do lugar certo ou remova-a do projeto.</p>
"""),

("videos", "Vídeos da ajuda: como salvar e apagar", f"""
<h2>Vídeos da ajuda</h2>
<p>Cada assunto desta ajuda tem um <b>lugar para vídeo</b>, na coluna da direita, ao lado do texto. Grave com o programa que preferir e salve o vídeo aqui. Na lista de assuntos, <b>●</b> verde = já tem vídeo; <b>○</b> = falta o vídeo. Marque <b>Mostrar só os que faltam vídeo</b> para ver o que ainda falta gravar.</p>
<h3>Salvar o vídeo de um assunto</h3>
<ol>
<li>Clique no assunto à esquerda.</li>
<li>Na coluna <b>Vídeos deste assunto</b>, clique em <b>Salvar vídeo no plugin...</b>, escolha o arquivo (MP4, AVI, MKV, WMV, MOV...), confira o nome e escreva para que serve. A janela mostra a pasta onde ele vai ficar.</li>
<li>Clique em <b>Salvar no plugin</b>: o vídeo é copiado para a <b>pasta dos vídeos</b> deste plugin, numa pasta só daquele assunto (ex.: <code>Calcular áreas</code>). Sem limite de tamanho ou duração. O arquivo original continua onde você gravou.</li>
</ol>
<p>O cartão do vídeo mostra onde ele foi salvo. <b>▶ Assistir</b> toca o vídeo (se o formato não tocar dentro do QGIS, ele abre sozinho no player do Windows). <b>Trocar...</b> põe outro arquivo no lugar; <b>Editar</b> muda o nome e o texto; <b>Mostrar na pasta</b> abre o Explorador com o arquivo selecionado.</p>
<h3>Apagar</h3>
<p><b>Apagar</b> tira o vídeo da ajuda e <b>apaga o arquivo da pasta dos vídeos</b> (a pasta do assunto some se ficar vazia). O plugin pergunta antes e mostra o caminho do arquivo.</p>
<h3>Mais vídeos (fora dos lugares)</h3>
<p><b>+ Mais um vídeo</b> acrescenta quantos vídeos quiser: escolha se ele aparece num assunto (embaixo do vídeo principal, na mesma pasta do assunto) ou em <b>Vídeos extras</b> (pasta <code>Vídeos extras</code>), o último item da lista.</p>
<h3>Levar os vídeos para os colegas</h3>
<p>Os vídeos chegam aos colegas <b>pela internet</b>: quando quem cuida dos plugins publica vídeos, o QGIS de cada colega avisa na barra de cima e baixa sozinho, em segundo plano, só os vídeos que ainda não tem (e tira os que saíram). Ele confere ao abrir o QGIS e a cada 2 horas; não precisa atualizar o plugin. Enquanto baixa, o cartão do vídeo mostra <b>Baixando</b>; sem internet, aparece <b>Baixar agora</b>. Os vídeos ficam numa pasta do QGIS fora do plugin, então atualizar o plugin não apaga nenhum vídeo. <b>Abrir a pasta</b> mostra essa pasta.</p>
{_cuidado("salvar, trocar, editar e apagar vídeos pede a senha dos vídeos. Assistir não pede.")}
"""),

("manutencao", "Para quem mantém o plugin", f"""
<h2>Para quem mantém o plugin</h2>
<p>Depois de qualquer mudança no código, rode no <b>Terminal Python</b> do QGIS (Complementos &gt; Terminal Python):</p>
<p><code>from norteagro_uso_solo import testes_reconhecimento, testes_conferencia, testes_correcao, testes_interface</code><br>
<code>testes_reconhecimento.main(); testes_conferencia.executar(); testes_correcao.executar(); testes_interface.executar(mostrar=False)</code></p>
<p>Os testes usam catálogo e pastas temporários e devolvem o projeto aberto como estava. Todos devem terminar em OK.</p>
<p>O histórico de mudanças e os detalhes técnicos estão no arquivo <code>README.md</code> dentro da pasta do plugin. Os vídeos da ajuda ficam em <code>videos</code> (lista em <code>videos.json</code>); o código da coluna de vídeos é <code>videos_ajuda.py</code>, igual nos dois plugins.</p>
"""),

]

TOPICO_DA_TELA = {
    "tela_escolha": "tela_inicial", "tela_inicial": "configurar_pasta", "tela_camadas": "gerenciar",
    "tela_nova_camada": "nova_camada", "lugar_quadro": "nova_camada", "adicionar_catalogo": "catalogo",
    "restaurar_catalogo": "catalogo", "tela_avulsa": "avulsa", "tela_areas": "calcular", "tela_referencias": "referencias", "tela_apelidos": "apelidos", "tela_correcao": "correcao",
    "padronizar_camada": "padronizar", "padronizar_todas": "padronizar", "destino_padronizacao": "padronizar",
    "tela_substituir": "substituir", "renomear_pasta": "pasta_renomear", "tela_modelos": "modelos_pastas",
    "modelo_do_catalogo": "modelos_pastas", "tela_ajuda": "comecar", "tela_semad": "semad",
}


def topico_da_janela(janela):
    """Assunto da ajuda para uma janela do plugin (a tela de modelos escolhe pela aba aberta)."""
    try:
        if hasattr(janela, "topico_ajuda"):
            return janela.topico_ajuda()
    except Exception:
        pass
    return TOPICO_DA_TELA.get(str(janela.property("naTela") or ""), "comecar")


HTML_EXTRAS = """
<h2>Vídeos extras</h2>
<p>Vídeos que não são de um assunto só - por exemplo, um projeto completo do começo ao fim, um caso real ou uma
dica rápida. Use <b>+ Mais um vídeo</b> (na coluna da direita) e escolha <b>Vídeos extras</b> em "Aparece em".</p>
<p>Para pôr um vídeo a mais dentro de um assunto, abra o assunto e use o mesmo botão.</p>
"""


def assuntos_numerados():
    """[(chave, "N. Título")] na ordem da lista (a numeração sai daqui: mudar a ordem não quebra nada)."""
    return [(tid, f"{n}. {titulo}") for n, (tid, titulo, _h) in enumerate(TOPICOS, 1)]


class TelaAjuda(QDialog):
    def __init__(self, parent=None, topico="comecar"):
        super().__init__(parent)
        from .estilo import cabecalho, preparar_dialogo
        from .videos_ajuda import EXTRAS, TITULO_EXTRAS, PainelVideos
        self._extras = EXTRAS
        preparar_dialogo(self, "tela_ajuda", "Norte Agro - Ajuda", (900, 560)); self.resize(1360, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        raiz = QVBoxLayout(self); raiz.setContentsMargins(16, 16, 16, 16); raiz.setSpacing(10)
        raiz.addWidget(cabecalho("Ajuda do plugin", "Como cada tela funciona, passo a passo, com o vídeo de cada assunto ao lado. "
                                 "Clique num assunto ou busque uma palavra.",
                                 os.path.join(os.path.dirname(__file__), "icon.png"), ajuda=False))
        div = QSplitter(Qt.Orientation.Horizontal); raiz.addWidget(div, 1)
        esq = QWidget(); le = QVBoxLayout(esq); le.setContentsMargins(0, 0, 0, 0)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("Buscar (ex.: sobreposição, KML, apelido)..."); self.busca.textChanged.connect(self._filtrar)
        le.addWidget(self.busca)
        self.so_faltam = QCheckBox("Mostrar só os que faltam vídeo"); self.so_faltam.toggled.connect(lambda _v: self._filtrar(self.busca.text()))
        le.addWidget(self.so_faltam)
        self.lista = QListWidget(); self.lista.currentItemChanged.connect(self._mostrar); le.addWidget(self.lista, 1)
        self.nada = QLabel("Nenhum assunto com essa palavra."); self.nada.setProperty("naSubtitle", True); self.nada.setVisible(False); le.addWidget(self.nada)
        legenda = QLabel("● tem vídeo   ○ falta vídeo"); legenda.setProperty("naSubtitle", True); le.addWidget(legenda)
        div.addWidget(esq)
        self.texto = QTextBrowser(); self.texto.setOpenLinks(False); self.texto.anchorClicked.connect(self._link); div.addWidget(self.texto)
        self.numerados = assuntos_numerados()
        self.videos = PainelVideos(self.numerados, self)
        self.videos.alterado.connect(self._marcar)
        div.addWidget(self.videos)
        div.setStretchFactor(0, 0); div.setStretchFactor(1, 1); div.setStretchFactor(2, 0)
        div.setSizes([300, 680, 360])
        for tid, titulo in self.numerados + [(EXTRAS, TITULO_EXTRAS)]:
            it = QListWidgetItem(titulo); it.setData(Qt.ItemDataRole.UserRole, tid); self.lista.addItem(it)
        self._marcar()
        self.abrir(topico)

    def _marcar(self):
        """Bolinha verde nos assuntos que já têm vídeo."""
        from .videos_ajuda import assuntos_com_video, bolinha, ler
        itens = ler()
        feitos = assuntos_com_video(itens)
        cheio, vazio = bolinha("#46741F"), bolinha("")
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            tid = it.data(Qt.ItemDataRole.UserRole)
            if tid == self._extras:
                n = len([x for x in itens if x.get("assunto") == self._extras])
                it.setIcon(cheio if n else vazio)
                continue
            it.setIcon(cheio if tid in feitos else vazio)
        if self.so_faltam.isChecked():
            self._filtrar(self.busca.text())

    def abrir(self, topico):
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == topico:
                self.lista.item(i).setHidden(False); self.lista.setCurrentRow(i); return
        self.lista.setCurrentRow(0)

    def _html(self, tid):
        if tid == self._extras:
            return HTML_EXTRAS
        return next((h for t, _ti, h in TOPICOS if t == tid), "")

    def _mostrar(self, item, _antigo=None):
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        self.texto.setHtml(CSS + self._html(tid))
        self.videos.mostrar(tid, item.text())
        termo = self.busca.text().strip()
        if termo:
            self.texto.find(termo)

    def _link(self, url):
        alvo = url.fragment() or url.toString().lstrip("#")
        if alvo:
            self.busca.clear(); self.so_faltam.setChecked(False); self.abrir(alvo)

    def _filtrar(self, termo):
        import unicodedata
        from .videos_ajuda import assuntos_com_video
        def sem(t): return "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")
        alvo = sem(termo.strip()); primeiro = None
        feitos = assuntos_com_video() if self.so_faltam.isChecked() else set()
        for i in range(self.lista.count()):
            it = self.lista.item(i); tid = it.data(Qt.ItemDataRole.UserRole)
            mostra = not alvo or alvo in sem(it.text()) or alvo in sem(self._html(tid))
            if self.so_faltam.isChecked() and (tid in feitos or tid == self._extras):
                mostra = False
            it.setHidden(not mostra)
            if mostra and primeiro is None: primeiro = i
        self.nada.setText("Todos os assuntos já têm vídeo." if self.so_faltam.isChecked() and not alvo else "Nenhum assunto com essa palavra.")
        self.nada.setVisible(primeiro is None)
        if primeiro is not None:
            atual = self.lista.currentRow()
            if atual < 0 or self.lista.item(atual).isHidden(): self.lista.setCurrentRow(primeiro)
            else: self._mostrar(self.lista.currentItem())


def abrir_ajuda(parent=None, topico=None):
    """Abre a ajuda sem travar a janela de onde veio (dá para ler e usar o plugin ao mesmo tempo)."""
    if topico is None and parent is not None:
        topico = topico_da_janela(parent)
    dlg = TelaAjuda(parent, topico or "comecar")
    dlg.setWindowModality(Qt.WindowModality.NonModal); dlg.show(); dlg.raise_(); dlg.activateWindow()
    return dlg
