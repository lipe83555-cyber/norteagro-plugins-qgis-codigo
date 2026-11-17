# -*- coding: utf-8 -*-
"""Busca automática de imagens de satélite em cores reais (Planta de Passivos e Uso do Solo).

Duas fontes públicas, sem chave de API:

* Esri World Imagery Wayback - arquivo de todas as versões do World Imagery desde 2014
  (Maxar/Vantor, Airbus...; em geral 0,3 a 0,6 m por pixel). No centro do imóvel o plugin
  descobre só as versões em que a imagem daquele lugar mudou (serviço "tilemap") e lê a data
  de captura, o satélite e a resolução no serviço de metadados de cada versão.
* Sentinel-2 L2A (ESA/Copernicus), catálogo STAC Earth Search (Element 84 / AWS) - 10 m,
  passagem a cada ~5 dias desde 2015. As nuvens são medidas só sobre o imóvel (camada SCL).

Regra (para cada mapa): a imagem mais recente do ano pedido com a melhor qualidade em cores reais.
  Se naquele ano houver imagem de alta resolução (Wayback), ela vence; senão, a cena Sentinel-2 mais
  recente do ano sem nuvem sobre o imóvel. Passivos: mapa esquerdo = ano 2019, direito = ano atual.
  Uso do Solo: mapa principal = ano atual. Sem imagem no ano atual ainda, usa a do ano anterior.

Velocidade: cada consulta a esses servidores leva ~1 s. Por isso tudo roda em paralelo: o Wayback
é percorrido em vários trechos ao mesmo tempo, os metadados são lidos em paralelo e a busca do
Sentinel-2 de cada ano corre junto com o Wayback. O resultado fica guardado na sessão: buscar de
novo o mesmo imóvel e anos é instantâneo.

O Google Earth Pro (imagens históricas) não tem serviço aberto que permita isso.
"""

import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRasterLayer

from . import log

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro",
         "Outubro", "Novembro", "Dezembro")

URL_CFG_WAYBACK = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
URL_TILEMAP = ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/"
               "{num}/{z}/{row}/{col}")
URL_TILE = ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/"
            "MapServer/tile/{num}/{{z}}/{{y}}/{{x}}")
URL_STAC = "https://earth-search.aws.element84.com/v1/search"
COLECAO_S2 = "sentinel-2-c1-l2a"
SCL_NUVEM = (3, 8, 9, 10)  # sombra de nuvem, nuvem média, nuvem alta, cirro
LIMITE_NUVENS = 1.0        # % do imóvel coberto por nuvem/sombra para considerar a cena limpa
LIMITE_SEM_DADOS = 0.5     # % do imóvel fora da cena
TRECHOS_WAYBACK = 12       # trechos do histórico percorridos ao mesmo tempo
CONEXOES = 12              # consultas simultâneas
TEMPO_LIMITE_MS = 20000    # uma consulta que trava não segura a busca inteira
VALIDADE_CACHE_S = 3600

_CACHE = {}
_CACHE_CFG = {}
_TRAVA = threading.Lock()


class Cancelado(Exception):
    pass


# ---------------------------------------------------------------- datas
def data_extenso(iso):
    """'2019-11-04' -> '04 de Novembro de 2019' (como nas plantas do escritório)."""
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}"


def data_br(iso):
    d = date.fromisoformat(str(iso)[:10])
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- rede
# As consultas usam urllib (Python puro) e não o QgsBlockingNetworkRequest: a rede do QGIS não pode ser
# usada por várias linhas de execução ao mesmo tempo (pode travar o QGIS esperando a linha principal).
_ABRIDOR = None


