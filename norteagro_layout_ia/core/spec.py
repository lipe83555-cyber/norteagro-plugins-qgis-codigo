# -*- coding: utf-8 -*-
"""Contrato declarativo da proposta de layout e seu validador.

A IA (ou o usuário) descreve a página e uma lista de elementos. Nada aqui é
executado como código: o validador só aceita os campos conhecidos, descarta
caminhos, extensões geográficas e qualquer coisa executável vinda do modelo.

Formato (compatível com a v0.1.1 e ampliado de forma opcional):

{
  "versao": "1.0",
  "page": {"width_mm": 420, "height_mm": 297},
  "elements": [
    {"id": "mapa_principal", "type": "map", "x": 0.01, "y": 0.01, "w": 0.77, "h": 0.97,
     "role": "principal",                       # novo (opcional)
     "map": {                                   # novo (opcional) - configuração do mapa
        "layers": ["AREA_DO_IMOVEL", "..."],    # nomes de camada do projeto
        "crs": "EPSG:31982",
        "extent_mode": "camada|manual|municipio|estado|brasil|tema|projeto",
        "extent_layer": "AREA_DO_IMOVEL",
        "margin": 0.10,
        "theme": "",
        "municipio": {"layer": "...", "field": "...", "value": "..."},
        "grid": true
     }},
    {"id": "titulo", "type": "label", "x": .., "text": "PLANTA ...", "font_size": 12, "bold": true,
     "align": "center"},
    {"id": "legenda", "type": "legend", "map_id": "mapa_principal", ...},
    {"id": "norte", "type": "north", "map_id": "mapa_principal", "north_mode": "true|grid"},
    {"id": "escala", "type": "scale", "map_id": "mapa_principal", "style": "bar|numeric"},
    {"id": "tab1", "type": "table", "rows": [["Descrição", "Hectares"], ...], "block": "remanescentes"},
    {"id": "logo", "type": "picture", "role": "logo"},
    {"id": "moldura", "type": "shape"}, {"id": "linha", "type": "line"}
  ]
}

Posições e tamanhos são frações da página (0 a 1). Página em milímetros. Fonte em pontos.
"""

import copy
import json
import re

VERSAO_CONTRATO = "1.0"
TIPOS = ("map", "label", "legend", "scale", "north", "shape", "line", "table", "picture")
TIPOS_VINCULADOS = ("legend", "scale", "north")
MAX_ELEMENTOS = 250
MODOS_EXTENSAO = ("camada", "manual", "municipio", "estado", "brasil", "tema", "projeto")
BLOCOS_AREAS = ("remanescentes", "app", "hidrografica", "totais")

# Sinônimos aceitos de entrada (v0.1.1 / respostas de IA em português)
_SINONIMOS_TIPO = {
    "mapa": "map", "map": "map", "texto": "label", "label": "label", "text": "label", "title": "label",
    "titulo": "label", "legenda": "legend", "legend": "legend", "escala": "scale", "scale": "scale",
    "scalebar": "scale", "scale_bar": "scale", "norte": "north", "north": "north", "north_arrow": "north",
    "forma": "shape", "shape": "shape", "rect": "shape", "rectangle": "shape", "box": "shape", "frame": "shape",
    "linha": "line", "line": "line", "tabela": "table", "table": "table", "imagem": "picture",
    "picture": "picture", "image": "picture", "logo": "picture",
}

# Campos que o modelo pode tentar enviar e que nunca são aceitos
_CAMPOS_PROIBIDOS = {"path", "src", "source", "file", "url", "extent", "code", "python", "script",
                     "expression", "exec", "eval", "layers_path"}


class ErroContrato(ValueError):
    """Proposta fora do contrato."""


def _num(v, padrao=0.0):
    try:
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return padrao
        return f
    except (TypeError, ValueError):
        return padrao


def _texto(v, limite=4000):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = "\n".join(str(x) for x in v)
    s = str(v).replace("\r\n", "\n").replace("\r", "\n")
    # travessões longos viram hífen (regra do escritório)
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    return s[:limite]


def extrair_json(texto):
    """Extrai o primeiro objeto JSON de uma resposta de IA (com ou sem cercas ```)."""
    if isinstance(texto, dict):
        return texto
    if texto is None:
        raise ErroContrato("Resposta vazia.")
    s = str(texto).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S | re.I)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    ini = s.find("{")
    if ini < 0:
        raise ErroContrato("A resposta não contém um objeto JSON.")
    nivel = 0
    em_texto = False
    escape = False
    for i in range(ini, len(s)):
        c = s[i]
        if em_texto:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                em_texto = False
            continue
        if c == '"':
            em_texto = True
        elif c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                try:
                    return json.loads(s[ini:i + 1])
                except json.JSONDecodeError as e:
                    raise ErroContrato(f"JSON inválido: {e}") from e
    raise ErroContrato("JSON incompleto (chaves não fecham).")


