"""Nucleo comune delle app da cellulare (una app per portafoglio).

Ogni app è un file piccolo che chiama main() con titolo e icona; posizioni e password
NON stanno nel codice ma nei secrets di Streamlit (Settings > Secrets su Streamlit Cloud).

Simboli accettati in [[titoli]].simbolo:
  "PRY.MI"              Yahoo Finance (azioni, ETF, fondi 0P...)
  "AMZN/EURUSD=X"       prezzo in valuta diviso il cambio = prezzo in euro
  "ft:IE00BD4GTQ32:EUR" scheda fondo del Financial Times (fondi assenti su Yahoo)
Prezzi non ufficiali e possibilmente in ritardo.
"""
import datetime as dt
import hmac
import re
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import requests
import streamlit as st

ROMA = ZoneInfo("Europe/Rome")
URL_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
URL_FT = "https://markets.ft.com/data/funds/tearsheet/summary"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

CSS = """
<style>
.block-container {padding: 1rem 0.8rem 2rem; max-width: 560px;}
header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {display: none !important;}
.titolo {font-size: 1.35rem; font-weight: 700; margin: 0 0 8px;}
.tot {border-radius: 14px; padding: 14px 16px; margin: 4px 0 10px; background: var(--card);}
.tot .lbl {font-size: .85rem; opacity: .75;}
.tot .big {font-size: 2.1rem; font-weight: 700; line-height: 1.15;}
.tot .sub {font-size: 1rem; margin-top: 2px;}
.card {padding: 11px 14px; margin: 6px 0; border-radius: 12px; background: var(--card);}
.riga {display: flex; justify-content: space-between; align-items: center; gap: 10px;}
.carico {display: flex; justify-content: space-between; margin-top: 7px; padding-top: 6px;
         border-top: 1px solid rgba(127,127,127,.2); font-size: .85rem;}
.carico .val {font-weight: 600;}
.tot .sep {border-top: 1px solid rgba(127,127,127,.25); margin: 10px 0 8px;}
.tot .med {font-size: 1.35rem; font-weight: 700;}
.card .nome {font-weight: 600; font-size: 1.02rem;}
.card .valf {font-size: 1rem; margin-top: 3px;}
.card .valf b {font-size: 1.15rem;}
.card .dett {font-size: .8rem; opacity: .7; margin-top: 2px;}
.card .dx {text-align: right; white-space: nowrap;}
.card .pct {font-weight: 700; font-size: 1.1rem;}
.card .eur {font-size: .85rem;}
.su {color: #16a34a;} .giu {color: #dc2626;} .par {opacity: .7;}
:root {--card: rgba(127,127,127,.10);}
.stButton, .stButton button {width: 100% !important;}
.stButton button { height: 3rem; font-size: 1.05rem; font-weight: 600;}
.nota {font-size: .75rem; opacity: .6; margin-top: 14px;}
</style>
"""


# ----------------------------------------------------------------------------- dati
def _serie_yahoo(sim: str):
    """(chiusure {data: prezzo}, ultimo prezzo, orario ultimo prezzo)."""
    for _ in range(3):
        r = requests.get(URL_YAHOO.format(sim), params={"range": "1mo", "interval": "1d"},
                         headers=UA, timeout=15)
        if r.status_code != 429:
            break
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    m = res["meta"]
    quando = dt.datetime.fromtimestamp(m["regularMarketTime"], dt.timezone.utc)
    prezzo = float(m["regularMarketPrice"])
    chiusure = {}
    for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]):
        if c is not None:
            chiusure[dt.datetime.fromtimestamp(t, dt.timezone.utc).date()] = float(c)
    # Yahoo lascia spesso a null la candela dell'ultima seduta: uso il prezzo dei metadati
    chiusure[quando.date()] = prezzo
    return chiusure, prezzo, quando


def _num(s: str) -> float:
    return float(s.replace(",", "").strip())


def _serie_ft(sim: str):
    """Scheda fondo FT: ultimo NAV, variazione rispetto al NAV precedente e data."""
    _, isin, val = sim.split(":")
    t = requests.get(URL_FT, params={"s": f"{isin}:{val}"}, headers=UA, timeout=20).text
    v = re.findall(r'mod-ui-data-list__value">(.*?)</span>', t, re.S)
    if len(v) < 2:
        raise ValueError("FT: fondo non trovato")
    prezzo = _num(re.sub("<.*?>", "", v[0]))
    var = _num(re.sub("<.*?>", "", v[1]).split("/")[0])
    m = re.search(r"as of ([A-Z][a-z]{2} \d{1,2} \d{4})", t)
    if not m:
        raise ValueError("FT: data del NAV non trovata")
    giorno = dt.datetime.strptime(m.group(1), "%b %d %Y").date()
    quando = dt.datetime.combine(giorno, dt.time(12), dt.timezone.utc)
    return {giorno - dt.timedelta(days=1): prezzo - var, giorno: prezzo}, prezzo, quando