def _abridor():
    """urllib com o proxy configurado no QGIS (Configurações > Opções > Rede), se houver."""
    global _ABRIDOR
    if _ABRIDOR is not None:
        return _ABRIDOR
    import ssl
    import urllib.request
    handlers = []
    try:
        from qgis.core import QgsSettings
        st = QgsSettings()
        if str(st.value("proxy/proxyEnabled", "false")).lower() == "true":
            host = st.value("proxy/proxyHost", "") or ""
            porta = st.value("proxy/proxyPort", "") or ""
            usuario = st.value("proxy/proxyUser", "") or ""
            senha = st.value("proxy/proxyPassword", "") or ""
            if host:
                cred = f"{usuario}:{senha}@" if usuario else ""
                url = f"http://{cred}{host}:{porta}" if porta else f"http://{cred}{host}"
                handlers.append(urllib.request.ProxyHandler({"http": url, "https": url}))
    except Exception:
        pass
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    _ABRIDOR = urllib.request.build_opener(*handlers)
    return _ABRIDOR


def _requisitar(url, corpo=None, feedback=None, tentativas=2):
    import urllib.error
    import urllib.request
    ultimo = None
    for _ in range(tentativas):
        if feedback is not None and feedback.isCanceled():
            raise Cancelado()
        dados = None
        cab = {"User-Agent": "NorteAgro-Layout-IA (QGIS)"}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cab["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=dados, headers=cab)
        try:
            with _abridor().open(req, timeout=TEMPO_LIMITE_MS / 1000.0) as r:
                conteudo = r.read()
            if feedback is not None and feedback.isCanceled():
                raise Cancelado()
            return conteudo
        except Cancelado:
            raise
        except urllib.error.HTTPError as e:
            ultimo = f"código {e.code}"
            if e.code < 500:
                break
        except Exception as e:
            ultimo = str(e)
    raise IOError(f"falha ao acessar {url.split('?')[0]} ({ultimo})")


def _json(url, corpo=None, feedback=None):
    return json.loads(_requisitar(url, corpo, feedback).decode("utf-8"))


class Andamento:
    """Junta o andamento (0 a 1) de partes que correm em paralelo, cada uma com um peso."""

    def __init__(self, progresso, pesos):
        self.progresso = progresso
        total = float(sum(pesos.values())) or 1.0
        self.pesos = {k: v / total for k, v in pesos.items()}
        self.fracoes = {k: 0.0 for k in pesos}
        self.trava = threading.Lock()

    def parte(self, nome):
        def f(texto, frac=None):
            with self.trava:
                if frac is not None:
                    self.fracoes[nome] = max(self.fracoes[nome], max(0.0, min(1.0, frac)))
                geral = sum(self.pesos[k] * v for k, v in self.fracoes.items())
            self.progresso(texto, geral)
        return f


# ---------------------------------------------------------------- área
def area_imovel(camada, projeto=None):
    """Retângulo do imóvel em EPSG:4326 (lon/lat)."""
    projeto = projeto or QgsProject.instance()
    ct = QgsCoordinateTransform(camada.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), projeto)
    return ct.transformBoundingBox(camada.extent())


def _geojson(ret):
    x0, y0, x1, y1 = ret.xMinimum(), ret.yMinimum(), ret.xMaximum(), ret.yMaximum()
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


# ---------------------------------------------------------------- Esri Wayback
def _tile(lon, lat, z):
    n = 2 ** z
    lat = max(min(lat, 85.0), -85.0)
    col = int((lon + 180.0) / 360.0 * n)
    row = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return row, col


def _versoes_wayback(feedback=None):
    with _TRAVA:
        guardado = _CACHE_CFG.get("cfg")
    if guardado and time.time() - guardado[0] < VALIDADE_CACHE_S:
        return guardado[1]
    cfg = _json(URL_CFG_WAYBACK, feedback=feedback)
    saida = []
    for k, v in cfg.items():
        m = re.search(r"(\d{4}-\d{2}-\d{2})", v.get("itemTitle", ""))
        if m:
            saida.append({"num": int(k), "lancamento": m.group(1), "metadados": v.get("metadataLayerUrl", "")})
    saida.sort(key=lambda x: x["lancamento"], reverse=True)
    with _TRAVA:
        _CACHE_CFG["cfg"] = (time.time(), saida)
    return saida


