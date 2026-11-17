# -*- coding: utf-8 -*-
"""Catálogo, estilos e serialização de símbolos do Norte Agro."""
import json
import os
import re
import unicodedata
import time
from datetime import datetime
from .reconhecimento import gerar_apelidos_padrao, indice_apelidos, normalizar_chave

# O catálogo também é importado pelos testes de reconhecimento fora do QGIS.
# As rotinas visuais só são usadas quando QGIS/PyQt está disponível.
try:
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.core import (
        QgsExpressionContextUtils, QgsFillSymbol, QgsLinePatternFillSymbolLayer,
        QgsLineSymbol, QgsMarkerSymbol, QgsReadWriteContext, QgsRenderContext,
        QgsSymbolLayerUtils
    )
    QGIS_DISPONIVEL = True
except Exception:  # pragma: no cover - usado apenas nos testes puros fora do QGIS
    QSize = QColor = QDomDocument = None
    QgsExpressionContextUtils = QgsFillSymbol = QgsLinePatternFillSymbolLayer = None
    QgsLineSymbol = QgsMarkerSymbol = QgsReadWriteContext = QgsRenderContext = QgsSymbolLayerUtils = None
    QGIS_DISPONIVEL = False

GRUPOS_BASE = ["Uso do Solo", "Passivos e Compensação", "Ocultos (Salvar na pasta)", "SEMAD - SIGA"]
# v0.5.0: o grupo "SEMAD - SIGA" traz as camadas que o plugin busca no SIGA da SEMAD-GO (ver semad.py). Elas são
# referência: não entram no cálculo de áreas nem na correção.
# v0.7.0: os murundus convalidados saíram deste grupo: vão para a camada Murundus do Uso do Solo (catálogo do escritório).
# v0.2.0: o catálogo e os modelos ficam DENTRO do próprio plugin, na pasta dados/. Nada depende do Google Drive.
# O que vem de fábrica no ZIP fica em padrao/; a pasta dados/ nasce a partir dela (ou da cópia de segurança)
# e recebe tudo o que a pessoa adiciona. Uma cópia de segurança de dados/ fica no perfil do QGIS, porque
# reinstalar/atualizar o plugin apaga a pasta dele: na volta, os dados são restaurados sozinhos.
_PASTA_PLUGIN = os.path.dirname(os.path.abspath(__file__))
PASTA_PADRAO = os.path.join(_PASTA_PLUGIN, "padrao")
ARQUIVOS_DADOS = ("catalogo_extra.json", "modelos_norteagro.json")
# Caminho antigo no Drive: só é lido UMA vez, para trazer o que já existia (migração da v0.1.x).
_REL_CATALOGO = r"02. OPERACIONAL\02. CONHECIMENTO\QGIS\Projeto Modelo - Planta de Uso do Solo\ESTILOS\catalogo_extra.json"
_CHAVE_CAMINHO_CATALOGO = "norteagro_uso_solo/caminho_catalogo"


def _pasta_perfil():
    base = ""
    try:
        from qgis.core import QgsApplication
        base = str(QgsApplication.qgisSettingsDirPath() or "")
    except Exception:
        base = ""
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".norteagro")
    return os.path.join(base, "norteagro_uso_solo")


def _pasta_dados():
    """dados/ dentro do plugin; se o Windows não deixar gravar lá, usa o perfil do QGIS."""
    pasta = os.path.join(_PASTA_PLUGIN, "dados")
    try:
        os.makedirs(pasta, exist_ok=True)
        if os.access(pasta, os.W_OK):
            return pasta
    except Exception:
        pass
    pasta = os.path.join(_pasta_perfil(), "dados")
    try:
        os.makedirs(pasta, exist_ok=True)
    except Exception:
        pass
    return pasta


PASTA_DADOS = _pasta_dados()
CATALOGO_ESCRITORIO = os.path.join(PASTA_DADOS, "catalogo_extra.json")
_CAMINHO_REAL = CATALOGO_ESCRITORIO          # os testes trocam CATALOGO_ESCRITORIO por um arquivo temporário
_CACHE_ESCRITORIO = None

# arquivo, nome, tipo (P=polígono, L=linha, Pt=ponto), preenchimento, contorno
CATALOGO_FIXO = {
    "Uso do Solo": [
        ("RESERVA_LEGAL", "Reserva Legal", "P", "sem", "#23E316/0.7"),
        ("AREA_ENCRAVADA", "Área Encravada", "P", "sem", "#000000/0.5"),
        ("AREA_DO_IMOVEL", "Área do Imóvel", "P", "sem", "#000000/0.5"),
        ("LAGOA_NATURAL", "Lagoa Natural", "P", "#00FFE8@50", "#D000FF/0.1"),
        ("VEREDAS", "Veredas", "P", "sem", "#D000FF/0.5"),
        ("APP_TOTAL", "APP Total", "P", "sem", "#FFFA00/0.5"),
        ("TANQUE", "Tanque", "P", "H#0900FF/45/2 + H#0900FF/135/2", "#0900FF/0.5"),
        ("CACIMBA", "Cacimba", "P", "#003BFF@30", "#FFFFFF/0.1"),
        ("ENCOSTAS", "Encostas", "P", "sem", "#FFFFFF/0.5"),
        ("TOPO_DE_MORRO", "Topo de Morro", "P", "#D000FF@70", "#FFFA00/0.5"),
        ("BARRAGEM", "Barragem", "P", "#003BFF@50", "#003BFF/0.1"),
        ("NASCENTE", "Nascente", "Pt", "#003BFF@100", "#232323/0.3"),
        ("HIDROGRAFIA", "Hidrografia", "P", "#003BFF@100", "#003BFF/0.5"),
        ("SERVIDAO_ADMINISTRATIVA", "Servidão Administrativa", "P", "#000000@70", "#E31A1C/0.5"),
        ("AREA_DE_VEGETACAO", "Área de Vegetação Nativa", "P", "#33A02C@60", "#000000/0.1"),
        ("AREA_CONSOLIDADA", "Área Consolidada", "P", "#FFFA00@25", "#232323/0.1"),
        ("AREA_SUPRIMIDA_ANTES_2019", "Área Suprimida antes de 2019", "P", "H#FF7F00/45/2", "#FF7F00/0.1"),
        ("AREA_SUPRIMIDA_DEPOIS_2019", "Área Suprimida depois de 2019", "P", "#FF7F00@42", "#000000/0.1"),
        ("AREA_SUPRIMIDA", "Área Suprimida", "P", "sem", "#E31A1C/0.5"),
    ],
    "Passivos e Compensação": [
        ("AREA_DE_COMPENSACAO", "Área de Compensação", "P", "sem", "#00FFE8/0.5"),
        ("COMPENSACAO_FLORESTAL", "Compensação Florestal", "P", "X#FFFA00", "#FFFA00/0.1"),
        ("COMPENSACAO_DANOS", "Compensação de Danos", "P", "X#33A02C", "#33A02C/0.1"),
        ("AREA_RECOMPOSICAO", "Área de Recomposição", "P", "#E31A1C@40", "#232323/0.1"),
        ("AREA_LICENCIADA", "Área Licenciada", "P", "sem", "#FF7F00/0.5"),
        ("APP_SUPRIMIDA", "APP Suprimida", "P", "sem", "#E31A1C/0.5"),
        ("APP_ANTROPIZADA_APOS_2019", "APP Antropizada após 2019", "P", "H#D000FF/45/2", "#D000FF/0.1"),
        ("APP_ANTROPIZADA_ANTES_2019", "APP Antropizada antes de 2019", "P", "H#000000/45/2", "#000000/0.1"),
        ("AREA_EMBARGADA", "Área Embargada", "P", "#E31A1C@40", "#232323/0.1"),
    ],
    "Ocultos (Salvar na pasta)": [
        ("RESERVA_SUPRIMIDA", "Reserva Suprimida", "P", "sem", "#00FFE8/0.1"),
        ("RESERVA_CONSOLIDADA", "Reserva Consolidada", "P", "sem", "#003BFF/0.1"),
        ("SUPRESSAO_PASSIVEL_DEPOIS_2019", "Supressão Passível depois de 2019", "P", "#FF7F00@100", "#FF7F00/0.26"),
        ("SUPRESSAO_PASSIVEL_ANTES_2019", "Supressão Passível antes de 2019", "P", "X#D000FF", "#D000FF/0.26"),
        ("SUPRESSAO_PASSIVEL_TOTAL", "Supressão Passível Total", "P", "#D000FF@40", "#D000FF/0.1"),
        ("RESERVA_PRESERVADA", "Reserva Preservada", "P", "sem", "#FFFFFF/0.1"),
        ("AREA_DE_GLEBAS", "Área de Glebas", "P", "sem", "#232323/0.1"),
        ("APP_CONSOLIDADA", "APP Consolidada", "P", "H#00FFE8/20/1", "#00FFE8/0.2"),
        ("APP_PRESERVADA", "APP Preservada", "P", "H#33A02C/20/1", "#33A02C/0.2"),
    ],
    "SEMAD - SIGA": [
        ("SEMAD_MURUNDUS_2020", "Campos de Murundus 2020 SEMAD", "P", "H#C49A55/45/2", "#C49A55/0.4"),
        ("SEMAD_APP_DECLIVIDADE", "APP de Declividade SEMAD", "P", "#C0392B@40", "#C0392B/0.4"),
        ("SEMAD_APP_BORDA_CHAPADA", "APP de Borda de Chapada SEMAD", "P", "#8E44AD@40", "#8E44AD/0.4"),
        ("SEMAD_APP_TOPO_MORRO", "APP de Topo de Morro SEMAD", "P", "#D35400@40", "#D35400/0.4"),
        ("SEMAD_UC", "Unidades de Conservação SEMAD", "P", "sem", "#1E8449/0.8"),
    ],
}


