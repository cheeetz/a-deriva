#!/usr/bin/env python3
"""O PLACAR DO CAMPEONATO, da Steam pro ranking.json — rodado de hora em hora pelo GitHub Actions.

SEM CHAVE NENHUMA. O placar público da Steam sai em XML no steamcommunity.com, e o nome e o
avatar de cada jogador saem do perfil, também em XML. Conferido em 11/09/2026 com o placar de um
jogo publicado. Isso importa porque o repositório do site é público: a chave de publisher nunca
pode morar aqui (ver docs/STEAM.md, 8.1, no repositório do jogo).

O QUE ELE LÊ é o campeonato.json, na raiz do site:

    appid     o app do jogo na Steam; null = ainda não existe, e o robô não faz nada
    edicoes   uma por mês: {"edicao": 1, "mes": "2026-10", "celestial": "bobo"}
              "teste": true marca uma temporada de TESTE, sem prêmio -- a de outubro/2026,
              do lançamento até a 1ª edição. O placar é o mesmo campeonato_AAAA_MM, e a página
              mostra que ele zera no mês seguinte.

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
# A VERSAO 2 (25/10/2026) mantem os cinco primeiros no lugar e acrescenta: [5] 1 se o melhor lance
# saiu no mapa do dia (em dobro), [6] a hora dele, [7] o dia dos lances de hoje, [8] quantos vem a
# seguir e [9...] o segundo do dia de cada um. Os horarios NAO vao pro ranking.json: o site so
# precisa do dobro, pra conferir o teto. A versao 1 continua valendo pra quem nao atualizou.
VERSAO_DETALHES = (1, 2)
VEZES_MAPA_DO_DIA = 2

# A CONFERENCIA DE PLAUSIBILIDADE, e por que ela existe (teste de vulnerabilidade de 11/10/2026).
# O placar da Steam e gravado pelo cliente: quem tem o jogo consegue mandar qualquer numero, com
# um programa qualquer ou um jogo modificado. Sem servidor nosso nao ha como impedir -- mas a
# regra do campeonato poe tetos que um numero inventado dificilmente respeita, e o robo confere:
#
#   1. o melhor lance nao passa do maximo da raridade e da estrela dele (no clique, x1,5; no mapa
#      do dia, x2 -- desde 25/10/2026);
#   2. o total nao passa de DIAS x 10 x o melhor lance -- cada dia conta 10 peixes, e nenhum
#      deles vale mais que o melhor do mes;
#   3. o total nao e menor que o melhor lance, e quem tem pontos tem melhor lance.
#
# QUEM FALHA NAO SOME: ganha "conferir" com o motivo, e a pagina mostra "em conferencia". A
# ranking.html promete que o placar inteiro fica publicado; o que decide o premio e o Jean,
# olhando o podio antes de conceder. Os numeros sao os de scripts/jogo/campeonato.gd no jogo.
PONTOS_RARIDADE = {"comum": 2, "incomum": 4, "raro": 10, "epico": 30, "lendario": 80,
                   "celestial": 3000}   # o celestial varia por mapa; 3.000 e o de Noronha, o maior
VEZES_ESTRELA = {"bronze": 1, "prata": 2, "ouro": 3, "platina": 5}
# O TETO DO CELESTIAL POR VERSAO DOS DETALHES. Desde a 1.3 (25/10/2026) o celestial cresce pela
# raiz da raridade e o maior e o do Sao Francisco, 1.340; quem ainda manda a versao 1 jogou pela
# regra antiga, em que o de Noronha valia 3.000, e nao pode ser marcado por isso.
CELESTIAL_POR_VERSAO = {1: 3000, 2: 1340}
MELHORES_POR_DIA = 10


def dias_decorridos(mes, agora):
    """Quantos dias (UTC) da edicao ja comecaram: o dia de hoje conta, o mes fechado conta inteiro."""
    ini = datetime.datetime.strptime(mes + "-01", "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    fim = datetime.datetime.strptime(mes_seguinte(mes) + "-01", "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    if agora >= fim:
        return (fim - ini).days
    return max(1, (agora - ini).days + 1)


def conferir(item, dias):
    """O motivo da suspeita, ou None se a entrada respeita os tetos da regra."""
    total = item.get("pontos", 0)
    m = item.get("melhor")
    if total <= 0:
        return None
    if not m or not m.get("pontos"):
        return "sem o melhor lance"
    base = PONTOS_RARIDADE.get(m.get("raridade"), 0)
    if m.get("raridade") == "celestial":
        # O MELHOR DE ANTES DA ATUALIZACAO (26/10/2026). Quem pescou o melhor do mes na 1.2 e
        # atualizou no meio do mes manda os detalhes na versao 2, mas com o melhor lance da regra
        # antiga -- e ele chega sem hora, porque a 1.2 nao gravava. Sem hora, vale o teto antigo.
        versao = m.get("versao", 1)
        if versao == 2 and not m.get("hora"):
            versao = 1
        base = CELESTIAL_POR_VERSAO.get(versao, 3000)
    teto_lance = base * VEZES_ESTRELA.get(m.get("estrela"), 0) * 1.5
    if m.get("dobro"):
        teto_lance *= VEZES_MAPA_DO_DIA
    if m["pontos"] > teto_lance:
        return "melhor lance acima do maximo da raridade"
    if total < m["pontos"]:
        return "total menor que o melhor lance"
    if total > dias * MELHORES_POR_DIA * m["pontos"]:
        return "total acima do possivel em %d dia(s)" % dias
    return None


def baixa(url):
    # A COMUNIDADE GUARDA CACHE POR URL: em 14/10/2026 o placar já estava público e a mesma URL
    # ainda devolvia "No public global leaderboards" por um bom tempo. Um parâmetro que muda a
    # cada passada pula esse cache -- e o das entradas também, que é o que anda.
    url += ("&" if "?" in url else "?") + "_=%d" % time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "a-deriva-ranking (github actions)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def detalhes(hexa):
    """A Valve devolve os inteiros dos detalhes como hex, 8 dígitos cada, little-endian."""
    hexa = (hexa or "").strip()
    return [struct.unpack("<i", bytes.fromhex(hexa[i:i + 8]))[0] for i in range(0, len(hexa) - 7, 8)]


def acha_placar(appid, nome):
    bruto = baixa("%s/stats/%s/leaderboards/?xml=1" % (COMUNIDADE, appid))
    try:
        raiz = ET.fromstring(bruto)
    except ET.ParseError:
        # APP SEM PÁGINA PÚBLICA responde a página de ERRO da comunidade -- HTML, e com status
        # 200, então nem o urlopen reclama. Foi o que o 5284480 devolveu em 16/09/2026, antes de
        # a loja abrir. Não é defeito nosso, e não pode derrubar um robô que roda de hora em
        # hora: sem placar, a página fica vazia e o mês segue.
        print("  a comunidade não devolveu XML (app sem página pública?): sem placar por ora")
        return None
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
    # o tamanho exato de cada versão, e não "pelo menos 5": no teste com outro jogo, 6 inteiros
    # quaisquer começando por 1 viraram um lance de mentira
    if not d or d[0] not in VERSAO_DETALHES:
        return None
    if d[0] == 1 and len(d) != 5:
        return None
    if d[0] == 2 and (len(d) < 9 or not 0 <= d[8] <= MELHORES_POR_DIA or len(d) != 9 + d[8]):
        return None
    lance = {
        "raridade": RARIDADES[d[1]] if 0 <= d[1] < len(RARIDADES) else "",
        "estrela": ESTRELAS[d[2]] if 0 <= d[2] < len(ESTRELAS) else "",
        "cm": d[3] / 10,
        "pontos": d[4],
    }
    if d[0] == 2:
        lance["versao"] = 2
        if d[5] == 1:
            lance["dobro"] = True
        if d[6] > 0:
            lance["hora"] = True   # so o fato: a hora mesmo nao vai pro ranking.json
    return lance


def entradas(appid, lbid, fora=()):
    """As entradas do placar, sem as contas desclassificadas (campeonato.json, "desclassificados").

    DESCLASSIFICADO SAI DA LISTA, por conta e nao por nome (21/10/2026): nome a pessoa troca
    quando quer, a conta nao. O "conferir" de baixo continua sendo o primeiro aviso; a lista e a
    decisao do Jean depois de olhar, e quem esta nela nao aparece mais no site.
    O QUANTOS conta depois da peneira, pra lista publicada nao encolher por causa dela."""
    url = "%s/stats/%s/leaderboards/%s/?xml=1&start=1&end=%d" % (COMUNIDADE, appid, lbid, QUANTOS + len(fora))
    raiz = ET.fromstring(baixa(url))
    lista = []
    for en in raiz.iter("entry"):
        steamid = en.findtext("steamid")
        if steamid in fora:
            continue
        if len(lista) >= QUANTOS:
            break
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
    fora = set(str(s) for s in cfg.get("desclassificados", []))
    lista = entradas(appid, lbid, fora) if lbid else []
    dias = dias_decorridos(ed["mes"], agora)
    for item in lista:
        motivo = conferir(item, dias)
        if motivo:
            item["conferir"] = motivo
            print("  EM CONFERENCIA: %s (%d pts) -- %s" % (item["nome"], item["pontos"], motivo))

    novo = {
        "edicao": ed.get("edicao", 1),
        "teste": bool(ed.get("teste", False)),
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