def _normalizar_tipo(t):
    t = str(t or "").strip().lower()
    return _SINONIMOS_TIPO.get(t, t)


def _normalizar_mapa(cfg):
    if not isinstance(cfg, dict):
        return {}
    saida = {}
    camadas = cfg.get("layers")
    if isinstance(camadas, (list, tuple)):
        saida["layers"] = [_texto(x, 200) for x in camadas if str(x).strip()][:200]
    if cfg.get("crs"):
        crs = _texto(cfg.get("crs"), 60).strip()
        if re.fullmatch(r"(EPSG|ESRI|IAU_\d+|USER):\d+", crs, re.I) or crs.upper().startswith("PROJ:"):
            saida["crs"] = crs.upper() if crs.upper().startswith(("EPSG", "ESRI")) else crs
    modo = str(cfg.get("extent_mode") or "").strip().lower()
    if modo in MODOS_EXTENSAO:
        saida["extent_mode"] = modo
    if cfg.get("extent_layer"):
        saida["extent_layer"] = _texto(cfg.get("extent_layer"), 200)
    if "margin" in cfg:
        saida["margin"] = max(0.0, min(1.0, _num(cfg.get("margin"), 0.10)))
    if cfg.get("theme"):
        saida["theme"] = _texto(cfg.get("theme"), 200)
    mun = cfg.get("municipio")
    if isinstance(mun, dict):
        saida["municipio"] = {k: _texto(mun.get(k), 200) for k in ("layer", "field", "value") if mun.get(k)}
    if "grid" in cfg:
        saida["grid"] = bool(cfg.get("grid"))
    # Extensão manual só é aceita quando vem do usuário (marcada como tal)
    ext = cfg.get("manual_extent")
    if cfg.get("_origem_usuario") and isinstance(ext, (list, tuple)) and len(ext) == 4:
        saida["manual_extent"] = [_num(x) for x in ext]
        saida["_origem_usuario"] = True
    return saida


