"""
app.py — Dashboard Financeiro Pessoal (v2 — redesign visual)
Rodar: streamlit run app.py
"""

import calendar
import hashlib
import re
from datetime import date as _date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import finance_utils as fu
import cloud_storage

# Sincronizar dados da nuvem (GitHub Gist) no início de cada deployment
cloud_storage.sync_from_cloud()

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Finanças Pessoais",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS Customizado — tema verde suave
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* ============ GLOBAL ============ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* Hide default Streamlit header/footer */
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}

/* ============ SIDEBAR ============ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1B5E40 0%, #2E7D5B 40%, #3A9D6F 100%);
    color: white;
}
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] .stCaption {
    color: white !important;
}
section[data-testid="stSidebar"] .stRadio > div > label {
    color: rgba(255,255,255,0.85) !important;
    padding: 6px 12px;
    border-radius: 8px;
    transition: all 0.2s;
}
section[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: rgba(255,255,255,0.12);
}
section[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"],
section[data-testid="stSidebar"] .stRadio [aria-checked="true"] + label {
    background: rgba(255,255,255,0.2) !important;
    color: white !important;
    font-weight: 600;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.2);
}

/* Sidebar balance card at bottom */
.sidebar-balance {
    background: rgba(255,255,255,0.15);
    border-radius: 12px;
    padding: 16px;
    margin-top: 12px;
    text-align: center;
    backdrop-filter: blur(4px);
}
.sidebar-balance .balance-label {
    font-size: 0.75rem;
    color: rgba(255,255,255,0.7);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 4px;
}
.sidebar-balance .balance-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: white;
}
.sidebar-balance .balance-period {
    font-size: 0.7rem;
    color: rgba(255,255,255,0.6);
    margin-top: 4px;
}

/* Section headers in sidebar */
.sidebar-section {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: rgba(255,255,255,0.45);
    margin-top: 16px;
    margin-bottom: 4px;
    font-weight: 600;
}

/* ============ MAIN CONTENT ============ */
.main .block-container {
    padding-top: 1.5rem;
    max-width: 1200px;
}

/* Page title */
.page-title {
    font-size: 1.6rem;
    font-weight: 700;
    color: #1B5E40;
    margin-bottom: 4px;
}
.page-subtitle {
    font-size: 0.85rem;
    color: #888;
    margin-bottom: 20px;
}

/* ============ METRIC CARDS ============ */
.metric-card {
    background: white;
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 1px solid #f0f0f0;
    text-align: left;
    transition: transform 0.2s, box-shadow 0.2s;
    height: 100%;
}
.metric-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}
.metric-card .mc-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    margin-bottom: 12px;
}
.metric-card .mc-label {
    font-size: 0.75rem;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    font-weight: 500;
}
.metric-card .mc-value {
    font-size: 1.35rem;
    font-weight: 700;
    margin-bottom: 2px;
}
.metric-card .mc-sub {
    font-size: 0.7rem;
    color: #aaa;
}

