"""
finance_utils.py — funções utilitárias do dashboard financeiro pessoal.
"""

import json
import re
import io as _io
import csv as _csv
import os
import shutil
import unicodedata
import uuid
from datetime import datetime as _datetime
from pathlib import Path
from typing import Optional, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RECORRENTE_KEYWORDS = [
    "aluguel", "iptu", "internet", "plano", "spotify", "academia",
    "cloud", "iptv", "mei", "chatgpt", "apple", "dentista", "gympass",
]

MONTH_DIR = Path("data/monthly")
RECEITAS_PATH = Path("data/receitas.csv")
SETTINGS_PATH = Path("data/settings.json")
INSTALLMENTS_PATH = Path("data/installments.csv")

GRUPOS_DEFAULT = [
    "Mercado", "Farmácia", "Comida", "Transporte", "Lazer",
    "Saúde", "Beleza", "Serviço", "Casa", "Outros",
]
CONTAS_DEFAULT = ["Pix", "Cartão Renato", "Cartão Ana", "Dinheiro", "Outro"]

# Colunas canônicas de transactions (parcelado/parcela_* removidos — agora em installments)
TRANSACTIONS_COLS = [
    "id", "data", "descricao", "nota", "categoria", "grupo",
    "valor", "conta_cartao", "recorrente",
]

INSTALLMENTS_COLS = [
    "id", "descricao", "nota", "categoria", "grupo",
    "conta_cartao", "valor_parcela", "parcelas_total",
    "start_month", "ativo",
]

# Colunas mínimas de um df de base mensal vazio
_BASE_EMPTY_COLS = [
    "descricao", "nota", "categoria", "previsto", "real",
    "diferenca", "recorrente", "parcelado", "parcela_atual", "parcelas_total",
]


# ---------------------------------------------------------------------------
# Limpeza de moeda
# ---------------------------------------------------------------------------

def clean_currency(val) -> float:
    """
    Converte valores monetários sujos em float.

    Suporta:
      - "R$ 1.234,56"  -> 1234.56
      - "$ 117.00"     -> 117.0
      - "1234,56"      -> 1234.56
      - "1.234.567,89" -> 1234567.89
      - 1234.56 (já float/int)
      - None / "" / NaN -> 0.0
    """
    if val is None:
        return 0.0

    if isinstance(val, (int, float)):
        if pd.isna(val):
            return 0.0
        return float(val)

    s = str(val).strip()

    # Remove símbolos de moeda e espaços
    s = re.sub(r"[R\$\s]", "", s)
    if s == "" or s == "-":
        return 0.0

    # Detecta formato: se tem vírgula E ponto, o último separador é o decimal
    if "," in s and "." in s:
        # Ex.: "1.234,56" -> remover pontos (milhar), trocar vírgula por ponto
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            # Ex.: "1,234.56" -> remover vírgulas (milhar)
            s = s.replace(",", "")
    elif "," in s:
        # Vírgula única: milhar US ("1,200" → 1200) ou decimal BR ("1,50" → 1.5)
        # Heurística: se exatamente 3 dígitos após a vírgula e nenhum ponto → milhar
        parts = s.split(",")
        if (
            len(parts) == 2
            and len(parts[1]) == 3
            and parts[1].isdigit()
            and parts[0].lstrip("-").isdigit()
        ):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")

    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Normalização de colunas
# ---------------------------------------------------------------------------

_COL_MAP = {
    # padrões com encoding quebrado ou variações
    "descricao": "descricao",
    "descrição": "descricao",
    "descri??o": "descricao",
    "descri\ufffd\ufffdo": "descricao",
    "item": "descricao",
    "categoria": "categoria",
    "category": "categoria",
    "custo previsto": "previsto",
    "previsto": "previsto",
    "budget": "previsto",
    "custo real": "real",
    "real": "real",
    "actual": "real",
    "gasto": "real",
    "diferenca": "diferenca",
    "diferença": "diferenca",
    "diff": "diferenca",
    "diferença (r$)": "diferenca",
    "observacao": "obs",
    "observação": "obs",
    "obs": "obs",
    "nota": "obs",
}


def _slugify(s: str) -> str:
    """Remove acentos, passa para lower e strip."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renomeia colunas do DataFrame para nomes canônicos.
    Colunas não reconhecidas são mantidas com slug simples.
    """
    new_cols = {}
    for col in df.columns:
        slug = _slugify(col)
        new_cols[col] = _COL_MAP.get(slug, slug)
    df = df.rename(columns=new_cols)
    return df


# ---------------------------------------------------------------------------
# Formato largo → formato longo
# ---------------------------------------------------------------------------

_FIXED_CAT_MAP = {
    "aluguel":     "Moradia",
    "internet":    "Moradia",
    "plano":       "Moradia",
    "luz":         "Moradia",
    "agua":        "Moradia",
    "faxina":      "Casa",
    "obra":        "Casa",
    "sofa":        "Móveis",
    "mei":         "Impostos",
    "impostos":    "Impostos",
    "ipva":        "Impostos",
    "iptu":        "Impostos",
    "veiculo":     "Transporte",
    "gympass":     "Saúde",
    "suplementos": "Saúde",
    "cabelo":      "Cuidados Pessoais",
    "corte":       "Cuidados Pessoais",
    "iptv":        "Entretenimento",
    "entrada":     "Moradia",
}


def _infer_fixed_cat(desc: str) -> str:
    """Infere categoria para item fixo da coluna Descrição."""
    lower = _slugify(desc)
    for kw, cat in _FIXED_CAT_MAP.items():
        if _slugify(kw) in lower:
            return cat
    return "Fixos"