def normalizar(proposta, origem="ia"):
    """Valida e normaliza uma proposta. Retorna (proposta_normalizada, avisos).

    origem="ia" descarta qualquer extensão manual vinda do modelo.
    Levanta ErroContrato quando a estrutura é inutilizável.
    """
    if isinstance(proposta, str):
        proposta = extrair_json(proposta)
    if not isinstance(proposta, dict):
        raise ErroContrato("A proposta deve ser um objeto JSON.")
    avisos = []
    pagina = proposta.get("page") or proposta.get("pagina") or {}
    if not isinstance(pagina, dict):
        pagina = {}
    largura = _num(pagina.get("width_mm", pagina.get("largura_mm", pagina.get("width"))), 420.0)
    altura = _num(pagina.get("height_mm", pagina.get("altura_mm", pagina.get("height"))), 297.0)
    if not (50 <= largura <= 2000 and 50 <= altura <= 2000):
        avisos.append(f"Tamanho de página inválido ({largura} x {altura} mm); usado A3 paisagem.")
        largura, altura = 420.0, 297.0
    brutos = proposta.get("elements", proposta.get("elementos"))
    if not isinstance(brutos, list):
        raise ErroContrato("A proposta não tem a lista 'elements'.")
    if len(brutos) > MAX_ELEMENTOS:
        avisos.append(f"A proposta tem {len(brutos)} elementos; mantidos os primeiros {MAX_ELEMENTOS}.")
        brutos = brutos[:MAX_ELEMENTOS]

    elementos = []
    ids = set()
    for i, e in enumerate(brutos):
        if not isinstance(e, dict):
            avisos.append(f"Elemento {i + 1} ignorado: não é um objeto.")
            continue
        tipo = _normalizar_tipo(e.get("type", e.get("tipo")))
        if tipo not in TIPOS:
            avisos.append(f"Elemento {i + 1} ignorado: tipo desconhecido '{e.get('type')}'.")
            continue
        ident = re.sub(r"[^A-Za-z0-9_\-]", "_", str(e.get("id") or f"{tipo}_{i + 1}"))[:60] or f"{tipo}_{i + 1}"
        base = ident
        n = 2
        while ident in ids:
            ident = f"{base}_{n}"
            n += 1
        ids.add(ident)
        x, y = _num(e.get("x")), _num(e.get("y"))
        w, h = _num(e.get("w", e.get("width"))), _num(e.get("h", e.get("height")))
        # Aceita milímetros ou pixels por engano: converte se claramente fora de 0..1
        if max(x, y, w, h) > 1.5:
            if max(x + w, 0) <= largura * 1.05 and max(y + h, 0) <= altura * 1.05:
                x, w = x / largura, w / largura
                y, h = y / altura, h / altura
                avisos.append(f"Elemento '{ident}': posição em mm convertida para fração da página.")
        if w <= 0 or h <= 0:
            if tipo == "line" and (w > 0 or h > 0):
                w, h = max(w, 0.0005), max(h, 0.0005)
            else:
                avisos.append(f"Elemento '{ident}' ignorado: largura ou altura zero.")
                continue
        el = {"id": ident, "type": tipo, "x": x, "y": y, "w": w, "h": h}
        for proibido in _CAMPOS_PROIBIDOS & set(e):
            if proibido == "extent" and tipo == "map":
                avisos.append(f"Elemento '{ident}': extensão geográfica proposta pela IA descartada.")
        if tipo == "label":
            el["text"] = _texto(e.get("text", e.get("texto")))
            el["font_size"] = max(3.0, min(96.0, _num(e.get("font_size", e.get("fonte")), 10.0)))
            el["bold"] = bool(e.get("bold", e.get("negrito", False)))
            al = str(e.get("align", e.get("alinhamento", "left"))).lower()
            el["align"] = {"centro": "center", "centre": "center", "direita": "right", "esquerda": "left",
                           "justify": "left"}.get(al, al if al in ("left", "center", "right") else "left")
            if e.get("frame"):
                el["frame"] = True
        elif tipo == "table":
            linhas = e.get("rows", e.get("linhas"))
            if isinstance(linhas, list):
                el["rows"] = [[_texto(c, 300) for c in (r if isinstance(r, (list, tuple)) else [r])]
                              for r in linhas][:200]
            else:
                el["rows"] = []
            if e.get("text"):
                el["text"] = _texto(e.get("text"))
            if str(e.get("block", "")).lower() in BLOCOS_AREAS:
                el["block"] = str(e.get("block")).lower()
            if e.get("title"):
                el["title"] = _texto(e.get("title"), 200)
        elif tipo in TIPOS_VINCULADOS:
            if e.get("map_id") or e.get("mapa"):
                el["map_id"] = str(e.get("map_id") or e.get("mapa"))
            if tipo == "north":
                modo = str(e.get("north_mode", "true")).lower()
                el["north_mode"] = "grid" if modo in ("grid", "grade", "norte de grade") else "true"
            if tipo == "scale":
                estilo = str(e.get("style", "bar")).lower()
                el["style"] = "numeric" if estilo in ("numeric", "numerica", "numérica", "number") else "bar"
            if tipo == "legend" and e.get("title") is not None:
                el["title"] = _texto(e.get("title"), 200)
        elif tipo == "picture":
            papel = str(e.get("role", e.get("papel", ""))).lower()
            if papel in ("logo", "logotipo") or str(e.get("type", "")).lower() == "logo":
                papel = "logo"
            el["role"] = papel if papel in ("logo", "assinatura", "imagem") else "imagem"
            if e.get("description") or e.get("descricao"):
                el["description"] = _texto(e.get("description") or e.get("descricao"), 300)
        elif tipo == "map":
            papel = str(e.get("role", e.get("papel", "principal"))).lower()
            el["role"] = papel if papel in ("principal", "localizacao", "detalhe") else "principal"
            cfg = dict(e.get("map") or {})
            if origem != "usuario":
                cfg.pop("_origem_usuario", None)
                cfg.pop("manual_extent", None)
            el["map"] = _normalizar_mapa(cfg)
            if e.get("description") or e.get("descricao"):
                el["description"] = _texto(e.get("description") or e.get("descricao"), 300)
        elif tipo in ("shape", "line"):
            if e.get("fill"):
                el["fill"] = bool(e.get("fill"))
        # campos opcionais comuns
        if isinstance(e.get("review"), list):
            el["review"] = [_texto(x, 300) for x in e["review"]][:20]
        if e.get("probable_map"):
            el["probable_map"] = True
        elementos.append(el)

    if not elementos:
        raise ErroContrato("A proposta não tem nenhum elemento válido.")

    # vínculos
    mapas = [e["id"] for e in elementos if e["type"] == "map"]
    for el in elementos:
        if el["type"] in TIPOS_VINCULADOS and el.get("map_id") and el["map_id"] not in mapas:
            avisos.append(f"Elemento '{el['id']}': mapa vinculado '{el['map_id']}' não existe; vínculo removido.")
            el.pop("map_id")

    return {
        "versao": VERSAO_CONTRATO,
        "page": {"width_mm": largura, "height_mm": altura},
        "elements": elementos,
    }, avisos


def para_mm(el, pagina):
    """Converte a caixa fracionária de um elemento para milímetros."""
    W, H = pagina["width_mm"], pagina["height_mm"]
    return el["x"] * W, el["y"] * H, el["w"] * W, el["h"] * H


def copiar(proposta):
    return copy.deepcopy(proposta)


def contar_por_tipo(proposta):
    contagem = {t: 0 for t in TIPOS}
    for el in proposta.get("elements", []):
        contagem[el["type"]] = contagem.get(el["type"], 0) + 1
    return contagem