def _data_meta(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        v = int(valor)
        if 19000101 <= v <= 21001231:  # SRC_DATE = aaaammdd
            return date(v // 10000, v // 100 % 100, v % 100).isoformat()
        return datetime.utcfromtimestamp(v / 1000.0).date().isoformat()
    s = str(valor)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    return None


def _metadados_wayback(url_meta, lon, lat, feedback=None):
    """Data de captura, resolução e satélite da imagem no ponto. Primeiro uma consulta direta à camada de
    metadados das escalas de fazenda (rápida); se não vier nada, o 'identify' em todas as camadas."""
    from urllib.parse import urlencode
    campos = "SRC_DATE,SRC_DATE2,SRC_RES,NICE_DESC,SRC_DESC"
    a = None
    for camada in (6, 5):
        q = urlencode({"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                       "spatialRel": "esriSpatialRelIntersects", "outFields": campos, "returnGeometry": "false",
                       "f": "json"})
        try:
            feats = _json(f"{url_meta}/{camada}/query?{q}", feedback=feedback).get("features") or []
        except Cancelado:
            raise
        except Exception:
            feats = []
        if feats:
            a = feats[0].get("attributes") or {}
            break
    if a is None:
        d = 0.005
        q = urlencode({"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326,
                       "layers": "all", "tolerance": 0, "mapExtent": f"{lon - d},{lat - d},{lon + d},{lat + d}",
                       "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"})
        res = sorted(_json(f"{url_meta}/identify?{q}", feedback=feedback).get("results") or [],
                     key=lambda r: r.get("layerId", 99))
        if not res:
            return None
        a = res[0].get("attributes") or {}
    try:
        resol = float(str(a.get("SRC_RES")).replace(",", "."))
    except (TypeError, ValueError):
        resol = None
    return {"data": _data_meta(a.get("SRC_DATE2")) or _data_meta(a.get("SRC_DATE")), "resolucao": resol,
            "provedor": (a.get("NICE_DESC") or "").strip(), "sensor": (a.get("SRC_DESC") or "").strip()}


def _desc_wayback(c):
    res = f"{c['resolucao']:.2f} m".replace(".", ",") if c.get("resolucao") else "resolução ?"
    origem = " ".join(x for x in (c.get("provedor"), c.get("sensor")) if x)
    return f"{data_br(c['data'])}  ·  Esri Wayback{(' - ' + origem) if origem else ''}  ·  {res}"


def buscar_wayback(lon, lat, feedback=None, progresso=None, z=16):
    """Versões distintas da imagem no ponto (uma por data de captura), da mais nova para a mais antiga.

    O histórico é dividido em trechos percorridos ao mesmo tempo; cada versão nova encontrada já tem os
    metadados pedidos em paralelo."""
    progresso = progresso or (lambda t, f=None: None)
    versoes = _versoes_wayback(feedback)
    nums = [v["num"] for v in versoes]
    row, col = _tile(lon, lat, z)
    n = len(versoes)
    inicios = sorted({int(i * n / TRECHOS_WAYBACK) for i in range(TRECHOS_WAYBACK)})
    limites = inicios[1:] + [n]
    achadas = {}  # num -> versão
    trava = threading.Lock()
    feitos = [0]

    def avisar():
        with trava:
            feitos[0] += 1
            frac = min(0.6, 0.6 * feitos[0] / (len(inicios) * 3.0))
        progresso("Esri Wayback: percorrendo o histórico de imagens...", frac)

    def percorrer(ini, fim):
        i = ini
        while i < fim:
            j = _json(URL_TILEMAP.format(num=versoes[i]["num"], z=z, row=row, col=col), feedback=feedback)
            avisar()
            if not (j.get("data") or [0])[0]:
                return
            sel = (j.get("select") or [versoes[i]["num"]])[0]
            if sel not in nums:
                return
            with trava:
                novo = sel not in achadas
                achadas[sel] = versoes[nums.index(sel)]
            if not novo:
                return
            i = nums.index(sel) + 1

    def metadados(v):
        try:
            return v, _metadados_wayback(v["metadados"], lon, lat, feedback)
        except Cancelado:
            raise
        except Exception as e:  # metadado de uma versão indisponível não derruba a busca
            log.aviso(f"Metadados da versão Wayback {v['lancamento']} indisponíveis: {e}")
            return v, None

    progresso("Esri Wayback: percorrendo o histórico de imagens...", 0.02)
    with ThreadPoolExecutor(min(CONEXOES, len(inicios))) as ex:
        for f in [ex.submit(percorrer, a, b) for a, b in zip(inicios, limites)]:
            f.result()
    lista = sorted(achadas.values(), key=lambda v: v["lancamento"], reverse=True)
    resultado = []
    with ThreadPoolExecutor(CONEXOES) as ex:
        futuros = [ex.submit(metadados, v) for v in lista]
        for k, f in enumerate(futuros):
            v, meta = f.result()
            progresso(f"Esri Wayback: lendo datas e satélites ({k + 1} de {len(futuros)})...",
                      0.6 + 0.4 * (k + 1) / max(1, len(futuros)))
            if meta and meta["data"]:
                c = dict(meta, fonte="wayback", num=v["num"], lancamento=v["lancamento"], nuvens=None,
                         credito="Esri World Imagery Wayback" + (f" ({meta['provedor']})" if meta["provedor"] else ""))
                c["descricao"] = _desc_wayback(c)
                resultado.append(c)
    unicas = {}
    for c in resultado:  # a versão mais nova de cada captura (tratamento de cor mais recente)
        unicas.setdefault(c["data"], c)
    progresso("Esri Wayback: concluído.", 1.0)
    return sorted(unicas.values(), key=lambda c: c["data"], reverse=True)


# ---------------------------------------------------------------- Sentinel-2
def limpa(c):
    return c.get("fonte") != "sentinel2" or (c.get("nuvens", 100) <= LIMITE_NUVENS and
                                             c.get("sem_dados", 100) <= LIMITE_SEM_DADOS)


def buscar_sentinel(ret, inicio, fim, feedback=None, progresso=None, max_verificar=12, parar_apos=3, lote=12):
    """Cenas Sentinel-2 L2A sobre o imóvel entre inicio e fim (date), da mais nova para a mais antiga,
    com as nuvens medidas sobre o imóvel (camada SCL). A medição roda num processo separado (GDAL), em
    lotes; para depois de achar `parar_apos` cenas limpas."""
    from . import gdal_processo
    progresso = progresso or (lambda t, f=None: None)
    corpo = {"collections": [COLECAO_S2], "intersects": _geojson(ret),
             "datetime": f"{inicio.isoformat()}T00:00:00Z/{fim.isoformat()}T23:59:59Z", "limit": 60,
             "query": {"eo:cloud_cover": {"lt": 80}},
             "sortby": [{"field": "properties.datetime", "direction": "desc"}],
             "fields": {"include": ["id", "properties.datetime", "properties.eo:cloud_cover", "assets.scl.href",
                                    "assets.visual.href"]}}
    feicoes = _json(URL_STAC, corpo, feedback).get("features") or []
    feicoes.sort(key=lambda f: f.get("properties", {}).get("datetime", ""), reverse=True)
    cenas = {}
    ordem = []
    for f in feicoes[:max_verificar]:
        ativos = f.get("assets") or {}
        visual = (ativos.get("visual") or {}).get("href")
        scl = (ativos.get("scl") or {}).get("href")
        if visual and scl and f.get("id") not in cenas:
            cenas[f["id"]] = (f, visual, scl)
            ordem.append(f["id"])
    total = max(1, len(ordem))
    progresso("Sentinel-2: conferindo nuvens sobre o imóvel...", 0.1)
    bbox = [ret.xMinimum(), ret.yMinimum(), ret.xMaximum(), ret.yMaximum()]
    medidas = {}
    for k in range(0, len(ordem), lote):
        ids = ordem[k:k + lote]

        def chegou(r):
            medidas[r.get("id")] = r
            progresso(f"Sentinel-2: conferidas {len(medidas)} de {total} cenas...", 0.1 + 0.9 * len(medidas) / total)

        gdal_processo.executar({"acao": "nuvens", "itens": [{"id": i, "href": cenas[i][2], "bbox": bbox}
                                                              for i in ids]}, chegou, feedback)
        limpas = [i for i in ordem[:k + lote] if i in medidas and "erro" not in medidas[i] and
                  medidas[i]["nuvens"] <= LIMITE_NUVENS and medidas[i]["sem_dados"] <= LIMITE_SEM_DADOS]
        if len(limpas) >= parar_apos:
            break
    saida = []
    for i in ordem:
        m = medidas.get(i)
        if not m:
            continue
        if "erro" in m:
            log.aviso(f"Cena {i}: {m['erro']}")
            continue
        f, visual, _scl = cenas[i]
        dia = f["properties"]["datetime"][:10]
        c = {"fonte": "sentinel2", "data": dia, "resolucao": 10.0, "nuvens": m["nuvens"], "sem_dados": m["sem_dados"],
             "id": i, "href": visual, "credito": "Sentinel-2 (ESA/Copernicus)"}
        extra = f"nuvens no imóvel {m['nuvens']:.0f}%" + (f", fora da cena {m['sem_dados']:.0f}%"
                                                           if m["sem_dados"] > 0.5 else "")
        c["descricao"] = f"{data_br(dia)}  ·  Sentinel-2  ·  10 m  ·  {extra}"
        saida.append(c)
    progresso("Sentinel-2: concluído.", 1.0)
    return saida


def _sentinel_do_ano(ret, ano, feedback, progresso, avisos, recuar=False):
    """{ano_usado: cenas} - o ano pedido e, se não houver cena limpa e recuar=True, o ano anterior."""
    hoje = date.today()
    saida = {}
    for k, a in enumerate((ano, ano - 1) if recuar else (ano,)):
        ini, fim = date(a, 1, 1), min(date(a, 12, 31), hoje)
        if ini > hoje:
            continue
        prog = progresso if k == 0 else (lambda t, f=None: progresso(t, None if f is None else 0.9 + 0.1 * f))
        try:
            s2 = buscar_sentinel(ret, ini, fim, feedback, prog)
        except Cancelado:
            raise
        except Exception as e:
            s2 = []
            avisos.append(f"Sentinel-2 indisponível agora ({e}).")
        saida[a] = s2
        if any(limpa(c) for c in s2):
            break
    return saida


# ---------------------------------------------------------------- busca completa
def _ordem_qualidade(c):
    """Melhor qualidade primeiro (resolução arredondada a 0,1 m); empatando, a mais recente."""
    return (round(c.get("resolucao") or 99.0, 1), -date.fromisoformat(c["data"]).toordinal())


def _combinar(ano, wb, s2_por_ano, rotulo, avisos):
    """Imagens do ano, melhor primeiro: alta resolução (Wayback) do ano, se houver, e depois as cenas
    Sentinel-2 do ano sem nuvem sobre o imóvel, da mais recente para a mais antiga."""
    for a in sorted(s2_por_ano or {ano: []}, reverse=True):
        s2 = s2_por_ano.get(a, [])
        melhores = sorted([c for c in wb if c["data"][:4] == str(a)] + [c for c in s2 if limpa(c)],
                          key=_ordem_qualidade)
        if not melhores and s2 and a == min(s2_por_ano):
            melhores = sorted(s2, key=lambda c: c["nuvens"] + c["sem_dados"])
            avisos.append(f"Nenhuma imagem de {a} sem nuvens sobre o imóvel; escolhida a com menos nuvens.")
        if melhores:
            if a != ano:
                avisos.append(f"Ainda não há imagem de {ano} para o imóvel; usada a mais recente de {a}.")
            return melhores + [c for c in s2 if c not in melhores]
    melhores = sorted([c for c in wb if c["data"][:4] == str(ano)], key=_ordem_qualidade)
    if melhores:
        return melhores
    avisos.append(f"Nenhuma imagem de {ano} encontrada para o imóvel ({rotulo}).")
    return []


def buscar(ret, ano_antiga, ano_recente, feedback=None, progresso=None, tipos=("antiga", "recente")):
    """ret: retângulo do imóvel em lon/lat. Para cada tipo pedido, a imagem mais recente do ano com a melhor
    qualidade em cores reais: "antiga" = do ano_antiga (ex.: 2019), "recente" = do ano_recente (ano atual).
    Retorna {"antiga": [...], "recente": [...], "avisos": [...]} com a escolhida primeiro."""
    progresso = progresso or (lambda t, f=None: None)
    chave = (round(ret.xMinimum(), 4), round(ret.yMinimum(), 4), round(ret.xMaximum(), 4), round(ret.yMaximum(), 4),
             ano_antiga, ano_recente, tuple(sorted(tipos)), date.today().isoformat())
    with _TRAVA:
        guardado = _CACHE.get(chave)
    if guardado and time.time() - guardado[0] < VALIDADE_CACHE_S:
        progresso("Busca concluída (resultado guardado desta sessão).", 1.0)
        return json.loads(json.dumps(guardado[1]))

    avisos = []
    centro = ret.center()
    pesos = {"wayback": 3}
    if "antiga" in tipos:
        pesos["antiga"] = 1
    if "recente" in tipos:
        pesos["recente"] = 1
    andamento = Andamento(progresso, pesos)
    progresso("Procurando imagens (Esri Wayback e Sentinel-2 ao mesmo tempo)...", 0.0)
    with ThreadPoolExecutor(3) as ex:
        f_wb = ex.submit(buscar_wayback, centro.x(), centro.y(), feedback, andamento.parte("wayback"))
        f_ant = ex.submit(_sentinel_do_ano, ret, ano_antiga, feedback, andamento.parte("antiga"), avisos) \
            if "antiga" in tipos else None
        f_rec = ex.submit(_sentinel_do_ano, ret, ano_recente, feedback, andamento.parte("recente"), avisos, True) \
            if "recente" in tipos else None
        try:
            wb = f_wb.result()
        except Cancelado:
            raise
        except Exception as e:
            wb = []
            avisos.append(f"Esri Wayback indisponível agora ({e}).")
        s2_ant = f_ant.result() if f_ant else None
        s2_rec = f_rec.result() if f_rec else None
    saida = {"avisos": avisos}
    if "antiga" in tipos:
        lst = _combinar(ano_antiga, wb, s2_ant, "imagem antiga", avisos)
        saida["antiga"] = lst + [c for c in wb if c not in lst]
    if "recente" in tipos:
        lst = _combinar(ano_recente, wb, s2_rec, "imagem recente", avisos)
        saida["recente"] = lst + [c for c in wb if c not in lst]
    progresso("Busca concluída.", 1.0)
    with _TRAVA:
        _CACHE[chave] = (time.time(), json.loads(json.dumps(saida)))
    return saida


def buscar_periodo(ret, inicio=None, fim=None, feedback=None, progresso=None):
    """Busca só de imagem (sem planta), com os mesmos critérios das plantas.

    inicio/fim = None -> "mais recente": a imagem mais recente do ano atual (ou do anterior, se ainda não
    houver) com a melhor qualidade em cores reais - igual ao mapa direito dos Passivos.
    inicio/fim = date -> imagens capturadas no período; a recomendada é a de melhor qualidade (alta
    resolução quando houver) e, empatando, a mais recente. Cenas Sentinel-2 com nuvem sobre a área vão
    para o fim da lista. Retorna {"imagens": [...], "avisos": [...]}, a recomendada primeiro."""
    progresso = progresso or (lambda t, f=None: None)
    if inicio is None or fim is None:
        r = buscar(ret, None, date.today().year, feedback, progresso, tipos=("recente",))
        return {"imagens": r.get("recente") or [], "avisos": r.get("avisos") or []}
    chave = ("periodo", round(ret.xMinimum(), 4), round(ret.yMinimum(), 4), round(ret.xMaximum(), 4),
             round(ret.yMaximum(), 4), inicio.isoformat(), fim.isoformat(), date.today().isoformat())
    with _TRAVA:
        guardado = _CACHE.get(chave)
    if guardado and time.time() - guardado[0] < VALIDADE_CACHE_S:
        progresso("Busca concluída (resultado guardado desta sessão).", 1.0)
        return json.loads(json.dumps(guardado[1]))
    avisos = []
    centro = ret.center()
    andamento = Andamento(progresso, {"wayback": 3, "s2": 2})
    progresso("Procurando imagens (Esri Wayback e Sentinel-2 ao mesmo tempo)...", 0.0)
    ini_s2 = max(inicio, date(2015, 7, 1))
    with ThreadPoolExecutor(2) as ex:
        f_wb = ex.submit(buscar_wayback, centro.x(), centro.y(), feedback, andamento.parte("wayback"))
        f_s2 = ex.submit(buscar_sentinel, ret, ini_s2, fim, feedback, andamento.parte("s2"), 18, 6) \
            if ini_s2 <= fim else None
        try:
            wb = f_wb.result()
        except Cancelado:
            raise
        except Exception as e:
            wb = []
            avisos.append(f"Esri Wayback indisponível agora ({e}).")
        try:
            s2 = f_s2.result() if f_s2 else []
        except Cancelado:
            raise
        except Exception as e:
            s2 = []
            avisos.append(f"Sentinel-2 indisponível agora ({e}).")
    a, b = inicio.isoformat(), fim.isoformat()
    boas = sorted([c for c in wb if a <= c["data"] <= b] + [c for c in s2 if limpa(c)], key=_ordem_qualidade)
    nubladas = sorted([c for c in s2 if not limpa(c)], key=lambda c: c["data"], reverse=True)
    if not boas and nubladas:
        avisos.append("Nenhuma imagem do período sem nuvens sobre a área; as opções têm nuvens.")
    if not boas and not nubladas:
        avisos.append("Nenhuma imagem encontrada nesse período para a área.")
    saida = {"imagens": boas + nubladas, "avisos": avisos}
    progresso("Busca concluída.", 1.0)
    with _TRAVA:
        _CACHE[chave] = (time.time(), json.loads(json.dumps(saida)))
    return saida


# ---------------------------------------------------------------- camada no projeto
def nome_camada(c):
    fonte = "Esri Wayback" if c["fonte"] == "wayback" else "Sentinel-2"
    return f"Imagem {data_br(c['data'])} - {fonte}"


def criar_camada(c, ret, pasta, feedback=None):
    """Camada raster da candidata. Wayback = XYZ (sem baixar); Sentinel-2 = recorte local em GeoTIFF
    (baixado num processo separado, para o QGIS não congelar se a internet estiver lenta)."""
    if c["fonte"] == "wayback":
        fonte = "type=xyz&url=" + URL_TILE.format(num=c["num"]) + "&zmax=19&zmin=0"
        cam = QgsRasterLayer(fonte, nome_camada(c), "wms")
    else:
        from . import gdal_processo
        os.makedirs(pasta, exist_ok=True)
        arq = os.path.join(pasta, f"{c['id']}_cores_reais.tif")
        if not os.path.isfile(arq):
            cx, cy = ret.center().x(), ret.center().y()
            meio = max(ret.width(), ret.height()) * 0.8 + 0.003
            r = gdal_processo.executar({"acao": "recorte", "itens": [{
                "id": c["id"], "href": c["href"], "destino": arq,
                "bbox": [cx - meio, cy - meio, cx + meio, cy + meio]}]}, feedback=feedback)
            if not r or "erro" in r[0] or not os.path.isfile(arq):
                raise IOError(f"Não foi possível baixar o recorte da imagem {c['id']}: "
                              f"{(r[0].get('erro') if r else 'sem resposta')}")
        cam = QgsRasterLayer(arq, nome_camada(c), "gdal")
    if not cam.isValid():
        raise IOError(f"A camada da imagem de {data_br(c['data'])} não abriu.")
    cam.setCustomProperty("na_imagem", json.dumps(c, ensure_ascii=False))
    return cam


def candidata_da_camada(cam):
    try:
        return json.loads(cam.customProperty("na_imagem", "") or "null")
    except ValueError:
        return None