def _melt_wide_format(
    df: pd.DataFrame,
    include_fixed: bool = True,
    include_unnamed: bool = True,
) -> pd.DataFrame:
    """
    Converte planilha larga em tabela longa (descricao, categoria, previsto, real).

    Estrutura esperada:
      [col vazia opcional]  Descrição  Custo  [status]  Cat1  Unnamed  Cat2  Unnamed  ...

    Parâmetros:
      include_fixed   — inclui itens fixos (coluna Descrição). Desativar quando a aba
                        "Despesas mensais" já fornece esses itens com previsto/real precisos.
      include_unnamed — inclui blocos sem header nomeado (seções anônimas como "Outros").
                        Desativar para ignorar blocos como "Cartão c6 recorrente".
    """
    cols = list(df.columns)

    def _is_named(c) -> bool:
        s = str(c).strip()
        return bool(s) and s.lower() not in ("nan", "") and not s.startswith("Unnamed:")

    def _cat_name(s: str) -> str:
        """'Mercado (2.000,00)' → 'Mercado'"""
        return re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()

    def _clean(v) -> str:
        s = str(v).strip() if v is not None and not (
            isinstance(v, float) and pd.isna(v)
        ) else ""
        return "" if s.lower() == "nan" else s

    # Auto-detecta coluna de descrição (pode estar deslocada se col 0 é vazia)
    desc_col = 0
    for i, c in enumerate(cols):
        if "descri" in _slugify(str(c)):
            desc_col = i
            break
    cost_col = desc_col + 1
    cat_start = desc_col + 3  # pula: descrição, custo, status/nota

    # Monta pares (índice_valor, nome_categoria, é_anônimo)
    named_val_cols: set[int] = set()
    cat_pairs: list[tuple[int, str, bool]] = []

    # 1) Colunas com header nomeado (blocos oficiais de categoria)
    for i in range(cat_start, len(cols)):
        if _is_named(cols[i]):
            cat_pairs.append((i, _cat_name(str(cols[i]).strip()), False))
            named_val_cols.add(i)

    # 2) Colunas sem header com dados numéricos (blocos anônimos, ex: "Cartão c6")
    for i in range(cat_start, len(cols) - 1):
        if i in named_val_cols:
            continue
        if df.iloc[:, i].apply(
            lambda v: isinstance(v, (int, float)) and not pd.isna(v)
        ).any():
            cat_pairs.append((i, "Outros", True))

    cat_pairs.sort(key=lambda x: x[0])

    # Filtra pares conforme flags
    active_pairs = [
        (i, name) for i, name, is_unnamed in cat_pairs
        if not is_unnamed or include_unnamed
    ]

    records = []
    for _, row in df.iterrows():
        rv = row.tolist()

        # Item fixo (coluna Descrição) — ignorado quando include_fixed=False
        if include_fixed:
            desc_main = _clean(rv[desc_col]) if desc_col < len(rv) else ""
            custo     = _clean(rv[cost_col]) if cost_col < len(rv) else ""
            if desc_main:
                previsto = clean_currency(custo)
                records.append({
                    "descricao": desc_main,
                    "categoria": _infer_fixed_cat(desc_main),
                    "previsto":  previsto,
                    "real":      previsto,
                })

        # Sub-itens de cada par (valor, descrição)
        for cat_i, cat_name in active_pairs:
            if cat_i >= len(rv):
                continue
            val_str = _clean(rv[cat_i])
            if not val_str:
                continue
            amount = clean_currency(val_str)
            if amount == 0:
                continue
            desc_i    = cat_i + 1
            item_desc = _clean(rv[desc_i]) if desc_i < len(rv) else ""
            records.append({
                "descricao": item_desc if item_desc else cat_name,
                "categoria": cat_name,
                "previsto":  0.0,
                "real":      amount,
            })

    if not records:
        return pd.DataFrame(columns=["descricao", "categoria", "previsto", "real"])
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Inferência de recorrentes
# ---------------------------------------------------------------------------

def infer_recorrente(descricao: str) -> bool:
    """Retorna True se a descrição contém palavra-chave de recorrente."""
    if not isinstance(descricao, str):
        return False
    desc_lower = descricao.lower()
    return any(kw in desc_lower for kw in RECORRENTE_KEYWORDS)


# ---------------------------------------------------------------------------
# Inferência de parcelamentos (legado — apenas para CSVs base antigos)
# ---------------------------------------------------------------------------

_PARCELA_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def infer_parcelas(descricao: str) -> "tuple[bool, int, int]":
    """
    Detecta parcelamento pela descrição.
    Ex.: "Sofá - 5/6" -> (True, 5, 6)

    Retorna (parcelado, parcela_atual, parcelas_total).
    Mantido para compatibilidade com CSVs base existentes.
    """
    if not isinstance(descricao, str):
        return False, 0, 0
    m = _PARCELA_RE.search(descricao)
    if m:
        atual = int(m.group(1))
        total = int(m.group(2))
        return True, atual, total
    return False, 0, 0


# ---------------------------------------------------------------------------
# Carregamento de CSV mensal
# ---------------------------------------------------------------------------

def load_month_csv(filepath: Union[str, Path]) -> pd.DataFrame:
    """
    Lê e limpa um CSV mensal de despesas.

    Suporta dois formatos:
      - Simples: Descrição, Categoria, Custo Previsto, Custo Real, Diferença
      - Largo:   Descrição, Custo, <status>, <pares (R$ valor, desc) por categoria>

    Em ambos:
      - Pula linhas de título antes do header (detecta row com "descri")
      - Tenta utf-8-sig / utf-8 / latin-1 / cp1252
      - Infere recorrente e parcelamentos (legado)
    """
    path = Path(filepath)

    # 1. Detectar encoding
    content = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Não foi possível ler {filepath} com nenhum encoding.")

    # 2. Encontrar linha do header (contém "descri")
    raw_rows = list(_csv.reader(_io.StringIO(text)))
    header_idx = 0
    for i, row in enumerate(raw_rows):
        if any("descri" in str(c).lower() for c in row):
            header_idx = i
            break

    # 3. Ler com pandas a partir do header real
    df = pd.read_csv(_io.StringIO(text), skiprows=header_idx, skip_blank_lines=True)

    # 4. Detectar formato: simples vs. largo
    test_df = normalize_columns(df.copy())
    is_wide = "previsto" not in test_df.columns or "real" not in test_df.columns

    if is_wide:
        df = _melt_wide_format(df)
    else:
        df = test_df

    # 5. Garantir colunas mínimas
    for col in ("descricao", "categoria", "previsto", "real"):
        if col not in df.columns:
            df[col] = "" if col in ("descricao", "categoria") else 0.0

    # 6. Remover linhas completamente vazias
    df = df.dropna(how="all")
    df = df[~(df.astype(str).apply(lambda r: r.str.strip()).eq("").all(axis=1))]

    # 7. Converter moeda
    for col in ("previsto", "real"):
        df[col] = df[col].apply(clean_currency)

    # 8. Calcular diferença
    if "diferenca" not in df.columns:
        df["diferenca"] = df["real"] - df["previsto"]
    else:
        df["diferenca"] = df["diferenca"].apply(clean_currency)

    # 9. Strings e limpeza final
    df["descricao"] = df["descricao"].fillna("").astype(str).str.strip()
    df["categoria"] = df["categoria"].fillna("").astype(str).str.strip()
    df = df[df["descricao"].str.len() > 0].reset_index(drop=True)

    # 10. Inferir recorrente e parcelas (legado)
    df["recorrente"] = df["descricao"].apply(infer_recorrente)
    parcelas = df["descricao"].apply(lambda d: infer_parcelas(d))
    df["parcelado"] = parcelas.apply(lambda x: x[0])
    df["parcela_atual"] = parcelas.apply(lambda x: x[1])
    df["parcelas_total"] = parcelas.apply(lambda x: x[2])

    return df