/* Card color variants */
.mc-green .mc-icon { background: #E8F5E9; color: #2E7D32; }
.mc-green .mc-value { color: #2E7D32; }
.mc-red .mc-icon { background: #FFEBEE; color: #C62828; }
.mc-red .mc-value { color: #C62828; }
.mc-blue .mc-icon { background: #E3F2FD; color: #1565C0; }
.mc-blue .mc-value { color: #1565C0; }
.mc-amber .mc-icon { background: #FFF8E1; color: #F57F17; }
.mc-amber .mc-value { color: #F57F17; }
.mc-teal .mc-icon { background: #E0F2F1; color: #00695C; }
.mc-teal .mc-value { color: #00695C; }

/* ============ SECTION CARDS ============ */
.section-card {
    background: white;
    border-radius: 14px;
    padding: 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 1px solid #f0f0f0;
    margin-bottom: 16px;
}
.section-card h3 {
    font-size: 1rem;
    font-weight: 600;
    color: #333;
    margin-bottom: 16px;
}

/* ============ PROGRESS BARS (budget limits) ============ */
.limit-item {
    padding: 12px 0;
    border-bottom: 1px solid #f5f5f5;
}
.limit-item:last-child {
    border-bottom: none;
}
.limit-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}
.limit-cat {
    font-weight: 600;
    font-size: 0.85rem;
    color: #333;
}
.limit-values {
    font-size: 0.75rem;
    color: #888;
}
.limit-bar-bg {
    width: 100%;
    height: 8px;
    background: #f0f0f0;
    border-radius: 4px;
    overflow: hidden;
}
.limit-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}
.limit-pct {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 12px;
    display: inline-block;
}
.pct-ok { background: #E8F5E9; color: #2E7D32; }
.pct-warn { background: #FFF8E1; color: #F57F17; }
.pct-danger { background: #FFEBEE; color: #C62828; }

/* ============ TRANSACTION LIST ============ */
.tx-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid #f5f5f5;
}
.tx-item:last-child { border-bottom: none; }
.tx-left {
    display: flex;
    align-items: center;
    gap: 12px;
}
.tx-icon {
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: #f5f5f5;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
}
.tx-desc {
    font-weight: 500;
    font-size: 0.85rem;
    color: #333;
}
.tx-meta {
    font-size: 0.7rem;
    color: #999;
}
.tx-valor-neg {
    font-weight: 600;
    color: #C62828;
    font-size: 0.9rem;
}
.tx-valor-pos {
    font-weight: 600;
    color: #2E7D32;
    font-size: 0.9rem;
}

/* ============ PERIOD BADGE ============ */
.period-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #f0f0f0;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.8rem;
    color: #555;
    font-weight: 500;
    margin-bottom: 16px;
}

/* ============ SUBSCRIPTION CARD ============ */
.sub-card {
    background: white;
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    border: 1px solid #f0f0f0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}
.sub-left {
    display: flex;
    align-items: center;
    gap: 14px;
}
.sub-icon {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    background: #f5f5f5;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
}
.sub-name {
    font-weight: 600;
    font-size: 0.9rem;
    color: #333;
}
.sub-detail {
    font-size: 0.72rem;
    color: #999;
}
.sub-valor {
    font-weight: 700;
    color: #C62828;
    font-size: 0.95rem;
}
.sub-dia {
    font-size: 0.7rem;
    color: #999;
}

/* ============ BILL ROW ============ */
.bill-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 0;
    border-bottom: 1px solid #f5f5f5;
}
.bill-row:last-child { border-bottom: none; }
.bill-nome { font-weight: 500; color: #333; font-size: 0.85rem; }
.bill-cat {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 500;
    background: #E8F5E9;
    color: #2E7D32;
}
.bill-venc { font-size: 0.8rem; color: #888; }
.bill-valor { font-weight: 600; color: #333; font-size: 0.85rem; }
.bill-pago {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 600;
}
.bill-pago-sim { background: #E8F5E9; color: #2E7D32; }
.bill-pago-nao { background: #FFEBEE; color: #C62828; }

/* ============ MISC ============ */
/* Slightly round all Streamlit dataframes */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
}

/* Remove Streamlit metric default styling when using custom cards */
div[data-testid="stMetric"] {
    background: white;
    border-radius: 12px;
    padding: 12px 16px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05);
    border: 1px solid #f0f0f0;
}

/* Plotly charts rounded */
.js-plotly-plot {
    border-radius: 12px;
}

/* Summary badges for bills page */
.summary-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 8px;
}
.badge-green { background: #E8F5E9; color: #2E7D32; }
.badge-red { background: #FFEBEE; color: #C62828; }
.badge-gray { background: #f0f0f0; color: #555; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Autenticação simples
# ---------------------------------------------------------------------------

def _check_auth() -> bool:
    """Returns True if the user is authenticated."""
    try:
        _expected = st.secrets["auth"]["password_hash"]
    except Exception:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown("## 🔒 Dashboard Financeiro Pessoal")
    st.markdown("Acesso restrito. Por favor, informe a senha.")
    _pw = st.text_input("Senha", type="password", key="_auth_pw")
    if st.button("Entrar", key="_auth_btn"):
        if hashlib.sha256(_pw.encode()).hexdigest() == _expected:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Senha incorreta. Tente novamente.")
    st.stop()
    return False

_check_auth()

MONTH_DIR = Path("data/monthly")
RECEITAS_PATH = Path("data/receitas.csv")

MONTH_DIR.mkdir(parents=True, exist_ok=True)
RECEITAS_PATH.parent.mkdir(parents=True, exist_ok=True)
if not RECEITAS_PATH.exists():
    pd.DataFrame(columns=fu.RECEITAS_COLS).to_csv(RECEITAS_PATH, index=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(v: float) -> str:
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"

def color_delta(v: float) -> str:
    return "normal" if v >= 0 else "inverse"

def month_label(ym: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.strptime(ym, "%Y-%m")
        return dt.strftime("%b/%Y").capitalize()
    except Exception:
        return ym

def month_label_full(ym: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.strptime(ym, "%Y-%m")
        meses = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
                 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
                 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
        return f"{meses.get(dt.month, dt.strftime('%B'))} de {dt.year}"
    except Exception:
        return ym

def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y}-{m:02d}"

def _prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m -= 1
    if m < 1:
        m, y = 12, y - 1
    return f"{y}-{m:02d}"

def _get_last_n_months(current: str, n: int) -> list:
    """Get list of last n months ending with current."""
    months = [current]
    ym = current
    for _ in range(n - 1):
        ym = _prev_month(ym)
        months.insert(0, ym)
    return months

def _cat_icon(cat: str) -> str:
    """Get emoji icon for a category."""
    icons = {
        "alimentação": "🍽️", "moradia": "🏠", "transporte": "🚗",
        "saúde": "💊", "lazer": "🎮", "educação": "📚",
        "tecnologia": "💻", "cuidados pessoais": "✂️", "casa": "🏡",
        "impostos": "📄", "entretenimento": "🎬", "móveis": "🪑",
        "vestuário": "👔", "freelance": "💼", "investimento": "📈",
    }
    return icons.get(cat.lower().strip(), "📌")

def _sub_icon(name: str) -> str:
    """Get emoji icon for a subscription."""
    icons = {
        "netflix": "🎬", "spotify": "🎵", "amazon": "📦",
        "disney": "🏰", "youtube": "▶️", "hbo": "🎭",
        "apple": "🍎", "google": "🔍", "chatgpt": "🤖",
        "gympass": "🏋️", "academia": "🏋️", "icloud": "☁️",
    }
    for key, icon in icons.items():
        if key in name.lower():
            return icon
    return "📱"


# ---------------------------------------------------------------------------
# Custom HTML card helpers
# ---------------------------------------------------------------------------

def metric_card(icon: str, label: str, value: str, sub: str, color_class: str):
    return f"""
    <div class="metric-card {color_class}">
        <div class="mc-icon">{icon}</div>
        <div class="mc-label">{label}</div>
        <div class="mc-value">{value}</div>
        <div class="mc-sub">{sub}</div>
    </div>
    """

# ---------------------------------------------------------------------------
# Load settings & compute saldo for sidebar
# ---------------------------------------------------------------------------

settings = fu.load_settings()
current_month = settings["current_month"]

# ---------------------------------------------------------------------------
# Sidebar — navegação
# ---------------------------------------------------------------------------

st.sidebar.markdown("""
<div style="text-align:center; padding: 10px 0 6px 0;">
    <div style="font-size: 2rem;">💰</div>
    <div style="font-size: 1.2rem; font-weight: 700; color: white;">Finanças Pessoais</div>
    <div style="font-size: 0.72rem; color: rgba(255,255,255,0.6);">Seu organizador financeiro</div>
</div>
""", unsafe_allow_html=True)

# All pages in a single radio with visual section labels
ALL_PAGES = [
    "— PRINCIPAL —",
    "📊 Dashboard",
    "💳 Transações",
    "📊 Orçamento",
    "📈 Anual",
    "— GESTÃO —",
    "🎯 Limites & Categorias",
    "📋 Contas a Pagar",
    "🔄 Assinaturas",
    "💳 Parcelamentos",
    "— DADOS —",
    "⬆️ Upload",
    "💵 Receitas",
    "📋 Relatório",
]

# Use selectbox for clean navigation with section headers
page = st.sidebar.radio(
    "Navegação",
    [p for p in ALL_PAGES if not p.startswith("—")],
    label_visibility="collapsed",
    key="nav_main",
)

# Inject section headers via CSS/HTML above the radio
st.sidebar.markdown("""
<style>
/* Style the radio to look like grouped navigation */
section[data-testid="stSidebar"] .stRadio > div {
    gap: 2px;
}
</style>
""", unsafe_allow_html=True)

# Sidebar — Config
st.sidebar.divider()
with st.sidebar.expander("⚙️ Configurações"):
    _cfg = fu.load_settings()
    st.caption(f"Mês atual: **{_cfg['current_month']}**")
    _new_month_input = st.text_input(
        "Editar mês (YYYY-MM)", value=_cfg["current_month"], key="cfg_month_input"
    )
    if st.button("Salvar", key="cfg_save_btn"):
        if re.match(r"^\d{4}-\d{2}$", _new_month_input.strip()):
            _cfg["current_month"] = _new_month_input.strip()
            fu.save_settings(_cfg)
            st.success("Salvo!")
            st.rerun()
        else:
            st.error("Formato inválido. Use YYYY-MM.")

    st.divider()
    st.caption("Grupos (1 por linha)")
    _grupos_txt = st.text_area(
        "Grupos",
        value="\n".join(_cfg.get("grupos_default", fu.GRUPOS_DEFAULT)),
        key="cfg_grupos_ta",
        label_visibility="collapsed",
        height=120,
    )
    st.caption("Contas / Cartões (1 por linha)")
    _contas_txt = st.text_area(
        "Contas",
        value="\n".join(_cfg.get("contas_default", fu.CONTAS_DEFAULT)),
        key="cfg_contas_ta",
        label_visibility="collapsed",
        height=100,
    )
    if st.button("Salvar listas", key="cfg_listas_btn", use_container_width=True):
        _cfg["grupos_default"] = [g.strip() for g in _grupos_txt.splitlines() if g.strip()]
        _cfg["contas_default"] = [c.strip() for c in _contas_txt.splitlines() if c.strip()]
        fu.save_settings(_cfg)
        st.success("Listas salvas!")
        st.rerun()

    st.divider()
    if st.button("📦 Backup agora", key="cfg_backup_btn", use_container_width=True):
        try:
            _bk_path = fu.backup_data_dir()
            st.success(f"Backup criado!")
        except Exception as _bk_err:
            st.error(f"Erro no backup: {_bk_err}")

# Sidebar — Saldo do período
_sb_receitas = fu.load_receitas(RECEITAS_PATH)
_sb_rec_mes = _sb_receitas[_sb_receitas["mes"] == current_month]["valor"].sum() if not _sb_receitas.empty else 0.0

_sb_base = fu.safe_load_month_csv(current_month, MONTH_DIR)
_sb_base_total = _sb_base["real"].sum() if not _sb_base.empty and "real" in _sb_base.columns else 0.0
_sb_trans = fu.load_transactions(current_month)
_sb_trans_total = _sb_trans["valor"].sum() if not _sb_trans.empty else 0.0
_sb_inst = fu.get_installments_for_month(current_month)
_sb_inst_total = _sb_inst["valor_parcela"].sum() if not _sb_inst.empty else 0.0
_sb_despesas = _sb_base_total + _sb_trans_total + _sb_inst_total
_sb_saldo = _sb_rec_mes - _sb_despesas

# Get first/last day of month
try:
    _sb_y = int(current_month[:4])
    _sb_m = int(current_month[5:7])
    _sb_last_day = calendar.monthrange(_sb_y, _sb_m)[1]
    _sb_period = f"01/{_sb_m:02d}/{_sb_y} — {_sb_last_day}/{_sb_m:02d}/{_sb_y}"
except Exception:
    _sb_period = current_month

st.sidebar.markdown(f"""
<div class="sidebar-balance">
    <div class="balance-label">Saldo do Período</div>
    <div class="balance-value" style="color: {'#81C784' if _sb_saldo >= 0 else '#EF9A9A'}">{fmt(_sb_saldo)}</div>
    <div class="balance-period">{_sb_period}</div>
</div>
""", unsafe_allow_html=True)


# ===========================================================================
# PÁGINA: DASHBOARD
# ===========================================================================

if page == "📊 Dashboard":
    st.markdown(f'<div class="page-title">Dashboard</div>', unsafe_allow_html=True)

    # Sync all sources to budget CSV before loading
    fu.sync_all_to_budget(current_month, MONTH_DIR)

    # Period badge
    try:
        _y = int(current_month[:4])
        _m = int(current_month[5:7])
        _last_day = calendar.monthrange(_y, _m)[1]
        period_str = f"📅 01/{_m:02d}/{_y} — {_last_day}/{_m:02d}/{_y}"
    except Exception:
        period_str = f"📅 {current_month}"

    st.markdown(f'<span class="period-badge">{period_str}</span>', unsafe_allow_html=True)

    # Load all data for current month
    df_base = fu.safe_load_month_csv(current_month, MONTH_DIR)
    if not df_base.empty:
        for _col in ("grupo", "conta_cartao", "nota"):
            if _col not in df_base.columns:
                df_base[_col] = ""

    df_trans = fu.load_transactions(current_month)
    df_inst = fu.get_installments_for_month(current_month)

    # Calculate totals
    base_real = df_base["real"].sum() if not df_base.empty and "real" in df_base.columns else 0.0
    trans_real = df_trans["valor"].sum() if not df_trans.empty else 0.0
    inst_real = df_inst["valor_parcela"].sum() if not df_inst.empty else 0.0
    total_despesas = base_real + trans_real + inst_real

    df_receitas = fu.load_receitas(RECEITAS_PATH)
    receita_mes = df_receitas[df_receitas["mes"] == current_month]["valor"].sum() if not df_receitas.empty else 0.0
    saldo = receita_mes - total_despesas

    # Budget limit alerts
    limits_status = fu.get_limits_status(current_month, MONTH_DIR)
    alerts_count = sum(1 for ls in limits_status if ls["pct_usado"] >= 80)

    # ---- Metric Cards ----
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card("💰", "Receita Total", fmt(receita_mes), "Período atual", "mc-green"), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("🛒", "Despesas Totais", fmt(total_despesas), "Período atual", "mc-red"), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("💎", "Saldo Líquido", fmt(saldo), "Receita − Despesas", "mc-teal" if saldo >= 0 else "mc-red"), unsafe_allow_html=True)
    with c4:
        alert_sub = f"{alerts_count} categoria(s) ≥ 80%" if alerts_count > 0 else "Tudo dentro do limite"
        st.markdown(metric_card("⚠️", "Alertas Limite", str(alerts_count), alert_sub, "mc-amber" if alerts_count > 0 else "mc-green"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Charts Row ----
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("#### 🍩 Gastos por Categoria")
        # Build category data from all sources
        cat_data = {}
        if not df_base.empty and "categoria" in df_base.columns:
            for cat, grp in df_base.groupby("categoria"):
                if str(cat).strip():
                    cat_data[str(cat)] = cat_data.get(str(cat), 0) + float(grp["real"].sum())
        if not df_trans.empty and "categoria" in df_trans.columns:
            for cat, grp in df_trans.groupby("categoria"):
                if str(cat).strip():
                    cat_data[str(cat)] = cat_data.get(str(cat), 0) + float(grp["valor"].sum())
        if not df_inst.empty and "categoria" in df_inst.columns:
            for cat, grp in df_inst.groupby("categoria"):
                if str(cat).strip():
                    cat_data[str(cat)] = cat_data.get(str(cat), 0) + float(grp["valor_parcela"].sum())

        if cat_data:
            cat_df = pd.DataFrame([
                {"categoria": k, "valor": v}
                for k, v in sorted(cat_data.items(), key=lambda x: x[1], reverse=True)
            ])
            colors = ["#2E7D32", "#43A047", "#66BB6A", "#81C784", "#A5D6A7",
                      "#C8E6C9", "#E8F5E9", "#FFF9C4", "#FFE082", "#FFCC80"]
            fig_donut = px.pie(
                cat_df, values="valor", names="categoria",
                hole=0.55,
                color_discrete_sequence=colors,
            )
            fig_donut.update_traces(
                textposition='inside',
                textinfo='percent',
                hovertemplate='%{label}<br>R$ %{value:,.2f}<extra></extra>',
            )
            fig_donut.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=True,
                legend=dict(orientation="h", yanchor="top", y=-0.1, x=0.5, xanchor="center"),
                height=350,
            )
            st.plotly_chart(fig_donut, use_container_width=True)

            # Category values list
            for _, row in cat_df.head(5).iterrows():
                st.markdown(f"**{_cat_icon(row['categoria'])} {row['categoria']}** — {fmt(row['valor'])}")
        else:
            st.info("Sem dados de despesas para este mês.")

    with col_chart2:
        st.markdown("#### 📊 Receitas vs Despesas — Evolução Mensal")

        # Historical totals (verified by user)
        _HISTORICAL_DESPESAS = {
            "2026-01": 11584.0,
            "2026-02": 14287.0,
            "2026-03": 12712.0,
        }

        # Build chart: last 3 historical months + current month + future months with data
        chart_rows = []

        # Add historical months
        for hm in sorted(_HISTORICAL_DESPESAS.keys()):
            _h_rec = df_receitas[df_receitas["mes"] == hm]["valor"].sum() if not df_receitas.empty else 0.0
            chart_rows.append({
                "mes": month_label(hm),
                "Receitas": _h_rec,
                "Despesas": _HISTORICAL_DESPESAS[hm],
            })

        # Add current month (live data)
        chart_rows.append({
            "mes": month_label(current_month),
            "Receitas": receita_mes,
            "Despesas": total_despesas,
        })

        # Add future months if they have data
        _check = _next_month(current_month)
        for _ in range(5):
            _m_csv_path = MONTH_DIR / f"despesas_{_check}.csv"
            if _m_csv_path.exists():
                _m_base = fu.safe_load_month_csv(_check, MONTH_DIR)
                _m_base_total = _m_base["real"].sum() if not _m_base.empty and "real" in _m_base.columns else 0.0
                _m_trans = fu.load_transactions(_check)
                _m_trans_total = _m_trans["valor"].sum() if not _m_trans.empty else 0.0
                _m_inst = fu.get_installments_for_month(_check)
                _m_inst_total = _m_inst["valor_parcela"].sum() if not _m_inst.empty else 0.0
                _m_desp = _m_base_total + _m_trans_total + _m_inst_total
                _m_rec = df_receitas[df_receitas["mes"] == _check]["valor"].sum() if not df_receitas.empty else 0.0
                if _m_desp > 0 or _m_rec > 0:
                    chart_rows.append({"mes": month_label(_check), "Receitas": _m_rec, "Despesas": _m_desp})
            _check = _next_month(_check)

        chart_df = pd.DataFrame(chart_rows)

        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=chart_df["mes"], y=chart_df["Receitas"],
            name="Receitas", marker_color="#43A047",
        ))
        fig_bar.add_trace(go.Bar(
            x=chart_df["mes"], y=chart_df["Despesas"],
            name="Despesas", marker_color="#EF5350",
        ))
        fig_bar.update_layout(
            barmode="group",
            margin=dict(t=10, b=40, l=40, r=10),
            height=350,
            legend=dict(orientation="h", yanchor="top", y=1.08, x=0.5, xanchor="center"),
            yaxis=dict(tickformat=",.0f", tickprefix="R$ "),
            xaxis=dict(tickangle=0),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Bottom Row: Recent Transactions + Budget Limits ----
    col_tx, col_limits = st.columns(2)

    with col_tx:
        st.markdown("#### ⏱️ Últimas Transações")

        # Build recent transactions list
        recent_items = []

        # From transactions
        if not df_trans.empty:
            for _, t in df_trans.iterrows():
                desc = str(t.get("descricao", "")).strip()
                nota = str(t.get("nota", "")).strip()
                cat = str(t.get("categoria", "")).strip()
                data = str(t.get("data", "")).strip()
                recent_items.append({
                    "desc": desc or nota or "—",
                    "meta": f"{data} · {cat}" if cat else data,
                    "valor": -float(t.get("valor", 0)),
                    "icon": _cat_icon(cat),
                    "date": data,
                })

        # From receitas for this month
        if not df_receitas.empty:
            rec_mes = df_receitas[df_receitas["mes"] == current_month]
            for _, r in rec_mes.iterrows():
                recent_items.append({
                    "desc": str(r.get("fonte", "Receita")),
                    "meta": f"{current_month} · Receita",
                    "valor": float(r.get("valor", 0)),
                    "icon": "💰",
                    "date": current_month + "-01",
                })

        # Sort by date desc, show last 8
        recent_items.sort(key=lambda x: x.get("date", ""), reverse=True)
        recent_items = recent_items[:8]

        if recent_items:
            for item in recent_items:
                val = item["valor"]
                val_class = "tx-valor-pos" if val > 0 else "tx-valor-neg"
                val_str = f"+{fmt(abs(val))}" if val > 0 else f"−{fmt(abs(val))}"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #f5f5f5;">'
                    f'<div style="display:flex;align-items:center;gap:12px;">'
                    f'<div style="width:36px;height:36px;border-radius:8px;background:#f5f5f5;display:flex;align-items:center;justify-content:center;font-size:0.9rem;">{item["icon"]}</div>'
                    f'<div>'
                    f'<div style="font-weight:500;font-size:0.85rem;color:#333;">{item["desc"]}</div>'
                    f'<div style="font-size:0.7rem;color:#999;">{item["meta"]}</div>'
                    f'</div>'
                    f'</div>'
                    f'<div class="{val_class}">{val_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Nenhuma transação recente.")

    with col_limits:
        st.markdown("#### 🎯 Limites — Situação")

        if limits_status:
            for ls in limits_status:
                pct = ls["pct_usado"]
                if pct < 70:
                    bar_color = "#43A047"
                    pct_class = "pct-ok"
                elif pct < 90:
                    bar_color = "#F9A825"
                    pct_class = "pct-warn"
                else:
                    bar_color = "#E53935"
                    pct_class = "pct-danger"
                bar_width = min(pct, 100)

                st.markdown(
                    f'<div class="section-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
                    f'<span style="font-weight:600;font-size:0.85rem;color:#333;">{_cat_icon(ls["categoria"])} {ls["categoria"]}</span>'
                    f'<span class="limit-pct {pct_class}">{pct:.0f}% usado</span>'
                    f'</div>'
                    f'<div style="width:100%;height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;">'
                    f'<div style="height:100%;width:{bar_width}%;background:{bar_color};border-radius:4px;"></div>'
                    f'</div>'
                    f'<div style="font-size:0.75rem;color:#888;margin-top:6px;">Gasto: {fmt(ls["gasto"])} / Limite: {fmt(ls["limite"])} — Restante: {fmt(ls["restante"])}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Summary
            ok_count = sum(1 for ls in limits_status if ls["pct_usado"] < 70)
            warn_count = sum(1 for ls in limits_status if 70 <= ls["pct_usado"] < 90)
            danger_count = sum(1 for ls in limits_status if ls["pct_usado"] >= 90)

            if ok_count:
                st.markdown(f'<div style="background:#E8F5E9;padding:8px 14px;border-radius:8px;margin-bottom:6px;font-size:0.8rem;color:#2E7D32;">🟢 {ok_count} categoria(s) dentro do limite</div>', unsafe_allow_html=True)
            if warn_count:
                st.markdown(f'<div style="background:#FFF8E1;padding:8px 14px;border-radius:8px;margin-bottom:6px;font-size:0.8rem;color:#F57F17;">🟡 {warn_count} categoria(s) perto do limite</div>', unsafe_allow_html=True)
            if danger_count:
                st.markdown(f'<div style="background:#FFEBEE;padding:8px 14px;border-radius:8px;margin-bottom:6px;font-size:0.8rem;color:#C62828;">🔴 {danger_count} categoria(s) acima de 90%</div>', unsafe_allow_html=True)
        else:
            st.info("Nenhum limite configurado. Vá em 🎯 Limites & Categorias para definir.")


# ===========================================================================
# PÁGINA: TRANSAÇÕES (antigo "Lançar Gasto")
# ===========================================================================

elif page == "💳 Transações":
    st.markdown('<div class="page-title">Transações</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{month_label_full(current_month)}</div>', unsafe_allow_html=True)

    # Flash de sucesso
    _flash = st.session_state.pop("_gasto_flash", None)
    if _flash:
        st.success(_flash)

    # --- Carregar transactions do mês ---
    df_trans = fu.load_transactions(current_month)

    # --- Modo edição ---
    edit_id = st.session_state.get("_trans_edit_id")
    edit_row = None
    is_edit = False
    if edit_id:
        rows = df_trans[df_trans["id"].astype(str) == str(edit_id)]
        if not rows.empty:
            edit_row = rows.iloc[0]
            is_edit = True
        else:
            st.session_state.pop("_trans_edit_id", None)

    # --- Categorias ---
    base_path = MONTH_DIR / f"despesas_{current_month}.csv"
    DEFAULT_CATS = [
        "Alimentação", "Moradia", "Transporte", "Saúde", "Lazer",
        "Educação", "Tecnologia", "Cuidados Pessoais", "Casa",
        "Impostos", "Entretenimento", "Outro",
    ]
    cat_options = DEFAULT_CATS[:]
    if base_path.exists():
        try:
            _bc = fu.load_month_csv(base_path)
            _bc_cats = sorted(c for c in _bc["categoria"].dropna().unique() if str(c).strip())
            if _bc_cats:
                cat_options = _bc_cats + [c for c in ["Outro"] if c not in _bc_cats]
        except Exception:
            pass

    _sg = settings.get("grupos_default", fu.GRUPOS_DEFAULT)
    GRUPOS = _sg if "Outro" in _sg else _sg + ["Outro"]
    _sc = settings.get("contas_default", fu.CONTAS_DEFAULT)
    CONTAS = _sc if "Outro" in _sc else _sc + ["Outro"]

    if is_edit:
        st.subheader(f"✏️ Editando: {edit_row.get('descricao', '') or edit_row.get('nota', '')}")
        if st.button("↩ Cancelar edição"):
            st.session_state.pop("_trans_edit_id", None)
            st.rerun()
    else:
        st.subheader("➕ Novo lançamento")

    def _get(field, default=""):
        if is_edit and edit_row is not None:
            v = edit_row.get(field, default)
            return v if str(v) not in ("nan", "None", "") else default
        return default

    def _cat_idx(val):
        try: return cat_options.index(val)
        except ValueError: return 0

    def _grupo_idx(val):
        try: return GRUPOS.index(val)
        except ValueError: return 0

    def _conta_idx(val):
        try: return CONTAS.index(val)
        except ValueError: return 0

    with st.form("form_gasto"):
        col1, col2 = st.columns(2)
        with col1:
            _data_default = _date.today()
            if is_edit:
                try:
                    from datetime import datetime as _dt2
                    _data_default = _dt2.strptime(_get("data"), "%Y-%m-%d").date()
                except Exception:
                    pass
            data_input = st.date_input("Data", value=_data_default)
            descricao_input = st.text_input("Descrição", value=_get("descricao"), placeholder="Ex: Almoço, Uber...")
            nota_input = st.text_input("Nota (opcional)", value=_get("nota"), placeholder="Ex: iFood #123")
            valor_input = st.number_input(
                "Valor (R$)", min_value=0.01, step=0.01, format="%.2f",
                value=max(0.01, float(edit_row["valor"]) if is_edit and edit_row is not None else 0.01),
            )
        with col2:
            cat_sel = st.selectbox("Categoria", cat_options, index=_cat_idx(_get("categoria")))
            cat_custom = st.text_input("Nova categoria", key="cat_cust") if cat_sel == "Outro" else ""
            grupo_sel = st.selectbox("Grupo", GRUPOS, index=_grupo_idx(_get("grupo")))
            grupo_custom = st.text_input("Novo grupo", key="grp_cust") if grupo_sel == "Outro" else ""
            conta_sel = st.selectbox("Conta / Cartão", CONTAS, index=_conta_idx(_get("conta_cartao")))
            conta_custom = st.text_input("Outra conta", key="cnt_cust") if conta_sel == "Outro" else ""
            recorrente_input = st.checkbox("Recorrente", value=bool(_get("recorrente", False)) if is_edit else False)

        btn_label = "💾 Salvar alterações" if is_edit else "💾 Salvar lançamento"
        submitted = st.form_submit_button(btn_label, use_container_width=True)

    if submitted:
        final_cat = cat_custom.strip() if cat_sel == "Outro" else cat_sel
        final_grupo = grupo_custom.strip() if grupo_sel == "Outro" else grupo_sel
        final_conta = conta_custom.strip() if conta_sel == "Outro" else conta_sel
        row = {
            "data": str(data_input),
            "descricao": descricao_input.strip(),
            "nota": nota_input.strip(),
            "categoria": final_cat,
            "grupo": final_grupo,
            "valor": float(valor_input),
            "conta_cartao": final_conta,
            "recorrente": recorrente_input,
        }
        if is_edit:
            fu.update_transaction(current_month, edit_id, row)
            st.session_state.pop("_trans_edit_id", None)
            st.session_state["_gasto_flash"] = "✅ Lançamento atualizado!"
        else:
            fu.append_transaction(current_month, row)
            st.session_state["_gasto_flash"] = "✅ Lançamento salvo!"
        st.rerun()

    # --- Tabela ---
    st.divider()
    st.subheader(f"Lançamentos — {month_label(current_month)}")

    df_trans = fu.load_transactions(current_month)
    if df_trans.empty:
        st.info("Nenhum lançamento neste mês.")
    else:
        df_show = df_trans.copy()
        df_show["valor"] = df_show["valor"].apply(fmt)
        show_cols = ["data", "descricao", "nota", "categoria", "grupo", "valor", "conta_cartao", "recorrente"]
        st.dataframe(
            df_show[[c for c in show_cols if c in df_show.columns]],
            use_container_width=True, hide_index=True,
        )
        st.metric("Total lançado", fmt(fu.load_transactions(current_month)["valor"].sum()))

        st.subheader("Gerenciar")
        col_e, col_d = st.columns(2)

        def _label(tid):
            r = df_trans[df_trans["id"].astype(str) == str(tid)]
            if r.empty: return tid
            r = r.iloc[0]
            desc = str(r.get("descricao", "")).strip() or str(r.get("nota", "")).strip() or "—"
            return f"{r.get('data', '')} | {desc} | {fmt(float(r.get('valor', 0)))}"

        ids = df_trans["id"].tolist()
        with col_e:
            st.caption("Editar")
            edit_sel = st.selectbox("Selecionar", ids, format_func=_label, key="edit_sel")
            if st.button("✏️ Carregar para edição"):
                st.session_state["_trans_edit_id"] = edit_sel
                st.rerun()
        with col_d:
            st.caption("Deletar")
            del_sel = st.selectbox("Selecionar", ids, format_func=_label, key="del_sel")
            if st.button("🗑️ Deletar", type="secondary"):
                fu.delete_transaction(current_month, str(del_sel))
                st.success("Deletado.")
                st.rerun()


# ===========================================================================
# PÁGINA: LIMITES & CATEGORIAS
# ===========================================================================

elif page == "🎯 Limites & Categorias":
    st.markdown('<div class="page-title">Limites & Categorias</div>', unsafe_allow_html=True)

    try:
        _y = int(current_month[:4])
        _m = int(current_month[5:7])
        _last_day = calendar.monthrange(_y, _m)[1]
        period_str = f"📅 01/{_m:02d}/{_y} — {_last_day}/{_m:02d}/{_y}"
    except Exception:
        period_str = f"📅 {current_month}"
    st.markdown(f'<span class="period-badge">{period_str}</span>', unsafe_allow_html=True)

    col_cats, col_limits = st.columns(2)

    with col_cats:
        st.subheader("📂 Categorias")
        st.caption("Gerencie suas categorias de gastos e receitas.")

        DEFAULT_CATS = [
            "Alimentação", "Moradia", "Transporte", "Saúde", "Lazer",
            "Educação", "Tecnologia", "Cuidados Pessoais", "Casa",
            "Impostos", "Entretenimento", "Vestuário",
        ]

        # Show existing categories as tags
        cats_html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;">'
        for cat in DEFAULT_CATS:
            cats_html += f'''
            <span style="display:inline-flex;align-items:center;gap:4px;padding:6px 14px;
            background:#E8F5E9;border-radius:20px;font-size:0.8rem;font-weight:500;color:#2E7D32;">
            {_cat_icon(cat)} {cat} <span style="font-size:0.65rem;background:#C8E6C9;padding:1px 6px;border-radius:8px;">Desp</span>
            </span>'''
        cats_html += '</div>'
        st.markdown(cats_html, unsafe_allow_html=True)

    with col_limits:
        st.subheader("🎯 Limites por Categoria")
        st.caption("Defina um orçamento máximo mensal para cada categoria de despesa.")

        # Add new limit
        with st.form("add_limit_form"):
            lc1, lc2 = st.columns(2)
            with lc1:
                limit_cat = st.selectbox("Categoria", DEFAULT_CATS, key="limit_cat_sel")
            with lc2:
                limit_val = st.number_input("Limite (R$)", min_value=0.01, step=50.0, value=500.0, key="limit_val_input")
            if st.form_submit_button("➕ Adicionar Limite", use_container_width=True):
                fu.set_budget_limit(limit_cat, limit_val)
                st.success(f"Limite de {fmt(limit_val)} definido para {limit_cat}!")
                st.rerun()

        # Show current limits with status
        limits_status = fu.get_limits_status(current_month, MONTH_DIR)
        if limits_status:
            for ls in limits_status:
                pct = ls["pct_usado"]
                if pct < 70:
                    bar_color = "#43A047"
                    pct_class = "pct-ok"
                elif pct < 90:
                    bar_color = "#F9A825"
                    pct_class = "pct-warn"
                else:
                    bar_color = "#E53935"
                    pct_class = "pct-danger"
                bar_width = min(pct, 100)

                st.markdown(
                    f'<div class="section-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
                    f'<span style="font-weight:600;font-size:0.85rem;color:#333;">{_cat_icon(ls["categoria"])} {ls["categoria"]}</span>'
                    f'<span class="limit-pct {pct_class}">{pct:.0f}% usado</span>'
                    f'</div>'
                    f'<div style="font-size:0.75rem;color:#888;margin-bottom:6px;">Limite: {fmt(ls["limite"])}</div>'
                    f'<div style="width:100%;height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;">'
                    f'<div style="height:100%;width:{bar_width}%;background:{bar_color};border-radius:4px;"></div>'
                    f'</div>'
                    f'<div style="display:flex;justify-content:space-between;margin-top:6px;">'
                    f'<span style="font-size:0.75rem;font-weight:600;color:#333;">Gasto: {fmt(ls["gasto"])}</span>'
                    f'<span style="font-size:0.75rem;color:#888;">Restante: {fmt(ls["restante"])}</span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Remove limit buttons
            st.divider()
            st.caption("Remover limite:")
            limit_to_remove = st.selectbox("Categoria", [ls["categoria"] for ls in limits_status], key="remove_limit_sel")
            if st.button("🗑️ Remover Limite", type="secondary"):
                fu.remove_budget_limit(limit_to_remove)
                st.success(f"Limite removido para {limit_to_remove}.")
                st.rerun()
        else:
            st.info("Nenhum limite configurado ainda.")

    # Summary section
    st.divider()
    st.subheader("📋 Resumo de Limites")
    if limits_status:
        ok = sum(1 for ls in limits_status if ls["pct_usado"] < 70)
        warn = sum(1 for ls in limits_status if 70 <= ls["pct_usado"] < 90)
        danger = sum(1 for ls in limits_status if ls["pct_usado"] >= 90)

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown(f'<div style="background:#E8F5E9;padding:14px;border-radius:12px;text-align:center;"><span style="font-size:1.5rem;">🟢</span><br><b>{ok}</b> dentro do limite</div>', unsafe_allow_html=True)
        with sc2:
            st.markdown(f'<div style="background:#FFF8E1;padding:14px;border-radius:12px;text-align:center;"><span style="font-size:1.5rem;">🟡</span><br><b>{warn}</b> perto do limite</div>', unsafe_allow_html=True)
        with sc3:
            st.markdown(f'<div style="background:#FFEBEE;padding:14px;border-radius:12px;text-align:center;"><span style="font-size:1.5rem;">🔴</span><br><b>{danger}</b> acima de 90%</div>', unsafe_allow_html=True)


# ===========================================================================
# PÁGINA: CONTAS A PAGAR
# ===========================================================================

elif page == "📋 Contas a Pagar":
    st.markdown('<div class="page-title">Controle de Contas a Pagar</div>', unsafe_allow_html=True)

    # Month navigation
    if "bills_month" not in st.session_state:
        st.session_state["bills_month"] = current_month

    bills_month = st.session_state["bills_month"]

    col_prev, col_month, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("◀ Mês anterior", key="bills_prev"):
            st.session_state["bills_month"] = _prev_month(bills_month)
            st.rerun()
    with col_month:
        st.markdown(f"<div style='text-align:center;font-size:1.1rem;font-weight:600;padding:8px;'>{month_label_full(bills_month)}</div>", unsafe_allow_html=True)
    with col_next:
        if st.button("Próximo mês ▶", key="bills_next"):
            st.session_state["bills_month"] = _next_month(bills_month)
            st.rerun()

    # Add bill template
    st.divider()
    with st.expander("➕ Adicionar Conta ao Template"):
        with st.form("add_bill"):
            bc1, bc2 = st.columns(2)
            with bc1:
                bill_nome = st.text_input("Nome da conta", placeholder="Ex: Internet, Aluguel...")
                bill_cat = st.selectbox("Categoria", ["Moradia", "Serviços", "Transporte", "Saúde", "Educação", "Outro"])
            with bc2:
                bill_dia = st.number_input("Dia do vencimento", min_value=1, max_value=31, value=10)
                bill_valor = st.number_input("Valor (R$)", min_value=0.01, step=10.0, value=100.0)
            if st.form_submit_button("Adicionar Conta", use_container_width=True):
                fu.add_bill_template(bill_nome.strip(), bill_cat, bill_dia, bill_valor)
                st.success(f"Conta '{bill_nome}' adicionada!")
                st.rerun()

    # Show bills for this month
    bills = fu.sync_bills_for_month(bills_month)

    if bills:
        total_bills = sum(b["valor_real"] for b in bills)
        total_pago = sum(b["valor_real"] for b in bills if b["pago"])
        total_pendente = total_bills - total_pago

        # Summary badges
        st.markdown(
            f'<div style="display:flex;gap:10px;margin:16px 0;flex-wrap:wrap;">'
            f'<span class="summary-badge badge-green">✓ Pago: {fmt(total_pago)}</span>'
            f'<span class="summary-badge badge-red">✗ Pendente: {fmt(total_pendente)}</span>'
            f'<span class="summary-badge badge-gray">Total: {fmt(total_bills)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Bills table — with editable value
        st.caption("💡 Ajuste o valor real de contas variáveis (água, luz, etc.) antes de marcar como pago.")
        for bill in sorted(bills, key=lambda x: x["dia_vencimento"]):
            c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1.5, 1, 2, 1.5, 1])
            with c1:
                st.markdown(f"**{bill['nome']}**")
            with c2:
                st.markdown(f"<span class='bill-cat'>{bill['categoria']}</span>", unsafe_allow_html=True)
            with c3:
                st.write(f"Dia {bill['dia_vencimento']}")
            with c4:
                new_val = st.number_input(
                    "Valor (R$)",
                    min_value=0.0,
                    step=10.0,
                    value=float(bill["valor_real"]),
                    key=f"bill_val_{bill['id']}",
                    label_visibility="collapsed",
                    format="%.2f",
                )
                if abs(new_val - float(bill["valor_real"])) > 0.01:
                    fu.update_bill_valor_real(bills_month, bill["id"], new_val, MONTH_DIR)
                    st.rerun()
            with c5:
                pago = bill["pago"]
                if st.checkbox("Pago?", value=pago, key=f"bill_pago_{bill['id']}"):
                    if not pago:
                        fu.toggle_bill_paid(bills_month, bill["id"], MONTH_DIR)
                        st.rerun()
                else:
                    if pago:
                        fu.toggle_bill_paid(bills_month, bill["id"], MONTH_DIR)
                        st.rerun()
            with c6:
                if st.button("🗑️", key=f"del_bill_{bill['id']}"):
                    fu.remove_bill_template(bill["id"])
                    st.rerun()
    else:
        st.info("Nenhuma conta cadastrada. Use o formulário acima para adicionar contas ao template.")


# ===========================================================================
# PÁGINA: ASSINATURAS
# ===========================================================================

elif page == "🔄 Assinaturas":
    st.markdown('<div class="page-title">Assinaturas</div>', unsafe_allow_html=True)

    try:
        _y = int(current_month[:4])
        _m = int(current_month[5:7])
        _last_day = calendar.monthrange(_y, _m)[1]
        period_str = f"📅 01/{_m:02d}/{_y} — {_last_day}/{_m:02d}/{_y}"
    except Exception:
        period_str = f"📅 {current_month}"
    st.markdown(f'<span class="period-badge">{period_str}</span>', unsafe_allow_html=True)

    subs = fu.load_subscriptions()
    active_subs = [s for s in subs if s.get("ativo", True)]

    total_mensal = sum(s.get("valor", 0) for s in active_subs)
    total_anual = total_mensal * 12

    # Summary cards
    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.markdown(metric_card("💳", "Total Mensal", fmt(total_mensal), "Todas as assinaturas", "mc-red"), unsafe_allow_html=True)
    with mc2:
        st.markdown(metric_card("📆", "Total Anual", fmt(total_anual), "Projeção 12 meses", "mc-amber"), unsafe_allow_html=True)
    with mc3:
        st.markdown(metric_card("🔢", "Nº de Assinaturas", str(len(active_subs)), "Ativas", "mc-blue"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Add subscription
    with st.expander("➕ Nova Assinatura"):
        with st.form("add_sub"):
            sc1, sc2 = st.columns(2)
            with sc1:
                sub_nome = st.text_input("Nome", placeholder="Ex: Netflix, Spotify...")
                sub_valor = st.number_input("Valor mensal (R$)", min_value=0.01, step=5.0, value=29.90)
                sub_dia = st.number_input("Dia do desconto", min_value=1, max_value=31, value=15)
            with sc2:
                sub_site = st.text_input("Site (opcional)", placeholder="netflix.com")
                sub_email = st.text_input("Email da conta (opcional)", placeholder="email@gmail.com")
                sub_obs = st.text_input("Observação (opcional)", placeholder="Plano família")
            if st.form_submit_button("Adicionar Assinatura", use_container_width=True):
                fu.add_subscription(sub_nome.strip(), sub_valor, sub_dia, sub_site.strip(), sub_email.strip(), sub_obs.strip())
                st.success(f"Assinatura '{sub_nome}' adicionada!")
                st.rerun()

    # List subscriptions
    st.subheader("📱 Minhas Assinaturas")

    if active_subs:
        for sub in active_subs:
            icon = _sub_icon(sub.get('nome', ''))
            nome = sub.get('nome', '—')
            site = sub.get('site', '')
            email = sub.get('email', '')
            obs = sub.get('obs', '')
            valor = fmt(sub.get('valor', 0))
            dia = sub.get('dia_desconto', '—')

            detail_parts = []
            if site:
                detail_parts.append(f"🔗 {site}")
            if email:
                detail_parts.append(email)
            if obs:
                detail_parts.append(obs)
            detail_text = " · ".join(detail_parts)

            st.markdown(
                f'<div class="sub-card">'
                f'<div class="sub-left">'
                f'<div class="sub-icon">{icon}</div>'
                f'<div>'
                f'<div class="sub-name">{nome}</div>'
                f'<div class="sub-detail">{detail_text}</div>'
                f'</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<div class="sub-valor">{valor}/mês</div>'
                f'<div class="sub-dia">Desconta dia {dia}</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button(f"🗑️ Remover {nome}", key=f"del_sub_{sub['id']}"):
                fu.remove_subscription(sub["id"])
                st.rerun()
    else:
        st.info("Nenhuma assinatura cadastrada.")


# ===========================================================================
# PÁGINA: PARCELAMENTOS
# ===========================================================================

elif page == "💳 Parcelamentos":
    st.markdown('<div class="page-title">Parcelamentos</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{month_label_full(current_month)}</div>', unsafe_allow_html=True)

    # Flash
    _flash_inst = st.session_state.pop("_inst_flash", None)
    if _flash_inst:
        st.success(_flash_inst)

    df_inst_all = fu.load_installments()

    # Modo edição
    inst_edit_id = st.session_state.get("_inst_edit_id")
    inst_edit_row = None
    is_inst_edit = False
    if inst_edit_id:
        rows = df_inst_all[df_inst_all["id"].astype(str) == str(inst_edit_id)]
        if not rows.empty:
            inst_edit_row = rows.iloc[0]
            is_inst_edit = True
        else:
            st.session_state.pop("_inst_edit_id", None)

    DEFAULT_CATS_INST = [
        "Alimentação", "Moradia", "Transporte", "Saúde", "Lazer",
        "Educação", "Tecnologia", "Cuidados Pessoais", "Casa",
        "Impostos", "Entretenimento", "Móveis", "Outro",
    ]
    _sgi = settings.get("grupos_default", fu.GRUPOS_DEFAULT)
    GRUPOS_INST = _sgi if "Outro" in _sgi else _sgi + ["Outro"]
    _sci = settings.get("contas_default", fu.CONTAS_DEFAULT)
    CONTAS_INST = _sci if "Outro" in _sci else _sci + ["Outro"]

    def _iget(field, default=""):
        if is_inst_edit and inst_edit_row is not None:
            v = inst_edit_row.get(field, default)
            return v if str(v) not in ("nan", "None", "") else default
        return default

    def _iidx(opts, val):
        try: return opts.index(val)
        except ValueError: return 0

    if is_inst_edit:
        st.subheader(f"✏️ Editando: {_iget('descricao')}")
        if st.button("↩ Cancelar edição"):
            st.session_state.pop("_inst_edit_id", None)
            st.rerun()
    else:
        st.subheader("➕ Novo contrato")

    with st.form("form_installment"):
        col1, col2 = st.columns(2)
        with col1:
            inst_desc = st.text_input("Descrição", value=_iget("descricao"), placeholder="Ex: Sofá, Notebook...")
            inst_nota = st.text_input("Nota (opcional)", value=_iget("nota"))
            inst_valor = st.number_input(
                "Valor da parcela (R$)", min_value=0.01, step=0.01, format="%.2f",
                value=max(0.01, float(inst_edit_row["valor_parcela"]) if is_inst_edit and inst_edit_row is not None else 0.01),
            )
            inst_total = st.number_input(
                "Total de parcelas", min_value=2, step=1,
                value=int(_iget("parcelas_total", 2)) if is_inst_edit else 2,
            )
        with col2:
            inst_cat_sel = st.selectbox("Categoria", DEFAULT_CATS_INST, index=_iidx(DEFAULT_CATS_INST, _iget("categoria")))
            inst_cat_custom = st.text_input("Nova categoria", key="inst_cat_cust") if inst_cat_sel == "Outro" else ""
            inst_grupo_sel = st.selectbox("Grupo", GRUPOS_INST, index=_iidx(GRUPOS_INST, _iget("grupo")))
            inst_grupo_custom = st.text_input("Novo grupo", key="inst_grp_cust") if inst_grupo_sel == "Outro" else ""
            inst_conta_sel = st.selectbox("Conta / Cartão", CONTAS_INST, index=_iidx(CONTAS_INST, _iget("conta_cartao")))
            inst_conta_custom = st.text_input("Outra conta", key="inst_cnt_cust") if inst_conta_sel == "Outro" else ""
            inst_start = st.text_input("Mês inicial (YYYY-MM)", value=_iget("start_month", current_month))
            inst_ativo = st.checkbox("Ativo", value=(str(_iget("ativo", "True")).lower() not in ("false", "0", "no")))

        btn_inst = "💾 Salvar alterações" if is_inst_edit else "💾 Criar contrato"
        submitted_inst = st.form_submit_button(btn_inst, use_container_width=True)

    if submitted_inst:
        erros_inst = []
        if not inst_desc.strip(): erros_inst.append("Informe a descrição.")
        if inst_valor <= 0: erros_inst.append("Valor deve ser maior que zero.")
        if not re.match(r"^\d{4}-\d{2}$", inst_start.strip()): erros_inst.append("Mês inicial inválido.")
        if inst_total < 2: erros_inst.append("Total de parcelas deve ser ≥ 2.")

        if erros_inst:
            for e in erros_inst: st.error(e)
        else:
            final_cat = inst_cat_custom.strip() if inst_cat_sel == "Outro" else inst_cat_sel
            final_grupo = inst_grupo_custom.strip() if inst_grupo_sel == "Outro" else inst_grupo_sel
            final_conta = inst_conta_custom.strip() if inst_conta_sel == "Outro" else inst_conta_sel

            new_inst = {
                "id": str(inst_edit_id) if is_inst_edit else str(__import__("uuid").uuid4()),
                "descricao": inst_desc.strip(),
                "nota": inst_nota.strip(),
                "categoria": final_cat,
                "grupo": final_grupo,
                "conta_cartao": final_conta,
                "valor_parcela": float(inst_valor),
                "parcelas_total": int(inst_total),
                "start_month": inst_start.strip(),
                "ativo": inst_ativo,
            }

            df_inst_all = fu.load_installments()
            if is_inst_edit:
                idx = df_inst_all.index[df_inst_all["id"].astype(str) == str(inst_edit_id)]
                if len(idx):
                    for k, v in new_inst.items():
                        df_inst_all.at[idx[0], k] = v
                st.session_state.pop("_inst_edit_id", None)
                st.session_state["_inst_flash"] = "✅ Contrato atualizado!"
            else:
                df_inst_all = pd.concat([df_inst_all, pd.DataFrame([new_inst])], ignore_index=True)
                st.session_state["_inst_flash"] = "✅ Contrato criado!"

            fu.save_installments(df_inst_all)
            st.rerun()

    # Lista de contratos
    st.divider()
    df_inst_all = fu.load_installments()

    if df_inst_all.empty:
        st.info("Nenhum contrato cadastrado.")
    else:
        df_preview = df_inst_all.copy()
        def _parcela_now(row):
            try:
                pa = fu._diff_months(current_month, str(row["start_month"])) + 1
                pt = int(row["parcelas_total"])
                if 1 <= pa <= pt: return f"{pa}/{pt}"
                elif pa > pt: return "concluído"
                else: return "não iniciado"
            except Exception: return "—"

        df_preview["parcela_agora"] = df_preview.apply(_parcela_now, axis=1)
        df_preview["valor_parcela"] = df_preview["valor_parcela"].apply(fmt)

        ativos = df_preview[df_preview["ativo"] == True]
        inativos = df_preview[df_preview["ativo"] == False]

        st.subheader("Contratos ativos")
        if ativos.empty:
            st.info("Nenhum contrato ativo.")
        else:
            show_cols_inst = ["descricao", "categoria", "conta_cartao", "valor_parcela", "start_month", "parcelas_total", "parcela_agora"]
            st.dataframe(
                ativos[[c for c in show_cols_inst if c in ativos.columns]]
                .rename(columns={"valor_parcela": "parcela (R$)", "parcela_agora": f"parcela em {current_month}"}),
                use_container_width=True, hide_index=True,
            )

        if not inativos.empty:
            with st.expander("Contratos inativos"):
                st.dataframe(
                    inativos[[c for c in show_cols_inst if c in inativos.columns]]
                    .rename(columns={"valor_parcela": "parcela (R$)", "parcela_agora": f"parcela em {current_month}"}),
                    use_container_width=True, hide_index=True,
                )

        st.subheader("Gerenciar")
        col_ei, col_di = st.columns(2)
        def _ilabel(iid):
            r = df_inst_all[df_inst_all["id"].astype(str) == str(iid)]
            if r.empty: return iid
            r = r.iloc[0]
            return f"{r['descricao']} | {fmt(float(r['valor_parcela']))} × {int(r['parcelas_total'])}x"

        iids = df_inst_all["id"].tolist()
        with col_ei:
            st.caption("Editar")
            edit_inst_sel = st.selectbox("Selecionar", iids, format_func=_ilabel, key="edit_inst_sel")
            if st.button("✏️ Carregar para edição", key="edit_inst_btn"):
                st.session_state["_inst_edit_id"] = edit_inst_sel
                st.rerun()
        with col_di:
            st.caption("Deletar")
            del_inst_sel = st.selectbox("Selecionar", iids, format_func=_ilabel, key="del_inst_sel")
            if st.button("🗑️ Deletar contrato", type="secondary", key="del_inst_btn"):
                df_inst_all = df_inst_all[df_inst_all["id"].astype(str) != str(del_inst_sel)]
                fu.save_installments(df_inst_all)
                st.success("Contrato deletado.")
                st.rerun()

    # Extração automática
    st.divider()
    st.subheader("🔍 Extrair parcelamentos do CSV mensal")
    _months_avail = fu.available_months()
    if not _months_avail:
        st.info("Nenhum CSV mensal disponível.")
    else:
        _default_idx = _months_avail.index(current_month) if current_month in _months_avail else len(_months_avail) - 1
        _ext_month = st.selectbox("Mês", _months_avail, index=_default_idx, key="ext_month_sel")

        _PREV_KEY = "_inst_extract_preview"
        if st.button("🔍 Extrair", key="btn_extract_inst"):
            _df_upd, _df_new, _n_cre, _n_upd = fu.extract_installments_from_month(_ext_month)
            st.session_state[_PREV_KEY] = (_df_upd, _df_new, _n_cre, _n_upd, _ext_month)
            st.rerun()

        if _PREV_KEY in st.session_state:
            _df_upd, _df_new, _n_cre, _n_upd, _prev_month = st.session_state[_PREV_KEY]
            if _n_cre == 0 and _n_upd == 0:
                st.info(f"Nenhum parcelamento encontrado em {_prev_month}.")
            else:
                st.info(f"**{_n_cre}** novo(s) · **{_n_upd}** atualizado(s)")
                if not _df_new.empty:
                    _show_cols = [c for c in ["descricao", "categoria", "conta_cartao", "valor_parcela", "parcelas_total", "start_month"] if c in _df_new.columns]
                    st.dataframe(_df_new[_show_cols], use_container_width=True, hide_index=True)

            _col_save, _col_cancel = st.columns(2)
            with _col_save:
                if st.button("✅ Confirmar", key="btn_confirm_extract", type="primary"):
                    fu.save_installments(_df_upd)
                    st.session_state.pop(_PREV_KEY, None)
                    st.session_state["_inst_flash"] = f"✅ {_n_cre} criado(s), {_n_upd} atualizado(s)."
                    st.rerun()
            with _col_cancel:
                if st.button("❌ Cancelar", key="btn_cancel_extract"):
                    st.session_state.pop(_PREV_KEY, None)
                    st.rerun()


# ===========================================================================
# PÁGINA: ORÇAMENTO
# ===========================================================================

elif page == "📊 Orçamento":
    st.markdown('<div class="page-title">Orçamento</div>', unsafe_allow_html=True)

    # Sync all sources before showing budget
    fu.sync_all_to_budget(current_month, MONTH_DIR)

    _oc_cfg = fu.load_settings()
    _oc_cur = _oc_cfg["current_month"]
    try:
        _oc_year_def = int(_oc_cur[:4])
        _oc_month_def = int(_oc_cur[5:7])
    except Exception:
        _oc_year_def = _date.today().year
        _oc_month_def = _date.today().month

    _oc_today_year = _date.today().year
    _oc_year_opts = list(range(_oc_today_year - 2, _oc_today_year + 3))

    col_oc_y, col_oc_m = st.columns(2)
    with col_oc_y:
        _oc_year_sel = st.selectbox("Ano", _oc_year_opts, index=_oc_year_opts.index(_oc_year_def) if _oc_year_def in _oc_year_opts else 2, key="oc_year")
    with col_oc_m:
        _oc_month_sel = st.selectbox("Mês", list(range(1, 13)), format_func=lambda m: calendar.month_abbr[m], index=_oc_month_def - 1, key="oc_month")
    mes_oc = f"{_oc_year_sel}-{_oc_month_sel:02d}"

    st.subheader(f"Orçamento — {month_label(mes_oc)}")

    _OC_DEFAULT_CATS = [
        "Alimentação", "Moradia", "Transporte", "Saúde", "Lazer",
        "Educação", "Tecnologia", "Cuidados Pessoais", "Casa",
        "Impostos", "Entretenimento", "Móveis", "Outro",
    ]

    df_oc = fu.load_budget_csv(mes_oc, MONTH_DIR)
    _oc_extra_cats = sorted(c for c in df_oc["categoria"].unique() if str(c).strip() and c not in _OC_DEFAULT_CATS) if not df_oc.empty else []
    _oc_cat_opts = _OC_DEFAULT_CATS + _oc_extra_cats

    _oc_base_exists = (MONTH_DIR / f"despesas_{mes_oc}.csv").exists()
    if _oc_base_exists:
        st.info(f"Carregado `despesas_{mes_oc}.csv` — {len(df_oc)} linha(s).")
    else:
        st.info(f"`despesas_{mes_oc}.csv` não existe; será criado ao salvar.")

    if not df_oc.empty:
        _oc_edit_df = df_oc[["descricao", "categoria", "previsto", "real"]].copy()
        _oc_edit_df["real"] = pd.to_numeric(_oc_edit_df["real"], errors="coerce").fillna(0.0)
    else:
        _oc_edit_df = pd.DataFrame(columns=["descricao", "categoria", "previsto", "real"])

    # Use a content-based key so the editor refreshes when data changes
    # (st.data_editor caches state by key — a static key shows stale values)
    _oc_hash = hashlib.md5(
        _oc_edit_df.to_csv(index=False).encode()
    ).hexdigest()[:8]

    edited_oc = st.data_editor(
        _oc_edit_df,
        column_config={
            "descricao": st.column_config.TextColumn("Descrição"),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=_oc_cat_opts),
            "previsto": st.column_config.NumberColumn("Previsto (R$)", min_value=0.0, format="%.2f"),
            "real": st.column_config.NumberColumn("Real (R$)", min_value=0.0, format="%.2f"),
        },
        num_rows="dynamic", use_container_width=True, hide_index=True, key=f"budget_editor_{mes_oc}_{_oc_hash}",
    )

    # Totals
    _oc_prev_total = pd.to_numeric(edited_oc.get("previsto", pd.Series([])), errors="coerce").fillna(0).sum()
    _oc_real_total = pd.to_numeric(edited_oc.get("real", pd.Series([])), errors="coerce").fillna(0).sum()
    _oc_diff = _oc_real_total - _oc_prev_total

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("Total Previsto", fmt(_oc_prev_total))
    with mc2:
        st.metric("Total Real", fmt(_oc_real_total))
    with mc3:
        st.metric("Diferença", fmt(_oc_diff), delta=f"{_oc_diff:+,.2f}".replace(",", "."))

    if st.button("💾 Salvar Orçamento", type="primary"):
        _oc_save = edited_oc.copy()
        _oc_save["descricao"] = _oc_save.get("descricao", pd.Series([""] * len(_oc_save))).fillna("").astype(str)
        _oc_save["categoria"] = _oc_save.get("categoria", pd.Series([""] * len(_oc_save))).fillna("").astype(str)
        _oc_save["real"] = pd.to_numeric(_oc_save.get("real", pd.Series([0.0] * len(_oc_save))), errors="coerce").fillna(0.0)
        fu.save_budget_csv(mes_oc, _oc_save, MONTH_DIR)
        st.success(f"✅ Salvo `despesas_{mes_oc}.csv`.")
        st.rerun()


# ===========================================================================
# PÁGINA: UPLOAD
# ===========================================================================

elif page == "⬆️ Upload":
    st.markdown('<div class="page-title">Upload de Despesas</div>', unsafe_allow_html=True)

    mes_upload = st.text_input("Mês de referência (YYYY-MM)", value=fu.load_settings()["current_month"])

    if not re.match(r"^\d{4}-\d{2}$", mes_upload.strip()):
        st.warning("Formato de mês inválido. Use YYYY-MM.")
        st.stop()

    uploaded = st.file_uploader("Selecione o arquivo de despesas", type=["csv", "xlsx"])

    if uploaded:
        mes = mes_upload.strip()
        raw_path = MONTH_DIR / f"despesas_{mes}.csv"
        is_xlsx = uploaded.name.lower().endswith(".xlsx")

        if is_xlsx:
            import tempfile, os as _os
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as _tmp:
                _tmp.write(uploaded.read())
                _tmp_path = _tmp.name
            try:
                df_prev = fu.load_month_excel(_tmp_path)
                fu.save_budget_csv(mes, df_prev)
                _n_fixo = int((df_prev.get("_origem", "") == "fixo").sum())
                _n_var = int((df_prev.get("_origem", "") == "variavel").sum())
                st.success(f"Excel importado — **{len(df_prev)} linhas** ({_n_fixo} fixos · {_n_var} variáveis)")
                _col_f, _col_v = st.columns(2)
                with _col_f:
                    st.caption(f"Fixos ({_n_fixo})")
                    _df_fix = df_prev[df_prev.get("_origem", "") == "fixo"] if "_origem" in df_prev.columns else df_prev
                    st.dataframe(_df_fix[["descricao", "categoria", "previsto", "real"]].head(15), use_container_width=True, hide_index=True)
                with _col_v:
                    st.caption(f"Variáveis ({_n_var})")
                    _df_var = df_prev[df_prev.get("_origem", "") == "variavel"] if "_origem" in df_prev.columns else pd.DataFrame()
                    if not _df_var.empty:
                        st.dataframe(_df_var[["descricao", "categoria", "real"]].head(15), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Erro ao processar Excel: {e}")
            finally:
                _os.unlink(_tmp_path)
        else:
            raw_path.write_bytes(uploaded.read())
            try:
                df_prev = fu.load_month_csv(raw_path)
                st.success(f"Arquivo salvo ({len(df_prev)} linhas)")
                st.dataframe(df_prev[["descricao", "categoria", "previsto", "real", "diferenca", "recorrente", "parcelado"]].head(20))
            except Exception as e:
                st.error(f"Erro ao processar: {e}")
                raw_path.unlink(missing_ok=True)


# ===========================================================================
# PÁGINA: RECEITAS
# ===========================================================================

elif page == "💵 Receitas":
    st.markdown('<div class="page-title">Receitas</div>', unsafe_allow_html=True)

    with st.form("form_receita"):
        col1, col2 = st.columns(2)
        with col1:
            mes_rec = st.text_input("Mês (YYYY-MM)", value=fu.load_settings()["current_month"])
            fonte = st.text_input("Fonte", placeholder="Salário, Freela, etc.")
        with col2:
            valor_str = st.text_input("Valor (R$)", placeholder="5000.00")
            obs_rec = st.text_input("Observação (opcional)")
        submitted_rec = st.form_submit_button("Adicionar Receita")

    if submitted_rec:
        erros = []
        if not re.match(r"^\d{4}-\d{2}$", mes_rec.strip()): erros.append("Mês inválido.")
        if not fonte.strip(): erros.append("Informe a fonte.")
        valor_rec = fu.clean_currency(valor_str)
        if valor_rec <= 0: erros.append("Valor deve ser maior que zero.")
        if erros:
            for e in erros: st.error(e)
        else:
            fu.save_receita(mes_rec.strip(), fonte.strip(), valor_rec, obs_rec.strip(), RECEITAS_PATH)
            st.success(f"Receita de {fmt(valor_rec)} adicionada para {mes_rec}.")

    st.divider()
    st.subheader("Histórico")
    df_rec = fu.load_receitas(RECEITAS_PATH)
    if df_rec.empty:
        st.info("Nenhuma receita cadastrada.")
    else:
        df_rec_show = df_rec.copy()
        df_rec_show["valor"] = df_rec_show["valor"].apply(fmt)
        st.dataframe(df_rec_show, use_container_width=True, hide_index=True)
        st.metric("Total geral", fmt(fu.load_receitas(RECEITAS_PATH)["valor"].sum()))


# ===========================================================================
# PÁGINA: RELATÓRIO
# ===========================================================================

elif page == "📋 Relatório":
    st.markdown('<div class="page-title">Relatório / Fechamento do Mês</div>', unsafe_allow_html=True)

    _rel_cfg = fu.load_settings()
    _rel_cur = _rel_cfg["current_month"]
    try:
        _rel_year_def = int(_rel_cur[:4])
        _rel_month_def = int(_rel_cur[5:7])
    except Exception:
        _rel_year_def = _date.today().year
        _rel_month_def = _date.today().month

    _rel_today_year = _date.today().year
    _rel_year_opts = list(range(_rel_today_year - 2, _rel_today_year + 3))

    col_rel_y, col_rel_m = st.columns(2)
    with col_rel_y:
        _rel_year_sel = st.selectbox("Ano", _rel_year_opts, index=_rel_year_opts.index(_rel_year_def) if _rel_year_def in _rel_year_opts else 2, key="rel_year")
    with col_rel_m:
        _rel_month_sel = st.selectbox("Mês", list(range(1, 13)), format_func=lambda m: calendar.month_abbr[m], index=_rel_month_def - 1, key="rel_month")
    mes_rel = f"{_rel_year_sel}-{_rel_month_sel:02d}"

    st.subheader(f"Fechar mês: {month_label(mes_rel)}")

    _rel_closed_path = Path("data/closed") / f"{mes_rel}.json"
    _rel_pdf_path = Path("exports") / f"{mes_rel}_relatorio.pdf"

    _rel_already_closed = _rel_closed_path.exists()
    _rel_already_pdf = _rel_pdf_path.exists()

    _rel_can_proceed = True
    if _rel_already_closed or _rel_already_pdf:
        _what = []
        if _rel_already_closed: _what.append("snapshot")
        if _rel_already_pdf: _what.append("PDF")
        st.warning(f"⚠️ Já existem para **{mes_rel}**: {', '.join(_what)}.")
        _rel_can_proceed = st.checkbox("Confirmar sobrescrita", key="rel_overwrite")

    if _rel_can_proceed:
        if st.button("✅ Fechar mês (backup + PDF)", type="primary", key="rel_close_btn"):
            with st.spinner("Gerando relatório..."):
                try:
                    _rel_bk = fu.backup_data_dir()
                    st.info("Backup criado.")

                    _rel_base = fu.safe_load_month_csv(mes_rel, MONTH_DIR)
                    for _c in ("grupo", "conta_cartao", "nota"):
                        if _c not in _rel_base.columns: _rel_base[_c] = ""
                    if not _rel_base.empty:
                        _rel_base["_source"] = "base"
                        if "parcelado" not in _rel_base.columns: _rel_base["parcelado"] = False
                        if "parcela_str" not in _rel_base.columns: _rel_base["parcela_str"] = ""

                    _rel_trans = fu.load_transactions(mes_rel)
                    _rel_trans_rows = []
                    for _, _t in _rel_trans.iterrows():
                        _td = str(_t.get("descricao", "")).strip()
                        _tn = str(_t.get("nota", "")).strip()
                        _rel_trans_rows.append({
                            "descricao": _td if _td else _tn,
                            "nota": _tn,
                            "categoria": str(_t.get("categoria", "")),
                            "grupo": str(_t.get("grupo", "")),
                            "previsto": 0.0,
                            "real": float(_t.get("valor", 0)),
                            "diferenca": float(_t.get("valor", 0)),
                            "recorrente": bool(_t.get("recorrente", False)),
                            "conta_cartao": str(_t.get("conta_cartao", "")),
                            "parcelado": False, "parcela_str": "", "_source": "transaction",
                        })

                    _rel_inst = fu.get_installments_for_month(mes_rel)
                    _rel_inst_rows = []
                    for _, _i in _rel_inst.iterrows():
                        _rel_inst_rows.append({
                            "descricao": str(_i.get("descricao", "")),
                            "nota": str(_i.get("nota", "")),
                            "categoria": str(_i.get("categoria", "")),
                            "grupo": str(_i.get("grupo", "")),
                            "previsto": 0.0,
                            "real": float(_i.get("valor_parcela", 0)),
                            "diferenca": float(_i.get("valor_parcela", 0)),
                            "recorrente": False,
                            "conta_cartao": str(_i.get("conta_cartao", "")),
                            "parcelado": True,
                            "parcela_str": str(_i.get("parcela_str", "")),
                            "_source": "installment",
                        })

                    _rel_parts = []
                    if not _rel_base.empty: _rel_parts.append(_rel_base)
                    if _rel_trans_rows: _rel_parts.append(pd.DataFrame(_rel_trans_rows))
                    if _rel_inst_rows: _rel_parts.append(pd.DataFrame(_rel_inst_rows))

                    if _rel_parts:
                        _df_rel = pd.concat(_rel_parts, ignore_index=True)
                        for _c in ("descricao", "categoria", "grupo", "conta_cartao", "nota", "parcela_str"):
                            _df_rel[_c] = _df_rel[_c].fillna("").astype(str).str.strip()
                        for _c in ("previsto", "real", "diferenca"):
                            _df_rel[_c] = pd.to_numeric(_df_rel[_c], errors="coerce").fillna(0.0)
                        _df_rel["recorrente"] = _df_rel["recorrente"].fillna(False).astype(bool)
                    else:
                        _df_rel = pd.DataFrame()

                    _rel_receitas = fu.load_receitas(RECEITAS_PATH)
                    _rel_receita = float(_rel_receitas[_rel_receitas["mes"] == mes_rel]["valor"].sum() if not _rel_receitas.empty else 0.0)

                    _rel_snap = fu.generate_month_snapshot(mes_rel, _df_rel, _rel_receita, _rel_inst)
                    _rel_snap_path = fu.save_month_snapshot(mes_rel, _rel_snap)
                    _rel_pdf_out = fu.generate_month_pdf(mes_rel, _rel_snap)
                    st.success(f"PDF gerado!")

                    with open(_rel_pdf_out, "rb") as _f:
                        st.download_button("📥 Baixar PDF", data=_f.read(), file_name=_rel_pdf_out.name, mime="application/pdf", key="dl_new_pdf")

                except Exception as _rel_err:
                    import traceback as _tb
                    st.error(f"Erro: {_rel_err}")
                    st.code(_tb.format_exc())

    if _rel_already_pdf:
        st.divider()
        with open(_rel_pdf_path, "rb") as _f:
            st.download_button("📥 Baixar PDF existente", data=_f.read(), file_name=_rel_pdf_path.name, mime="application/pdf", key="dl_existing_pdf")


# ===========================================================================
# PÁGINA: ANUAL
# ===========================================================================

elif page == "📈 Anual":
    st.markdown('<div class="page-title">Dashboard Anual</div>', unsafe_allow_html=True)

    months_with_data = fu.available_months_with_data(MONTH_DIR)
    df_receitas = fu.load_receitas(RECEITAS_PATH)

    if not months_with_data:
        st.warning("Nenhum dado encontrado.")
        st.stop()

    rows = []
    for mes in months_with_data:
        df_b = fu.safe_load_month_csv(mes, MONTH_DIR)
        df_b_v = df_b[(df_b["descricao"].str.len() > 0) & (df_b["categoria"].str.len() > 0)] if not df_b.empty else df_b
        rec_mes = df_receitas[df_receitas["mes"] == mes]["valor"].sum()
        df_t = fu.load_transactions(mes)
        trans_real = df_t["valor"].sum() if not df_t.empty else 0.0
        df_i = fu.get_installments_for_month(mes)
        inst_real = df_i["valor_parcela"].sum() if not df_i.empty else 0.0
        total_real_mes = (df_b_v["real"].sum() if not df_b_v.empty else 0.0) + trans_real + inst_real
        rows.append({
            "mes": mes, "label": month_label(mes),
            "previsto": df_b_v["previsto"].sum() if not df_b_v.empty else 0.0,
            "real": total_real_mes, "receita": rec_mes,
            "saldo": rec_mes - total_real_mes,
        })
    serie = pd.DataFrame(rows)

    total_prev_ano = serie["previsto"].sum()
    total_real_ano = serie["real"].sum()
    total_rec_ano = serie["receita"].sum()
    saldo_ano = total_rec_ano - total_real_ano

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card("📋", "Previsto (Ano)", fmt(total_prev_ano), f"{len(months_with_data)} meses", "mc-blue"), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("🛒", "Real (Ano)", fmt(total_real_ano), "Despesas totais", "mc-red"), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("💰", "Receita (Ano)", fmt(total_rec_ano), "Receitas totais", "mc-green"), unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("💎", "Saldo Anual", fmt(saldo_ano), "Receita − Despesas", "mc-teal" if saldo_ano >= 0 else "mc-red"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    st.subheader("Total Real por Mês")
    fig_serie = go.Figure()
    fig_serie.add_trace(go.Bar(x=serie["label"], y=serie["previsto"], name="Previsto", marker_color="#66BB6A"))
    fig_serie.add_trace(go.Bar(x=serie["label"], y=serie["real"], name="Real", marker_color="#EF5350"))
    if serie["receita"].sum() > 0:
        fig_serie.add_trace(go.Scatter(x=serie["label"], y=serie["receita"], name="Receita", mode="lines+markers", line=dict(color="#2E7D32", width=2)))
    fig_serie.update_layout(barmode="group", xaxis_title="Mês", yaxis_title="R$", yaxis=dict(tickprefix="R$ "))
    st.plotly_chart(fig_serie, use_container_width=True)

    st.divider()
    col_a1, col_a2 = st.columns(2)

    with col_a1:
        st.subheader("Top Categorias no Ano")
        all_cat_dfs = []
        for mes in months_with_data:
            df_b = fu.safe_load_month_csv(mes, MONTH_DIR)
            if not df_b.empty:
                df_b_v = df_b[(df_b["descricao"].str.len() > 0) & (df_b["categoria"].str.len() > 0)]
                all_cat_dfs.append(df_b_v[["categoria", "real"]])
            df_t = fu.load_transactions(mes)
            if not df_t.empty:
                all_cat_dfs.append(df_t[["categoria", "valor"]].rename(columns={"valor": "real"}))
            df_i = fu.get_installments_for_month(mes)
            if not df_i.empty:
                all_cat_dfs.append(df_i[["categoria", "valor_parcela"]].rename(columns={"valor_parcela": "real"}))
        if all_cat_dfs:
            df_ano = pd.concat(all_cat_dfs, ignore_index=True)
            top_cat = df_ano.groupby("categoria")["real"].sum().sort_values(ascending=False).head(10).reset_index()
            colors = ["#1B5E40", "#2E7D32", "#388E3C", "#43A047", "#4CAF50",
                      "#66BB6A", "#81C784", "#A5D6A7", "#C8E6C9", "#E8F5E9"]
            st.plotly_chart(
                px.pie(top_cat, values="real", names="categoria", hole=0.4, color_discrete_sequence=colors),
                use_container_width=True,
            )

    with col_a2:
        st.subheader("Maiores Estouros no Ano")
        estouro_rows = []
        for mes in months_with_data:
            df_b = fu.safe_load_month_csv(mes, MONTH_DIR)
            if not df_b.empty:
                df_b_v = df_b[(df_b["descricao"].str.len() > 0) & (df_b["categoria"].str.len() > 0)]
                est = df_b_v[df_b_v["real"] > df_b_v["previsto"]].copy()
                if not est.empty:
                    est["estouro"] = est["real"] - est["previsto"]
                    estouro_rows.append(est)
        if estouro_rows:
            df_est_ano = pd.concat(estouro_rows, ignore_index=True)
            top_est = df_est_ano.groupby(["categoria", "descricao"])["estouro"].sum().sort_values(ascending=False).head(10).reset_index()
            fig_est = px.bar(
                top_est, x="estouro", y="descricao", orientation="h",
                color="categoria", labels={"estouro": "R$ Estouro", "descricao": ""},
                color_discrete_sequence=["#EF5350", "#FF7043", "#FFA726", "#FFCA28", "#FFE082"],
            )
            fig_est.update_layout(yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_est, use_container_width=True)

    st.divider()
    st.subheader("Resumo por Mês")
    serie_show = serie.copy()
    for col in ("previsto", "real", "receita", "saldo"):
        serie_show[col] = serie_show[col].apply(fmt)
    st.dataframe(
        serie_show.rename(columns={
            "mes": "Mês", "label": "Período", "previsto": "Previsto",
            "real": "Real", "receita": "Receita", "saldo": "Saldo",
        })[["Período", "Previsto", "Real", "Receita", "Saldo"]],
        use_container_width=True, hide_index=True,
    )
