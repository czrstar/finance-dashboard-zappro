"""
app.py — Dashboard Financeiro Pessoal
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

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Dashboard Financeiro",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Autenticação simples
# ---------------------------------------------------------------------------

def _check_auth() -> bool:
    """Returns True if the user is authenticated."""
    try:
        _expected = st.secrets["auth"]["password_hash"]
    except Exception:
        return True  # sem secrets configurado → ambiente local, sem bloqueio

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
    # Brazilian format: R$ 1.234,56
    s = f"{v:,.2f}"                        # "1,234.56" (US)
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")  # "1.234,56"
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


def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y}-{m:02d}"


# ---------------------------------------------------------------------------
# Sidebar — navegação
# ---------------------------------------------------------------------------

st.sidebar.title("💰 Finanças Pessoais")
page = st.sidebar.radio(
    "Navegação",
    [
        "📅 Mensal", "📆 Anual", "⚡ Lançar Gasto", "💳 Parcelamentos",
        "📊 Orçamento", "⬆️ Upload", "💵 Receitas", "📋 Relatório",
    ],
    label_visibility="collapsed",
)

# ---------------------------------------------------------------------------
# Sidebar — Config (sempre visível)
# ---------------------------------------------------------------------------

st.sidebar.divider()
with st.sidebar.expander("⚙️ Config"):
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
        height=160,
    )
    st.caption("Contas / Cartões (1 por linha)")
    _contas_txt = st.text_area(
        "Contas",
        value="\n".join(_cfg.get("contas_default", fu.CONTAS_DEFAULT)),
        key="cfg_contas_ta",
        label_visibility="collapsed",
        height=120,
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
            st.success(f"Backup criado em:\n`{_bk_path}`")
        except Exception as _bk_err:
            st.error(f"Erro no backup: {_bk_err}")

    _recent = fu.list_backups(5)
    if _recent:
        st.caption("Últimos backups:")
        for _bp in _recent:
            st.code(str(_bp), language=None)

# ---------------------------------------------------------------------------
# PÁGINA: UPLOAD
# ---------------------------------------------------------------------------

if page == "⬆️ Upload":
    st.title("⬆️ Upload de Despesas Mensais")

    mes_upload = st.text_input(
        "Mês de referência (YYYY-MM)", value=fu.load_settings()["current_month"],
        help="Ex.: 2026-03 para março de 2026"
    )

    if not re.match(r"^\d{4}-\d{2}$", mes_upload.strip()):
        st.warning("Formato de mês inválido. Use YYYY-MM.")
        st.stop()

    uploaded = st.file_uploader(
        "Selecione o arquivo de despesas", type=["csv", "xlsx"],
        help="CSV simples ou Excel (.xlsx) com abas de orçamento mensal"
    )

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

                # Contagem por origem
                _n_fixo = int((df_prev.get("_origem", "") == "fixo").sum())
                _n_var  = int((df_prev.get("_origem", "") == "variavel").sum())
                st.success(
                    f"Excel importado → `{raw_path}` — "
                    f"**{len(df_prev)} linhas** "
                    f"({_n_fixo} fixos · {_n_var} variáveis)"
                )

                # Preview por origem
                _col_f, _col_v = st.columns(2)
                with _col_f:
                    st.caption(f"Fixos ({_n_fixo}) — aba Despesas Mensais")
                    _df_fix = df_prev[df_prev.get("_origem", "") == "fixo"] if "_origem" in df_prev.columns else df_prev
                    st.dataframe(
                        _df_fix[["descricao", "categoria", "previsto", "real"]].head(15),
                        use_container_width=True, hide_index=True,
                    )
                with _col_v:
                    st.caption(f"Variáveis ({_n_var}) — blocos laterais")
                    _df_var = df_prev[df_prev.get("_origem", "") == "variavel"] if "_origem" in df_prev.columns else pd.DataFrame()
                    if not _df_var.empty:
                        st.dataframe(
                            _df_var[["descricao", "categoria", "real"]].head(15),
                            use_container_width=True, hide_index=True,
                        )
            except Exception as e:
                st.error(f"Erro ao processar Excel: {e}")
            finally:
                _os.unlink(_tmp_path)
        else:
            raw_path.write_bytes(uploaded.read())
            try:
                df_prev = fu.load_month_csv(raw_path)
                st.success(f"Arquivo salvo: `{raw_path}` ({len(df_prev)} linhas)")
                st.dataframe(df_prev[["descricao", "categoria", "previsto", "real",
                                       "diferenca", "recorrente", "parcelado"]].head(20))
            except Exception as e:
                st.error(f"Erro ao processar: {e}")
                raw_path.unlink(missing_ok=True)

    st.divider()
    st.info(
        "**Formatos aceitos:**\n\n"
        "- **CSV simples:** `Descrição`, `Categoria`, `Custo Previsto`, `Custo Real`, `Diferença`\n"
        "- **Excel (.xlsx):** detecta automaticamente abas de orçamento mensal "
        "(formato simples ou largo com categorias laterais)"
    )


# ---------------------------------------------------------------------------
# PÁGINA: RECEITAS
# ---------------------------------------------------------------------------

elif page == "💵 Receitas":
    st.title("💵 Lançar Receitas")

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
        if not re.match(r"^\d{4}-\d{2}$", mes_rec.strip()):
            erros.append("Mês inválido (use YYYY-MM).")
        if not fonte.strip():
            erros.append("Informe a fonte.")
        valor_rec = fu.clean_currency(valor_str)
        if valor_rec <= 0:
            erros.append("Valor deve ser maior que zero.")
        if erros:
            for e in erros:
                st.error(e)
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


# ---------------------------------------------------------------------------
# PÁGINA: LANÇAR GASTO — CRUD completo
# ---------------------------------------------------------------------------

elif page == "⚡ Lançar Gasto":
    st.title("⚡ Lançar Gasto")

    # Flash de sucesso
    _flash = st.session_state.pop("_gasto_flash", None)
    if _flash:
        st.success(_flash)

    settings = fu.load_settings()
    current_month = settings["current_month"]
    st.caption(
        f"Mês: **{month_label(current_month)}** (`{current_month}`). "
        "Altere em ⚙️ Config."
    )

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

    # --- Categorias do CSV base ---
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

    # --- Cabeçalho do form ---
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
        try:
            return cat_options.index(val)
        except ValueError:
            return 0

    def _grupo_idx(val):
        try:
            return GRUPOS.index(val)
        except ValueError:
            return 0

    def _conta_idx(val):
        try:
            return CONTAS.index(val)
        except ValueError:
            return 0

    # --- Form ---
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
            descricao_input = st.text_input("Descrição", value=_get("descricao"),
                                            placeholder="Ex: Almoço, Uber...")
            nota_input = st.text_input("Nota (opcional)", value=_get("nota"),
                                       placeholder="Ex: Droga Raia, iFood #123")
            valor_input = st.number_input(
                "Valor (R$)",
                min_value=0.01, step=0.01, format="%.2f",
                value=max(0.01, float(edit_row["valor"]) if is_edit and edit_row is not None else 0.01),
            )

        with col2:
            cat_sel = st.selectbox("Categoria", cat_options, index=_cat_idx(_get("categoria")))
            cat_custom = (
                st.text_input("Nova categoria", key="cat_cust")
                if cat_sel == "Outro" else ""
            )
            grupo_sel = st.selectbox("Grupo", GRUPOS, index=_grupo_idx(_get("grupo")))
            grupo_custom = (
                st.text_input("Novo grupo", key="grp_cust")
                if grupo_sel == "Outro" else ""
            )
            conta_sel = st.selectbox("Conta / Cartão", CONTAS, index=_conta_idx(_get("conta_cartao")))
            conta_custom = (
                st.text_input("Outra conta", key="cnt_cust")
                if conta_sel == "Outro" else ""
            )
            recorrente_input = st.checkbox(
                "Recorrente",
                value=bool(_get("recorrente", False)) if is_edit else False,
            )

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
        show_cols = ["data", "descricao", "nota", "categoria", "grupo",
                     "valor", "conta_cartao", "recorrente"]
        st.dataframe(
            df_show[[c for c in show_cols if c in df_show.columns]],
            use_container_width=True, hide_index=True,
        )
        st.metric("Total lançado", fmt(fu.load_transactions(current_month)["valor"].sum()))

        st.subheader("Gerenciar")
        col_e, col_d = st.columns(2)

        def _label(tid):
            r = df_trans[df_trans["id"].astype(str) == str(tid)]
            if r.empty:
                return tid
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


# ---------------------------------------------------------------------------
# PÁGINA: PARCELAMENTOS — CRUD
# ---------------------------------------------------------------------------

elif page == "💳 Parcelamentos":
    st.title("💳 Parcelamentos")

    # Flash
    _flash_inst = st.session_state.pop("_inst_flash", None)
    if _flash_inst:
        st.success(_flash_inst)

    settings = fu.load_settings()
    current_month = settings["current_month"]

    df_inst_all = fu.load_installments()

    # Modo edição de contrato
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
        try:
            return opts.index(val)
        except ValueError:
            return 0

    # --- Form ---
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
            inst_desc = st.text_input("Descrição", value=_iget("descricao"),
                                      placeholder="Ex: Sofá, Notebook...")
            inst_nota = st.text_input("Nota (opcional)", value=_iget("nota"),
                                      placeholder="Ex: Magazine Luiza, 0% juros")
            inst_valor = st.number_input(
                "Valor da parcela (R$)", min_value=0.01, step=0.01, format="%.2f",
                value=max(0.01, float(inst_edit_row["valor_parcela"]) if is_inst_edit and inst_edit_row is not None else 0.01),
            )
            inst_total = st.number_input(
                "Total de parcelas", min_value=2, step=1,
                value=int(_iget("parcelas_total", 2)) if is_inst_edit else 2,
            )

        with col2:
            inst_cat_sel = st.selectbox(
                "Categoria", DEFAULT_CATS_INST,
                index=_iidx(DEFAULT_CATS_INST, _iget("categoria")),
            )
            inst_cat_custom = (
                st.text_input("Nova categoria", key="inst_cat_cust")
                if inst_cat_sel == "Outro" else ""
            )
            inst_grupo_sel = st.selectbox(
                "Grupo", GRUPOS_INST,
                index=_iidx(GRUPOS_INST, _iget("grupo")),
            )
            inst_grupo_custom = (
                st.text_input("Novo grupo", key="inst_grp_cust")
                if inst_grupo_sel == "Outro" else ""
            )
            inst_conta_sel = st.selectbox(
                "Conta / Cartão", CONTAS_INST,
                index=_iidx(CONTAS_INST, _iget("conta_cartao")),
            )
            inst_conta_custom = (
                st.text_input("Outra conta", key="inst_cnt_cust")
                if inst_conta_sel == "Outro" else ""
            )
            inst_start = st.text_input(
                "Mês inicial (YYYY-MM)", value=_iget("start_month", current_month),
                help="Mês da 1ª parcela"
            )
            inst_ativo = st.checkbox(
                "Ativo", value=(str(_iget("ativo", "True")).lower() not in ("false", "0", "no"))
            )

        btn_inst = "💾 Salvar alterações" if is_inst_edit else "💾 Criar contrato"
        submitted_inst = st.form_submit_button(btn_inst, use_container_width=True)

    if submitted_inst:
        erros_inst = []
        if not inst_desc.strip():
            erros_inst.append("Informe a descrição.")
        if inst_valor <= 0:
            erros_inst.append("Valor deve ser maior que zero.")
        if not re.match(r"^\d{4}-\d{2}$", inst_start.strip()):
            erros_inst.append("Mês inicial inválido (use YYYY-MM).")
        if inst_total < 2:
            erros_inst.append("Total de parcelas deve ser ≥ 2.")

        if erros_inst:
            for e in erros_inst:
                st.error(e)
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
                df_inst_all = pd.concat(
                    [df_inst_all, pd.DataFrame([new_inst])], ignore_index=True
                )
                st.session_state["_inst_flash"] = "✅ Contrato criado!"

            fu.save_installments(df_inst_all)
            st.rerun()

    # --- Lista de contratos ---
    st.divider()
    df_inst_all = fu.load_installments()

    if df_inst_all.empty:
        st.info("Nenhum contrato cadastrado.")
    else:
        # Calcular parcela do mês atual para cada contrato
        df_preview = df_inst_all.copy()
        def _parcela_now(row):
            try:
                pa = fu._diff_months(current_month, str(row["start_month"])) + 1
                pt = int(row["parcelas_total"])
                if 1 <= pa <= pt:
                    return f"{pa}/{pt}"
                elif pa > pt:
                    return "concluído"
                else:
                    return "não iniciado"
            except Exception:
                return "—"

        df_preview["parcela_agora"] = df_preview.apply(_parcela_now, axis=1)
        df_preview["valor_parcela"] = df_preview["valor_parcela"].apply(fmt)

        ativos = df_preview[df_preview["ativo"] == True]
        inativos = df_preview[df_preview["ativo"] == False]

        st.subheader("Contratos ativos")
        if ativos.empty:
            st.info("Nenhum contrato ativo.")
        else:
            show_cols_inst = ["descricao", "categoria", "conta_cartao",
                              "valor_parcela", "start_month", "parcelas_total", "parcela_agora"]
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

        # Editar / Deletar
        st.subheader("Gerenciar")
        col_ei, col_di = st.columns(2)

        def _ilabel(iid):
            r = df_inst_all[df_inst_all["id"].astype(str) == str(iid)]
            if r.empty:
                return iid
            r = r.iloc[0]
            return f"{r['descricao']} | {fmt(float(r['valor_parcela']))} × {int(r['parcelas_total'])}x | início {r['start_month']}"

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

    # --- Extração automática ---
    st.divider()
    st.subheader("🔍 Extrair parcelamentos do CSV mensal")

    _months_avail = fu.available_months()
    if not _months_avail:
        st.info("Nenhum CSV mensal disponível para extração.")
    else:
        _default_idx = (
            _months_avail.index(current_month)
            if current_month in _months_avail
            else len(_months_avail) - 1
        )
        _ext_month = st.selectbox(
            "Mês",
            _months_avail,
            index=_default_idx,
            key="ext_month_sel",
        )

        _PREV_KEY = "_inst_extract_preview"

        if st.button("🔍 Extrair parcelamentos do mês selecionado", key="btn_extract_inst"):
            _df_upd, _df_new, _n_cre, _n_upd = fu.extract_installments_from_month(_ext_month)
            st.session_state[_PREV_KEY] = (_df_upd, _df_new, _n_cre, _n_upd, _ext_month)
            st.rerun()

        if _PREV_KEY in st.session_state:
            _df_upd, _df_new, _n_cre, _n_upd, _prev_month = st.session_state[_PREV_KEY]

            if _n_cre == 0 and _n_upd == 0:
                st.info(f"Nenhum parcelamento encontrado em {_prev_month}.")
            else:
                st.info(
                    f"**Mês {_prev_month}** — "
                    f"**{_n_cre}** contrato(s) novo(s) · **{_n_upd}** atualizado(s)"
                )
                if not _df_new.empty:
                    _show_cols = [c for c in [
                        "descricao", "categoria", "conta_cartao",
                        "valor_parcela", "parcelas_total", "start_month",
                    ] if c in _df_new.columns]
                    st.dataframe(
                        _df_new[_show_cols].rename(columns={"valor_parcela": "parcela (R$)"}),
                        use_container_width=True,
                        hide_index=True,
                    )

            _col_save, _col_cancel = st.columns(2)
            with _col_save:
                if st.button("✅ Confirmar e salvar", key="btn_confirm_extract", type="primary"):
                    fu.save_installments(_df_upd)
                    st.session_state.pop(_PREV_KEY, None)
                    st.session_state["_inst_flash"] = (
                        f"✅ {_n_cre} contrato(s) criado(s), {_n_upd} atualizado(s)."
                    )
                    st.rerun()
            with _col_cancel:
                if st.button("❌ Cancelar", key="btn_cancel_extract"):
                    st.session_state.pop(_PREV_KEY, None)
                    st.rerun()


# ---------------------------------------------------------------------------
# PÁGINA: ORÇAMENTO
# ---------------------------------------------------------------------------

elif page == "📊 Orçamento":
    st.title("📊 Orçamento")

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
        _oc_year_sel = st.selectbox(
            "Ano", _oc_year_opts,
            index=_oc_year_opts.index(_oc_year_def) if _oc_year_def in _oc_year_opts else 2,
            key="oc_year",
        )
    with col_oc_m:
        _oc_month_sel = st.selectbox(
            "Mês", list(range(1, 13)),
            format_func=lambda m: calendar.month_abbr[m],
            index=_oc_month_def - 1,
            key="oc_month",
        )
    mes_oc = f"{_oc_year_sel}-{_oc_month_sel:02d}"

    st.subheader(f"Orçamento — {month_label(mes_oc)}")

    _OC_DEFAULT_CATS = [
        "Alimentação", "Moradia", "Transporte", "Saúde", "Lazer",
        "Educação", "Tecnologia", "Cuidados Pessoais", "Casa",
        "Impostos", "Entretenimento", "Móveis", "Outro",
    ]

    df_oc = fu.load_budget_csv(mes_oc, MONTH_DIR)

    # Categorias: defaults + quaisquer que já existam no CSV
    _oc_extra_cats = sorted(
        c for c in df_oc["categoria"].unique()
        if str(c).strip() and c not in _OC_DEFAULT_CATS
    ) if not df_oc.empty else []
    _oc_cat_opts = _OC_DEFAULT_CATS + _oc_extra_cats

    _oc_base_exists = (MONTH_DIR / f"despesas_{mes_oc}.csv").exists()
    if _oc_base_exists:
        st.info(f"Carregado `despesas_{mes_oc}.csv` — {len(df_oc)} linha(s).")
    else:
        st.info(f"`despesas_{mes_oc}.csv` não existe; será criado ao salvar.")

    st.caption("Edite o orçamento abaixo. Use ➕ para adicionar linhas e 🗑 para deletar.")

    _oc_edit_df = (
        df_oc[["descricao", "categoria", "previsto"]].copy()
        if not df_oc.empty
        else pd.DataFrame(columns=["descricao", "categoria", "previsto"])
    )

    edited_oc = st.data_editor(
        _oc_edit_df,
        column_config={
            "descricao": st.column_config.TextColumn("Descrição"),
            "categoria": st.column_config.SelectboxColumn(
                "Categoria", options=_oc_cat_opts,
            ),
            "previsto": st.column_config.NumberColumn(
                "Previsto (R$)", min_value=0.0, format="%.2f",
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"budget_editor_{mes_oc}",
    )

    _oc_total = pd.to_numeric(edited_oc.get("previsto", pd.Series([])), errors="coerce").fillna(0).sum()
    st.metric("Total Previsto", fmt(_oc_total))

    if st.button("💾 Salvar Orçamento", type="primary"):
        # Preservar real de linhas que já existiam (match por descricao+categoria)
        _oc_real_map = {
            (str(r["descricao"]).strip(), str(r["categoria"]).strip()): float(r.get("real", 0))
            for _, r in df_oc.iterrows()
            if str(r.get("descricao", "")).strip()
        }
        _oc_save = edited_oc.copy()
        _oc_save["descricao"] = _oc_save.get("descricao", pd.Series([""] * len(_oc_save))).fillna("").astype(str)
        _oc_save["categoria"] = _oc_save.get("categoria", pd.Series([""] * len(_oc_save))).fillna("").astype(str)
        _oc_save["real"] = _oc_save.apply(
            lambda r: _oc_real_map.get(
                (r.get("descricao", "").strip(), r.get("categoria", "").strip()), 0.0
            ),
            axis=1,
        )
        fu.save_budget_csv(mes_oc, _oc_save, MONTH_DIR)
        _oc_saved_n = len(_oc_save[_oc_save["descricao"].str.strip().str.len() > 0])
        st.success(f"✅ Salvo `despesas_{mes_oc}.csv` ({_oc_saved_n} linhas).")
        st.rerun()


# ---------------------------------------------------------------------------
# PÁGINA: RELATÓRIO / FECHAMENTO DO MÊS
# ---------------------------------------------------------------------------

elif page == "📋 Relatório":
    st.title("📋 Relatório / Fechamento do Mês")

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
        _rel_year_sel = st.selectbox(
            "Ano", _rel_year_opts,
            index=_rel_year_opts.index(_rel_year_def) if _rel_year_def in _rel_year_opts else 2,
            key="rel_year",
        )
    with col_rel_m:
        _rel_month_sel = st.selectbox(
            "Mês", list(range(1, 13)),
            format_func=lambda m: calendar.month_abbr[m],
            index=_rel_month_def - 1,
            key="rel_month",
        )
    mes_rel = f"{_rel_year_sel}-{_rel_month_sel:02d}"

    st.subheader(f"Fechar mês: {month_label(mes_rel)}")

    _rel_closed_path = Path("data/closed") / f"{mes_rel}.json"
    _rel_pdf_path = Path("exports") / f"{mes_rel}_relatorio.pdf"

    _rel_already_closed = _rel_closed_path.exists()
    _rel_already_pdf = _rel_pdf_path.exists()

    _rel_can_proceed = True
    if _rel_already_closed or _rel_already_pdf:
        _what = []
        if _rel_already_closed:
            _what.append(f"snapshot `{_rel_closed_path}`")
        if _rel_already_pdf:
            _what.append(f"PDF `{_rel_pdf_path}`")
        st.warning(f"⚠️ Já existem para **{mes_rel}**: {', '.join(_what)}.")
        _rel_can_proceed = st.checkbox("Confirmar sobrescrita", key="rel_overwrite")

    if _rel_can_proceed:
        if st.button("✅ Fechar mês (backup + PDF)", type="primary", key="rel_close_btn"):
            with st.spinner("Gerando relatório..."):
                try:
                    # 1. Backup
                    _rel_bk = fu.backup_data_dir()
                    st.info(f"Backup criado: `{_rel_bk}`")

                    # 2. Carregar dados do mês (mesma lógica do Mensal)
                    _rel_base = fu.safe_load_month_csv(mes_rel, MONTH_DIR)
                    for _c in ("grupo", "conta_cartao", "nota"):
                        if _c not in _rel_base.columns:
                            _rel_base[_c] = ""
                    if not _rel_base.empty:
                        _rel_base["_source"] = "base"
                        if "parcelado" not in _rel_base.columns:
                            _rel_base["parcelado"] = False
                        if "parcela_str" not in _rel_base.columns:
                            _rel_base["parcela_str"] = ""

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
                            "parcelado": False, "parcela_str": "",
                            "_source": "transaction",
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
                    if not _rel_base.empty:
                        _rel_parts.append(_rel_base)
                    if _rel_trans_rows:
                        _rel_parts.append(pd.DataFrame(_rel_trans_rows))
                    if _rel_inst_rows:
                        _rel_parts.append(pd.DataFrame(_rel_inst_rows))

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
                    _rel_receita = float(
                        _rel_receitas[_rel_receitas["mes"] == mes_rel]["valor"].sum()
                        if not _rel_receitas.empty else 0.0
                    )

                    # 3. Snapshot JSON
                    _rel_snap = fu.generate_month_snapshot(mes_rel, _df_rel, _rel_receita, _rel_inst)
                    _rel_snap_path = fu.save_month_snapshot(mes_rel, _rel_snap)
                    st.info(f"Snapshot salvo: `{_rel_snap_path}`")

                    # 4. PDF
                    _rel_pdf_out = fu.generate_month_pdf(mes_rel, _rel_snap)
                    st.success(f"PDF gerado: `{_rel_pdf_out}`")

                    with open(_rel_pdf_out, "rb") as _f:
                        st.download_button(
                            "📥 Baixar PDF do Relatório",
                            data=_f.read(),
                            file_name=_rel_pdf_out.name,
                            mime="application/pdf",
                            key="dl_new_pdf",
                        )

                except Exception as _rel_err:
                    import traceback as _tb
                    st.error(f"Erro ao fechar mês: {_rel_err}")
                    st.code(_tb.format_exc())

    # Download de PDF já existente
    if _rel_already_pdf:
        st.divider()
        with open(_rel_pdf_path, "rb") as _f:
            st.download_button(
                "📥 Baixar PDF existente",
                data=_f.read(),
                file_name=_rel_pdf_path.name,
                mime="application/pdf",
                key="dl_existing_pdf",
            )


# ---------------------------------------------------------------------------
# PÁGINAS: MENSAL e ANUAL
# ---------------------------------------------------------------------------

else:
    # -----------------------------------------------------------------------
    # PÁGINA: MENSAL
    # -----------------------------------------------------------------------

    if page == "📅 Mensal":
        st.title("📅 Dashboard Mensal")

        # Seletor de mês independente de arquivos
        settings_month = fu.load_settings()["current_month"]
        try:
            _def_year = int(settings_month[:4])
            _def_month_num = int(settings_month[5:7])
        except Exception:
            _def_year = _date.today().year
            _def_month_num = _date.today().month

        today_year = _date.today().year
        year_opts = list(range(today_year - 2, today_year + 3))

        col_y, col_m = st.columns(2)
        with col_y:
            year_sel = st.selectbox(
                "Ano",
                year_opts,
                index=year_opts.index(_def_year) if _def_year in year_opts else 2,
                key="mes_year",
            )
        with col_m:
            month_num_sel = st.selectbox(
                "Mês",
                list(range(1, 13)),
                format_func=lambda m: calendar.month_abbr[m],
                index=_def_month_num - 1,
                key="mes_month",
            )
        mes_sel = f"{year_sel}-{month_num_sel:02d}"

        ov_path = MONTH_DIR / f"overrides_{mes_sel}.csv"

        # --- Carregar 3 fontes ---
        df_base = fu.safe_load_month_csv(mes_sel, MONTH_DIR)
        for _col in ("grupo", "conta_cartao", "nota"):
            if _col not in df_base.columns:
                df_base[_col] = ""
        if not df_base.empty:
            df_base["_source"] = "base"
            if "parcelado" not in df_base.columns:
                df_base["parcelado"] = False
            if "parcela_str" not in df_base.columns:
                df_base["parcela_str"] = ""

        # Transactions
        df_trans_mes = fu.load_transactions(mes_sel)
        trans_rows = []
        for _, t in df_trans_mes.iterrows():
            desc = str(t.get("descricao", "")).strip()
            nota = str(t.get("nota", "")).strip()
            trans_rows.append({
                "descricao": desc if desc else nota,
                "nota": nota,
                "categoria": str(t.get("categoria", "")),
                "grupo": str(t.get("grupo", "")),
                "previsto": 0.0,
                "real": float(t.get("valor", 0)),
                "diferenca": float(t.get("valor", 0)),
                "recorrente": bool(t.get("recorrente", False)),
                "conta_cartao": str(t.get("conta_cartao", "")),
                "parcelado": False,
                "parcela_str": "",
                "_source": "transaction",
            })

        # Installments
        df_inst_mes = fu.get_installments_for_month(mes_sel)
        inst_rows = []
        for _, inst in df_inst_mes.iterrows():
            inst_rows.append({
                "descricao": str(inst.get("descricao", "")),
                "nota": str(inst.get("nota", "")),
                "categoria": str(inst.get("categoria", "")),
                "grupo": str(inst.get("grupo", "")),
                "previsto": 0.0,
                "real": float(inst.get("valor_parcela", 0)),
                "diferenca": float(inst.get("valor_parcela", 0)),
                "recorrente": False,
                "conta_cartao": str(inst.get("conta_cartao", "")),
                "parcelado": True,
                "parcela_str": str(inst.get("parcela_str", "")),
                "_source": "installment",
            })

        # Combinar
        all_parts = []
        if not df_base.empty:
            all_parts.append(df_base)
        if trans_rows:
            all_parts.append(pd.DataFrame(trans_rows))
        if inst_rows:
            all_parts.append(pd.DataFrame(inst_rows))

        if not all_parts:
            df = pd.DataFrame()
        else:
            df = pd.concat(all_parts, ignore_index=True)
            for _col in ("descricao", "categoria", "grupo", "conta_cartao", "nota", "parcela_str"):
                df[_col] = df[_col].fillna("").astype(str).str.strip()
            for _col in ("previsto", "real", "diferenca"):
                df[_col] = pd.to_numeric(df[_col], errors="coerce").fillna(0.0)
            df["recorrente"] = df["recorrente"].fillna(False).astype(bool)
            df["parcelado"] = df["parcelado"].fillna(False).astype(bool)

        if df.empty:
            st.info(
                f"Sem dados para **{month_label(mes_sel)}**. "
                "Faça upload de um CSV base, lance transações ou cadastre parcelamentos."
            )
            st.stop()

        # Receita do mês
        df_receitas = fu.load_receitas(RECEITAS_PATH)
        rec_mes_df = df_receitas[df_receitas["mes"] == mes_sel]
        receita_mes = rec_mes_df["valor"].sum() if not rec_mes_df.empty else 0.0

        # ---- Filtros (sidebar) --------------------------------------------
        st.sidebar.divider()
        st.sidebar.subheader("Filtros")
        apenas_rec = st.sidebar.toggle("Apenas Recorrentes", value=False)

        def _clean_opts(series):
            return {
                v for v in series.unique()
                if str(v).strip() and str(v).strip().lower() != "nan"
            }

        _s_fil = fu.load_settings()
        _glob_grupos = {g for g in _s_fil.get("grupos_default", fu.GRUPOS_DEFAULT) if g.strip()}
        _glob_contas = {c for c in _s_fil.get("contas_default", fu.CONTAS_DEFAULT) if c.strip()}

        grupos_disp = sorted(_clean_opts(df["grupo"]) | _glob_grupos)
        contas_disp = sorted(_clean_opts(df["conta_cartao"]) | _glob_contas)

        grupo_filter = st.sidebar.multiselect("Grupo", grupos_disp) if grupos_disp else []
        conta_filter = st.sidebar.multiselect("Conta / Cartão", contas_disp) if contas_disp else []

        df_view = df[df["recorrente"]] if apenas_rec else df.copy()
        if grupo_filter:
            df_view = df_view[df_view["grupo"].isin(grupo_filter)]
        if conta_filter:
            df_view = df_view[df_view["conta_cartao"].isin(conta_filter)]

        df_graf = df_view[
            (df_view["descricao"].str.len() > 0) & (df_view["categoria"].str.len() > 0)
        ]

        # ---- Cards --------------------------------------------------------
        total_prev = df_graf["previsto"].sum()
        total_real = df_graf["real"].sum()
        diff = total_real - total_prev
        pct = (total_real / total_prev * 100) if total_prev > 0 else 0
        total_parc = df_inst_mes["valor_parcela"].sum() if not df_inst_mes.empty else 0.0
        saldo = receita_mes - total_real

        st.subheader(f"Resumo — {month_label(mes_sel)}")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Previsto", fmt(total_prev))
        c2.metric("Total Real", fmt(total_real))
        # "inverse": over-budget (diff>0) → red; under-budget (diff<0) → green ✅
        c3.metric("Diferença", fmt(diff), delta=f"{diff:+.2f}", delta_color="inverse")
        c4.metric("% Orçamento Usado", f"{pct:.1f}%")
        c5.metric("Parcelamentos", fmt(total_parc))

        if receita_mes > 0:
            st.metric(
                f"Saldo (Receita {fmt(receita_mes)} - Despesas)",
                fmt(saldo), delta=f"{saldo:+.2f}", delta_color=color_delta(saldo),
            )

        st.divider()

        # ---- Gráficos -----------------------------------------------------
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.subheader("Previsto vs Real por Categoria")
            if not df_graf.empty:
                cat_df = (
                    df_graf.groupby("categoria")[["previsto", "real"]]
                    .sum().reset_index().sort_values("real", ascending=False)
                )
                fig = px.bar(
                    cat_df, x="categoria", y=["previsto", "real"],
                    barmode="group", labels={"value": "R$", "variable": "Tipo"},
                    color_discrete_map={"previsto": "#5B9BD5", "real": "#E07B54"},
                )
                fig.update_layout(xaxis_tickangle=-35, margin=dict(b=80))
                st.plotly_chart(fig, use_container_width=True)

        with col_g2:
            st.subheader("Top 10 Descrições por Gasto Real")
            if not df_graf.empty:
                df_top = df_graf[df_graf["real"] > 0].copy()
                nota_s = df_top.get("nota", pd.Series([""] * len(df_top), index=df_top.index))
                df_top["_label"] = df_top["descricao"].where(
                    df_top["descricao"].str.len() > 0, nota_s.fillna("")
                )
                top_desc = (
                    df_top.groupby("_label")["real"].sum()
                    .sort_values(ascending=False).head(10).reset_index()
                    .rename(columns={"_label": "descricao"})
                )
                fig2 = px.bar(
                    top_desc, x="real", y="descricao", orientation="h",
                    labels={"real": "R$", "descricao": ""},
                    color="real", color_continuous_scale="Oranges",
                )
                fig2.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)

        st.divider()

        # ---- Tabelas -------------------------------------------------------
        tab1, tab2, tab3, tab4 = st.tabs(
            ["🔴 Estouros", "🔁 Recorrentes", "💳 Parcelamentos", "⚙️ Editar Recorrentes"]
        )

        with tab1:
            st.subheader("Itens que Estouraram o Orçamento")
            estouros = df_graf[
                (df_graf["real"] > df_graf["previsto"]) & (df_graf["previsto"] > 0)
            ].copy()
            estouros["estouro"] = estouros["real"] - estouros["previsto"]
            if estouros.empty:
                st.success("Nenhum item estourou o orçamento! 🎉")
            else:
                st.dataframe(
                    estouros[["descricao", "categoria", "previsto", "real", "estouro"]]
                    .sort_values("estouro", ascending=False),
                    use_container_width=True,
                )

        with tab2:
            st.subheader("Recorrentes / Fixos")
            rec_df = df_graf[df_graf["recorrente"]].copy()
            if rec_df.empty:
                st.info("Nenhum item recorrente.")
            else:
                st.dataframe(
                    rec_df[["descricao", "categoria", "real"]].sort_values("real", ascending=False),
                    use_container_width=True,
                )
                st.metric("Total Recorrentes", fmt(rec_df["real"].sum()))

        with tab3:
            st.subheader("Parcelamentos Ativos")
            # Usar apenas installments calculados (fonte canônica)
            if df_inst_mes.empty:
                st.info("Nenhum parcelamento ativo para este mês. Cadastre em 💳 Parcelamentos.")
            else:
                parc_show = df_inst_mes[["descricao", "categoria", "conta_cartao",
                                         "parcela_str", "valor_parcela"]].copy()
                parc_show["valor_parcela"] = parc_show["valor_parcela"].apply(fmt)
                st.dataframe(
                    parc_show.rename(columns={
                        "parcela_str": "parcela", "valor_parcela": "valor (R$)",
                    }),
                    use_container_width=True, hide_index=True,
                )
                st.metric("Total Parcelamentos", fmt(df_inst_mes["valor_parcela"].sum()))

        with tab4:
            st.subheader("Editar Marcação de Recorrentes")
            st.caption("Afeta apenas itens do CSV base. Clique em 'Salvar' para persistir.")
            edit_df = df_base[["descricao", "categoria", "real", "recorrente"]].copy() if not df_base.empty else pd.DataFrame()
            if edit_df.empty:
                st.info("Nenhum dado do CSV base para editar.")
            else:
                edit_df = edit_df[edit_df["descricao"].str.len() > 0]
                edited = st.data_editor(
                    edit_df,
                    column_config={
                        "recorrente": st.column_config.CheckboxColumn("Recorrente?"),
                        "real": st.column_config.NumberColumn("Real (R$)", format="%.2f"),
                    },
                    disabled=["descricao", "categoria", "real"],
                    use_container_width=True, hide_index=True,
                )
                if st.button("💾 Salvar overrides"):
                    ov_path.parent.mkdir(parents=True, exist_ok=True)
                    edited[["descricao", "categoria", "recorrente"]].to_csv(ov_path, index=False)
                    st.success(f"Salvo em `{ov_path}`")
                    st.rerun()

        st.divider()
        st.subheader("💡 Insights do Mês")
        for ins in fu.generate_insights(df_graf, receita_mes):
            st.markdown(f"- {ins}")

    # -----------------------------------------------------------------------
    # PÁGINA: ANUAL
    # -----------------------------------------------------------------------

    elif page == "📆 Anual":
        st.title("📆 Dashboard Anual")

        months_with_data = fu.available_months_with_data(MONTH_DIR)
        df_receitas = fu.load_receitas(RECEITAS_PATH)

        if not months_with_data:
            st.warning("Nenhum dado encontrado. Faça upload ou lance transações.")
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
                "mes": mes,
                "label": month_label(mes),
                "previsto": df_b_v["previsto"].sum() if not df_b_v.empty else 0.0,
                "real": total_real_mes,
                "receita": rec_mes,
                "saldo": rec_mes - total_real_mes,
            })
        serie = pd.DataFrame(rows)

        total_prev_ano = serie["previsto"].sum()
        total_real_ano = serie["real"].sum()
        total_rec_ano = serie["receita"].sum()
        saldo_ano = total_rec_ano - total_real_ano

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Previsto (Ano)", fmt(total_prev_ano))
        c2.metric("Total Real (Ano)", fmt(total_real_ano))
        c3.metric("Receita Total (Ano)", fmt(total_rec_ano))
        c4.metric("Saldo Anual", fmt(saldo_ano),
                  delta=f"{saldo_ano:+.2f}", delta_color=color_delta(saldo_ano))

        st.divider()
        st.subheader("Total Real por Mês")
        fig_serie = go.Figure()
        fig_serie.add_trace(go.Bar(x=serie["label"], y=serie["previsto"],
                                   name="Previsto", marker_color="#5B9BD5"))
        fig_serie.add_trace(go.Bar(x=serie["label"], y=serie["real"],
                                   name="Real", marker_color="#E07B54"))
        if serie["receita"].sum() > 0:
            fig_serie.add_trace(go.Scatter(x=serie["label"], y=serie["receita"],
                                           name="Receita", mode="lines+markers",
                                           line=dict(color="#27AE60", width=2)))
        fig_serie.update_layout(barmode="group", xaxis_title="Mês", yaxis_title="R$")
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
                top_cat = (
                    df_ano.groupby("categoria")["real"].sum()
                    .sort_values(ascending=False).head(10).reset_index()
                )
                st.plotly_chart(
                    px.pie(top_cat, values="real", names="categoria",
                           title="Distribuição por Categoria (Ano)"),
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
                        est["mes"] = mes
                        estouro_rows.append(est)
            if estouro_rows:
                df_est_ano = pd.concat(estouro_rows, ignore_index=True)
                top_est = (
                    df_est_ano.groupby(["categoria", "descricao"])["estouro"]
                    .sum().sort_values(ascending=False).head(10).reset_index()
                )
                fig_est = px.bar(
                    top_est, x="estouro", y="descricao", orientation="h",
                    color="categoria", labels={"estouro": "R$ Estouro", "descricao": ""},
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
                "mes": "Mês", "label": "Período",
                "previsto": "Previsto", "real": "Real",
                "receita": "Receita", "saldo": "Saldo",
            })[["Período", "Previsto", "Real", "Receita", "Saldo"]],
            use_container_width=True, hide_index=True,
        )