# ---------------------------------------------------------------------------
# Importação de Excel (.xlsx)
# ---------------------------------------------------------------------------

def load_month_excel(filepath: Union[str, Path]) -> pd.DataFrame:
    """
    Importa um arquivo .xlsx de despesas mensais.

    Fontes aceitas (em ordem de prioridade):
      (A) Aba "simples" (Custo previsto + Custo Real): itens fixos com previsto/real oficiais.
      (B) Aba "larga" (blocos de categoria laterais): SOMENTE os blocos com header nomeado
          — ignora itens fixos duplicados (col Descrição) e blocos anônimos (ex: "Cartão c6").

    O DataFrame retornado inclui coluna '_origem' ("fixo" | "variavel") para relatório;
    essa coluna é ignorada por save_budget_csv (não é persistida no CSV).
    """
    path = Path(filepath)
    xl = pd.ExcelFile(path, engine="openpyxl")

    df_simple: Optional[pd.DataFrame] = None
    df_wide:   Optional[pd.DataFrame] = None

    for sheet in xl.sheet_names:
        raw = pd.read_excel(xl, sheet_name=sheet, header=None)

        # Localiza linha de cabeçalho (contém "descri")
        header_row = None
        for ri in range(min(10, len(raw))):
            if any("descri" in str(v).lower() for v in raw.iloc[ri] if pd.notna(v)):
                header_row = ri
                break
        if header_row is None:
            continue

        # Relê com cabeçalho correto; normaliza NaN/vazio → "Unnamed: N"
        df = pd.read_excel(xl, sheet_name=sheet, header=header_row)
        df.columns = [
            str(c).strip()
            if (pd.notna(c) and str(c).strip() and str(c).strip().lower() != "nan")
            else f"Unnamed: {i}"
            for i, c in enumerate(df.columns)
        ]
        df = df.dropna(how="all")

        test_df = normalize_columns(df.copy())
        has_simple = "previsto" in test_df.columns and "real" in test_df.columns

        if has_simple and df_simple is None:
            # (A) Aba formato simples — itens fixos com previsto/real
            for col in ("descricao", "categoria", "previsto", "real"):
                if col not in test_df.columns:
                    test_df[col] = "" if col in ("descricao", "categoria") else 0.0
            for col in ("previsto", "real"):
                test_df[col] = test_df[col].apply(clean_currency)
            test_df["descricao"] = test_df["descricao"].fillna("").astype(str).str.strip()
            test_df["categoria"] = test_df["categoria"].fillna("").astype(str).str.strip()
            test_df = test_df[test_df["descricao"].str.len() > 0].reset_index(drop=True)
            test_df["_origem"] = "fixo"
            df_simple = test_df

        elif not has_simple:
            # (B) Aba formato largo:
            #   include_fixed=False  → ignora coluna Descrição (resumo manual com PAGO)
            #   include_unnamed=False → ignora blocos sem header (ex: "Cartão c6 recorrente")
            parsed = _melt_wide_format(df, include_fixed=False, include_unnamed=False)
            if df_wide is None or len(parsed) > len(df_wide):
                df_wide = parsed

    if df_wide is not None:
        df_wide = df_wide.copy()
        df_wide["_origem"] = "variavel"

    # Mescla: (A) + itens de (B) não presentes em (A)
    if df_simple is not None and df_wide is not None:
        simple_descs = set(df_simple["descricao"].apply(_slugify))
        df_lateral = df_wide[~df_wide["descricao"].apply(_slugify).isin(simple_descs)].copy()
        df_result = pd.concat([df_simple, df_lateral], ignore_index=True)
    elif df_simple is not None:
        df_result = df_simple
    elif df_wide is not None:
        df_result = df_wide
    else:
        return pd.DataFrame(columns=_BASE_EMPTY_COLS)

    # Pós-processamento
    for col in ("descricao", "categoria", "previsto", "real"):
        if col not in df_result.columns:
            df_result[col] = "" if col in ("descricao", "categoria") else 0.0
    for col in ("previsto", "real"):
        df_result[col] = df_result[col].apply(clean_currency)
    df_result["diferenca"] = df_result["real"] - df_result["previsto"]
    df_result["descricao"] = df_result["descricao"].fillna("").astype(str).str.strip()
    df_result["categoria"] = df_result["categoria"].fillna("").astype(str).str.strip()
    df_result = df_result[df_result["descricao"].str.len() > 0].reset_index(drop=True)
    df_result["recorrente"] = df_result["descricao"].apply(infer_recorrente)
    parcelas = df_result["descricao"].apply(lambda d: infer_parcelas(d))
    df_result["parcelado"] = parcelas.apply(lambda x: x[0])
    df_result["parcela_atual"] = parcelas.apply(lambda x: x[1])
    df_result["parcelas_total"] = parcelas.apply(lambda x: x[2])

    return df_result


def apply_overrides(df: pd.DataFrame, overrides_path: Union[str, Path]) -> pd.DataFrame:
    """Aplica overrides de recorrente salvos pelo usuário."""
    path = Path(overrides_path)
    if not path.exists():
        return df
    try:
        ov = pd.read_csv(path)
        # ov tem colunas: descricao, categoria, recorrente
        ov_map = {
            (r["descricao"], r["categoria"]): bool(r["recorrente"])
            for _, r in ov.iterrows()
        }
        def apply_row(row):
            key = (row["descricao"], row["categoria"])
            if key in ov_map:
                row["recorrente"] = ov_map[key]
            return row
        df = df.apply(apply_row, axis=1)
    except Exception:
        pass
    return df


# ---------------------------------------------------------------------------
# Carregamento de todos os meses
# ---------------------------------------------------------------------------

def available_months(month_dir: Union[str, Path] = MONTH_DIR) -> list[str]:
    """
    Retorna lista de meses disponíveis (YYYY-MM) com base nos arquivos
    data/monthly/despesas_YYYY-MM.csv.
    """
    p = Path(month_dir)
    if not p.exists():
        return []
    months = []
    for f in sorted(p.glob("despesas_*.csv")):
        m = re.match(r"despesas_(\d{4}-\d{2})\.csv", f.name)
        if m:
            months.append(m.group(1))
    return months