# Nomes oficiais de exibição, conforme a Planilha de Padronização do escritório.
# ARQUIVO continua sendo a chave interna e o nome dos arquivos no disco.
NOMES_EXIBICAO = {
    "AREA_DO_IMOVEL": "Área Total do Imóvel",
    "AREA_DE_GLEBAS": "Área de Glebas do Imóvel",
    "SERVIDAO_ADMINISTRATIVA": "Servidão Administrativa",
    "AREA_ENCRAVADA": "Área Encravada",
    "AREA_DE_VEGETACAO": "Área de Vegetação Nativa",
    "HIDROGRAFIA": "Hidrografia",
    "NASCENTE": "Nascentes",
    "BARRAGEM": "Barramentos",
    "VEREDAS": "Veredas",
    "LAGOA_NATURAL": "Lagoa Natural",
    "TOPO_DE_MORRO": "Topo de Morros",
    "ENCOSTAS": "Encostas",
    "CACIMBA": "Cacimba",
    "TANQUE": "Tanques",
    "APP_PRESERVADA": "APP Preservada",
    "APP_CONSOLIDADA": "APP Consolidada",
    "APP_SUPRIMIDA": "APP Suprimida",
    "APP_ANTROPIZADA_ANTES_2019": "APP Suprimida antes de 2019",
    "APP_ANTROPIZADA_APOS_2019": "APP Suprimida depois de 2019",
    "APP_TOTAL": "APP Total",
    "AREA_SUPRIMIDA": "Área Suprimida",
    "AREA_SUPRIMIDA_ANTES_2019": "Área Suprimida antes de 2019",
    "AREA_SUPRIMIDA_DEPOIS_2019": "Área Suprimida depois de 2019",
    "AREA_CONSOLIDADA": "Área Consolidada",
    "RESERVA_LEGAL": "Área de Reserva Legal",
    "RESERVA_PRESERVADA": "Área de Reserva Legal Preservada",
    "RESERVA_CONSOLIDADA": "Área de Reserva Legal Consolidada",
    "RESERVA_SUPRIMIDA": "Área de Reserva Legal Suprimida",
    "AREA_RECOMPOSICAO": "Área de Recomposição",
    "AREA_DE_COMPENSACAO": "Área de Compensação",
    "COMPENSACAO_DANOS": "Área de Compensação por Danos",
    "COMPENSACAO_FLORESTAL": "Área de Compensação Florestal",
    "AREA_LICENCIADA": "Área Licenciada",
    "SUPRESSAO_PASSIVEL_TOTAL": "Supressão em Área Passível",
    "SUPRESSAO_PASSIVEL_ANTES_2019": "Supressão em Área Passível antes de 2019",
    "SUPRESSAO_PASSIVEL_DEPOIS_2019": "Supressão em Área Passível após 2019",
    "AREA_EMBARGADA": "Área Embargada",
    "SEMAD_MURUNDUS_2020": "Campos de Murundus 2020 - mapeamento original (SEMAD)",
    "SEMAD_APP_DECLIVIDADE": "APP de Declividade (SEMAD)",
    "SEMAD_APP_BORDA_CHAPADA": "APP de Borda de Chapada (SEMAD)",
    "SEMAD_APP_TOPO_MORRO": "APP de Topo de Morro (SEMAD)",
    "SEMAD_UC": "Unidades de Conservação (SEMAD)",
}

ITENS_PLANILHA_PADRONIZACAO = [
    "Área Total do Imóvel", "Área de Glebas do Imóvel", "Servidão Administrativa",
    "Área Encravada", "Área de Vegetação Nativa", "Hidrografia", "Nascentes",
    "Barramentos", "Veredas", "Lagoa Natural", "Topo de Morros", "Encostas",
    "Cacimba", "Tanques", "APP Preservada", "APP Consolidada", "APP Suprimida",
    "APP Suprimida antes de 2019", "APP Suprimida depois de 2019", "APP Total",
    "Área Suprimida", "Área Suprimida antes de 2019", "Área Suprimida depois de 2019",
    "Área Consolidada", "Área de Reserva Legal", "Área de Reserva Legal Preservada",
    "Área de Reserva Legal Consolidada", "Área de Reserva Legal Suprimida",
    "Área de Reserva Legal Suprimida antes de 2019", "Área de Reserva Legal Suprimida depois de 2019",
    "Área de Recomposição", "Área de Compensação", "Área de Compensação por Danos",
    "Área de Compensação Florestal", "Área Licenciada", "Supressão em Área Passível",
    "Supressão em Área Passível antes de 2019", "Supressão em Área Passível após 2019",
    "Área Embargada",
]

# Classes do fechamento do imóvel. O JSON do escritório pode substituir esta lista
# pela chave "fechamento"; a lógica interna continua usando somente ARQUIVO.
FECHAMENTO_PADRAO = [
    "AREA_SUPRIMIDA_ANTES_2019",
    "AREA_SUPRIMIDA_DEPOIS_2019",
    "AREA_CONSOLIDADA",
    "AREA_DE_VEGETACAO",
]

# Chaves internas usadas explicitamente nas operações espaciais e nos quadros do Excel.
ARQUIVOS_LOGICA = {
    "RESERVA_LEGAL", "RESERVA_PRESERVADA", "RESERVA_CONSOLIDADA", "RESERVA_SUPRIMIDA",
    "APP_TOTAL", "APP_PRESERVADA", "APP_CONSOLIDADA", "APP_SUPRIMIDA",
    "APP_ANTROPIZADA_ANTES_2019", "APP_ANTROPIZADA_APOS_2019",
    "AREA_DE_VEGETACAO", "AREA_CONSOLIDADA", "AREA_DO_IMOVEL", "AREA_SUPRIMIDA",
    "AREA_SUPRIMIDA_ANTES_2019", "AREA_SUPRIMIDA_DEPOIS_2019",
    "HIDROGRAFIA", "BARRAGEM", "CACIMBA", "TANQUE", "LAGOA_NATURAL",
    "SUPRESSAO_PASSIVEL_TOTAL", "SUPRESSAO_PASSIVEL_ANTES_2019", "SUPRESSAO_PASSIVEL_DEPOIS_2019",
    "COMPENSACAO_DANOS", "COMPENSACAO_FLORESTAL", "AREA_RECOMPOSICAO",
} | set(FECHAMENTO_PADRAO)

INVALIDOS_WINDOWS = r'\/:*?"<>|'


def limpar_nome_pasta(nome):
    """Nome de pasta Unicode: remove caracteres inválidos e apenas espaços/pontos do fim."""
    texto = str(nome or "")
    texto = re.sub(r'[\\/:*?"<>|]', "", texto)
    texto = texto.rstrip(" .")
    return texto.strip() or "CAMADA"


def nome_exibicao_padrao(arquivo, fallback=""):
    """Nome oficial fixo; fallback nunca altera o ARQUIVO."""
    arquivo = str(arquivo or "").upper()
    if arquivo in NOMES_EXIBICAO:
        return NOMES_EXIBICAO[arquivo]
    base = str(fallback or arquivo).strip()
    return base or arquivo.replace("_", " ")


def pasta_camada_entrada(entrada):
    return limpar_nome_pasta(str((entrada or {}).get("nome") or (entrada or {}).get("arquivo") or "CAMADA"))


