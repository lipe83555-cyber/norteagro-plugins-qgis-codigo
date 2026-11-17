# -*- coding: utf-8 -*-
"""v3.9.6: modelos do escritório - estrutura de pastas (com camadas), temas de cores e
estilo da tabela (Quadro de Áreas).

v0.2.0: ficam em modelos_norteagro.json na pasta dados/ do próprio plugin (ao lado do catálogo), com cópia de
segurança no perfil do QGIS. Nada depende do Google Drive.
"""
import base64
import copy
import json
import os
import re
import time
from datetime import datetime

from . import catalogo

def _compat():
    from . import compat
    return compat


PADRAO = "Padrão Norte Agro"
NOME_MAE_PADRAO = "MAPA USO DO SOLO"   # v0.0.0: nome sugerido da pasta mãe nos modelos que não definem um
FUNCIONAIS = ("shapefiles", "kml", "projetos")   # pastas que o plugin conhece (v0.0.0: a pessoa cria se quiser)
OBRIGATORIAS = ("shapefiles",)                    # v3.9.9: só esta é obrigatória; kml e projetos são opcionais
_SEM_SUBPASTA = ("shapefiles", "kml")              # pastas das camadas e dos KML: não aceitam extras
_CACHE = {"caminho": None, "mtime": None, "estado": None}


# ------------------------------------------------------------------ arquivo
def caminho_modelos():
    return os.path.join(os.path.dirname(catalogo.CATALOGO_ESCRITORIO), "modelos_norteagro.json")


def _vazio():
    return {"pastas": [], "temas_cores": [], "tabelas": []}


def _normalizar(dados):
    estado = _vazio()
    if isinstance(dados, dict):
        for chave in estado:
            if isinstance(dados.get(chave), list):
                estado[chave] = [x for x in dados[chave] if isinstance(x, dict) and str(x.get("nome") or "").strip()]
    return estado


def estado_modelos(forcar=False):
    cam = caminho_modelos()
    try:
        mtime = os.path.getmtime(cam) if os.path.isfile(cam) else None
    except OSError:
        mtime = None
    catalogo.preparar_dados()
    if not forcar and _CACHE["caminho"] == cam and _CACHE["mtime"] == mtime and _CACHE["estado"] is not None:
        return copy.deepcopy(_CACHE["estado"])
    try:
        # arquivo ainda não existe (ex.: testes): usa os modelos de fábrica (pasta padrao/)
        origem = cam if os.path.isfile(cam) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "padrao",
                                                                "modelos_norteagro.json")
        with open(origem, "r", encoding="utf-8") as arq:
            estado = _normalizar(json.load(arq))
    except Exception:
        estado = _vazio()
    _CACHE.update(caminho=cam, mtime=mtime, estado=estado)
    return copy.deepcopy(estado)


def _gravar(mutador):
    """Grava com trava; relê sob a trava e nunca sobrescreve um arquivo ilegível."""
    catalogo.preparar_dados()
    cam = caminho_modelos(); pasta = os.path.dirname(cam)
    os.makedirs(pasta, exist_ok=True)
    trava = cam + ".lock"; fd = None
    for _ in range(50):
        try:
            fd = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time()}".encode("ascii", "ignore")); break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(trava) > 30:
                    os.remove(trava); continue
            except OSError:
                pass
            time.sleep(0.1)
    if fd is None:
        raise TimeoutError("Os modelos estão sendo gravados por outra janela do QGIS. Tente de novo em alguns segundos.")
    temporario = cam + f".tmp.{os.getpid()}"
    try:
        if os.path.isfile(cam):
            try:
                with open(cam, "r", encoding="utf-8") as arq:
                    estado = _normalizar(json.load(arq))
            except Exception as exc:
                raise RuntimeError(f"O arquivo de modelos não pôde ser lido ({exc}). Nada foi gravado para não perder modelos.")
        else:
            estado = _vazio()
        mutador(estado)
        with open(temporario, "w", encoding="utf-8") as arq:
            json.dump(estado, arq, ensure_ascii=False, indent=2)
        os.replace(temporario, cam)
        catalogo.guardar_copia_seguranca(cam)
        _CACHE.update(caminho=None, mtime=None, estado=None)
        return copy.deepcopy(estado)
    finally:
        try:
            if fd is not None: os.close(fd)
        except OSError: pass
        try:
            if os.path.exists(temporario): os.remove(temporario)
        except OSError: pass
        try: os.remove(trava)
        except OSError: pass


