"""Variazione di oggi del portafoglio, pensata per il telefono.

Titoli e quantità NON stanno nel codice: si leggono dai secrets di Streamlit
(.streamlit/secrets.toml in locale, Settings > Secrets su Streamlit Cloud).
Prezzi: Yahoo Finance, dato non ufficiale e possibilmente in ritardo.
"""
import datetime as dt
import hmac
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import requests
import streamlit as st

ROMA = ZoneInfo("Europe/Rome")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

st.set_page_config(page_title="Variazione oggi", page_icon="📈", layout="centered")

st.markdown("""
<style>
.block-container {padding: 1rem 0.8rem 2rem; max-width: 560px;}
header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {display: none !important;}
.titolo {font-size: 1.35rem; font-weight: 700; margin: 0 0 8px;}
.tot {border-radius: 14px; padding: 14px 16px; margin: 4px 0 10px; background: var(--card);}
.tot .lbl {font-size: .85rem; opacity: .75;}
.tot .big {font-size: 2.1rem; font-weight: 700; line-height: 1.15;}
.tot .sub {font-size: 1rem; margin-top: 2px;}
.card {display: flex; justify-content: space-between; align-items: center; gap: 10px;
       padding: 11px 14px; margin: 6px 0; border-radius: 12px; background: var(--card);}
.card .nome {font-weight: 600; font-size: 1.02rem;}
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
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- accesso
def accesso_ok() -> bool:
    pwd = st.secrets.get("password")
    if not pwd or st.session_state.get("ok"):
        return True
    st.markdown("### Variazione oggi")
    tentativo = st.text_input("Password", type="password")
    if tentativo:
        if hmac.compare_digest(tentativo, str(pwd)):
            st.session_state["ok"] = True
            st.rerun()
        st.error("Password errata")
    return False


# ----------------------------------------------------------------------------- dati
def _serie(sim: str):
    """(chiusure {data: prezzo}, ultimo prezzo, orario ultimo prezzo)."""
    for _ in range(3):
        r = requests.get(URL.format(sim), params={"range": "10d", "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
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


def _prima_di(chiusure: dict, giorno: dt.date):
    prec = [d for d in chiusure if d < giorno]
    return (max(prec), chiusure[max(prec)]) if prec else (None, None)


def quota(sim: str) -> dict:
    """Prezzo, chiusura precedente e orario. 'AMZN/EURUSD=X' = titolo in USD convertito in euro."""
    if "/" in sim:
        tit, cam = sim.split("/")
        ct, pt, qt = _serie(tit)
        cc, pc, _ = _serie(cam)
        d_prec, c_prec = _prima_di(ct, qt.date())
        fx_prec = None
        if d_prec:
            _, fx_prec = _prima_di(cc, d_prec + dt.timedelta(days=1))
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


def classe(x: float) -> str:
    return "su" if x > 0.00005 else "giu" if x < -0.00005 else "par"


# ----------------------------------------------------------------------------- pagina
if not accesso_ok():
    st.stop()

titoli = [t for t in st.secrets.get("titoli", []) if float(t.get("quantita", 0)) > 0]
if not titoli:
    st.error("Nessun titolo configurato nei secrets (sezione [[titoli]]).")
    st.stop()

st.markdown('<div class="titolo">Variazione oggi</div>', unsafe_allow_html=True)
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
    righe.append({"nome": t["nome"], "prezzo": d["prezzo"], "var": var, "impatto": impatto,
                  "valore": q * d["prezzo"], "q": q, "ora": d["ora"].astimezone(ROMA)})

valore = sum(r["valore"] for r in righe)
impatto = sum(r["impatto"] for r in righe)
var_tot = impatto / (valore - impatto) if valore - impatto else 0.0
ultima = max((r["ora"] for r in righe), default=dati["_alle"])
oggi = dt.datetime.now(ROMA).date()
etichetta = "Variazione di oggi" if ultima.date() == oggi else f"Ultima seduta, {ultima:%d/%m}"

st.markdown(f"""
<div class="tot">
  <div class="lbl">{etichetta}</div>
  <div class="big {classe(impatto)}">{eur(impatto, True)}</div>
  <div class="sub"><span class="{classe(var_tot)}"><b>{pct(var_tot)}</b></span>
     &nbsp;·&nbsp; valore {eur(valore)}</div>
</div>
""", unsafe_allow_html=True)

ordine = st.radio("Ordina per", ["Impatto €", "Variazione %", "Nome"], horizontal=True,
                  label_visibility="collapsed")
chiave = {"Impatto €": lambda r: -r["impatto"], "Variazione %": lambda r: -r["var"],
          "Nome": lambda r: r["nome"].lower()}[ordine]

html = []
for r in sorted(righe, key=chiave):
    prezzo = f"{r['prezzo']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    html.append(f"""
<div class="card">
  <div><div class="nome">{r['nome']}</div>
       <div class="dett">{prezzo} € · {f"{r['q']:,.0f}".replace(",", ".")} pz · {r['ora']:%d/%m %H:%M}</div></div>
  <div class="dx"><div class="pct {classe(r['var'])}">{pct(r['var'])}</div>
       <div class="eur {classe(r['impatto'])}">{eur(r['impatto'], True)}</div></div>
</div>""")
st.markdown("".join(html), unsafe_allow_html=True)

if errori:
    st.warning("Prezzo non disponibile per: " + ", ".join(errori))

st.markdown(f"""<div class="nota">Aggiornato alle {dati['_alle']:%H:%M:%S} · fonte Yahoo Finance,
dato non ufficiale e con possibile ritardo. Variazione rispetto alla chiusura della seduta precedente.</div>""",
            unsafe_allow_html=True)