# Lista dos 246 municípios de Goiás. A comparação é exata após normalização forte.
MUNICIPIOS_GOIAS_NOMES = (
    'Abadia de Goiás',
    'Abadiânia',
    'Acreúna',
    'Adelândia',
    'Água Fria de Goiás',
    'Água Limpa',
    'Águas Lindas de Goiás',
    'Alexânia',
    'Aloândia',
    'Alto Horizonte',
    'Alto Paraíso de Goiás',
    'Alvorada do Norte',
    'Amaralina',
    'Americano do Brasil',
    'Amorinópolis',
    'Anápolis',
    'Anhanguera',
    'Anicuns',
    'Aparecida de Goiânia',
    'Aparecida do Rio Doce',
    'Aporé',
    'Araçu',
    'Aragarças',
    'Aragoiânia',
    'Araguapaz',
    'Arenópolis',
    'Aruanã',
    'Aurilândia',
    'Avelinópolis',
    'Baliza',
    'Barro Alto',
    'Bela Vista de Goiás',
    'Bom Jardim de Goiás',
    'Bom Jesus de Goiás',
    'Bonfinópolis',
    'Bonópolis',
    'Brazabrantes',
    'Britânia',
    'Buriti Alegre',
    'Buriti de Goiás',
    'Buritinópolis',
    'Cabeceiras',
    'Cachoeira Alta',
    'Cachoeira de Goiás',
    'Cachoeira Dourada',
    'Caçu',
    'Caiapônia',
    'Caldas Novas',
    'Caldazinha',
    'Campestre de Goiás',
    'Campinaçu',
    'Campinorte',
    'Campo Alegre de Goiás',
    'Campo Limpo de Goiás',
    'Campos Belos',
    'Campos Verdes',
    'Carmo do Rio Verde',
    'Castelândia',
    'Catalão',
    'Caturaí',
    'Cavalcante',
    'Ceres',
    'Cezarina',
    'Chapadão do Céu',
    'Cidade Ocidental',
    'Cocalzinho de Goiás',
    'Colinas do Sul',
    'Córrego do Ouro',
    'Corumbá de Goiás',
    'Corumbaíba',
    'Cristalina',
    'Cristianópolis',
    'Crixás',
    'Cromínia',
    'Cumari',
    'Damianópolis',
    'Damolândia',
    'Davinópolis',
    'Diorama',
    'Doverlândia',
    'Edealina',
    'Edéia',
    'Estrela do Norte',
    'Faina',
    'Fazenda Nova',
    'Firminópolis',
    'Flores de Goiás',
    'Formosa',
    'Formoso',
    'Gameleira de Goiás',
    'Divinópolis de Goiás',
    'Goianápolis',
    'Goiandira',
    'Goianésia',
    'Goiânia',
    'Goianira',
    'Goiás',
    'Goiatuba',
    'Gouvelândia',
    'Guapó',
    'Guaraíta',
    'Guarani de Goiás',
    'Guarinos',
    'Heitoraí',
    'Hidrolândia',
    'Hidrolina',
    'Iaciara',
    'Inaciolândia',
    'Indiara',
    'Inhumas',
    'Ipameri',
    'Ipiranga de Goiás',
    'Iporá',
    'Israelândia',
    'Itaberaí',
    'Itaguari',
    'Itaguaru',
    'Itajá',
    'Itapaci',
    'Itapirapuã',
    'Itapuranga',
    'Itarumã',
    'Itauçu',
    'Itumbiara',
    'Ivolândia',
    'Jandaia',
    'Jaraguá',
    'Jataí',
    'Jaupaci',
    'Jesúpolis',
    'Joviânia',
    'Jussara',
    'Lagoa Santa',
    'Leopoldo de Bulhões',
    'Luziânia',
    'Mairipotaba',
    'Mambaí',
    'Mara Rosa',
    'Marzagão',
    'Matrinchã',
    'Maurilândia',
    'Mimoso de Goiás',
    'Minaçu',
    'Mineiros',
    'Moiporá',
    'Monte Alegre de Goiás',
    'Montes Claros de Goiás',
    'Montividiu',
    'Montividiu do Norte',
    'Morrinhos',
    'Morro Agudo de Goiás',
    'Mossâmedes',
    'Mozarlândia',
    'Mundo Novo',
    'Mutunópolis',
    'Nazário',
    'Nerópolis',
    'Niquelândia',
    'Nova América',
    'Nova Aurora',
    'Nova Crixás',
    'Nova Glória',
    'Nova Iguaçu de Goiás',
    'Nova Roma',
    'Nova Veneza',
    'Novo Brasil',
    'Novo Gama',
    'Novo Planalto',
    'Orizona',
    'Ouro Verde de Goiás',
    'Ouvidor',
    'Padre Bernardo',
    'Palestina de Goiás',
    'Palmeiras de Goiás',
    'Palmelo',
    'Palminópolis',
    'Panamá',
    'Paranaiguara',
    'Paraúna',
    'Perolândia',
    'Petrolina de Goiás',
    'Pilar de Goiás',
    'Piracanjuba',
    'Piranhas',
    'Pirenópolis',
    'Pires do Rio',
    'Planaltina',
    'Pontalina',
    'Porangatu',
    'Porteirão',
    'Portelândia',
    'Posse',
    'Professor Jamil',
    'Quirinópolis',
    'Rialma',
    'Rianápolis',
    'Rio Quente',
    'Rio Verde',
    'Rubiataba',
    'Sanclerlândia',
    'Santa Bárbara de Goiás',
    'Santa Cruz de Goiás',
    'Santa Fé de Goiás',
    'Santa Helena de Goiás',
    'Santa Isabel',
    'Santa Rita do Araguaia',
    'Santa Rita do Novo Destino',
    'Santa Rosa de Goiás',
    'Santa Tereza de Goiás',
    'Santa Terezinha de Goiás',
    'Santo Antônio da Barra',
    'Santo Antônio de Goiás',
    'Santo Antônio do Descoberto',
    'São Domingos',
    'São Francisco de Goiás',
    "São João D'Aliança",
    'São João da Paraúna',
    'São Luís de Montes Belos',
    'São Luíz do Norte',
    'São Miguel do Araguaia',
    'São Miguel do Passa Quatro',
    'São Patrício',
    'São Simão',
    'Senador Canedo',
    'Serranópolis',
    'Silvânia',
    'Simolândia',
    "Sítio D'Abadia",
    'Taquaral de Goiás',
    'Teresina de Goiás',
    'Terezópolis de Goiás',
    'Três Ranchos',
    'Trindade',
    'Trombas',
    'Turvânia',
    'Turvelândia',
    'Uirapuru',
    'Uruaçu',
    'Uruana',
    'Urutaí',
    'Valparaíso de Goiás',
    'Varjão',
    'Vianópolis',
    'Vicentinópolis',
    'Vila Boa',
    'Vila Propício',
)
MUNICIPIOS_GOIAS = frozenset(normalizar_chave(x) for x in MUNICIPIOS_GOIAS_NOMES)


def normalizar_arquivo(nome):
    """Gera nome de arquivo em maiúsculas, sem acento e com sublinhados."""
    texto = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto.upper()).strip("_")
    return re.sub(r"_+", "_", texto)


def _cor(texto, opacidade=100):
    cor = QColor(texto)
    cor.setAlphaF(max(0.0, min(100.0, float(opacidade))) / 100.0)
    return cor


def simbolo_notacao(tipo, preenchimento="sem", contorno="#232323/0.3"):
    """Converte a notação compacta do catálogo em símbolo QGIS."""
    cor_contorno, esp = (contorno.split("/") + ["0.3"])[:2]
    if tipo == "Pt":
        cor = preenchimento.split("@")[0] if preenchimento.startswith("#") else "#003BFF"
        return QgsMarkerSymbol.createSimple({
            "name": "circle", "color": cor, "size": "2",
            "outline_color": cor_contorno, "outline_width": esp,
        })
    if tipo == "L":
        cor = preenchimento.split("@")[0] if preenchimento.startswith("#") else cor_contorno
        largura = esp if float(esp) > 0 else "0.3"
        return QgsLineSymbol.createSimple({"color": cor, "width": largura})
    simbolo = QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "outline_color": cor_contorno, "outline_width": esp,
    })
    base = simbolo.symbolLayer(0)
    base.setStrokeColor(QColor(cor_contorno)); base.setStrokeWidth(float(esp))
    if preenchimento.startswith("#"):
        hexa, op = preenchimento.split("@", 1)
        base.setFillColor(_cor(hexa, op))
    else:
        base.setFillColor(QColor(0, 0, 0, 0))

    def adicionar_hachura(token, angulo_padrao=None):
        partes = token[1:].split("/")
        cor = partes[0]
        angulo = float(partes[1]) if len(partes) > 1 else float(angulo_padrao)
        distancia = float(partes[2]) if len(partes) > 2 else 2.0
        camada = QgsLinePatternFillSymbolLayer()
        camada.setLineAngle(angulo); camada.setDistance(distancia)
        camada.setSubSymbol(QgsLineSymbol.createSimple({"color": cor, "width": "0.3"}))
        simbolo.appendSymbolLayer(camada)

    if preenchimento.startswith("H"):
        for token in (p.strip() for p in preenchimento.split("+")):
            adicionar_hachura(token)
    elif preenchimento.startswith("X"):
        adicionar_hachura("H" + preenchimento[1:], 45)
        adicionar_hachura("H" + preenchimento[1:], 135)
    return simbolo


def simbolo_padrao(tipo):
    """Símbolo inicial para camadas personalizadas."""
    if tipo == "Pt":
        return QgsMarkerSymbol.createSimple({"name": "circle", "color": "#3388FF", "size": "2", "outline_color": "#232323"})
    if tipo == "L":
        return QgsLineSymbol.createSimple({"color": "#3388FF", "width": "0.5"})
    return QgsFillSymbol.createSimple({"color": "51,136,255,90", "outline_color": "#232323", "outline_width": "0.3"})


def simbolo_para_xml(simbolo):
    """Serializa um QgsSymbol em XML para armazenamento no projeto/JSON."""
    doc = QDomDocument("norteagro_symbol")
    elem = QgsSymbolLayerUtils.saveSymbol("simbolo", simbolo, doc, QgsReadWriteContext())
    doc.appendChild(elem)
    return doc.toString()


def simbolo_de_xml(xml):
    """Restaura um QgsSymbol salvo pelo QgsSymbolLayerUtils."""
    if not xml:
        return None
    doc = QDomDocument()
    resultado = doc.setContent(xml)
    ok = resultado[0] if isinstance(resultado, tuple) else bool(resultado)
    if not ok:
        return None
    return QgsSymbolLayerUtils.loadSymbol(doc.documentElement(), QgsReadWriteContext())


def _entrada_fixa(grupo, item, ordem, nomes_exibicao=None):
    arquivo, nome_original, tipo, preenchimento, contorno = item
    nomes_exibicao = nomes_exibicao or {}
    nome = str(nomes_exibicao.get(arquivo) or nome_exibicao_padrao(arquivo, nome_original))
    return {
        "arquivo": arquivo, "nome": nome, "nome_exibicao": nome, "nome_original": nome_original,
        "tipo": tipo, "grupo": grupo, "preenchimento": preenchimento, "contorno": contorno,
        "estilo_xml": "", "personalizada": False, "origem": "fixa", "ordem": ordem,
        "pasta_camada": limpar_nome_pasta(nome),
    }


