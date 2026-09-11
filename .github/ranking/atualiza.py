#!/usr/bin/env python3
"""O PLACAR DO CAMPEONATO, da Steam pro ranking.json — rodado de hora em hora pelo GitHub Actions.

SEM CHAVE NENHUMA. O placar público da Steam sai em XML no steamcommunity.com, e o nome e o
avatar de cada jogador saem do perfil, também em XML. Conferido em 11/09/2026 com o placar de um
jogo publicado. Isso importa porque o repositório do site é público: a chave de publisher nunca
pode morar aqui (ver docs/STEAM.md, 8.1, no repositório do jogo).

O QUE ELE LÊ é o campeonato.json, na raiz do site:

    appid     o app do jogo na Steam; null = ainda não existe, e o robô não faz nada
    edicoes   uma por mês: {"edicao": 1, "mes": "2026-10", "celestial": "bobo"}

A edição mostrada é a mais recente cujo mês já começou (em UTC). O placar de cada mês se chama
"campeonato_2026_10" — é o nome que o jogo cria, em scripts/jogo/campeonato.gd.

O QUE ELE ESCREVE é o ranking.json que a ranking.html lê. Só escreve se algo além da hora mudou:
commit de hora em hora com o mesmo placar é histórico sujo e nada mais.

Pra testar com outro jogo:
    python atualiza.py --appid 247080 --placar "DLC HARDCORE All Chars_PROD" --mes 2026-09 --saida teste.json
"""
import argparse
import datetime
import json
import os
import struct
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

SITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMUNIDADE = "https://steamcommunity.com"
QUANTOS = 50

# a ordem é a de Tipos.Raridade e MedidaPeixe no jogo — o número que viaja nos detalhes
RARIDADES = ["comum", "incomum", "raro", "epico", "lendario", "celestial"]
ESTRELAS = ["", "bronze", "prata", "ouro", "platina"]
VERSAO_DETALHES = 1


def baixa(url):
    req = urllib.request.Request(url, headers={"User-Agent": "a-deriva-ranking (github actions)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def detalhes(hexa):
    """A Valve devolve os inteiros dos detalhes como hex, 8 dígitos cada, little-endian."""
    hexa = (hexa or "").strip()
    return [struct.unpack("<i", bytes.fromhex(hexa[i:i + 8]))[0] for i in range(0, len(hexa) - 7, 8)]


def acha_placar(appid, nome):
    raiz = ET.fromstring(baixa("%s/stats/%s/leaderboards/?xml=1" % (COMUNIDADE, appid)))
    for lb in raiz.iter("leaderboard"):
        if (lb.findtext("name") or "") == nome:
            return lb.findtext("lbid")
    return None


def perfil(steamid):
    try:
        raiz = ET.fromstring(baixa("%s/profiles/%s/?xml=1" % (COMUNIDADE, steamid)))
        return raiz.findtext("steamID"), raiz.findtext("avatarMedium")
    except Exception as erro:  # perfil fora do ar não pode derrubar o placar inteiro
        print("  perfil %s não veio: %s" % (steamid, erro))
        return None, None


def melhor_lance(d):
    # são exatamente 5, e não "pelo menos 5": no teste com outro jogo, 6 inteiros quaisquer
    # começando por 1 viraram um lance de mentira
    if len(d) != 5 or d[0] != VERSAO_DETALHES:
        return None
    return {
        "raridade": RARIDADES[d[1]] if 0 <= d[1] < len(RARIDADES) else "",
        "estrela": ESTRELAS[d[2]] if 0 <= d[2] < len(ESTRELAS) else "",
        "cm": d[3] / 10,
        "pontos": d[4],
    }


def entradas(appid, lbid):
    url = "%s/stats/%s/leaderboards/%s/?xml=1&start=1&end=%d" % (COMUNIDADE, appid, lbid, QUANTOS)
    raiz = ET.fromstring(baixa(url))
    lista = []
    for en in raiz.iter("entry"):
        steamid = en.findtext("steamid")
        nome, avatar = perfil(steamid)
        item = {"nome": nome or "Pescador", "pontos": int(en.findtext("score") or 0)}
        if avatar:
            item["avatar"] = avatar
        lance = melhor_lance(detalhes(en.findtext("details")))
        if lance:
            item["melhor"] = lance
        lista.append(item)
        time.sleep(0.5)  # educação com o steamcommunity: são até 50 perfis por hora
    return lista


def mes_seguinte(mes):
    ano, m = (int(x) for x in mes.split("-"))
    return "%04d-%02d" % (ano + (m == 12), 1 if m == 12 else m + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appid")
    ap.add_argument("--placar", help="nome do placar, no lugar do campeonato_AAAA_MM")
    ap.add_argument("--mes", help="o mês de agora, AAAA-MM (padrão: o mês UTC corrente)")
    ap.add_argument("--saida", default=os.path.join(SITE, "ranking.json"))
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(SITE, "campeonato.json"), encoding="utf-8"))
    appid = args.appid or cfg.get("appid")
    if not appid:
        print("sem appid no campeonato.json: nada a fazer")
        return 0

    agora = datetime.datetime.now(datetime.timezone.utc)
    mes_agora = args.mes or agora.strftime("%Y-%m")
    comecadas = [e for e in cfg.get("edicoes", []) if e.get("mes") and e["mes"] <= mes_agora]
    if not comecadas:
        print("nenhuma edição começou até %s: nada a fazer" % mes_agora)
        return 0
    ed = max(comecadas, key=lambda e: e["mes"])

    nome = args.placar or "campeonato_" + ed["mes"].replace("-", "_")
    lbid = acha_placar(appid, nome)
    print("edição %s (%s): placar %s -> %s" % (ed.get("edicao"), ed["mes"], nome, lbid or "ainda não existe"))
    lista = entradas(appid, lbid) if lbid else []

    novo = {
        "edicao": ed.get("edicao", 1),
        "celestial": ed.get("celestial", "bobo"),
        "inicio": ed["mes"] + "-01T00:00:00Z",
        "fim": mes_seguinte(ed["mes"]) + "-01T00:00:00Z",
        "atualizado": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entradas": lista,
    }

    if os.path.exists(args.saida):
        try:
            velho = json.load(open(args.saida, encoding="utf-8"))
            if {k: v for k, v in velho.items() if k != "atualizado"} == \
               {k: v for k, v in novo.items() if k != "atualizado"}:
                print("placar igual ao publicado: nada a escrever")
                return 0
        except ValueError:
            pass

    with open(args.saida, "w", encoding="utf-8", newline="\n") as f:
        json.dump(novo, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("escrevi %s com %d entrada(s)" % (args.saida, len(lista)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