def _carimbo():
    return {"autor": catalogo._autor_atual(), "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _nome_livre(nome):
    nome = re.sub(r"\s+", " ", str(nome or "")).strip()
    if not nome:
        raise ValueError("Dê um nome ao modelo.")
    if nome.casefold() == PADRAO.casefold():
        raise ValueError(f'"{PADRAO}" é o modelo fixo do plugin. Use outro nome.')
    return nome


def _salvar_lista(chave, item, nome_antigo=None):
    nome = item["nome"]
    def alterar(estado):
        lista = estado[chave]
        antigo = str(nome_antigo or "").casefold()
        if any(str(x.get("nome", "")).casefold() == nome.casefold() and str(x.get("nome", "")).casefold() != antigo for x in lista):
            raise ValueError(f'Já existe um modelo chamado "{nome}".')
        lista[:] = [x for x in lista if str(x.get("nome", "")).casefold() not in (antigo, nome.casefold())]
        lista.append(dict(item, **_carimbo()))
        lista.sort(key=lambda x: str(x.get("nome", "")).casefold())
    _gravar(alterar)
    return item


def _remover_lista(chave, nome):
    def alterar(estado):
        antes = len(estado[chave])
        estado[chave] = [x for x in estado[chave] if str(x.get("nome", "")).casefold() != str(nome).casefold()]
        if len(estado[chave]) == antes:
            raise ValueError(f'O modelo "{nome}" não existe mais.')
    _gravar(alterar)


def _achar(lista, nome):
    return next((copy.deepcopy(x) for x in lista if str(x.get("nome", "")).casefold() == str(nome or "").casefold()), None)


# ------------------------------------------------------------------ estrutura de pastas
# v0.0.0 (formato_pastas 2): o modelo é uma árvore livre de pastas que começa no LOCAL escolhido em Configurar pasta
# ("Criar dentro de"). Dentro dele ficam quantas pastas mãe a pessoa quiser, cada uma com as subpastas que quiser.
#   "pastas":     caminhos "MAE/sub/sub" a partir do local (só as pastas finais; as de cima são criadas junto);
#   "pasta_mapa": caminho da pasta onde o plugin grava as camadas (shapefiles) - "" = o próprio local.
# shapefiles, kml e projetos são pastas comuns que a pessoa cria se quiser: kml dentro da pasta do mapa liga o KML
# automático; projetos dentro dela vira o lugar sugerido do .qgz; shapefiles nasce sozinha com a primeira camada.
def modelo_pasta_padrao():
    m = NOME_MAE_PADRAO
    return {"nome": PADRAO, "fixo": True, "formato_pastas": 2, "pasta_mapa": m, "camadas": [], "tema_cores": "",
            "pastas": [f"{m}/shapefiles", f"{m}/kml", f"{m}/projetos", f"{m}/layout", f"{m}/plantas pdf"]}


def modelo_pasta_vazio():
    """Ponto de partida do botão Novo: árvore vazia (a pessoa cria as pastas mãe e as outras do zero)."""
    return {"nome": "Novo modelo", "formato_pastas": 2, "pastas": [], "pasta_mapa": "", "camadas": [], "tema_cores": ""}


def modelos_pasta():
    return [modelo_pasta_padrao()] + estado_modelos()["pastas"]


def modelo_pasta(nome):
    return _achar(modelos_pasta(), nome or PADRAO)


def limpar_subpasta(texto, mapa=None):
    """Caminho de pasta do modelo, com / . Com `mapa` (caminho da pasta do mapa), recusa pastas dentro de
    <mapa>/shapefiles e <mapa>/kml, onde o plugin grava as camadas e os KML."""
    partes = [x.strip() for x in re.split(r"[\\/]+", str(texto or "")) if x.strip()]
    if not partes:
        return ""
    for parte in partes:
        if parte in (".", "..") or re.search(r'[:*?"<>|]', parte) or parte.endswith("."):
            raise ValueError(f'Nome de pasta inválido: "{parte}" (sem : * ? " < > | e sem ponto no final).')
    if mapa is not None:
        base = [x.casefold() for x in str(mapa or "").split("/") if x]
        n = len(base)
        if [x.casefold() for x in partes[:n]] == base and len(partes) > n + 1 and partes[n].casefold() in _SEM_SUBPASTA:
            raise ValueError(f'"{partes[n]}" é onde o plugin grava as camadas e os KML; crie a subpasta em outro lugar.')
    return "/".join(partes)


def _dentro_do_mapa(caminho, mapa, nome):
    c = str(caminho or "").casefold(); r = ((str(mapa or "") + "/") if mapa else "").casefold() + nome
    return c == r or c.startswith(r + "/")


def _camada_modelo(item):
    if not isinstance(item, dict):
        return None
    if item.get("arquivo") and not item.get("nova"):
        return {"arquivo": catalogo.normalizar_arquivo(item["arquivo"])}
    nova = item.get("nova") if isinstance(item.get("nova"), dict) else item
    nome = str(nova.get("nome") or "").strip(); arquivo = catalogo.normalizar_arquivo(nova.get("arquivo") or nome)
    if not nome or not arquivo:
        return None
    tipo = str(nova.get("tipo") or "P"); tipo = tipo if tipo in ("P", "L", "Pt") else "P"
    quadro = str(nova.get("quadro") or "OUTRAS").upper()
    return {"nova": {"arquivo": arquivo, "nome": nome, "tipo": tipo, "grupo": str(nova.get("grupo") or "Uso do Solo").strip() or "Uso do Solo",
                     "estilo_xml": str(nova.get("estilo_xml") or ""),
                     "quadro": quadro if quadro in catalogo.CODIGOS_LUGAR_QUADRO else "OUTRAS"}}


def _converter_antigo(modelo):
    """Modelos de antes (caminhos a partir da pasta do mapa + opções kml/projetos) para o formato 2:
    a pasta do mapa vira a pasta mãe "MAPA USO DO SOLO" (ou "nome_mae") e as opções viram pastas comuns."""
    nome = str(modelo.get("nome_mae", NOME_MAE_PADRAO) or "").strip() or NOME_MAE_PADRAO
    try:
        nome = limpar_subpasta(nome)
        nome = nome if "/" not in nome else NOME_MAE_PADRAO
    except ValueError:
        nome = NOME_MAE_PADRAO
    sub = str(modelo.get("pasta_mapa") or "").strip("/")
    mapa = nome + ("/" + sub if sub else "")
    extras = [n for n, chave in (("shapefiles", "pasta_shapefiles"), ("kml", "gerar_kml"), ("projetos", "pasta_projetos"))
              if bool(modelo.get(chave, True))]
    pastas = [mapa + "/" + n for n in extras] + [nome + "/" + str(p) for p in (modelo.get("pastas") or []) if str(p).strip()]
    if not pastas:
        pastas = [mapa]
    return pastas, mapa


def normalizar_modelo_pasta(modelo):
    if modelo.get("formato_pastas") == 2:
        brutas, mapa_bruto = list(modelo.get("pastas") or []), str(modelo.get("pasta_mapa") or "")
    else:
        brutas, mapa_bruto = _converter_antigo(modelo)
    try:
        mapa = limpar_subpasta(mapa_bruto)
    except ValueError:
        mapa = ""
    pastas = []
    for x in brutas:
        limpa = limpar_subpasta(x, mapa)
        if limpa and limpa.casefold() not in [p.casefold() for p in pastas]:
            pastas.append(limpa)
    camadas, vistos = [], set()
    for item in modelo.get("camadas") or []:
        c = _camada_modelo(item)
        chave = (c or {}).get("arquivo") or ((c or {}).get("nova") or {}).get("arquivo")
        if c and chave not in vistos:
            camadas.append(c); vistos.add(chave)
    return {"nome": str(modelo.get("nome") or "").strip(), "formato_pastas": 2, "pastas": pastas, "pasta_mapa": mapa,
            "camadas": camadas, "tema_cores": str(modelo.get("tema_cores") or "").strip(),
            "gerar_kml": any(_dentro_do_mapa(p, mapa, "kml") for p in pastas),
            "pasta_projetos": any(_dentro_do_mapa(p, mapa, "projetos") for p in pastas)}


def pastas_maes(modelo):
    """Pastas mãe (primeiro nível dentro do local), na ordem do modelo. Quando as camadas ficam no próprio local,
    shapefiles, kml e projetos desse nível são pastas do plugin, não pastas mãe (não podem mudar de nome)."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao()); saida = []
    for p in m["pastas"] + ([m["pasta_mapa"]] if m["pasta_mapa"] else []):
        topo = p.split("/")[0]
        if not m["pasta_mapa"] and topo.casefold() in FUNCIONAIS:
            continue
        if topo and topo.casefold() not in [x.casefold() for x in saida]:
            saida.append(topo)
    return saida


def renomear_maes(modelo, nomes):
    """Cópia do modelo com as pastas mãe renomeadas ({nome no modelo: nome usado neste projeto})."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao())
    troca = {str(k).casefold(): str(v).strip() for k, v in (nomes or {}).items() if str(v or "").strip()}

    def ren(c):
        if not c:
            return c
        topo, _, resto = c.partition("/")
        novo = troca.get(topo.casefold(), topo)
        return novo + ("/" + resto if resto else "")
    saida = dict(m); saida["pastas"] = [ren(p) for p in m["pastas"]]; saida["pasta_mapa"] = ren(m["pasta_mapa"])
    return normalizar_modelo_pasta(saida)


def pastas_do_plugin(modelo):
    """Pastas que o plugin cria além das do modelo (a partir da pasta do mapa): shapefiles, se o modelo tem camadas."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao())
    tem = any(_dentro_do_mapa(p, m["pasta_mapa"], "shapefiles") for p in m["pastas"])
    return ["shapefiles"] if (m["camadas"] and not tem) else []


def salvar_modelo_pasta(modelo, nome_antigo=None):
    m = normalizar_modelo_pasta(modelo); m["nome"] = _nome_livre(m["nome"])
    m.pop("gerar_kml", None); m.pop("pasta_projetos", None)   # derivadas das pastas
    return _salvar_lista("pastas", m, nome_antigo)


def remover_modelo_pasta(nome):
    _remover_lista("pastas", nome)


def pasta_base(pasta, modelo=None):
    """Local (o "Criar dentro de") a partir da pasta do mapa: sobe os níveis de pasta_mapa.
    None se a pasta do mapa não termina nesse caminho."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao())
    atual = os.path.abspath(pasta)
    for parte in reversed([p for p in m["pasta_mapa"].split("/") if p]):
        if os.path.basename(atual).casefold() != parte.casefold():
            return None
        atual = os.path.dirname(atual)
    return atual


def ajustar_ao_disco(pasta, modelo=None):
    """(local, modelo) para uma pasta do mapa que já existe. Se a pasta mãe da pasta do mapa tem outro nome no
    disco (o nome da fazenda), devolve o modelo com essa pasta mãe renomeada. (None, modelo) se não encaixa."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao())
    base = pasta_base(pasta, m)
    if base is not None:
        return base, m
    partes = [p for p in m["pasta_mapa"].split("/") if p]
    if not partes:
        return None, m
    atual = os.path.abspath(pasta)
    for parte in reversed(partes[1:]):
        if os.path.basename(atual).casefold() != parte.casefold():
            return None, m
        atual = os.path.dirname(atual)
    m2 = renomear_maes(m, {partes[0]: os.path.basename(atual)})
    return os.path.dirname(atual), m2


def caminho_pasta_mapa(base, modelo=None):
    """Pasta do mapa (onde ficam as camadas) dentro do local escolhido."""
    m = normalizar_modelo_pasta(modelo or modelo_pasta_padrao())
    return os.path.join(base, *[p for p in m["pasta_mapa"].split("/") if p])


def pasta_mae(pasta, modelo=None):
    """Pasta mãe que contém a pasta do mapa (no disco), ou None."""
    base, m = ajustar_ao_disco(pasta, modelo)
    topo = [p for p in m["pasta_mapa"].split("/") if p]
    return os.path.join(base, topo[0]) if (base is not None and topo) else None


def criar_pastas(pasta, modelo=None):
    """Cria as pastas do modelo a partir do local (achado subindo da pasta do mapa `pasta`).
    Devolve as que não existiam, com o caminho a partir do local.
    Se a pasta do mapa não está no lugar que o modelo espera, cria só o que fica dentro dela."""
    base, m = ajustar_ao_disco(pasta, modelo)
    mapa = m["pasta_mapa"]
    novas = []

    def criar(raiz, rel, rotulo):
        destino = os.path.join(raiz, *rel.split("/"))
        if not os.path.isdir(destino):
            os.makedirs(destino, exist_ok=True); novas.append(rotulo)

    os.makedirs(pasta, exist_ok=True)
    for rel in pastas_do_plugin(m):
        criar(pasta, rel, (mapa + "/" + rel) if (mapa and base is not None) else rel)
    for rel in m["pastas"]:
        if base is not None:
            criar(base, rel, rel)
        elif not mapa:
            criar(pasta, rel, rel)
        elif rel.casefold().startswith(mapa.casefold() + "/"):
            criar(pasta, rel[len(mapa) + 1:], rel[len(mapa) + 1:])
    return novas


def camadas_ausentes_modelo(modelo, indice):
    """Camadas do catálogo citadas no modelo que não existem mais no catálogo."""
    return [c["arquivo"] for c in normalizar_modelo_pasta(modelo)["camadas"] if c.get("arquivo") and c["arquivo"] not in indice]


def entradas_camadas_modelo(modelo, indice):
    """[(entrada_catalogo, nova?)] na ordem do modelo; camadas do catálogo que sumiram ficam de fora
    (veja camadas_ausentes_modelo para avisar)."""
    saida = []
    for c in normalizar_modelo_pasta(modelo)["camadas"]:
        if c.get("arquivo"):
            if c["arquivo"] in indice:
                saida.append((indice[c["arquivo"]], False))
        else:
            n = dict(c["nova"]); n.update({"personalizada": True, "origem": "projeto", "ordem": 100000})
            saida.append((indice.get(n["arquivo"]) or n, n["arquivo"] not in indice))
    return saida


# ------------------------------------------------------------------ temas de cores das camadas
def _renderer_xml(renderer):
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.core import QgsReadWriteContext
    doc = QDomDocument(); el = renderer.save(doc, QgsReadWriteContext()); doc.appendChild(el)
    return doc.toString()


def renderer_de_xml(texto):
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.core import QgsFeatureRenderer, QgsReadWriteContext
    doc = QDomDocument()
    if not doc.setContent(str(texto or "")):
        return None
    return QgsFeatureRenderer.load(doc.documentElement(), QgsReadWriteContext())


def _fonte(camada):
    return os.path.normcase(os.path.abspath(str(camada.source() or "").split("|")[0])) if camada.source() else ""


def _pasta_mapa(projeto):
    from qgis.core import QgsExpressionContextUtils
    pasta = str(QgsExpressionContextUtils.projectScope(projeto).variable("norteagro_pasta") or "")
    return os.path.normcase(os.path.abspath(pasta)) if pasta else ""


def camadas_do_plugin(projeto, so_da_pasta=False):
    """Camadas do plugin na ordem da árvore. so_da_pasta: só as gravadas dentro da pasta do mapa."""
    from qgis.core import QgsVectorLayer
    ordem = [n.layerId() for n in projeto.layerTreeRoot().findLayers()]
    todas = [projeto.mapLayer(i) for i in ordem] + [c for i, c in projeto.mapLayers().items() if i not in ordem]
    saida = [c for c in todas if isinstance(c, QgsVectorLayer) and str(c.customProperty("norteagro/arquivo", "") or "")
             and str(c.customProperty("norteagro/conferencia", "") or "") != "1"]
    if so_da_pasta:
        pasta = _pasta_mapa(projeto)
        saida = [c for c in saida if pasta and _fonte(c).startswith(pasta + os.sep)]
    return saida


# v0.2.0: os temas valem para QUALQUER camada vetorial do projeto, não só as criadas pelo plugin.
# Cada camada é guardada pela linha do catálogo que o plugin reconhece nela (ex.: "Reserva Legal" -> RESERVA_LEGAL),
# assim a cor vale para a mesma camada em qualquer projeto, venha ela do plugin, de outro projeto ou criada à mão.
# Camada que o plugin não reconhece é guardada pelo próprio nome ("CAMADA:<nome normalizado>").
PREFIXO_NOME = "CAMADA:"


def camadas_vetoriais(projeto):
    """Todas as camadas vetoriais do projeto (ordem da árvore), menos a camada de conferência do plugin."""
    from qgis.core import QgsVectorLayer
    ordem = [n.layerId() for n in projeto.layerTreeRoot().findLayers()]
    todas = [projeto.mapLayer(i) for i in ordem] + [c for i, c in projeto.mapLayers().items() if i not in ordem]
    return [c for c in todas if isinstance(c, QgsVectorLayer) and c.isValid()
            and str(c.customProperty("norteagro/conferencia", "") or "") != "1"]


def chave_nome(camada):
    from .reconhecimento import normalizar_chave
    return PREFIXO_NOME + (normalizar_chave(camada.name()) or str(camada.name()).strip().upper())


def chaves_tema(projeto, camadas):
    """{id da camada: [chaves]}: primeiro a linha do catálogo (propriedade do plugin ou reconhecimento pelo nome),
    depois o nome da camada."""
    saida, reconhecer = {}, []
    for c in camadas:
        arq = str(c.customProperty("norteagro/arquivo", "") or "").upper()
        saida[c.id()] = [arq] if arq else []
        if not arq:
            reconhecer.append(c)
    if reconhecer:
        try:
            from .areas import prever_reconhecimentos
            prev, _ = prever_reconhecimentos(reconhecer, "", catalogo.indice_reconhecimento(projeto),
                                             catalogo.apelidos_manuais_projeto(projeto), {})
            for c in reconhecer:
                arq = str((prev.get(c.id()) or {}).get("arquivo") or "").upper()
                if arq:
                    saida[c.id()].append(arq)
        except Exception:
            pass
    for c in camadas:
        saida[c.id()].append(chave_nome(c))
    return saida


def capturar_tema(projeto, camadas=None, nomes=None):
    """Estilo de cada camada vetorial do projeto. Com duas camadas na mesma linha do catálogo vale a da pasta do
    mapa; senão, a primeira da árvore. `nomes` (dict opcional) recebe chave -> nome da camada, para exibir."""
    pasta = _pasta_mapa(projeto); estilos, da_pasta = {}, set()
    camadas = list(camadas) if camadas is not None else camadas_vetoriais(projeto)
    chaves = chaves_tema(projeto, camadas)
    for camada in camadas:
        try:
            if not camada.renderer():
                continue
            chave = chaves[camada.id()][0]
            na_pasta = bool(pasta) and _fonte(camada).startswith(pasta + os.sep)
            if chave in estilos and (chave in da_pasta or not na_pasta):
                continue
            estilos[chave] = _renderer_xml(camada.renderer())
            if nomes is not None:
                nomes[chave] = camada.name()
            if na_pasta:
                da_pasta.add(chave)
        except Exception:
            continue
    return estilos


def temas_cores():
    return estado_modelos()["temas_cores"]


def tema_cores(nome):
    return _achar(temas_cores(), nome)


def salvar_tema_cores(nome, estilos, nome_antigo=None, nomes=None):
    nome = _nome_livre(nome)
    if not estilos:
        raise ValueError("Nenhuma camada com estilo no projeto para guardar.")
    item = {"nome": nome, "estilos": dict(estilos)}
    nomes = {k: str(v) for k, v in (nomes or {}).items() if k in estilos and str(k).startswith(PREFIXO_NOME)}
    if nomes:
        item["nomes"] = nomes
    return _salvar_lista("temas_cores", item, nome_antigo)


def remover_tema_cores(nome):
    _remover_lista("temas_cores", nome)


def camadas_do_tema(tema, projeto, camadas=None):
    """[(camada, chave)] das camadas do projeto que têm cor guardada no tema."""
    estilos = (tema or {}).get("estilos") or {}
    camadas = list(camadas) if camadas is not None else camadas_vetoriais(projeto)
    chaves = chaves_tema(projeto, camadas)
    saida = []
    for c in camadas:
        chave = next((k for k in chaves.get(c.id(), []) if k in estilos), None)
        if chave:
            saida.append((c, chave))
    return saida


_TIPO_SIMBOLO = {0: "ponto", 1: "linha", 2: "polígono"}  # QgsSymbol.Marker / Line / Fill
_TIPO_CAMADA = {0: "ponto", 1: "linha", 2: "polígono"}   # QgsWkbTypes Point / Line / Polygon


def _tipo_compativel(renderer, camada):
    """v3.9.11: estilo de polígono não vai para camada de ponto (ficaria invisível), e vice-versa."""
    try:
        from qgis.core import QgsRenderContext
        simbolos = renderer.symbols(QgsRenderContext())
        if not simbolos:
            return True, ""
        tipo_s = _TIPO_SIMBOLO.get(int(simbolos[0].type()))
        tipo_c = _TIPO_CAMADA.get(int(camada.geometryType()))
        if tipo_s and tipo_c and tipo_s != tipo_c:
            return False, f"o tema guarda um estilo de {tipo_s} e a camada é de {tipo_c}"
    except Exception:
        pass
    return True, ""


def aplicar_tema(tema, projeto, gravar_qml=True, camadas=None):
    """Aplica o tema às camadas vetoriais do projeto (ou só às indicadas). Devolve (aplicadas, sem_estilo_no_tema, erros)."""
    from qgis.core import QgsMapLayer
    tema = tema_cores(tema) if isinstance(tema, str) else tema
    if not tema:
        raise ValueError("Tema de cores não encontrado.")
    estilos = tema.get("estilos") or {}
    categorias = _compat().categorias_sem_propriedades()
    camadas = list(camadas) if camadas is not None else camadas_vetoriais(projeto)
    com_cor = dict((c.id(), k) for c, k in camadas_do_tema(tema, projeto, camadas))
    aplicadas, sem, erros = [], [], []
    for camada in camadas:
        xml = estilos.get(com_cor.get(camada.id(), ""))
        if not xml:
            sem.append(camada.name()); continue
        try:
            r = renderer_de_xml(xml)
            if r is None:
                raise RuntimeError("estilo ilegível")
            certo, motivo = _tipo_compativel(r, camada)
            if not certo:
                erros.append(f"{camada.name()}: não aplicado, {motivo}"); continue
            camada.setRenderer(r); camada.triggerRepaint(); aplicadas.append(camada.name())
            fonte = str(camada.source() or "").split("|")[0]
            if gravar_qml and fonte.lower().endswith(".shp") and os.path.isfile(fonte):
                camada.saveNamedStyle(os.path.splitext(fonte)[0] + ".qml", categories=categorias)
        except Exception as exc:
            erros.append(f"{camada.name()}: {exc}")
    if aplicadas:
        projeto.setDirty(True)
    return aplicadas, sem, erros


# ------------------------------------------------------------------ estilo da tabela
QUADROS_TABELA = [
    ("IMOVEL", "Áreas Totais do Imóvel", "E"), ("PASSIVOS", "Passivos ambientais", "D"),
    ("REMANESCENTES", "Áreas Remanescentes", "E"), ("ANTES", "Área antropizada antes de 2019", "D"),
    ("APP", "Área de Preservação Permanente", "E"), ("APOS", "Área antropizada após 2019", "D"),
    ("HIDRO", "Área Hidrográfica", "E"), ("COMPENSACAO", "Área Total de Compensação", "D"),
    ("OUTRAS", "Outras camadas", "E"),
]
TITULO_PADRAO_QUADRO = {q[0]: q[1] for q in QUADROS_TABELA}
CORES_PADRAO = {
    "titulo_fundo": "#E4EDD8", "titulo_texto": "#262621",
    "cabecalho_fundo": "#F0F0EB", "cabecalho_texto": "#262621",
    "planilha_fundo": "#E4EDD8", "planilha_texto": "#262621",
}
ROTULOS_CORES = [
    ("titulo_fundo", "Título dos quadros - fundo"), ("titulo_texto", "Título dos quadros - texto"),
    ("cabecalho_fundo", "Cabeçalho Descrição/Hectares - fundo"), ("cabecalho_texto", "Cabeçalho Descrição/Hectares - texto"),
    ("planilha_fundo", "Título da planilha - fundo"), ("planilha_texto", "Título da planilha - texto"),
]
# Linhas fixas que podem ser renomeadas (as das camadas usam o nome do catálogo e também podem).
LINHAS_PADRAO = [
    "Área Antropizada não Consolidada", "Área Consolidada", "Área de Vegetação Nativa", "Área sem classificação",
    "Área Suprimida antes de 2019", "Área Suprimida depois de 2019", "Área de Reserva Legal", "Área Fora da RL e APP",
    "APP Preservada", "APP Consolidada", "APP Suprimida", "APP Suprimida antes de 2019", "APP Suprimida depois de 2019",
    "Área de Reserva Legal Suprimida antes de 2019", "Área de Reserva Legal Suprimida depois de 2019",
    "Supressão em Área Passível antes de 2019", "Supressão em Área Passível após 2019", "Hidrografia",
    "Área de Compensação por Danos", "Área de Compensação Florestal", "Área de Recomposição", "Total", "Descrição", "Hectares",
]
TITULO_PLANILHA_PADRAO = "{imovel} - Quadro de Áreas"


def modelo_tabela_padrao():
    return {"nome": PADRAO, "fixo": True,
            "quadros": [{"id": i, "titulo": t, "lado": l, "visivel": True} for i, t, l in QUADROS_TABELA],
            "linhas": {}, "cores": dict(CORES_PADRAO), "fonte": "Calibri", "tamanho": 10,
            "titulo_planilha": TITULO_PLANILHA_PADRAO, "logo_png": "", "colunas": {"m2": False, "pct": False}}


def _cor(valor, padrao):
    valor = str(valor or "").strip()
    return valor.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", valor) else padrao


def normalizar_modelo_tabela(modelo):
    base = modelo_tabela_padrao(); m = modelo if isinstance(modelo, dict) else {}
    quadros, vistos = [], set()
    for q in m.get("quadros") or []:
        qid = str((q or {}).get("id") or "").upper()
        if qid in TITULO_PADRAO_QUADRO and qid not in vistos:
            vistos.add(qid)
            quadros.append({"id": qid, "titulo": str(q.get("titulo") or "").strip() or TITULO_PADRAO_QUADRO[qid],
                            "lado": "D" if str(q.get("lado") or "E").upper() == "D" else "E", "visivel": bool(q.get("visivel", True))})
    for q in base["quadros"]:
        if q["id"] not in vistos:
            quadros.append(dict(q))
    linhas = {str(k).strip(): str(v).strip() for k, v in (m.get("linhas") or {}).items()
              if str(k).strip() and str(v).strip() and str(k).strip() != str(v).strip()} if isinstance(m.get("linhas"), dict) else {}
    cores = {k: _cor((m.get("cores") or {}).get(k) if isinstance(m.get("cores"), dict) else "", v) for k, v in CORES_PADRAO.items()}
    try:
        tamanho = int(m.get("tamanho") or 10)
    except Exception:
        tamanho = 10
    colunas = m.get("colunas") if isinstance(m.get("colunas"), dict) else {}
    logo = str(m.get("logo_png") or "")
    try:
        if logo: base64.b64decode(logo, validate=True)
    except Exception:
        logo = ""
    return {"nome": str(m.get("nome") or base["nome"]).strip(), "fixo": bool(m.get("fixo", False)), "quadros": quadros,
            "linhas": linhas, "cores": cores, "fonte": str(m.get("fonte") or "Calibri").strip() or "Calibri",
            "tamanho": max(7, min(16, tamanho)), "titulo_planilha": str(m.get("titulo_planilha") or TITULO_PLANILHA_PADRAO).strip(),
            "logo_png": logo, "colunas": {"m2": bool(colunas.get("m2")), "pct": bool(colunas.get("pct"))}}


def modelos_tabela():
    return [modelo_tabela_padrao()] + [normalizar_modelo_tabela(x) for x in estado_modelos()["tabelas"]]


def modelo_tabela(nome):
    achado = _achar(modelos_tabela(), nome or PADRAO)
    return normalizar_modelo_tabela(achado) if achado else modelo_tabela_padrao()


def salvar_modelo_tabela(modelo, nome_antigo=None):
    m = normalizar_modelo_tabela(modelo); m["nome"] = _nome_livre(m["nome"]); m.pop("fixo", None)
    if not any(q["visivel"] for q in m["quadros"]):
        raise ValueError("Deixe pelo menos um quadro visível.")
    return _salvar_lista("tabelas", m, nome_antigo)


def remover_modelo_tabela(nome):
    _remover_lista("tabelas", nome)


def logo_de_arquivo(caminho, altura_max=120):
    """Lê uma imagem e devolve PNG em base64, reduzido para não pesar no arquivo de modelos."""
    from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from qgis.PyQt.QtGui import QImage
    img = QImage(caminho)
    if img.isNull():
        raise ValueError("Não foi possível abrir a imagem.")
    if img.height() > altura_max:
        img = img.scaledToHeight(altura_max, Qt.TransformationMode.SmoothTransformation)
    dados = QByteArray(); buf = QBuffer(dados); buf.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buf, "PNG"); buf.close()
    return base64.b64encode(bytes(dados)).decode("ascii")