def available_months_with_data(month_dir: Union[str, Path] = MONTH_DIR) -> list[str]:
    """
    Retorna meses com qualquer dado: base CSV ou transactions.
    Usado no Dashboard Anual para incluir meses sem CSV base.
    """
    p = Path(month_dir)
    if not p.exists():
        return []
    months: set[str] = set()
    for f in p.glob("despesas_*.csv"):
        m = re.match(r"despesas_(\d{4}-\d{2})\.csv", f.name)
        if m:
            months.add(m.group(1))
    for f in p.glob("transactions_*.csv"):
        m = re.match(r"transactions_(\d{4}-\d{2})\.csv", f.name)
        if m and f.stat().st_size > 0:
            months.add(m.group(1))
    return sorted(months)


def safe_load_month_csv(month: str, month_dir: Union[str, Path] = MONTH_DIR) -> pd.DataFrame:
    """
    Carrega CSV base do mês e aplica overrides.
    Retorna DataFrame vazio (com schema correto) se arquivo não existir.
    """
    p = Path(month_dir) / f"despesas_{month}.csv"
    if not p.exists():
        return pd.DataFrame(columns=_BASE_EMPTY_COLS)
    try:
        df = load_month_csv(p)
        ov_path = Path(month_dir) / f"overrides_{month}.csv"
        return apply_overrides(df, ov_path)
    except Exception:
        return pd.DataFrame(columns=_BASE_EMPTY_COLS)


def load_month_csvs(month_dir: Union[str, Path] = MONTH_DIR) -> dict[str, pd.DataFrame]:
    """Retorna dict {YYYY-MM: DataFrame} para todos os meses disponíveis."""
    p = Path(month_dir)
    result = {}
    for month in available_months(p):
        filepath = p / f"despesas_{month}.csv"
        ov_path = p / f"overrides_{month}.csv"
        try:
            df = load_month_csv(filepath)
            df = apply_overrides(df, ov_path)
            result[month] = df
        except Exception as e:
            print(f"[WARN] falha ao carregar {month}: {e}")
    return result


# ---------------------------------------------------------------------------
# Receitas
# ---------------------------------------------------------------------------

RECEITAS_COLS = ["mes", "fonte", "valor", "obs"]


def load_receitas(path: Union[str, Path] = RECEITAS_PATH) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=RECEITAS_COLS)
    try:
        df = pd.read_csv(p)
        df["valor"] = df["valor"].apply(clean_currency)
        return df
    except Exception:
        return pd.DataFrame(columns=RECEITAS_COLS)


def save_receita(mes: str, fonte: str, valor: float, obs: str = "",
                 path: Union[str, Path] = RECEITAS_PATH):
    """Adiciona uma linha em receitas.csv."""
    p = Path(path)
    new_row = pd.DataFrame([{"mes": mes, "fonte": fonte, "valor": valor, "obs": obs}])
    if p.exists() and p.stat().st_size > 0:
        df = pd.read_csv(p)
        df = pd.concat([df, new_row], ignore_index=True)
    else:
        df = new_row
    df.to_csv(p, index=False)


# ---------------------------------------------------------------------------
# Insights automáticos
# ---------------------------------------------------------------------------

def generate_insights(df: pd.DataFrame, receita_mes: float = 0.0) -> list[str]:
    """
    Retorna lista de strings com insights simples para o mês.
    """
    insights = []

    if df.empty:
        return ["Sem dados suficientes para gerar insights."]

    # Itens com real > 0 e com categoria
    df_valido = df[(df["real"] > 0) & (df["categoria"].str.len() > 0)]

    # 1. Categoria com maior estouro
    estouros = df_valido[df_valido["real"] > df_valido["previsto"]].copy()
    if not estouros.empty:
        estouros["estouro"] = estouros["real"] - estouros["previsto"]
        top_cat = (
            estouros.groupby("categoria")["estouro"].sum()
            .sort_values(ascending=False)
            .head(1)
        )
        cat, val = top_cat.index[0], top_cat.iloc[0]
        insights.append(
            f"**Maior estouro:** categoria '{cat}' ultrapassou o orçamento em R$ {val:,.2f}."
        )

    # 2. Recorrentes altos
    rec = df_valido[df_valido["recorrente"]]
    if not rec.empty:
        total_rec = rec["real"].sum()
        pct = (total_rec / df_valido["real"].sum() * 100) if df_valido["real"].sum() > 0 else 0
        insights.append(
            f"**Recorrentes:** somam R$ {total_rec:,.2f} ({pct:.1f}% do gasto total)."
            + (" Avaliar renegociações." if pct > 40 else "")
        )

    # 3. Parcelamentos pesando
    parc = df_valido[df_valido.get("parcelado", pd.Series(False, index=df_valido.index))]
    if not parc.empty:
        total_parc = parc["real"].sum()
        insights.append(
            f"**Parcelamentos:** R$ {total_parc:,.2f} em {len(parc)} parcela(s) ativa(s) este mês."
        )

    # 4. Saldo
    if receita_mes > 0:
        saldo = receita_mes - df_valido["real"].sum()
        emoji = "positivo" if saldo >= 0 else "negativo"
        insights.append(
            f"**Saldo do mês:** R$ {saldo:,.2f} ({emoji})."
        )

    if not insights:
        insights.append("Nenhum alerta relevante para este mês.")

    return insights[:4]


# ---------------------------------------------------------------------------
# Configurações (settings.json)
# ---------------------------------------------------------------------------