def catalogo_fixo_lista(nomes_exibicao=None):
    saida = []
    for grupo in GRUPOS_BASE:
        for ordem, item in enumerate(CATALOGO_FIXO[grupo]):
            saida.append(_entrada_fixa(grupo, item, ordem, nomes_exibicao))
    return saida


# Apelidos fixos gerados exclusivamente por regras; colisões são removidas no índice final.
APELIDOS_PADRAO = gerar_apelidos_padrao(catalogo_fixo_lista())


def extras_projeto(projeto):
    """Lê apenas os extras gravados nas variáveis do projeto atual."""
    escopo = QgsExpressionContextUtils.projectScope(projeto)
    bruto = str(escopo.variable("norteagro_extras") or "[]")
    try:
        dados = json.loads(bruto)
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def salvar_extras_projeto(projeto, extras):
    QgsExpressionContextUtils.setProjectVariable(
        projeto, "norteagro_extras", json.dumps(extras, ensure_ascii=False)
    )
    projeto.setDirty(True)


def _estado_vazio():
    return {
        "extras": [], "ocultas": [], "removidas": [], "apelidos": {}, "nomes_exibicao": {},
        "fechamento": list(FECHAMENTO_PADRAO),
        "fechamento_inclui_hidrografia": False,
        "nao_recortar": [],
        "referencias": [],
        "estilos_padrao": {},
    }


def _normalizar_referencias(lista):
    """v3.9.5: aceita textos simples ou {"nome","autor","data"}; remove repetidos pela chave normalizada."""
    saida, vistos = [], set()
    for item in lista if isinstance(lista, list) else []:
        if isinstance(item, dict):
            nome = str(item.get("nome") or "").strip(); extra = {k: str(v) for k, v in item.items() if k in ("autor", "data")}
        else:
            nome = str(item or "").strip(); extra = {}
        chave = normalizar_chave(nome)
        if not nome or not chave or chave in vistos:
            continue
        vistos.add(chave); saida.append(dict({"nome": nome}, **extra))
    return saida


def _normalizar_estado(dados):
    """Aceita também o formato legado (lista simples de extras)."""
    if isinstance(dados, list):
        estado = _estado_vazio()
        estado["extras"] = dados
        return estado
    if not isinstance(dados, dict):
        return _estado_vazio()
    apelidos = dados.get("apelidos", {})
    if not isinstance(apelidos, dict):
        apelidos = {}
    nomes = dados.get("nomes_exibicao", {})
    if not isinstance(nomes, dict):
        nomes = {}
    fechamento = dados.get("fechamento", FECHAMENTO_PADRAO)
    if not isinstance(fechamento, list):
        fechamento = list(FECHAMENTO_PADRAO)
    nao_recortar = dados.get("nao_recortar", [])
    if not isinstance(nao_recortar, list):
        nao_recortar = []
    estado = {
        "extras": dados.get("extras", []) if isinstance(dados.get("extras", []), list) else [],
        "ocultas": [str(x).upper() for x in dados.get("ocultas", []) if str(x).strip()],
        "removidas": dados.get("removidas", []) if isinstance(dados.get("removidas", []), list) else [],
        "apelidos": {str(k): str(v).upper() for k, v in apelidos.items() if str(k).strip() and str(v).strip()},
        "nomes_exibicao": {str(k).upper(): str(v).strip() for k, v in nomes.items() if str(k).strip() and str(v).strip()},
        "fechamento": [str(x).upper().strip() for x in fechamento if str(x).strip()],
        "fechamento_inclui_hidrografia": bool(dados.get("fechamento_inclui_hidrografia", False)),
        "nao_recortar": [str(x).upper().strip() for x in nao_recortar if str(x).strip()],
    }
    estado["referencias"] = _normalizar_referencias(dados.get("referencias", []))
    estilos = dados.get("estilos_padrao", {})
    estado["estilos_padrao"] = {str(k).upper(): str(v) for k, v in (estilos.items() if isinstance(estilos, dict) else [])
                                if str(k).strip() and str(v).strip()}
    # v3.9: chaves opcionais da resolução topológica (só gravadas se já existirem no JSON).
    for chave in ("prioridade_fechamento", "prioridade_app", "prioridade_reserva", "prioridade_antropizada"):
        if isinstance(dados.get(chave), list):
            estado[chave] = [str(x).upper().strip() for x in dados[chave] if str(x).strip()]
    if isinstance(dados.get("largura_max_lasca_m"), (int, float)) and not isinstance(dados.get("largura_max_lasca_m"), bool):
        estado["largura_max_lasca_m"] = max(0.0, float(dados["largura_max_lasca_m"]))
    return estado


CATALOGO_EMBUTIDO = os.path.join(PASTA_PADRAO, "catalogo_extra.json")