def _serie(sim: str):
    return _serie_ft(sim) if sim.startswith("ft:") else _serie_yahoo(sim)


def _prima_di(chiusure: dict, giorno: dt.date):
    prec = [d for d in chiusure if d < giorno]
    return (max(prec), chiusure[max(prec)]) if prec else (None, None)


def quota(sim: str) -> dict:
    """Prezzo, prezzo precedente e orario. 'X/EURUSD=X' = prezzo in valuta convertito in euro."""
    if "/" in sim:
        tit, cam = sim.split("/")
        ct, pt, qt = _serie(tit)
        cc, pc, _ = _serie(cam)
        d_prec, c_prec = _prima_di(ct, qt.date())
        fx_prec = _prima_di(cc, d_prec + dt.timedelta(days=1))[1] if d_prec else None
        # valore in euro al cambio attuale (come la macro Excel)
        return {"prezzo": pt / pc, "prec": c_prec / fx_prec if c_prec and fx_prec else None, "ora": qt}
    c, p, q = _serie(sim)
    _, prec = _prima_di(c, q.date())
    return {"prezzo": p, "prec": prec, "ora": q}


@st.cache_data(ttl=60, show_spinner=False)
def scarica(simboli: tuple) -> dict:
    def uno(s):
        try:
            return s, quota(s)
        except Exception as e:  # un titolo che non risponde non blocca gli altri
            return s, {"errore": str(e)[:80]}
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = dict(ex.map(uno, simboli))
    out["_alle"] = dt.datetime.now(ROMA)
    return out


# ----------------------------------------------------------------------------- formato
def eur(x: float, segno=False) -> str:
    s = f"{x:+,.0f}" if segno else f"{x:,.0f}"
    return s.replace(",", ".") + " €"


def pct(x: float) -> str:
    return f"{x:+.2%}".replace(".", ",")


def num_it(x: float, dec: int) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def classe(x: float) -> str:
    return "su" if x > 0.00005 else "giu" if x < -0.00005 else "par"


# ----------------------------------------------------------------------------- pagina
def accesso_ok(titolo: str) -> bool:
    pwd = st.secrets.get("password")
    if not pwd:  # senza password l'app non mostra nulla
        st.error("Password non configurata nei Secrets: aggiungi la riga password = \"...\".")
        return False
    if st.session_state.get("ok"):
        return True
    st.markdown(f"### {titolo}")
    tentativo = st.text_input("Password", type="password")
    if tentativo:
        if hmac.compare_digest(tentativo, str(pwd)):
            st.session_state["ok"] = True
            st.rerun()
        st.error("Password errata")
    return False