def _default_month() -> str:
    """Retorna mês atual em YYYY-MM no fuso de São Paulo."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")
        return _datetime.now(tz).strftime("%Y-%m")
    except Exception:
        return _datetime.now().strftime("%Y-%m")


def load_settings() -> dict:
    """Carrega data/settings.json; cria defaults se ausente ou inválido."""
    p = Path(SETTINGS_PATH)
    if p.exists() and p.stat().st_size > 0:
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            if "current_month" not in s:
                s["current_month"] = _default_month()
            if "grupos_default" not in s:
                s["grupos_default"] = GRUPOS_DEFAULT
            if "contas_default" not in s:
                s["contas_default"] = CONTAS_DEFAULT
            return s
        except Exception:
            pass
    return {
        "current_month": _default_month(),
        "grupos_default": GRUPOS_DEFAULT,
        "contas_default": CONTAS_DEFAULT,
    }


def save_settings(settings_dict: dict) -> None:
    """Persiste configurações em data/settings.json."""
    p = Path(SETTINGS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(settings_dict, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Transactions (lançamentos rápidos)
# ---------------------------------------------------------------------------

def load_transactions(month: str) -> pd.DataFrame:
    """
    Carrega data/monthly/transactions_{month}.csv.
    Backward-compat: ignora colunas extras (parcelado, parcela_*, forma_pagamento).
    """
    p = MONTH_DIR / f"transactions_{month}.csv"
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=TRANSACTIONS_COLS)
    try:
        df = pd.read_csv(p, encoding="utf-8", dtype=str)
        # Garantir colunas canônicas; colunas desconhecidas são descartadas
        for col in TRANSACTIONS_COLS:
            if col not in df.columns:
                df[col] = ""
        df = df[TRANSACTIONS_COLS].copy()
        df["valor"] = df["valor"].apply(clean_currency)
        df["recorrente"] = df["recorrente"].map(
            lambda v: str(v).strip().lower() in ("true", "1", "yes", "sim")
        )
        return df
    except Exception:
        return pd.DataFrame(columns=TRANSACTIONS_COLS)


def append_transaction(month: str, row_dict: dict) -> None:
    """Faz append de um lançamento em transactions_{month}.csv."""
    p = MONTH_DIR / f"transactions_{month}.csv"
    MONTH_DIR.mkdir(parents=True, exist_ok=True)
    if not str(row_dict.get("id", "")).strip():
        row_dict["id"] = str(uuid.uuid4())
    new_row = pd.DataFrame([row_dict])
    for col in TRANSACTIONS_COLS:
        if col not in new_row.columns:
            new_row[col] = ""
    new_row = new_row[TRANSACTIONS_COLS]
    if p.exists() and p.stat().st_size > 0:
        df = pd.read_csv(p, encoding="utf-8", dtype=str)
        # Garantir schema ao fazer append em arquivo antigo
        for col in TRANSACTIONS_COLS:
            if col not in df.columns:
                df[col] = ""
        df = df[TRANSACTIONS_COLS]
        df = pd.concat([df, new_row], ignore_index=True)
    else:
        df = new_row
    df.to_csv(p, index=False, encoding="utf-8")


def update_transaction(month: str, transaction_id: str, row_dict: dict) -> None:
    """Atualiza um lançamento existente por id (mantém id original)."""
    p = MONTH_DIR / f"transactions_{month}.csv"
    if not p.exists():
        return
    try:
        df = pd.read_csv(p, encoding="utf-8", dtype=str)
        for col in TRANSACTIONS_COLS:
            if col not in df.columns:
                df[col] = ""
        idx_list = df.index[df["id"].astype(str) == str(transaction_id)].tolist()
        if not idx_list:
            return
        row_dict["id"] = str(transaction_id)
        for col in TRANSACTIONS_COLS:
            df.at[idx_list[0], col] = str(row_dict.get(col, ""))
        df[TRANSACTIONS_COLS].to_csv(p, index=False, encoding="utf-8")
    except Exception:
        pass


def delete_transaction(month: str, transaction_id: str) -> None:
    """Remove um lançamento por id de transactions_{month}.csv."""
    p = MONTH_DIR / f"transactions_{month}.csv"
    if not p.exists():
        return
    try:
        df = pd.read_csv(p, encoding="utf-8", dtype=str)
        df = df[df["id"].astype(str) != str(transaction_id)]
        df.to_csv(p, index=False, encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Installments (contratos de parcelamento)
# ---------------------------------------------------------------------------

def _diff_months(target: str, start: str) -> int:
    """
    Número de meses de start até target (pode ser negativo se target < start).
    Ex.: target="2026-03", start="2026-01" → 2
    """
    yt, mt = int(target[:4]), int(target[5:7])
    ys, ms = int(start[:4]), int(start[5:7])
    return (yt - ys) * 12 + (mt - ms)


def load_installments() -> pd.DataFrame:
    """Carrega data/installments.csv; retorna DataFrame vazio se não existir."""
    p = Path(INSTALLMENTS_PATH)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=INSTALLMENTS_COLS)
    try:
        df = pd.read_csv(p, encoding="utf-8", dtype=str)
        for col in INSTALLMENTS_COLS:
            if col not in df.columns:
                df[col] = ""
        df["valor_parcela"] = df["valor_parcela"].apply(clean_currency)
        df["parcelas_total"] = pd.to_numeric(df["parcelas_total"], errors="coerce").fillna(0).astype(int)
        df["ativo"] = df["ativo"].map(
            lambda v: str(v).strip().lower() not in ("false", "0", "no", "nao", "não")
        )
        return df[INSTALLMENTS_COLS]
    except Exception:
        return pd.DataFrame(columns=INSTALLMENTS_COLS)


def save_installments(df: pd.DataFrame) -> None:
    """Persiste data/installments.csv."""
    p = Path(INSTALLMENTS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    for col in INSTALLMENTS_COLS:
        if col not in df.columns:
            df[col] = ""
    df[INSTALLMENTS_COLS].to_csv(p, index=False, encoding="utf-8")


def get_installments_for_month(month: str) -> pd.DataFrame:
    """
    Calcula parcelas ativas para o mês dado.

    Para cada contrato ativo:
      parcela_atual = diff_meses(month, start_month) + 1
      Inclui se 1 <= parcela_atual <= parcelas_total

    Retorna df com colunas:
      id, descricao, nota, categoria, grupo, conta_cartao,
      valor_parcela, parcelas_total, parcela_atual, parcela_str
    """
    _OUT_COLS = [
        "id", "descricao", "nota", "categoria", "grupo", "conta_cartao",
        "valor_parcela", "parcelas_total", "parcela_atual", "parcela_str",
    ]
    df = load_installments()
    if df.empty:
        return pd.DataFrame(columns=_OUT_COLS)

    rows = []
    for _, row in df.iterrows():
        if not bool(row.get("ativo", True)):
            continue
        start = str(row.get("start_month", "")).strip()
        if not re.match(r"^\d{4}-\d{2}$", start):
            continue
        parcelas_total = int(row.get("parcelas_total", 0))
        if parcelas_total < 1:
            continue
        parcela_atual = _diff_months(month, start) + 1
        if parcela_atual < 1 or parcela_atual > parcelas_total:
            continue
        rows.append({
            "id": str(row.get("id", "")),
            "descricao": str(row.get("descricao", "")),
            "nota": str(row.get("nota", "")),
            "categoria": str(row.get("categoria", "")),
            "grupo": str(row.get("grupo", "")),
            "conta_cartao": str(row.get("conta_cartao", "")),
            "valor_parcela": float(row.get("valor_parcela", 0)),
            "parcelas_total": parcelas_total,
            "parcela_atual": parcela_atual,
            "parcela_str": f"{parcela_atual}/{parcelas_total}",
        })

    if not rows:
        return pd.DataFrame(columns=_OUT_COLS)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Extração automática de parcelamentos a partir do CSV mensal
# ---------------------------------------------------------------------------

def extract_installments_from_month(
    month: str,
) -> "tuple[pd.DataFrame, pd.DataFrame, int, int]":
    """
    Extrai contratos de parcelamento de data/monthly/despesas_{month}.csv.

    Regras:
    - Procura r"\\b(\\d+)\\s*/\\s*(\\d+)\\b" em descricao; fallback para obs.
    - Ignora parcelas_total == 1.
    - descricao_base: remove o "n/n" e separadores finais.
    - valor_parcela: coluna real (ou previsto se real==0).
    - start_month: retroage (parcela_atual - 1) meses a partir de month.
    - Deduplicação por hash(descricao_base|conta_cartao|valor|start_month|total).

    Retorna (df_installments_atualizado, df_novos_contratos, created, updated).
    """
    import hashlib

    filepath = MONTH_DIR / f"despesas_{month}.csv"
    if not filepath.exists():
        return load_installments(), pd.DataFrame(columns=INSTALLMENTS_COLS), 0, 0

    try:
        df_month = load_month_csv(filepath)
    except Exception:
        return load_installments(), pd.DataFrame(columns=INSTALLMENTS_COLS), 0, 0

    _PARC_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
    _TRAIL_RE = re.compile(r"[\s\-–]+$")

    yt, mt = int(month[:4]), int(month[5:7])
    month_idx = yt * 12 + (mt - 1)  # 0-indexed absolute month

    extracted: list[dict] = []
    seen_hashes: set[str] = set()

    for _, row in df_month.iterrows():
        desc_val = str(row.get("descricao", ""))
        obs_val = str(row.get("obs", ""))

        m = _PARC_RE.search(desc_val)
        if m:
            descricao_base = _PARC_RE.sub("", desc_val)
            descricao_base = _TRAIL_RE.sub("", descricao_base)
            descricao_base = re.sub(r"\s+", " ", descricao_base).strip()
        else:
            m = _PARC_RE.search(obs_val)
            if not m:
                continue
            descricao_base = desc_val.strip()

        parcela_atual = int(m.group(1))
        parcelas_total = int(m.group(2))

        if parcelas_total == 1:
            continue
        if parcela_atual < 1 or parcela_atual > parcelas_total:
            continue
        if not descricao_base:
            continue

        valor_parcela = float(row.get("real", 0) or 0)
        if valor_parcela == 0:
            valor_parcela = float(row.get("previsto", 0) or 0)

        categoria = str(row.get("categoria", "")).strip()
        grupo = str(row.get("grupo", "")).strip()
        conta_cartao = str(row.get("conta_cartao", "")).strip()
        nota = str(obs_val).strip() if obs_val.strip() not in ("", "nan", "None") else ""

        start_idx = month_idx - (parcela_atual - 1)
        start_year = start_idx // 12
        start_mon = start_idx % 12 + 1
        start_month_str = f"{start_year:04d}-{start_mon:02d}"

        hash_key = hashlib.md5(
            "|".join([
                descricao_base,
                conta_cartao,
                f"{valor_parcela:.2f}",
                start_month_str,
                str(parcelas_total),
            ]).encode()
        ).hexdigest()[:16]

        if hash_key in seen_hashes:
            continue
        seen_hashes.add(hash_key)

        extracted.append({
            "_hash": hash_key,
            "descricao": descricao_base,
            "nota": nota,
            "categoria": categoria,
            "grupo": grupo,
            "conta_cartao": conta_cartao,
            "valor_parcela": valor_parcela,
            "parcelas_total": parcelas_total,
            "start_month": start_month_str,
        })

    _empty_new = pd.DataFrame(columns=INSTALLMENTS_COLS)
    if not extracted:
        return load_installments(), _empty_new, 0, 0

    df_inst = load_installments()

    def _norm(v) -> str:
        s = str(v).strip() if v is not None else ""
        return "" if s.lower() in ("nan", "none") else s

    def _row_hash(row: pd.Series) -> str:
        return hashlib.md5(
            "|".join([
                _norm(row.get("descricao", "")),
                _norm(row.get("conta_cartao", "")),
                f"{float(row.get('valor_parcela', 0) or 0):.2f}",
                _norm(row.get("start_month", "")),
                str(int(row.get("parcelas_total", 0))),
            ]).encode()
        ).hexdigest()[:16]

    existing_by_hash: dict[str, int] = {
        _row_hash(r): i for i, r in df_inst.iterrows()
    }

    created = 0
    updated = 0
    new_rows: list[dict] = []

    for item in extracted:
        h = item["_hash"]
        if h in existing_by_hash:
            df_inst.at[existing_by_hash[h], "ativo"] = True
            updated += 1
        else:
            new_rows.append({
                "id": str(uuid.uuid4()),
                "descricao": item["descricao"],
                "nota": item["nota"],
                "categoria": item["categoria"],
                "grupo": item["grupo"],
                "conta_cartao": item["conta_cartao"],
                "valor_parcela": item["valor_parcela"],
                "parcelas_total": item["parcelas_total"],
                "start_month": item["start_month"],
                "ativo": True,
            })
            created += 1

    df_new = pd.DataFrame(new_rows, columns=INSTALLMENTS_COLS) if new_rows else _empty_new
    if not df_new.empty:
        df_inst = pd.concat([df_inst, df_new], ignore_index=True)

    return df_inst, df_new, created, updated


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

_DATA_DIR = Path("data")
_BACKUPS_DIR = Path("data_backups")


def backup_data_dir() -> Path:
    """
    Copia o diretório data/ para data_backups/YYYYMMDD_HHMMSS/.
    Funciona em Windows e Mac (pathlib + shutil).
    Retorna o Path da subpasta criada.
    """
    timestamp = _datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = _BACKUPS_DIR / timestamp
    dest.mkdir(parents=True, exist_ok=True)
    if _DATA_DIR.exists():
        shutil.copytree(_DATA_DIR, dest / "data")
    return dest


def list_backups(n: int = 5) -> list[Path]:
    """Retorna os n backups mais recentes (ordem decrescente)."""
    if not _BACKUPS_DIR.exists():
        return []
    entries = sorted(
        (p for p in _BACKUPS_DIR.iterdir() if p.is_dir()),
        reverse=True,
    )
    return entries[:n]


# ---------------------------------------------------------------------------
# Orçamento (Budget) — edição direta do previsto
# ---------------------------------------------------------------------------

def load_budget_csv(month: str, month_dir: Union[str, Path] = MONTH_DIR) -> pd.DataFrame:
    """
    Carrega despesas_{month}.csv para edição do orçamento.
    Retorna DataFrame com colunas: descricao, categoria, previsto, real.
    Se não existir, retorna DataFrame vazio com essas colunas.
    """
    p = Path(month_dir) / f"despesas_{month}.csv"
    if not p.exists():
        return pd.DataFrame(columns=["descricao", "categoria", "previsto", "real"])
    try:
        df = load_month_csv(p)
        for col in ("descricao", "categoria", "previsto", "real"):
            if col not in df.columns:
                df[col] = "" if col in ("descricao", "categoria") else 0.0
        return df[["descricao", "categoria", "previsto", "real"]].copy()
    except Exception:
        return pd.DataFrame(columns=["descricao", "categoria", "previsto", "real"])


def save_budget_csv(month: str, df: pd.DataFrame,
                    month_dir: Union[str, Path] = MONTH_DIR) -> None:
    """
    Persiste orçamento em despesas_{month}.csv (UTF-8).
    df deve ter: descricao, categoria, previsto.
    real é preservado se presente; caso contrário, preenche 0.
    """
    p = Path(month_dir) / f"despesas_{month}.csv"
    Path(month_dir).mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["descricao"] = out["descricao"].fillna("").astype(str).str.strip()
    out["categoria"] = out["categoria"].fillna("").astype(str).str.strip()
    out["previsto"] = pd.to_numeric(out["previsto"], errors="coerce").fillna(0.0).clip(lower=0)
    if "real" not in out.columns:
        out["real"] = 0.0
    else:
        out["real"] = pd.to_numeric(out["real"], errors="coerce").fillna(0.0)
    out["diferenca"] = out["real"] - out["previsto"]
    out = out[out["descricao"].str.len() > 0].reset_index(drop=True)
    out[["descricao", "categoria", "previsto", "real", "diferenca"]].to_csv(
        p, index=False, encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fechamento do mês — snapshot JSON + PDF
# ---------------------------------------------------------------------------

def generate_month_snapshot(
    month: str,
    df: pd.DataFrame,
    receita_mes: float,
    df_inst_mes: pd.DataFrame,
) -> dict:
    """
    Gera dicionário de snapshot para fechamento do mês.
    df deve ser o DataFrame combinado (base + transactions + installments).
    """
    if df.empty or "descricao" not in df.columns:
        df_v = pd.DataFrame()
    else:
        df_v = df[df["descricao"].str.len() > 0].copy()

    total_prev = float(df_v["previsto"].sum()) if not df_v.empty else 0.0
    total_real = float(df_v["real"].sum()) if not df_v.empty else 0.0
    diff = total_real - total_prev
    pct = (total_real / total_prev * 100) if total_prev > 0 else 0.0

    # Por categoria
    por_cat: dict = {}
    if not df_v.empty and "categoria" in df_v.columns:
        for cat, grp in df_v.groupby("categoria"):
            if str(cat).strip():
                por_cat[str(cat)] = {
                    "previsto": round(float(grp["previsto"].sum()), 2),
                    "real": round(float(grp["real"].sum()), 2),
                }

    # Por grupo
    por_grp: dict = {}
    if not df_v.empty and "grupo" in df_v.columns:
        grp_sub = df_v[df_v["grupo"].fillna("").str.strip().str.len() > 0]
        for grp_name, grp in grp_sub.groupby("grupo"):
            por_grp[str(grp_name)] = {
                "previsto": round(float(grp["previsto"].sum()), 2),
                "real": round(float(grp["real"].sum()), 2),
            }

    # Parcelamentos
    parcelas_list: list = []
    if not df_inst_mes.empty:
        for _, row in df_inst_mes.iterrows():
            parcelas_list.append({
                "descricao": str(row.get("descricao", "")),
                "parcela_str": str(row.get("parcela_str", "")),
                "valor": round(float(row.get("valor_parcela", 0)), 2),
            })

    # Recorrentes
    total_rec = 0.0
    pct_rec = 0.0
    if not df_v.empty and "recorrente" in df_v.columns:
        rec_df = df_v[df_v["recorrente"].fillna(False).astype(bool)]
        total_rec = float(rec_df["real"].sum())
        pct_rec = (total_rec / total_real * 100) if total_real > 0 else 0.0

    return {
        "timestamp": _datetime.now().isoformat(),
        "month": month,
        "receita": round(receita_mes, 2),
        "totals": {
            "previsto": round(total_prev, 2),
            "real": round(total_real, 2),
            "diferenca": round(diff, 2),
            "pct_usado": round(pct, 2),
        },
        "por_categoria": por_cat,
        "por_grupo": por_grp,
        "parcelamentos": parcelas_list,
        "recorrentes": {
            "total": round(total_rec, 2),
            "pct_do_total": round(pct_rec, 2),
        },
    }


def save_month_snapshot(month: str, snapshot: dict) -> Path:
    """Salva snapshot em data/closed/{month}.json e retorna o Path."""
    p = Path("data/closed") / f"{month}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return p


def generate_month_pdf(month: str, snapshot: dict) -> Path:
    """
    Gera PDF do relatório mensal em exports/{month}_relatorio.pdf.
    Usa reportlab + matplotlib (fontes DejaVu do matplotlib para UTF-8).
    Retorna o Path do arquivo gerado.
    """
    import io as _bio
    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Registrar DejaVuSans (incluída no matplotlib) para suporte a acentos
    _mpl_font_dir = Path(_mpl.__file__).parent / "mpl-data" / "fonts" / "ttf"
    _font_name = "Helvetica"
    _font_bold = "Helvetica-Bold"
    for _fname, _ffile in (("DejaVuSans", "DejaVuSans.ttf"), ("DejaVuSans-Bold", "DejaVuSans-Bold.ttf")):
        _fpath = _mpl_font_dir / _ffile
        if _fpath.exists():
            try:
                pdfmetrics.registerFont(TTFont(_fname, str(_fpath)))
                if _fname == "DejaVuSans":
                    _font_name = "DejaVuSans"
                else:
                    _font_bold = "DejaVuSans-Bold"
            except Exception:
                pass

    exports_dir = Path("exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = exports_dir / f"{month}_relatorio.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    _ss = getSampleStyleSheet()

    def _ps(name, **kw):
        kw.setdefault("fontName", _font_name)
        return ParagraphStyle(name, parent=_ss["Normal"], **kw)

    sty_title = _ps("rpt_t", fontSize=17, spaceAfter=4, fontName=_font_bold)
    sty_h2 = _ps("rpt_h2", fontSize=11, spaceBefore=10, spaceAfter=4, fontName=_font_bold)
    sty_body = _ps("rpt_b", fontSize=9, spaceAfter=2)
    sty_caption = _ps("rpt_c", fontSize=8, textColor=rl_colors.grey)

    story: list = []

    try:
        from datetime import datetime as _dtt
        label = _dtt.strptime(month, "%Y-%m").strftime("%B/%Y").capitalize()
    except Exception:
        label = month

    story.append(Paragraph(f"Relatório Financeiro — {label}", sty_title))
    story.append(Paragraph(
        f"Gerado em: {snapshot['timestamp'][:19].replace('T', ' ')}",
        sty_caption,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # --- Resumo ---
    story.append(Paragraph("Resumo do Mês", sty_h2))
    totals = snapshot["totals"]
    receita = snapshot.get("receita", 0.0)
    saldo = receita - totals["real"]

    tbl_data = [
        ["Métrica", "Valor"],
        ["Receita", f"R$ {receita:,.2f}"],
        ["Total Previsto", f"R$ {totals['previsto']:,.2f}"],
        ["Total Real", f"R$ {totals['real']:,.2f}"],
        ["Diferença (Real − Prev.)", f"R$ {totals['diferenca']:,.2f}"],
        ["% Orçamento Usado", f"{totals['pct_usado']:.1f}%"],
        ["Saldo (Receita − Real)", f"R$ {saldo:,.2f}"],
    ]
    _hdr_blue = rl_colors.HexColor("#1A56DB")
    _row_alt = rl_colors.HexColor("#EBF5FB")
    _tbl_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _hdr_blue),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _font_bold),
        ("FONTNAME", (0, 1), (-1, -1), _font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_row_alt, rl_colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.grey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    t_sum = Table(tbl_data, colWidths=[9 * cm, 6 * cm])
    t_sum.setStyle(_tbl_style)
    story.append(t_sum)
    story.append(Spacer(1, 0.5 * cm))

    # --- Gráfico 1: Previsto vs Real por Categoria ---
    por_cat = snapshot.get("por_categoria", {})
    if por_cat:
        story.append(Paragraph("Previsto vs Real por Categoria", sty_h2))
        cats = sorted(por_cat, key=lambda c: por_cat[c]["real"], reverse=True)
        prevs = [por_cat[c]["previsto"] for c in cats]
        reals = [por_cat[c]["real"] for c in cats]
        fig1, ax1 = plt.subplots(figsize=(10, 4))
        x = range(len(cats))
        w = 0.38
        ax1.bar([i - w / 2 for i in x], prevs, w, label="Previsto", color="#636EFA", alpha=0.85)
        ax1.bar([i + w / 2 for i in x], reals, w, label="Real", color="#EF553B", alpha=0.85)
        ax1.set_xticks(list(x))
        ax1.set_xticklabels(cats, rotation=35, ha="right", fontsize=7)
        ax1.set_ylabel("R$")
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
        ax1.legend(fontsize=8)
        ax1.grid(axis="y", linestyle="--", alpha=0.4)
        plt.tight_layout()
        buf1 = _bio.BytesIO()
        fig1.savefig(buf1, format="png", dpi=130, bbox_inches="tight")
        plt.close(fig1)
        buf1.seek(0)
        story.append(Image(buf1, width=16 * cm, height=7 * cm))
        story.append(Spacer(1, 0.3 * cm))

    # --- Gráfico 2: Real por Grupo ---
    por_grp = snapshot.get("por_grupo", {})
    grp_items = sorted(
        [(k, v["real"]) for k, v in por_grp.items() if v["real"] > 0],
        key=lambda x: x[1], reverse=True,
    )
    if grp_items:
        story.append(Paragraph("Real por Grupo", sty_h2))
        glabels = [g[0] for g in grp_items]
        gvals = [g[1] for g in grp_items]
        fig2, ax2 = plt.subplots(figsize=(8, max(3, len(glabels) * 0.45)))
        ax2.barh(glabels[::-1], gvals[::-1], color="#00CC96", alpha=0.85)
        ax2.set_xlabel("R$")
        ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
        ax2.grid(axis="x", linestyle="--", alpha=0.4)
        plt.tight_layout()
        buf2 = _bio.BytesIO()
        fig2.savefig(buf2, format="png", dpi=130, bbox_inches="tight")
        plt.close(fig2)
        buf2.seek(0)
        h2 = min(8, max(3.5, len(glabels) * 0.5 + 1))
        story.append(Image(buf2, width=13 * cm, height=h2 * cm))
        story.append(Spacer(1, 0.3 * cm))

    # --- Recorrentes ---
    story.append(Paragraph("Recorrentes / Fixos", sty_h2))
    rec = snapshot.get("recorrentes", {})
    story.append(Paragraph(
        f"Total recorrentes: R$ {rec.get('total', 0):,.2f} "
        f"({rec.get('pct_do_total', 0):.1f}% do gasto total)",
        sty_body,
    ))
    story.append(Spacer(1, 0.3 * cm))

    # --- Parcelamentos ---
    parcelas = snapshot.get("parcelamentos", [])
    if parcelas:
        story.append(Paragraph("Parcelamentos Ativos no Mês", sty_h2))
        parc_data = [["Descrição", "Parcela", "Valor"]]
        for p_ in parcelas:
            parc_data.append([
                str(p_.get("descricao", "")),
                str(p_.get("parcela_str", "")),
                f"R$ {p_.get('valor', 0):,.2f}",
            ])
        t_parc = Table(parc_data, colWidths=[9 * cm, 3 * cm, 4 * cm])
        t_parc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _hdr_blue),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _font_bold),
            ("FONTNAME", (0, 1), (-1, -1), _font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_row_alt, rl_colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.grey),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_parc)

    doc.build(story)
    return pdf_path