def _ler_json(caminho):
    with open(caminho, "r", encoding="utf-8") as arq:
        return json.load(arq)


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = caminho + f".tmp.{os.getpid()}"
    try:
        with open(temporario, "w", encoding="utf-8") as arq:
            json.dump(dados, arq, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    finally:
        try:
            if os.path.exists(temporario):
                os.remove(temporario)
        except OSError:
            pass


def _catalogo_embutido():
    """Catálogo de fábrica (pasta padrao/ do plugin): camadas extras e cores padrão do escritório."""
    try:
        return _ler_json(CATALOGO_EMBUTIDO)
    except Exception:
        return _estado_vazio()


def _eh_real(caminho=None):
    """True quando o catálogo em uso é o da pasta dados/ do plugin (e não um arquivo de teste)."""
    return os.path.normcase(os.path.abspath(caminho or CATALOGO_ESCRITORIO)) == os.path.normcase(os.path.abspath(_CAMINHO_REAL))


# ---------------------------------------------------------------- cópia de segurança (perfil do QGIS)
def pasta_copia_seguranca():
    return os.path.join(_pasta_perfil(), "copia_dados")


def guardar_copia_seguranca(caminho):
    """Depois de cada gravação em dados/, guarda uma cópia no perfil do QGIS (sobrevive à reinstalação)."""
    try:
        if not _eh_real(os.path.join(os.path.dirname(caminho), "catalogo_extra.json")):
            return
        destino = os.path.join(pasta_copia_seguranca(), os.path.basename(caminho))
        _gravar_json(destino, _ler_json(caminho))
    except Exception:
        pass


# ---------------------------------------------------------------- migração única da v0.1.x (Drive G:)
def _catalogo_drive_antigo():
    """Arquivo do catálogo no Drive do escritório, se ele estiver acessível agora (só para a migração)."""
    candidatos = []
    try:
        from qgis.core import QgsSettings
        escolhido = str(QgsSettings().value(_CHAVE_CAMINHO_CATALOGO, "") or "").strip().strip('"')
        if escolhido:
            candidatos.append(escolhido if escolhido.lower().endswith(".json") else os.path.join(escolhido, "catalogo_extra.json"))
    except Exception:
        pass
    if os.name == "nt":
        for letra in "GHIJKLMNOPQRSTUVWXYZDEF":
            for raiz in ("Drives compartilhados", "Shared drives"):
                candidatos.append(letra + ":\\" + raiz + "\\" + _REL_CATALOGO)
    for caminho in candidatos:
        try:
            if os.path.isfile(caminho):
                return caminho
        except Exception:
            continue
    return ""


def _migrar_catalogo():
    """Estado inicial do catálogo vindo da versão antiga: Drive (se acessível) + o que ficou salvo só neste
    computador quando o Drive estava fora + cores padrão guardadas no QGIS. None se não há nada antigo."""
    estado = None
    drive = _catalogo_drive_antigo()
    if drive:
        try:
            estado = _normalizar_estado(_ler_json(drive))
        except Exception:
            estado = None
    local = None
    try:
        local = _ler_json(os.path.join(_pasta_perfil(), "catalogo_local.json"))
        if not isinstance(local, dict) or not isinstance(local.get("estado"), (dict, list)):
            local = None
    except Exception:
        local = None
    if local:
        if estado is None:
            estado = _normalizar_estado(local["estado"])
        elif local.get("pendente"):
            _aplicar_diferencas(_normalizar_estado(local.get("base") or {}), _normalizar_estado(local["estado"]), estado)
            estado = _normalizar_estado(estado)
    cores = _estilos_locais()
    if cores:
        estado = estado if estado is not None else _normalizar_estado(_catalogo_embutido())
        estado.setdefault("estilos_padrao", {}).update(cores)
    return estado


def _modelos_drive_antigo():
    drive = _catalogo_drive_antigo()
    if not drive:
        return None
    try:
        return _ler_json(os.path.join(os.path.dirname(drive), "modelos_norteagro.json"))
    except Exception:
        return None


def preparar_dados():
    """Garante que a pasta dados/ do plugin tem os arquivos. Ordem: cópia de segurança (reinstalação),
    dados da versão antiga (Drive / este computador), padrão de fábrica."""
    if not _eh_real():
        return
    for nome in ARQUIVOS_DADOS:
        destino = os.path.join(PASTA_DADOS, nome)
        if os.path.isfile(destino):
            continue
        dados = None
        try:
            copia = os.path.join(pasta_copia_seguranca(), nome)
            if os.path.isfile(copia):
                dados = _ler_json(copia)
        except Exception:
            dados = None
        if dados is None:
            try:
                dados = _migrar_catalogo() if nome == "catalogo_extra.json" else _modelos_drive_antigo()
            except Exception:
                dados = None
        if dados is None:
            try:
                dados = _ler_json(os.path.join(PASTA_PADRAO, nome))
            except Exception:
                dados = _estado_vazio() if nome == "catalogo_extra.json" else {"pastas": [], "temas_cores": [], "tabelas": []}
        try:
            _gravar_json(destino, dados)
            guardar_copia_seguranca(destino)
        except Exception:
            pass
    if _estilos_locais():
        try:
            from qgis.core import QgsSettings
            QgsSettings().remove(_CHAVE_ESTILOS_LOCAIS)   # já foram para dados/catalogo_extra.json
        except Exception:
            pass


def _chave_item(chave_lista, item):
    if chave_lista == "referencias":
        return normalizar_chave(item.get("nome", "") if isinstance(item, dict) else item)
    if isinstance(item, dict):
        return str(item.get("arquivo") or item.get("nome") or "").upper()
    return str(item).upper()


_LISTAS_POR_ITEM = {"extras", "removidas", "referencias", "ocultas"}
_DICIONARIOS = {"apelidos", "nomes_exibicao", "estilos_padrao"}


def _aplicar_diferencas(base, meu, alvo):
    """Aplica em `alvo` só o que mudou de `base` para `meu` (usado na migração das alterações antigas)."""
    for chave in set(base) | set(meu):
        b, m = base.get(chave), meu.get(chave)
        if json.dumps(b, sort_keys=True, ensure_ascii=False) == json.dumps(m, sort_keys=True, ensure_ascii=False):
            continue
        if chave in _DICIONARIOS:
            b = b if isinstance(b, dict) else {}; m = m if isinstance(m, dict) else {}
            destino = alvo.get(chave) if isinstance(alvo.get(chave), dict) else {}
            for k, v in m.items():
                if b.get(k) != v:
                    if chave == "apelidos":  # um apelido novo substitui o antigo de mesma chave
                        for antigo in [x for x in destino if normalizar_chave(x) == normalizar_chave(k)]:
                            destino.pop(antigo, None)
                    destino[k] = v
            for k in b:
                if k not in m:
                    destino.pop(k, None)
            alvo[chave] = destino
        elif chave in _LISTAS_POR_ITEM:
            b = b if isinstance(b, list) else []; m = m if isinstance(m, list) else []
            bi = {_chave_item(chave, x): x for x in b}; mi = {_chave_item(chave, x): x for x in m}
            destino = list(alvo.get(chave) or [])
            for k, item in mi.items():
                if k not in bi or bi[k] != item:
                    pos = next((i for i, y in enumerate(destino) if _chave_item(chave, y) == k), None)
                    if pos is None:
                        destino.append(item)
                    else:
                        destino[pos] = item
            for k in bi:
                if k not in mi:
                    destino = [y for y in destino if _chave_item(chave, y) != k]
            alvo[chave] = destino
        else:
            alvo[chave] = m
    return alvo


# Mantidas para as telas antigas: agora tudo é gravado no próprio plugin, nunca "só neste computador".
def ultima_gravacao_foi_local():
    return False


def texto_gravacao_local():
    return ""


def situacao_catalogo():
    return {"acessivel": True, "caminho": CATALOGO_ESCRITORIO, "pendente": False, "arquivo_local": CATALOGO_ESCRITORIO}


_CACHE_CHAVE = None


def _chave_arquivo():
    """Caminho + data de modificação do catálogo: se outro módulo/janela gravou, o cache é refeito."""
    try:
        return (CATALOGO_ESCRITORIO, os.path.getmtime(CATALOGO_ESCRITORIO), os.path.getsize(CATALOGO_ESCRITORIO))
    except OSError:
        return (CATALOGO_ESCRITORIO, None, None)


def _definir_cache(estado):
    global _CACHE_ESCRITORIO, _CACHE_CHAVE
    _CACHE_ESCRITORIO = estado
    _CACHE_CHAVE = _chave_arquivo() if estado is not None else None


def estado_catalogo_escritorio(forcar=False):
    """Lê o catálogo da pasta dados/ do plugin (cacheado enquanto o arquivo não muda)."""
    if _CACHE_ESCRITORIO is not None and not forcar and _CACHE_CHAVE == _chave_arquivo():
        return json.loads(json.dumps(_CACHE_ESCRITORIO, ensure_ascii=False))
    preparar_dados()
    try:
        if os.path.isfile(CATALOGO_ESCRITORIO):
            estado = _normalizar_estado(_ler_json(CATALOGO_ESCRITORIO))
        else:
            estado = _normalizar_estado(_catalogo_embutido())
    except Exception:
        # arquivo estragado: usa a cópia de segurança (ou o de fábrica) só para leitura
        try:
            estado = _normalizar_estado(_ler_json(os.path.join(pasta_copia_seguranca(), "catalogo_extra.json")))
        except Exception:
            estado = _normalizar_estado(_catalogo_embutido())
    _definir_cache(estado)
    return json.loads(json.dumps(estado, ensure_ascii=False))


def _autor_atual():
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "desconhecido"


def _gravar_catalogo_alteracao(mutador, permitir_local=True):
    """Relê o catálogo, aplica só a alteração pedida e grava na pasta dados/ do plugin (+ cópia de segurança)."""
    preparar_dados()
    caminho = CATALOGO_ESCRITORIO
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    lock = caminho + ".lock"; fd = None
    for _ in range(50):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time()}".encode("ascii", "ignore")); break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 30:
                    os.remove(lock); continue
            except OSError:
                pass
            time.sleep(0.1)
    if fd is None:
        raise TimeoutError("O catálogo está sendo gravado por outra janela do QGIS. Tente novamente em alguns segundos.")
    try:
        if os.path.isfile(caminho):
            try:
                estado = _normalizar_estado(_ler_json(caminho))
            except Exception:
                copia = os.path.join(pasta_copia_seguranca(), "catalogo_extra.json")
                estado = _normalizar_estado(_ler_json(copia) if os.path.isfile(copia) else _catalogo_embutido())
        else:
            estado = _normalizar_estado(_catalogo_embutido()) if _eh_real() else _estado_vazio()
        mutador(estado)
        _gravar_json(caminho, estado)
        guardar_copia_seguranca(caminho)
        _definir_cache(estado)
        return json.loads(json.dumps(estado, ensure_ascii=False))
    finally:
        try:
            if fd is not None: os.close(fd)
        except OSError: pass
        try: os.remove(lock)
        except OSError: pass


def _fixos_por_arquivo():
    return {x["arquivo"]: x for x in catalogo_fixo_lista()}


# v3.9.6: onde uma camada personalizada (polígono) entra no Quadro de Áreas.
# (código, texto da tela, quadro da planilha, explicação curta)
LUGARES_QUADRO = [
    ("IMOVEL", "Áreas Totais do Imóvel (classe de uso do solo)", "Áreas Totais do Imóvel",
     "Entra na soma que fecha com a Área Total do Imóvel. Onde ela se sobrepuser a outra classe, a área fica com a classe padrão e a sobreposição é avisada."),
    ("PASSIVOS", "Passivos ambientais", "Passivos ambientais",
     "Vira uma linha a mais no quadro Passivos ambientais. A parte que já estiver em outra linha desse quadro é descontada."),
    ("HIDRO", "Área Hidrográfica", "Área Hidrográfica",
     "Vira uma linha a mais no quadro Área Hidrográfica. A parte que já estiver em outra linha desse quadro é descontada."),
    ("COMPENSACAO", "Área Total de Compensação", "Área Total de Compensação",
     "Vira uma linha a mais no quadro Área Total de Compensação. A parte que já estiver em outra linha desse quadro é descontada."),
    ("OUTRAS", "Outras camadas (quadro próprio, sem total)", "Outras camadas",
     "Aparece no quadro Outras camadas, no fim do Quadro de Áreas, com a área dentro do imóvel. Não soma com nada."),
    ("NENHUM", "Não entra no Quadro de Áreas", "",
     "É calculada e aparece só na aba Todas as camadas."),
]
CODIGOS_LUGAR_QUADRO = [x[0] for x in LUGARES_QUADRO]
QUADRO_DO_LUGAR = {x[0]: x[2] for x in LUGARES_QUADRO}
EXPLICACAO_LUGAR = {x[0]: x[3] for x in LUGARES_QUADRO}


def lugar_quadro(entrada):
    """Lugar no quadro de uma entrada do catálogo. Camadas fixas não usam este campo
    (devolve ""); personalizadas antigas, sem o campo, continuam em Outras camadas."""
    if not entrada or not entrada.get("personalizada"):
        return ""
    if str(entrada.get("tipo") or "P") != "P":
        return "NENHUM"
    cod = str(entrada.get("quadro") or "").upper()
    return cod if cod in CODIGOS_LUGAR_QUADRO else "OUTRAS"