def main(titolo: str, icona: str = "📈", fondi: bool = False):
    """fondi=True: prezzi = NAV giornalieri, si mostra la data del NAV e non l'ora."""
    st.set_page_config(page_title=titolo, page_icon=icona, layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    if not accesso_ok(titolo):
        st.stop()

    titoli = [t for t in st.secrets.get("titoli", []) if float(t.get("quantita", 0)) > 0]
    if not titoli:
        st.error("Nessun titolo configurato nei secrets (sezione [[titoli]]).")
        st.stop()

    st.markdown(f'<div class="titolo">{titolo}</div>', unsafe_allow_html=True)
    if st.button("Aggiorna prezzi", type="primary", use_container_width=True):
        scarica.clear()

    with st.spinner("Scarico i prezzi..."):
        dati = scarica(tuple(t["simbolo"] for t in titoli))

    righe, errori = [], []
    for t in titoli:
        d = dati.get(t["simbolo"], {})
        if "errore" in d or not d.get("prezzo"):
            errori.append(t["nome"]); continue
        q = float(t["quantita"])
        var = d["prezzo"] / d["prec"] - 1 if d.get("prec") else 0.0
        impatto = q * (d["prezzo"] - d["prec"]) if d.get("prec") else 0.0
        inv = float(t.get("investito", 0) or 0)
        righe.append({"nome": t["nome"], "prezzo": d["prezzo"], "var": var, "impatto": impatto,
                      "valore": q * d["prezzo"], "q": q, "ora": d["ora"].astimezone(ROMA),
                      "inv": inv, "utile": q * d["prezzo"] - inv if inv else None})

    valore = sum(r["valore"] for r in righe)
    impatto = sum(r["impatto"] for r in righe)
    var_tot = impatto / (valore - impatto) if valore - impatto else 0.0
    con_carico = [r for r in righe if r["utile"] is not None]
    inv_tot = sum(r["inv"] for r in con_carico)
    utile_tot = sum(r["utile"] for r in con_carico)
    ultima = max((r["ora"] for r in righe), default=dati["_alle"])
    oggi = dt.datetime.now(ROMA).date()
    if fondi:
        # ogni fondo pubblica il NAV con il suo ritardo: si dichiarano tutte le date presenti
        date_nav = sorted({r["ora"].date() for r in righe})
        if len(date_nav) <= 1:
            etichetta = f"Ultima variazione dei NAV (al {ultima:%d/%m})"
        else:
            elenco = ", ".join(f"{d:%d/%m}" for d in date_nav[:-1]) + f" e {date_nav[-1]:%d/%m}"
            etichetta = f"Ultima variazione di ogni fondo (NAV al {elenco})"
        lab_v, lab_p = "Var. €", "Var. %"
    else:
        etichetta = "Variazione di oggi" if ultima.date() == oggi else f"Ultima seduta, {ultima:%d/%m}"
        lab_v, lab_p = "Oggi €", "Oggi %"

    st.markdown(f"""
<div class="tot">
  <div class="lbl">{etichetta}</div>
  <div class="big {classe(impatto)}">{eur(impatto, True)}</div>
  <div class="sub"><span class="{classe(var_tot)}"><b>{pct(var_tot)}</b></span>
     &nbsp;·&nbsp; valore {eur(valore)}</div>
  {f'''<div class="sep"></div>
  <div class="lbl">Dal carico (investiti {eur(inv_tot)})</div>
  <div class="med {classe(utile_tot)}">{eur(utile_tot, True)}
     <span style="font-size:1rem">{pct(utile_tot / inv_tot)}</span></div>''' if inv_tot else ''}
</div>
""", unsafe_allow_html=True)

    scelte = [lab_v, lab_p, "Dal carico"] + (["Valore"] if fondi else []) + ["Nome"]
    ordine = st.radio("Ordina per", scelte, horizontal=True, label_visibility="collapsed")
    chiave = {lab_v: lambda r: -r["impatto"], lab_p: lambda r: -r["var"],
              "Dal carico": lambda r: -(r["utile"] or 0), "Valore": lambda r: -r["valore"],
              "Nome": lambda r: r["nome"].lower()}[ordine]

    html = []
    for r in sorted(righe, key=chiave):
        if fondi:
            dett = (f"NAV {num_it(r['prezzo'], 3)} € · {num_it(r['q'], 3)} quote · "
                    f"al {r['ora']:%d/%m}")
        else:
            dett = (f"{num_it(r['prezzo'], 2)} € · {num_it(r['q'], 0)} pz · "
                    f"{r['ora']:%d/%m %H:%M}")
        valf = (f'<div class="valf">Valore attuale <b>{eur(r["valore"])}</b></div>'
                if fondi else "")
        carico = ""
        if r["utile"] is not None:
            carico = (f'<div class="carico"><span>Dal carico · investiti {eur(r["inv"])}</span>'
                      f'<span class="val {classe(r["utile"])}">{eur(r["utile"], True)} · '
                      f'{pct(r["utile"] / r["inv"])}</span></div>')
        html.append(f"""
<div class="card"><div class="riga">
  <div><div class="nome">{r['nome']}</div>{valf}<div class="dett">{dett}</div></div>
  <div class="dx"><div class="pct {classe(r['var'])}">{pct(r['var'])}</div>
       <div class="eur {classe(r['impatto'])}">{eur(r['impatto'], True)}</div></div>
</div>{carico}</div>""")
    st.markdown("".join(html), unsafe_allow_html=True)

    if errori:
        st.warning("Prezzo non disponibile per: " + ", ".join(errori))

    if fondi:
        spiega = ("fonti Yahoo Finance e Financial Times, dati non ufficiali. I NAV dei fondi sono "
                  "giornalieri e ogni società li pubblica con il suo ritardo (uno o due giorni), quindi "
                  "le date possono differire tra fondi; la variazione di ciascuno è rispetto al "
                  "suo NAV precedente.")
    else:
        spiega = ("fonte Yahoo Finance, dato non ufficiale e con possibile ritardo. "
                  "Oggi = rispetto alla chiusura della seduta precedente.")
    st.markdown(f"""<div class="nota">Aggiornato alle {dati['_alle']:%H:%M:%S} · {spiega}
Dal carico = valore attuale meno investito netto (al netto di dividendi incassati).</div>""",
                unsafe_allow_html=True)