def definir_lugar_quadro_escritorio(arquivo, codigo):
    """Altera só o lugar no quadro de uma camada já catalogada no escritório."""
    arquivo = normalizar_arquivo(arquivo); codigo = str(codigo or "").upper()
    if codigo not in CODIGOS_LUGAR_QUADRO:
        raise ValueError("Lugar no quadro inválido.")
    def alterar(estado):
        for x in estado["extras"]:
            if str(x.get("arquivo", "")).upper() == arquivo:
                x["quadro"] = codigo; x["autor_quadro"] = _autor_atual()
                x["data_quadro"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return
        raise ValueError(f"{arquivo} não está no catálogo do escritório.")
    _gravar_catalogo_alteracao(alterar)


def catalogar_escritorio(entrada):
    """Adiciona uma camada personalizada ao catálogo compartilhado, nunca automaticamente."""
    arquivo = normalizar_arquivo(str(entrada.get("arquivo") or entrada.get("nome") or ""))
    if not arquivo:
        raise ValueError("ARQUIVO inválido.")
    if arquivo in _fixos_por_arquivo():
        raise ValueError("Este ARQUIVO pertence ao catálogo fixo. Use 'Restaurar removidas' se necessário.")
    novo = {
        "nome": str(entrada.get("nome") or arquivo),
        "arquivo": arquivo,
        "tipo": str(entrada.get("tipo") or "P"),
        "grupo": str(entrada.get("grupo") or "Uso do Solo"),
        "estilo": str(entrada.get("estilo_xml") or entrada.get("estilo") or ""),
        "quadro": (str(entrada.get("quadro") or "").upper() if str(entrada.get("quadro") or "").upper() in CODIGOS_LUGAR_QUADRO else "OUTRAS"),
        "autor": _autor_atual(),
        "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    def alterar(estado):
        if any(str(x.get("arquivo", "")).upper() == arquivo for x in estado["extras"]):
            raise ValueError(f"{arquivo} já existe no catálogo do escritório.")
        estado["removidas"] = [x for x in estado["removidas"] if str(x.get("arquivo", "")).upper() != arquivo]
        estado["extras"].append(novo)
    _gravar_catalogo_alteracao(alterar)
    return novo


def remover_catalogo_escritorio(arquivo):
    """Oculta fixas ou move extras para 'removidas'. Nunca apaga dados de projeto."""
    arquivo = str(arquivo or "").upper()
    fixos = _fixos_por_arquivo()
    def alterar(estado):
        if arquivo in fixos:
            if arquivo not in estado["ocultas"]:
                estado["ocultas"].append(arquivo)
            return
        achados = [x for x in estado["extras"] if str(x.get("arquivo", "")).upper() == arquivo]
        if not achados:
            raise ValueError("A camada não está no catálogo do escritório.")
        entrada = achados[-1]
        estado["extras"] = [x for x in estado["extras"] if str(x.get("arquivo", "")).upper() != arquivo]
        estado["removidas"] = [x for x in estado["removidas"] if str(x.get("arquivo", "")).upper() != arquivo]
        entrada = dict(entrada); entrada["removida_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        estado["removidas"].append(entrada)
    return _gravar_catalogo_alteracao(alterar)


def itens_removidos_escritorio():
    """Lista fixas ocultas e extras removidas para a tela de restauração."""
    estado = estado_catalogo_escritorio(forcar=True)
    fixos = {x["arquivo"]: x for x in catalogo_fixo_lista(estado.get("nomes_exibicao", {}))}
    saida = []
    for arquivo in estado["ocultas"]:
        if arquivo in fixos:
            item = dict(fixos[arquivo]); item["classe_removida"] = "fixa"; saida.append(item)
    for entrada in estado["removidas"]:
        item = dict(entrada); item["classe_removida"] = "extra"; saida.append(item)
    return saida


def restaurar_catalogo_escritorio(arquivos):
    """Restaura fixas ocultas e/ou extras removidas selecionadas pelo usuário."""
    alvos = {str(x).upper() for x in arquivos}
    def alterar(estado):
        estado["ocultas"] = [x for x in estado["ocultas"] if str(x).upper() not in alvos]
        manter = []; restaurar = []
        for entrada in estado["removidas"]:
            if str(entrada.get("arquivo", "")).upper() in alvos:
                restaurar.append(dict(entrada))
            else:
                manter.append(entrada)
        existentes = {str(x.get("arquivo", "")).upper() for x in estado["extras"]}
        for entrada in restaurar:
            arquivo = str(entrada.get("arquivo", "")).upper()
            entrada.pop("removida_em", None)
            if arquivo and arquivo not in existentes:
                estado["extras"].append(entrada); existentes.add(arquivo)
        estado["removidas"] = manter
    return _gravar_catalogo_alteracao(alterar)


def arquivos_catalogados_escritorio():
    """Conjunto usado para filtrar o diálogo '+ Adicionar ao catálogo'."""
    estado = estado_catalogo_escritorio()
    fixos = set(_fixos_por_arquivo())
    extras = {str(x.get("arquivo", "")).upper() for x in estado["extras"]}
    return fixos | extras


def catalogo_completo(projeto):
    """Fixo - ocultas + extras do escritório + extras exclusivos deste projeto."""
    estado = estado_catalogo_escritorio()
    ocultas = set(estado["ocultas"])
    base_toda = catalogo_fixo_lista(estado.get("nomes_exibicao", {}))
    base = [x for x in base_toda if x["arquivo"] not in ocultas]
    mapa = {x["arquivo"]: dict(x, origem="fixa") for x in base}
    ordem_grupos = list(GRUPOS_BASE)

    # Primeiro entram os extras compartilhados.
    for item in estado["extras"]:
        try:
            arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
            if not arquivo or arquivo in _fixos_por_arquivo():
                continue
            grupo = str(item.get("grupo") or "Uso do Solo").strip() or "Uso do Solo"
            if grupo not in ordem_grupos: ordem_grupos.append(grupo)
            entrada = dict(item)
            nome = str(estado.get("nomes_exibicao", {}).get(arquivo) or item.get("nome") or arquivo)
            entrada.update({
                "arquivo": arquivo, "nome": nome, "nome_exibicao": nome,
                "tipo": str(item.get("tipo") or "P"), "grupo": grupo,
                "personalizada": True, "origem": "catalogada",
                "estilo_xml": str(item.get("estilo_xml") or item.get("estilo") or ""),
                "pasta_camada": limpar_nome_pasta(nome),
            })
            entrada.setdefault("ordem", 10000 + len(mapa))
            mapa[arquivo] = entrada
        except Exception:
            continue

    # Extras do projeto só aparecem se não houver uma versão fixa visível/catalogada.
    for item in extras_projeto(projeto):
        try:
            arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
            if not arquivo or arquivo in mapa:
                continue
            grupo = str(item.get("grupo") or "Uso do Solo").strip() or "Uso do Solo"
            if grupo not in ordem_grupos: ordem_grupos.append(grupo)
            entrada = dict(item)
            nome = str(item.get("nome") or arquivo)
            entrada.update({
                "arquivo": arquivo, "nome": nome, "nome_exibicao": nome,
                "tipo": str(item.get("tipo") or "P"), "grupo": grupo,
                "personalizada": True, "origem": "projeto", "pasta_camada": limpar_nome_pasta(nome),
            })
            entrada.setdefault("estilo_xml", ""); entrada.setdefault("ordem", 10000 + len(mapa))
            mapa[arquivo] = entrada
        except Exception:
            continue

    grupos = {g: [] for g in ordem_grupos}
    fixos_ordem = {x["arquivo"]: i for i, x in enumerate(base_toda)}
    for entrada in mapa.values():
        grupos.setdefault(entrada["grupo"], []).append(entrada)
    for grupo, itens in grupos.items():
        itens.sort(key=lambda x: (
            0 if x.get("origem") == "fixa" else 1,
            fixos_ordem.get(x["arquivo"], int(x.get("ordem", 99999))),
            x["nome"].casefold(),
        ))
    return grupos

def indice_catalogo(projeto):
    return {item["arquivo"]: item for itens in catalogo_completo(projeto).values() for item in itens}



def indice_reconhecimento(projeto):
    """Índice para cálculo: todas as fixas + extras catalogadas + extras do projeto."""
    estado = estado_catalogo_escritorio()
    mapa = {x["arquivo"]: dict(x) for x in catalogo_fixo_lista(estado.get("nomes_exibicao", {}))}
    for item in estado["extras"]:
        try:
            arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
            if not arquivo:
                continue
            entrada = dict(item)
            nome = str(estado.get("nomes_exibicao", {}).get(arquivo) or item.get("nome") or arquivo)
            entrada.update({
                "arquivo": arquivo, "nome": nome, "nome_exibicao": nome,
                "tipo": str(item.get("tipo") or "P"),
                "grupo": str(item.get("grupo") or "Uso do Solo"),
                "personalizada": True, "origem": "catalogada",
                "estilo_xml": str(item.get("estilo_xml") or item.get("estilo") or ""),
                "pasta_camada": limpar_nome_pasta(nome),
            })
            mapa[arquivo] = entrada
        except Exception:
            continue
    if projeto is not None:
        for item in extras_projeto(projeto):
            try:
                arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
                if not arquivo or arquivo in mapa:
                    continue
                entrada = dict(item)
                nome = str(item.get("nome") or arquivo)
                entrada.update({
                    "arquivo": arquivo, "nome": nome, "nome_exibicao": nome,
                    "tipo": str(item.get("tipo") or "P"),
                    "grupo": str(item.get("grupo") or "Uso do Solo"),
                    "personalizada": True, "origem": "projeto",
                    "pasta_camada": limpar_nome_pasta(nome),
                })
                mapa[arquivo] = entrada
            except Exception:
                continue
        # v3.9.6: camada personalizada criada em "Criar camadas em uma pasta" não entra nos extras
        # do projeto (aquele modo não altera o projeto); a definição fica gravada na própria camada.
        for camada in projeto.mapLayers().values():
            try:
                bruto = camada.customProperty("norteagro/definicao", "")
                if not bruto:
                    continue
                item = json.loads(str(bruto))
                arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
                if not arquivo or arquivo in mapa:
                    continue
                nome = str(item.get("nome") or arquivo)
                entrada = dict(item)
                entrada.update({
                    "arquivo": arquivo, "nome": nome, "nome_exibicao": nome,
                    "tipo": str(item.get("tipo") or "P"), "grupo": str(item.get("grupo") or "Uso do Solo"),
                    "personalizada": True, "origem": "camada", "pasta_camada": limpar_nome_pasta(nome),
                })
                mapa[arquivo] = entrada
            except Exception:
                continue
    return mapa


def apelidos_manuais_projeto(projeto):
    """Lê mapeamentos manuais salvos apenas no .qgz atual."""
    escopo = QgsExpressionContextUtils.projectScope(projeto)
    bruto = str(escopo.variable("norteagro_apelidos") or "{}")
    try:
        dados = json.loads(bruto)
        return {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
    except Exception:
        return {}


def salvar_apelidos_manuais_projeto(projeto, apelidos):
    QgsExpressionContextUtils.setProjectVariable(
        projeto, "norteagro_apelidos", json.dumps(apelidos or {}, ensure_ascii=False)
    )
    projeto.setDirty(True)


def apelidos_para_indice(indice):
    """Mescla padrão, nome de exibição atual, extras futuros e aliases do escritório."""
    tabela = {}
    for arquivo, entrada in indice.items():
        valores = set(APELIDOS_PADRAO.get(arquivo, []))
        # Importante: nomes_exibicao do JSON têm prioridade e precisam virar alias sem reiniciar o QGIS.
        valores.update(gerar_apelidos_padrao([entrada]).get(arquivo, []))
        tabela[arquivo] = sorted(x for x in valores if x)
    estado = estado_catalogo_escritorio()
    idx, ambiguos = indice_apelidos(
        tabela, estado.get("apelidos", {}), arquivos_validos=set(indice)
    )
    return tabela, idx, ambiguos


def salvar_apelido_escritorio(apelido, arquivo, indice=None):
    """Grava alias explícito nome -> ARQUIVO, relendo o JSON sob lock antes de salvar."""
    alias = str(apelido or "").strip()
    destino = str(arquivo or "").upper().strip()
    if not alias or not destino:
        raise ValueError("Apelido e destino são obrigatórios.")
    if indice is None:
        validos = set(_fixos_por_arquivo())
        validos |= {str(x.get("arquivo", "")).upper() for x in estado_catalogo_escritorio().get("extras", [])}
    else:
        validos = set(indice)
    if destino not in validos:
        raise ValueError(f"O destino {destino} não existe no catálogo.")
    chave = normalizar_chave(alias)
    if not chave:
        raise ValueError("O apelido não gera uma chave válida.")

    tabela = {}
    for arq in validos:
        if arq in APELIDOS_PADRAO:
            tabela[arq] = list(APELIDOS_PADRAO[arq])
        elif indice and arq in indice:
            tabela[arq] = gerar_apelidos_padrao([indice[arq]]).get(arq, [])
        else:
            tabela[arq] = []
    def sem_mesma_chave(aliases):
        # v0.1.1: cadastrar de novo o mesmo nome (com outra grafia) troca o destino em vez de dar conflito.
        return {k: v for k, v in aliases.items() if normalizar_chave(k) != chave}

    atual = estado_catalogo_escritorio(forcar=True)
    teste_alias = sem_mesma_chave(dict(atual.get("apelidos", {}))); teste_alias[alias] = destino
    _, ambiguos = indice_apelidos(tabela, teste_alias, arquivos_validos=validos)
    if chave in ambiguos:
        nomes = [str((indice or {}).get(a, {}).get("nome") or a) for a in ambiguos[chave]]
        raise ValueError("Este nome já é usado automaticamente por outra camada do catálogo ("
                         + ", ".join(nomes) + "). Use um nome mais completo.")

    def alterar(estado):
        aliases = sem_mesma_chave(dict(estado.get("apelidos", {})))
        teste = dict(aliases); teste[alias] = destino
        _, conflitos = indice_apelidos(tabela, teste, arquivos_validos=validos)
        if chave in conflitos:
            raise ValueError("Este apelido ficou ambíguo porque o catálogo foi alterado por outro usuário.")
        aliases[alias] = destino
        estado["apelidos"] = aliases
    _gravar_catalogo_alteracao(alterar)
    return alias, destino


def apelidos_escritorio(forcar=False):
    """Nome da camada -> ARQUIVO ensinados pelos usuários (catálogo do escritório)."""
    try:
        return dict(estado_catalogo_escritorio(forcar).get("apelidos", {}))
    except Exception:
        return {}


def remover_apelido_escritorio(apelido):
    chave = normalizar_chave(apelido)
    def alterar(estado):
        aliases = dict(estado.get("apelidos", {}))
        alvos = [k for k in aliases if k == apelido or normalizar_chave(k) == chave]
        if not alvos:
            raise ValueError("Este nome não está na lista do escritório.")
        for k in alvos:
            aliases.pop(k, None)
        estado["apelidos"] = aliases
    return _gravar_catalogo_alteracao(alterar)


def referencias_escritorio(forcar=False):
    """Nomes de camadas de referência do escritório (não entram no cálculo)."""
    try:
        return list(estado_catalogo_escritorio(forcar).get("referencias", []))
    except Exception:
        return []


def _palavras(texto):
    return {x for x in normalizar_chave(texto).split("_") if x}


def conflito_referencia_catalogo(nome, indice=None):
    """Retorna a camada do catálogo que o nome derrubaria (palavra genérica), ou ""."""
    palavras = _palavras(nome)
    if not palavras:
        return "nome vazio"
    indice = indice if indice is not None else indice_reconhecimento(None)
    tabela, alias_indice, _ = apelidos_para_indice(indice)
    candidatos = {}
    for arq, entrada in indice.items():
        for texto in (arq, entrada.get("nome", "")):
            candidatos.setdefault(normalizar_chave(texto), arq)
    for chave, arq in (alias_indice or {}).items():
        candidatos.setdefault(chave, arq)
    for chave, arq in candidatos.items():
        tk = {x for x in chave.split("_") if x}
        if tk and palavras <= tk:
            return arq
    return ""


def adicionar_referencia_escritorio(nome, indice=None):
    """Grava um nome na lista de referências do catálogo compartilhado (com lock)."""
    nome = str(nome or "").strip()
    chave = normalizar_chave(nome)
    if not nome or not chave:
        raise ValueError("Informe o nome da camada de referência.")
    conflito = conflito_referencia_catalogo(nome, indice)
    if conflito:
        entrada = (indice or indice_reconhecimento(None)).get(conflito, {})
        raise ValueError(f"\"{nome}\" é genérico demais: também faz parte do nome da camada do catálogo "
                         f"\"{entrada.get('nome', conflito)}\". Use um nome mais específico.")
    novo = {"nome": nome, "autor": _autor_atual(), "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    def alterar(estado):
        lista = _normalizar_referencias(estado.get("referencias", []))
        if any(normalizar_chave(x["nome"]) == chave for x in lista):
            raise ValueError(f"\"{nome}\" já está na lista de referências.")
        lista.append(novo); estado["referencias"] = lista
    _gravar_catalogo_alteracao(alterar)
    return novo


def remover_referencia_escritorio(nome):
    chave = normalizar_chave(nome)
    def alterar(estado):
        lista = _normalizar_referencias(estado.get("referencias", []))
        if not any(normalizar_chave(x["nome"]) == chave for x in lista):
            raise ValueError("Este nome não está na lista de referências.")
        estado["referencias"] = [x for x in lista if normalizar_chave(x["nome"]) != chave]
    return _gravar_catalogo_alteracao(alterar)


# ---------------------------------------------------------------- cor padrão editada pelo usuário
_CHAVE_ESTILOS_LOCAIS = "norteagro_uso_solo/estilos_padrao"


def _estilos_locais():
    """Cores padrão que a versão antiga guardava no QGIS quando o Drive estava fora (migradas para dados/)."""
    try:
        from qgis.core import QgsSettings
        dados = json.loads(str(QgsSettings().value(_CHAVE_ESTILOS_LOCAIS, "{}") or "{}"))
        return {str(k).upper(): str(v) for k, v in dados.items() if str(v).strip()} if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _gravar_estilos_locais(estilos):
    from qgis.core import QgsSettings
    QgsSettings().setValue(_CHAVE_ESTILOS_LOCAIS, json.dumps(estilos, ensure_ascii=False))


def estilos_padrao_ativos():
    """ARQUIVO -> símbolo (XML) escolhido como cor padrão (catálogo do plugin)."""
    estilos = dict(estado_catalogo_escritorio().get("estilos_padrao", {}))
    estilos.update(_estilos_locais())
    return estilos


def salvar_estilo_padrao(arquivo, xml):
    """Grava a nova cor padrão da camada no catálogo do plugin (pasta dados/)."""
    arquivo = str(arquivo).upper()

    def alterar(estado):
        estado.setdefault("estilos_padrao", {})[arquivo] = xml
    _gravar_catalogo_alteracao(alterar)
    locais = _estilos_locais()
    if locais.pop(arquivo, None) is not None:
        _gravar_estilos_locais(locais)
    return "escritorio"


def remover_estilo_padrao(arquivo):
    """Volta a camada para a cor original do plugin."""
    arquivo = str(arquivo).upper()
    locais = _estilos_locais()
    if locais.pop(arquivo, None) is not None:
        _gravar_estilos_locais(locais)
    if arquivo in estado_catalogo_escritorio().get("estilos_padrao", {}):
        _gravar_catalogo_alteracao(lambda estado: estado.setdefault("estilos_padrao", {}).pop(arquivo, None))


def simbolo_entrada(entrada):
    """Retorna um clone seguro do símbolo da entrada fixa ou personalizada.
    A cor padrão escolhida pelo usuário (estilos_padrao) tem prioridade."""
    personalizado = estilos_padrao_ativos().get(str(entrada.get("arquivo", "")).upper())
    simb = simbolo_de_xml(personalizado) if personalizado else None
    if simb:
        return simb
    simb = simbolo_de_xml(entrada.get("estilo_xml", "")) if entrada.get("estilo_xml") else None
    if simb:
        return simb
    return simbolo_notacao(
        entrada["tipo"], entrada.get("preenchimento", "sem"), entrada.get("contorno", "#232323/0.3")
    )


def catalogo_avulsa(projeto):
    """Catálogo disponível fora da pasta do mapa: fixas visíveis + extras catalogadas."""
    saida = {}
    for grupo, itens in catalogo_completo(projeto).items():
        filtrados = [dict(x) for x in itens if x.get("origem") in ("fixa", "catalogada")]
        if filtrados:
            saida[grupo] = filtrados
    return saida


def indice_catalogo_avulsa(projeto):
    """Índice das camadas do escritório que podem ser criadas em qualquer pasta."""
    return {item["arquivo"]: item for itens in catalogo_avulsa(projeto).values() for item in itens}


def nomes_exibicao_ativos(estado=None):
    """Tabela ARQUIVO -> nome de exibição; o JSON compartilhado tem prioridade."""
    estado = estado if isinstance(estado, dict) else estado_catalogo_escritorio()
    nomes = dict(NOMES_EXIBICAO)
    for item in estado.get("extras", []):
        arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
        if arquivo:
            nomes[arquivo] = str(item.get("nome") or arquivo).strip()
    for arquivo, nome in estado.get("nomes_exibicao", {}).items():
        if str(nome).strip():
            nomes[str(arquivo).upper()] = str(nome).strip()
    return nomes


def itens_planilha_sem_camada(estado=None):
    """Itens oficiais da Planilha de Padronização que ainda não têm ARQUIVO no catálogo."""
    nomes = nomes_exibicao_ativos(estado)
    chaves = {normalizar_chave(v) for v in nomes.values()}
    return [x for x in ITENS_PLANILHA_PADRONIZACAO if normalizar_chave(x) not in chaves]


def camadas_sem_nome_planilha():
    """Fixas sem correspondência oficial; devem usar fallback e ser informadas ao usuário."""
    return [x[0] for itens in CATALOGO_FIXO.values() for x in itens if x[0] not in NOMES_EXIBICAO]


def configuracao_geometrica(estado=None):
    """Configuração compartilhada da conferência geométrica, sem criar variáveis no projeto."""
    if estado is None:
        estado = estado_catalogo_escritorio() if QGIS_DISPONIVEL else _estado_vazio()
    estado = _normalizar_estado(estado)
    fechamento = list(estado.get("fechamento", FECHAMENTO_PADRAO))
    if estado.get("fechamento_inclui_hidrografia") and "HIDROGRAFIA" not in fechamento:
        fechamento.append("HIDROGRAFIA")
    return {
        "fechamento": fechamento,
        "fechamento_inclui_hidrografia": bool(estado.get("fechamento_inclui_hidrografia", False)),
        "nao_recortar": list(estado.get("nao_recortar") or []),
        # v3.9: prioridades da resolução topológica do quadro (vazio = padrão do plugin).
        "prioridade_fechamento": list(estado.get("prioridade_fechamento") or []),
        "prioridade_app": list(estado.get("prioridade_app") or []),
        "prioridade_reserva": list(estado.get("prioridade_reserva") or []),
        "prioridade_antropizada": list(estado.get("prioridade_antropizada") or []),
        "largura_max_lasca_m": float(estado.get("largura_max_lasca_m", 0.5)),
    }


def verificar_catalogo(projeto=None, estado=None):
    """Audita nomes, pastas, estilos e referências internas sem impedir a abertura do plugin.

    Retorna ``{"problemas": [...], "invalidos": set(...)}``. Quando chamado fora do
    QGIS, use ``projeto=None`` e um estado explícito ou o estado vazio.
    """
    if estado is None:
        estado = estado_catalogo_escritorio() if QGIS_DISPONIVEL else _estado_vazio()
    estado = _normalizar_estado(estado)
    problemas = []
    invalidos = set()

    fixos = {x["arquivo"]: x for x in catalogo_fixo_lista(estado.get("nomes_exibicao", {}))}
    extras = {}
    for item in estado.get("extras", []):
        arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
        if not arquivo:
            problemas.append("Extra do catálogo sem ARQUIVO válido.")
            continue
        nome = str(estado.get("nomes_exibicao", {}).get(arquivo) or item.get("nome") or arquivo).strip()
        extras[arquivo] = {
            "arquivo": arquivo, "nome": nome, "grupo": str(item.get("grupo") or "Uso do Solo"),
            "tipo": str(item.get("tipo") or "P"),
            "estilo_xml": str(item.get("estilo_xml") or item.get("estilo") or ""),
            "pasta_camada": limpar_nome_pasta(nome),
        }
    ativos = dict(fixos); ativos.update(extras)

    # Extras locais entram na checagem de colisão de nomes/pastas, mas não no catálogo compartilhado.
    if projeto is not None and QGIS_DISPONIVEL:
        for item in extras_projeto(projeto):
            arquivo = normalizar_arquivo(str(item.get("arquivo") or item.get("nome") or ""))
            if arquivo and arquivo not in ativos:
                nome = str(item.get("nome") or arquivo).strip()
                ativos[arquivo] = dict(item, arquivo=arquivo, nome=nome, pasta_camada=limpar_nome_pasta(nome))

    nomes = {}
    pastas = {}
    for arquivo, entrada in ativos.items():
        nome = str(entrada.get("nome") or "").strip()
        if not nome:
            problemas.append(f"{arquivo}: sem nome de exibição."); invalidos.add(arquivo); continue
        chave_nome = normalizar_chave(nome)
        nomes.setdefault(chave_nome, []).append(arquivo)
        pasta = limpar_nome_pasta(nome)
        pastas.setdefault(normalizar_chave(pasta), []).append(arquivo)
        if entrada.get("origem") == "fixa":
            pass
        elif arquivo in extras and not str(entrada.get("estilo_xml") or "").strip():
            problemas.append(f"{arquivo}: extra catalogada sem estilo XML."); invalidos.add(arquivo)

    for chave, arquivos in nomes.items():
        if chave and len(arquivos) > 1:
            problemas.append("Nome de exibição repetido: " + ", ".join(sorted(arquivos)))
            invalidos.update(arquivos)
    for chave, arquivos in pastas.items():
        if chave and len(arquivos) > 1:
            problemas.append("Pasta da camada repetida após limpeza: " + ", ".join(sorted(arquivos)))
            invalidos.update(arquivos)

    validos_definidos = set(fixos) | set(extras)
    removidos = {normalizar_arquivo(str(x.get("arquivo") or x.get("nome") or "")) for x in estado.get("removidas", [])}
    # Um extra removido pode não estar mais em "extras"; ele é válido se possuir definição mínima própria.
    removidos_definidos = {
        normalizar_arquivo(str(x.get("arquivo") or x.get("nome") or ""))
        for x in estado.get("removidas", [])
        if str(x.get("arquivo") or x.get("nome") or "").strip()
    }
    validos_historicos = validos_definidos | removidos_definidos
    faltantes_logica = sorted(ARQUIVOS_LOGICA - validos_definidos)
    if faltantes_logica:
        problemas.append("ARQUIVO(s) usados na lógica e ausentes do catálogo: " + ", ".join(faltantes_logica))
        invalidos.update(faltantes_logica)

    for alias, destino in estado.get("apelidos", {}).items():
        if str(destino).upper() not in validos_definidos:
            problemas.append(f"Apelido '{alias}' aponta para ARQUIVO inexistente: {destino}.")
    for arquivo in estado.get("nomes_exibicao", {}):
        if str(arquivo).upper() not in validos_definidos:
            problemas.append(f"nomes_exibicao cita ARQUIVO inexistente: {arquivo}.")
    for arquivo in estado.get("ocultas", []):
        if str(arquivo).upper() not in fixos:
            problemas.append(f"ocultas cita ARQUIVO fixo inexistente: {arquivo}.")
    for arquivo in removidos:
        if arquivo and arquivo not in validos_historicos:
            problemas.append(f"removidas cita ARQUIVO inexistente: {arquivo}.")

    fechamento = list(estado.get("fechamento", FECHAMENTO_PADRAO))
    for arquivo in fechamento:
        arq = str(arquivo).upper()
        if arq not in validos_definidos:
            problemas.append(f"fechamento cita ARQUIVO inexistente: {arquivo}.")
            invalidos.add(arq)
        elif arq in ativos and str(ativos[arq].get("tipo") or "") != "P":
            problemas.append(f"fechamento cita camada que não é poligonal: {arq}.")
            invalidos.add(arq)
    if estado.get("fechamento_inclui_hidrografia") and "HIDROGRAFIA" not in validos_definidos:
        problemas.append("fechamento_inclui_hidrografia está ativo, mas HIDROGRAFIA não existe no catálogo.")
        invalidos.add("HIDROGRAFIA")
    for arquivo in estado.get("nao_recortar", []):
        if str(arquivo).upper() not in validos_definidos:
            problemas.append(f"nao_recortar cita ARQUIVO inexistente: {arquivo}.")

    return {"problemas": problemas, "invalidos": invalidos}
