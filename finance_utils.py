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
# Cloud persistence (GitHub Gist)
# ---------------------------------------------------------------------------

try:
    import cloud_storage as _cloud
except ImportError:
    _cloud = None


def _persist(filepath):
    """Envia arquivo para armazenamento em nuvem (se configurado)."""
    if _cloud and _cloud.is_enabled():
        _cloud.persist(filepath)


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
    "Saúde", "Beleza", "Serviço", "Casa", "Suplementos",
    "Vitaminas", "Pets", "Entretenimento", "Carro",
    "Apartamento", "Gastos inesperados", "Outro",
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


def ensure_month_budget(month: str, month_dir: Union[str, Path] = MONTH_DIR) -> bool:
    """
    Auto-create budget CSV for *month* if it doesn't exist yet.
    Copies the most recent previous month's budget with real values reset to 0.
    Returns True if a new file was created.
    """
    p = Path(month_dir) / f"despesas_{month}.csv"
    if p.exists():
        return False

    # Find the most recent previous month that has a budget file
    avail = sorted(available_months(Path(month_dir)))
    prev = [m for m in avail if m < month]
    if not prev:
        return False  # no previous month to copy from

    src_month = prev[-1]
    src_path = Path(month_dir) / f"despesas_{src_month}.csv"
    try:
        df = load_month_csv(src_path)
        # Reset real values to 0 for the new month
        if "real" in df.columns:
            df["real"] = 0.0
        if "diferenca" in df.columns:
            df["diferenca"] = -pd.to_numeric(df["previsto"], errors="coerce").fillna(0.0)
        save_budget_csv(month, df, Path(month_dir))
        return True
    except Exception:
        return False


def safe_load_month_csv(month: str, month_dir: Union[str, Path] = MONTH_DIR) -> pd.DataFrame:
    """
    Carrega CSV base do mês e aplica overrides.
    Retorna DataFrame vazio (com schema correto) se arquivo não existir.
    Auto-cria o arquivo a partir do mês anterior se necessário.
    """
    p = Path(month_dir) / f"despesas_{month}.csv"
    if not p.exists():
        ensure_month_budget(month, month_dir)
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
    _persist(p)


def delete_receita(index: int, path: Union[str, Path] = RECEITAS_PATH):
    """Remove a receita at the given DataFrame index."""
    p = Path(path)
    if not p.exists():
        return
    df = pd.read_csv(p)
    if index < 0 or index >= len(df):
        return
    df = df.drop(index).reset_index(drop=True)
    df.to_csv(p, index=False)
    _persist(p)


def update_receita(index: int, mes: str, fonte: str, valor: float, obs: str = "",
                   path: Union[str, Path] = RECEITAS_PATH):
    """Update a receita at the given DataFrame index."""
    p = Path(path)
    if not p.exists():
        return
    df = pd.read_csv(p)
    if index < 0 or index >= len(df):
        return
    df.at[index, "mes"] = mes
    df.at[index, "fonte"] = fonte
    df.at[index, "valor"] = valor
    df.at[index, "obs"] = obs
    df.to_csv(p, index=False)
    _persist(p)


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
            else:
                # Merge: ensure all GRUPOS_DEFAULT entries are present
                existing = set(s["grupos_default"])
                for g in GRUPOS_DEFAULT:
                    if g not in existing:
                        # Insert before "Outro" if it exists, else append
                        if "Outro" in s["grupos_default"]:
                            idx = s["grupos_default"].index("Outro")
                            s["grupos_default"].insert(idx, g)
                        else:
                            s["grupos_default"].append(g)
                # Cleanup: remove "Outros" if "Outro" exists (deduplicate)
                if "Outro" in s["grupos_default"] and "Outros" in s["grupos_default"]:
                    s["grupos_default"].remove("Outros")
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
    _persist(p)


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
    _persist(p)


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
        _persist(p)
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
        _persist(p)
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
    _persist(p)


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
# Assinaturas (Subscriptions)
# ---------------------------------------------------------------------------

SUBSCRIPTIONS_PATH = Path("data/subscriptions.json")

def load_subscriptions() -> list[dict]:
    """Load subscriptions from JSON file."""
    p = SUBSCRIPTIONS_PATH
    if not p.exists() or p.stat().st_size == 0:
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_subscriptions(subs: list[dict]) -> None:
    """Save subscriptions to JSON file."""
    p = SUBSCRIPTIONS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)
    _persist(p)

def add_subscription(name: str, valor: float, dia_desconto: int, site: str = "", email: str = "", obs: str = "") -> dict:
    """Add a new subscription."""
    subs = load_subscriptions()
    new_sub = {
        "id": str(uuid.uuid4()),
        "nome": name,
        "valor": valor,
        "dia_desconto": dia_desconto,
        "site": site,
        "email": email,
        "obs": obs,
        "ativo": True,
    }
    subs.append(new_sub)
    save_subscriptions(subs)
    return new_sub

def remove_subscription(sub_id: str) -> None:
    """Remove a subscription by id."""
    subs = load_subscriptions()
    subs = [s for s in subs if s.get("id") != sub_id]
    save_subscriptions(subs)

def toggle_subscription(sub_id: str) -> None:
    """Toggle a subscription active/inactive."""
    subs = load_subscriptions()
    for s in subs:
        if s.get("id") == sub_id:
            s["ativo"] = not s.get("ativo", True)
    save_subscriptions(subs)


# ---------------------------------------------------------------------------
# Contas a Pagar (Bills)
# ---------------------------------------------------------------------------

BILLS_TEMPLATE_PATH = Path("data/bills_template.json")
BILLS_STATUS_DIR = Path("data/bills_status")

def load_bills_template() -> list[dict]:
    """Load bills template (recurring bills configuration)."""
    p = BILLS_TEMPLATE_PATH
    if not p.exists() or p.stat().st_size == 0:
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_bills_template(bills: list[dict]) -> None:
    """Save bills template."""
    p = BILLS_TEMPLATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(bills, f, ensure_ascii=False, indent=2)
    _persist(p)

def add_bill_template(nome: str, categoria: str, dia_vencimento: int, valor: float) -> dict:
    """Add a new bill to the template."""
    bills = load_bills_template()
    new_bill = {
        "id": str(uuid.uuid4()),
        "nome": nome,
        "categoria": categoria,
        "dia_vencimento": dia_vencimento,
        "valor": valor,
        "ativo": True,
    }
    bills.append(new_bill)
    save_bills_template(bills)
    return new_bill

def remove_bill_template(bill_id: str) -> None:
    """Remove a bill from template."""
    bills = load_bills_template()
    bills = [b for b in bills if b.get("id") != bill_id]
    save_bills_template(bills)

def load_bills_status(month: str) -> dict:
    """Load payment status for a given month.
    Returns dict {bill_id: {"pago": bool, "valor_real": float|None}}.
    Handles legacy format where value was just a bool."""
    p = BILLS_STATUS_DIR / f"{month}.json"
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Migrate legacy bool format to new dict format
        result = {}
        for k, v in raw.items():
            if isinstance(v, bool):
                result[k] = {"pago": v, "valor_real": None}
            elif isinstance(v, dict):
                result[k] = v
            else:
                result[k] = {"pago": False, "valor_real": None}
        return result
    except Exception:
        return {}

def save_bills_status(month: str, status: dict) -> None:
    """Save payment status for a given month."""
    p = BILLS_STATUS_DIR / f"{month}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    _persist(p)

def sync_bills_for_month(month: str) -> list[dict]:
    """Get bills for a month with their payment status and actual values."""
    template = load_bills_template()
    status = load_bills_status(month)
    result = []
    for bill in template:
        if not bill.get("ativo", True):
            continue
        bill_id = bill["id"]
        bill_status = status.get(bill_id, {"pago": False, "valor_real": None})
        valor_real = bill_status.get("valor_real")
        result.append({
            **bill,
            "pago": bill_status.get("pago", False),
            "valor_real": valor_real if valor_real is not None else bill["valor"],
        })
    return result

def toggle_bill_paid(month: str, bill_id: str, month_dir: Path = None) -> None:
    """Toggle a bill's paid status and sync to budget CSV."""
    if month_dir is None:
        month_dir = Path("data/monthly")
    status = load_bills_status(month)
    entry = status.get(bill_id, {"pago": False, "valor_real": None})
    entry["pago"] = not entry.get("pago", False)
    status[bill_id] = entry
    save_bills_status(month, status)
    # Direct sync: write this specific bill to budget CSV
    _direct_bill_to_budget(month, bill_id, entry, month_dir)

def _direct_bill_to_budget(month: str, bill_id: str, entry: dict, month_dir: Path) -> None:
    """Directly write a single bill's value to the matching budget row.
    Called immediately after toggling payment status.
    """
    import unicodedata as _ud, re as _re

    # Find the bill info from template
    template = load_bills_template()
    bill = None
    for b in template:
        if b.get("id") == bill_id:
            bill = b
            break
    if bill is None:
        return

    csv_path = month_dir / f"despesas_{month}.csv"
    if not csv_path.exists():
        return

    df = load_month_csv(csv_path)
    if df.empty or "descricao" not in df.columns or "real" not in df.columns:
        return

    is_paid = entry.get("pago", False)
    valor_real = entry.get("valor_real")
    valor = valor_real if valor_real is not None else bill.get("valor", 0)

    def _norm(s: str) -> str:
        s = str(s).lower().strip()
        s = _ud.normalize("NFD", s)
        s = "".join(c for c in s if _ud.category(c) != "Mn")
        s = _re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
        s = _re.sub(r"\s+", " ", s)
        return s

    bill_norm = _norm(bill["nome"])
    bill_cat = _norm(bill.get("categoria", ""))

    # Strategy 1: find budget row by name match
    target_idx = None
    for idx, row in df.iterrows():
        desc = _norm(str(row.get("descricao", "")))
        if (bill_norm == desc or bill_norm in desc or desc in bill_norm):
            target_idx = idx
            break

    # Strategy 2: category fallback — find a budget row with same category
    # that does NOT name-match any template bill
    if target_idx is None and bill_cat:
        # Build set of budget rows that are "owned" by name-matched bills
        owned_rows = set()
        for tb in template:
            tb_norm = _norm(tb["nome"])
            for idx, row in df.iterrows():
                desc = _norm(str(row.get("descricao", "")))
                if (tb_norm == desc or tb_norm in desc or desc in tb_norm):
                    owned_rows.add(idx)
                    break

        for idx, row in df.iterrows():
            if idx in owned_rows:
                continue
            row_cat = _norm(str(row.get("categoria", "")))
            if row_cat == bill_cat:
                target_idx = idx
                break

    if target_idx is None:
        return

    # Write the value
    if is_paid:
        df.at[target_idx, "real"] = float(valor)
    else:
        df.at[target_idx, "real"] = 0.0

    if "diferenca" in df.columns:
        df["diferenca"] = pd.to_numeric(df["real"], errors="coerce").fillna(0) - \
                          pd.to_numeric(df["previsto"], errors="coerce").fillna(0)
    save_budget_csv(month, df, month_dir)

def update_bill_valor_real(month: str, bill_id: str, valor_real: float, month_dir: Path = None) -> None:
    """Update the actual value for a bill in a specific month and sync to budget."""
    if month_dir is None:
        month_dir = Path("data/monthly")
    status = load_bills_status(month)
    entry = status.get(bill_id, {"pago": False, "valor_real": None})
    entry["valor_real"] = valor_real
    status[bill_id] = entry
    save_bills_status(month, status)
    # Direct sync to budget CSV
    _direct_bill_to_budget(month, bill_id, entry, month_dir)

def _sync_bills_to_budget(month: str, month_dir: Path) -> None:
    """Sync paid bills to the budget CSV 'real' column.

    Three-pass matching:
      Pass 0 — Reserve budget rows for ALL bills (paid or not) by name.
               This prevents category-fallback from stealing a row that
               belongs to a specific template bill.
      Pass 1 — Set 'real' value for paid bills whose rows were reserved.
      Pass 2 — Category fallback: unmatched paid bills are summed by
               category and placed in the first UNreserved budget row
               of that category.
    """
    import unicodedata, re

    csv_path = month_dir / f"despesas_{month}.csv"
    if not csv_path.exists():
        print(f"[sync_bills] CSV not found: {csv_path}")
        return

    df = load_month_csv(csv_path)
    if df.empty or "descricao" not in df.columns or "real" not in df.columns:
        print(f"[sync_bills] DF empty or missing columns")
        return

    bills = sync_bills_for_month(month)
    print(f"[sync_bills] {len(bills)} bills, paid: {sum(1 for b in bills if b['pago'])}")

    def _normalize(s: str) -> str:
        s = str(s).lower().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def _name_match(bnorm: str, desc_norm: str) -> bool:
        """Check if bill name matches budget description."""
        bnorm_no_conta = bnorm.replace("conta de ", "") if bnorm.startswith("conta de ") else None
        return (
            bnorm == desc_norm
            or bnorm in desc_norm
            or desc_norm in bnorm
            or (bnorm_no_conta is not None and (
                bnorm_no_conta == desc_norm
                or bnorm_no_conta in desc_norm
                or desc_norm in bnorm_no_conta))
        )

    # --- Pass 0: Reserve budget rows for ALL bills by name (paid or not) ---
    bill_to_row: dict[int, int] = {}    # bill index → budget row index
    reserved_rows: set[int] = set()      # budget row indices reserved by name match
    changed = False

    for bi, b in enumerate(bills):
        bnorm = _normalize(b["nome"])
        for idx, row in df.iterrows():
            if idx in reserved_rows:
                continue
            desc_norm = _normalize(str(row.get("descricao", "")))
            if _name_match(bnorm, desc_norm):
                bill_to_row[bi] = idx
                reserved_rows.add(idx)
                break

    # --- Pass 1: Set 'real' for paid bills that have a reserved row ---
    bill_matched = set()
    for bi, b in enumerate(bills):
        if not b["pago"]:
            continue
        if bi in bill_to_row:
            idx = bill_to_row[bi]
            valor = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
            old_real = float(df.at[idx, "real"]) if pd.notna(df.at[idx, "real"]) else 0.0
            if abs(valor - old_real) > 0.01:
                df.at[idx, "real"] = valor
                changed = True
            bill_matched.add(bi)

    # --- Pass 2: Category fallback for unmatched paid bills ---
    unmatched_bills_by_cat: dict[str, float] = {}
    for bi, b in enumerate(bills):
        if bi in bill_matched or not b["pago"]:
            continue
        cat_norm = _normalize(b.get("categoria", ""))
        if not cat_norm:
            continue
        valor = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
        unmatched_bills_by_cat[cat_norm] = unmatched_bills_by_cat.get(cat_norm, 0.0) + valor

    for cat_norm, total_valor in unmatched_bills_by_cat.items():
        # Find the first UNreserved budget row with matching category
        for idx, row in df.iterrows():
            if idx in reserved_rows:
                continue
            row_cat_norm = _normalize(str(row.get("categoria", "")))
            if row_cat_norm == cat_norm:
                # REPLACE — never add to existing value
                if abs(total_valor - float(row.get("real", 0))) > 0.01:
                    df.at[idx, "real"] = total_valor
                    changed = True
                reserved_rows.add(idx)
                break

    if changed:
        if "diferenca" in df.columns:
            df["diferenca"] = pd.to_numeric(df["real"], errors="coerce").fillna(0) - pd.to_numeric(df["previsto"], errors="coerce").fillna(0)
        save_budget_csv(month, df, month_dir)


def sync_all_to_budget(month: str, month_dir: Path) -> dict:
    """Master sync: update budget CSV 'real' column from ALL sources.
    - Contas a Pagar (bills marked as paid) — matched by name, then by category
    - Transações (individual expenses logged)
    - Parcelamentos (installments active this month)

    Returns a debug dict with sync details.
    """
    _debug = {"bills": 0, "trans": 0, "inst": 0, "trans_matches": [], "trans_total": 0.0, "changed": False}
    import unicodedata, re

    csv_path = month_dir / f"despesas_{month}.csv"
    if not csv_path.exists():
        _debug["error"] = f"CSV not found: {csv_path}"
        return _debug

    df = load_month_csv(csv_path)
    if df.empty or "descricao" not in df.columns or "real" not in df.columns:
        _debug["error"] = f"CSV empty or missing columns. Cols: {list(df.columns)}"
        return _debug

    def _normalize(s: str) -> str:
        s = str(s).lower().strip()
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def _name_match(bnorm: str, desc_norm: str) -> bool:
        bnorm_no_conta = bnorm.replace("conta de ", "") if bnorm.startswith("conta de ") else None
        if (bnorm == desc_norm
            or bnorm in desc_norm
            or desc_norm in bnorm
            or (bnorm_no_conta is not None and (
                bnorm_no_conta == desc_norm
                or bnorm_no_conta in desc_norm
                or desc_norm in bnorm_no_conta))):
            return True
        # Word overlap: if the first significant word (4+ chars) of one
        # appears in the other, consider a match. Handles "Apple iCloud" ↔ "Apple cloud".
        words_a = [w for w in bnorm.split() if len(w) >= 4]
        words_b = [w for w in desc_norm.split() if len(w) >= 4]
        if words_a and words_b and words_a[0] == words_b[0]:
            return True
        return False

    # 1. Bills — three-pass matching
    bills = sync_bills_for_month(month)
    changed = False

    # Reset ALL real values to 0 before recalculating from scratch.
    # This prevents stale values from previous (possibly incorrect) syncs.
    for idx in df.index:
        old_val = float(df.at[idx, "real"] if pd.notna(df.at[idx, "real"]) else 0)
        if old_val != 0.0:
            df.at[idx, "real"] = 0.0
            changed = True

    # Pass 0: Reserve rows for ALL bills by name
    bill_to_row: dict[int, int] = {}
    reserved_rows: set[int] = set()

    for bi, b in enumerate(bills):
        bnorm = _normalize(b["nome"])
        for idx, row in df.iterrows():
            if idx in reserved_rows:
                continue
            desc_norm = _normalize(str(row.get("descricao", "")))
            if _name_match(bnorm, desc_norm):
                bill_to_row[bi] = idx
                reserved_rows.add(idx)
                break

    # Pass 1: Set real for paid bills with reserved rows
    bill_matched = set()
    for bi, b in enumerate(bills):
        if not b["pago"]:
            continue
        if bi in bill_to_row:
            idx = bill_to_row[bi]
            valor = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
            old_real = float(df.at[idx, "real"]) if pd.notna(df.at[idx, "real"]) else 0.0
            if abs(valor - old_real) > 0.01:
                df.at[idx, "real"] = valor
                changed = True
            bill_matched.add(bi)

    # Pass 2: Category fallback for unmatched paid bills (unreserved rows only)
    # NOTE: Do NOT add to reserved_rows here — these rows must remain
    # available for transactions in Pass 3.  Track amounts in pass2_amounts
    # so Pass 3 can include them when computing the final real value.
    pass2_amounts: dict[int, float] = {}
    unmatched_bills_by_cat: dict[str, float] = {}
    for bi, b in enumerate(bills):
        if bi in bill_matched or not b["pago"]:
            continue
        cat_norm = _normalize(b.get("categoria", ""))
        if not cat_norm:
            continue
        valor = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
        unmatched_bills_by_cat[cat_norm] = unmatched_bills_by_cat.get(cat_norm, 0.0) + valor

    for cat_norm, total_valor in unmatched_bills_by_cat.items():
        for idx, row in df.iterrows():
            if idx in reserved_rows:
                continue
            row_cat_norm = _normalize(str(row.get("categoria", "")))
            if row_cat_norm == cat_norm:
                df.at[idx, "real"] = total_valor
                changed = True
                pass2_amounts[idx] = total_valor
                break

    # 2. Build transaction totals by category (for rows not matched to any bill)
    trans = load_transactions(month)
    _debug["trans"] = len(trans)
    _debug["trans_total"] = float(trans["valor"].sum()) if not trans.empty and "valor" in trans.columns else 0.0
    _debug["bills"] = len(bills)
    trans_by_cat: dict[str, float] = {}
    if not trans.empty and "categoria" in trans.columns:
        for cat, grp in trans.groupby("categoria"):
            cat_norm = _normalize(str(cat))
            trans_by_cat[cat_norm] = float(grp["valor"].sum())

    # Pass 3: Add transaction totals to budget rows.
    row_trans_totals: dict[int, float] = {}
    if not trans.empty and "categoria" in trans.columns:

        for _, t in trans.iterrows():
            t_desc = _normalize(str(t.get("descricao", "")))
            t_cat = _normalize(str(t.get("categoria", "")))
            t_val = float(t.get("valor", 0))
            if t_val == 0:
                continue

            t_grupo = _normalize(str(t.get("grupo", "")))
            matched_idx = None

            # Step 1: match transaction description → budget description
            # Only match if the category also matches, to avoid e.g. "Agua"
            # (Alimentação/Mercado) matching the "Agua" utility bill (Moradia).
            for idx, row in df.iterrows():
                bud_desc = _normalize(str(row.get("descricao", "")))
                if not bud_desc:
                    continue
                if _name_match(t_desc, bud_desc):
                    bud_cat = _normalize(str(row.get("categoria", "")))
                    if bud_cat == t_cat:
                        matched_idx = idx
                        break

            # Step 2: match transaction grupo → budget description
            # e.g. grupo "Farmácia" matches budget row "Farmacia"
            if matched_idx is None and t_grupo:
                for idx, row in df.iterrows():
                    bud_desc = _normalize(str(row.get("descricao", "")))
                    if not bud_desc:
                        continue
                    if _name_match(t_grupo, bud_desc):
                        matched_idx = idx
                        break

            # Step 3: fall back to category match (skip rows reserved by bills)
            # Prefer "generic" rows (desc contains "extra", "outros", "geral",
            # or matches the category name itself) over specific named rows.
            if matched_idx is None:
                _generic_idx = None
                _specific_idx = None
                for idx, row in df.iterrows():
                    if idx in reserved_rows:
                        continue
                    row_cat = _normalize(str(row.get("categoria", "")))
                    row_desc = _normalize(str(row.get("descricao", "")))
                    if row_cat == t_cat or row_desc == t_cat:
                        # Is this a "generic/catch-all" row?
                        if any(kw in row_desc for kw in ("extra", "outros", "geral", "diversos")) or row_desc == row_cat:
                            if _generic_idx is None:
                                _generic_idx = idx
                        else:
                            if _specific_idx is None:
                                _specific_idx = idx
                if _generic_idx is not None:
                    matched_idx = _generic_idx
                elif _specific_idx is not None:
                    matched_idx = _specific_idx

            # If no budget row found, auto-create one so the transaction
            # is counted in totals (prevents silent data loss).
            if matched_idx is None:
                orig_cat = str(t.get("categoria", "Extra"))
                new_row = pd.DataFrame([{
                    "descricao": t_grupo if t_grupo else orig_cat,
                    "categoria": orig_cat,
                    "previsto": 0.0,
                    "real": 0.0,
                    "diferenca": 0.0,
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                matched_idx = df.index[-1]
                changed = True
                _debug["trans_matches"].append(f"{t_desc}({t_val:.2f})→AUTO-CREATED row (cat={t_cat})")

            if matched_idx is not None:
                row_trans_totals[matched_idx] = row_trans_totals.get(matched_idx, 0.0) + t_val
                _debug["trans_matches"].append(f"{t_desc}({t_val:.2f})→row[{matched_idx}]={df.at[matched_idx, 'descricao']}")

        # Apply totals: for each budget row, real = bill_amount (Pass1 + Pass2) + transaction_total
        for idx, t_total in row_trans_totals.items():
            old_real = float(df.at[idx, "real"]) if pd.notna(df.at[idx, "real"]) else 0.0
            # Get bill amount already applied to this row (from Pass 1)
            bill_amount = 0.0
            for bi, ridx in bill_to_row.items():
                if ridx == idx and bi in bill_matched:
                    b = bills[bi]
                    bill_amount = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
                    break
            # Also include Pass 2 category-fallback bill amounts
            bill_amount += pass2_amounts.get(idx, 0.0)
            new_real = bill_amount + t_total
            if abs(new_real - old_real) > 0.01:
                df.at[idx, "real"] = new_real
                changed = True

    # Pass 4: Parcelamentos (installments) → budget rows
    # Each active installment for this month adds its valor_parcela to the
    # matching budget row (by description first, then category fallback).
    inst = get_installments_for_month(month)
    row_inst_totals: dict[int, float] = {}
    if not inst.empty:

        for _, i in inst.iterrows():
            i_desc = _normalize(str(i.get("descricao", "")))
            i_cat = _normalize(str(i.get("categoria", "")))
            i_val = float(i.get("valor_parcela", 0))
            if i_val == 0:
                continue

            matched_idx = None
            # First: match installment description → budget description
            for idx, row in df.iterrows():
                bud_desc = _normalize(str(row.get("descricao", "")))
                if bud_desc and _name_match(i_desc, bud_desc):
                    matched_idx = idx
                    break
            # Second: category fallback (skip reserved, prefer generic rows)
            if matched_idx is None:
                _generic_idx = None
                _specific_idx = None
                for idx, row in df.iterrows():
                    if idx in reserved_rows:
                        continue
                    row_cat = _normalize(str(row.get("categoria", "")))
                    row_desc = _normalize(str(row.get("descricao", "")))
                    if row_cat == i_cat or row_desc == i_cat:
                        if any(kw in row_desc for kw in ("extra", "outros", "geral", "diversos")) or row_desc == row_cat:
                            if _generic_idx is None:
                                _generic_idx = idx
                        else:
                            if _specific_idx is None:
                                _specific_idx = idx
                if _generic_idx is not None:
                    matched_idx = _generic_idx
                elif _specific_idx is not None:
                    matched_idx = _specific_idx
            # If no budget row found, auto-create one so the installment
            # is counted in totals (prevents silent data loss).
            if matched_idx is None:
                orig_cat = str(i.get("categoria", "Extra"))
                new_row = pd.DataFrame([{
                    "descricao": str(i.get("descricao", "Parcelamento")),
                    "categoria": orig_cat,
                    "previsto": 0.0,
                    "real": 0.0,
                    "diferenca": 0.0,
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                matched_idx = df.index[-1]
                changed = True
                _debug.setdefault("inst_auto_rows", []).append(
                    f"Auto-created row for installment '{i.get('descricao','')}' (cat={orig_cat})"
                )

            if matched_idx is not None:
                row_inst_totals[matched_idx] = row_inst_totals.get(matched_idx, 0.0) + i_val

        # Apply: add installment totals on top of existing real (which may
        # already include bills from Pass 1/2 and transactions from Pass 3).
        for idx, i_total in row_inst_totals.items():
            current_real = float(df.at[idx, "real"]) if pd.notna(df.at[idx, "real"]) else 0.0
            new_real = current_real + i_total
            # But we need to avoid double-counting if this same row also had
            # Pass 3 values. Pass 3 already set real = bill_amount + trans_total.
            # So we just ADD installment total on top.
            # To make this idempotent, we need to track what the "clean" value is.
            # Clean approach: recalculate from scratch.
            bill_amount = 0.0
            for bi, ridx in bill_to_row.items():
                if ridx == idx and bi in bill_matched:
                    b = bills[bi]
                    bill_amount = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
                    break
            bill_amount += pass2_amounts.get(idx, 0.0)
            trans_amount = row_trans_totals.get(idx, 0.0)
            correct_real = bill_amount + trans_amount + i_total
            if abs(correct_real - current_real) > 0.01:
                df.at[idx, "real"] = correct_real
                changed = True

    # Pass 5: Subscriptions (assinaturas ativas) → budget rows
    # These are auto-paid (credit card), so always count as "real".
    subs = load_subscriptions()
    active_subs = [s for s in subs if s.get("ativo", True)]
    _debug["subs"] = len(active_subs)
    if active_subs:
        row_sub_totals: dict[int, float] = {}

        for s in active_subs:
            s_name = _normalize(str(s.get("nome", "")))
            s_val = float(s.get("valor", 0))
            if s_val == 0:
                continue

            matched_idx = None
            # Step 1: match subscription name → budget description
            for idx, row in df.iterrows():
                bud_desc = _normalize(str(row.get("descricao", "")))
                if bud_desc and _name_match(s_name, bud_desc):
                    matched_idx = idx
                    break

            # If no budget row found, auto-create one
            if matched_idx is None:
                s_cat = str(s.get("categoria", "Extra"))
                new_row = pd.DataFrame([{
                    "descricao": str(s.get("nome", "Assinatura")),
                    "categoria": s_cat,
                    "previsto": 0.0,
                    "real": 0.0,
                    "diferenca": 0.0,
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                matched_idx = df.index[-1]
                changed = True
                _debug.setdefault("sub_auto_rows", []).append(
                    f"Auto-created row for subscription '{s.get('nome','')}' (cat={s_cat})"
                )

            if matched_idx is not None:
                row_sub_totals[matched_idx] = row_sub_totals.get(matched_idx, 0.0) + s_val
                _debug.setdefault("sub_matches", []).append(f"{s_name}({s_val:.2f})→row[{matched_idx}]={df.at[matched_idx, 'descricao']}")

        # Apply: recalculate real = bill (Pass1+Pass2) + trans + inst + sub for each matched row
        for idx, s_total in row_sub_totals.items():
            current_real = float(df.at[idx, "real"]) if pd.notna(df.at[idx, "real"]) else 0.0
            bill_amount = 0.0
            for bi, ridx in bill_to_row.items():
                if ridx == idx and bi in bill_matched:
                    b = bills[bi]
                    bill_amount = b["valor_real"] if b["valor_real"] is not None else b.get("valor", 0)
                    break
            bill_amount += pass2_amounts.get(idx, 0.0)
            trans_amount = row_trans_totals.get(idx, 0.0)
            inst_amount = row_inst_totals.get(idx, 0.0)
            correct_real = bill_amount + trans_amount + inst_amount + s_total
            if abs(correct_real - current_real) > 0.01:
                df.at[idx, "real"] = correct_real
                changed = True

    _debug["changed"] = changed
    _debug["row_trans_totals"] = {int(k): round(v, 2) for k, v in row_trans_totals.items()}
    if changed:
        if "diferenca" in df.columns:
            df["diferenca"] = pd.to_numeric(df["real"], errors="coerce").fillna(0) - pd.to_numeric(df["previsto"], errors="coerce").fillna(0)
        save_budget_csv(month, df, month_dir)
        _debug["saved"] = True
    else:
        _debug["saved"] = False
    return _debug


# ---------------------------------------------------------------------------
# Limites por Categoria (Budget Limits)
# ---------------------------------------------------------------------------

BUDGET_LIMITS_PATH = Path("data/budget_limits.json")

def load_budget_limits() -> dict:
    """Load budget limits per category. Returns dict {category: limit_value}."""
    p = BUDGET_LIMITS_PATH
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_budget_limits(limits: dict) -> None:
    """Save budget limits per category."""
    p = BUDGET_LIMITS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(limits, f, ensure_ascii=False, indent=2)
    _persist(p)

def set_budget_limit(categoria: str, valor: float) -> None:
    """Set budget limit for a category."""
    limits = load_budget_limits()
    limits[categoria] = valor
    save_budget_limits(limits)

def remove_budget_limit(categoria: str) -> None:
    """Remove budget limit for a category."""
    limits = load_budget_limits()
    limits.pop(categoria, None)
    save_budget_limits(limits)

def get_limits_status(month: str, month_dir: Union[str, Path] = MONTH_DIR) -> list[dict]:
    """
    Get status of all budget limits for a given month.
    Returns list of dicts with: categoria, limite, gasto, restante, pct_usado.
    """
    limits = load_budget_limits()
    if not limits:
        return []

    # Load all expenses for the month
    df_base = safe_load_month_csv(month, month_dir)
    df_trans = load_transactions(month)
    df_inst = get_installments_for_month(month)

    # Aggregate by category
    # NOTE: df_base["real"] already includes bills + transactions +
    # installments + subscriptions after sync_all_to_budget().
    # Do NOT re-add transactions or installments here — that causes
    # double-counting.
    gastos: dict[str, float] = {}

    if not df_base.empty and "categoria" in df_base.columns:
        for cat, grp in df_base.groupby("categoria"):
            cat_str = str(cat).strip()
            if cat_str:
                gastos[cat_str] = gastos.get(cat_str, 0) + float(grp["real"].sum())

    # Also count installments/transactions whose categories have NO budget
    # row at all (they would have been silently dropped by the sync).
    _budget_cats = set()
    if not df_base.empty and "categoria" in df_base.columns:
        _budget_cats = {str(c).strip().lower() for c in df_base["categoria"].dropna().unique()}

    if not df_inst.empty and "categoria" in df_inst.columns:
        for cat, grp in df_inst.groupby("categoria"):
            cat_str = str(cat).strip()
            if cat_str and cat_str.lower() not in _budget_cats:
                gastos[cat_str] = gastos.get(cat_str, 0) + float(grp["valor_parcela"].sum())

    if not df_trans.empty and "categoria" in df_trans.columns:
        for cat, grp in df_trans.groupby("categoria"):
            cat_str = str(cat).strip()
            if cat_str and cat_str.lower() not in _budget_cats:
                gastos[cat_str] = gastos.get(cat_str, 0) + float(grp["valor"].sum())

    result = []
    for cat, limite in sorted(limits.items()):
        gasto = gastos.get(cat, 0.0)
        restante = limite - gasto
        pct = (gasto / limite * 100) if limite > 0 else 0
        result.append({
            "categoria": cat,
            "limite": limite,
            "gasto": round(gasto, 2),
            "restante": round(restante, 2),
            "pct_usado": round(pct, 1),
        })
    return result


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
    _persist(p)


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
    Gera dicionário de snapshot completo para fechamento do mês.
    df = budget base (com real já sincronizado via sync_all_to_budget).
    Coleta dados de todas as fontes para o relatório PDF abrangente.
    """
    if df.empty or "descricao" not in df.columns:
        df_v = pd.DataFrame()
    else:
        df_v = df[df["descricao"].str.len() > 0].copy()

    total_prev = float(df_v["previsto"].sum()) if not df_v.empty else 0.0
    total_real = float(df_v["real"].sum()) if not df_v.empty else 0.0
    diff = total_real - total_prev
    pct = (total_real / total_prev * 100) if total_prev > 0 else 0.0
    savings_rate = ((receita_mes - total_real) / receita_mes * 100) if receita_mes > 0 else 0.0

    # --- Por categoria ---
    por_cat: dict = {}
    if not df_v.empty and "categoria" in df_v.columns:
        for cat, grp in df_v.groupby("categoria"):
            if str(cat).strip():
                p = round(float(grp["previsto"].sum()), 2)
                r = round(float(grp["real"].sum()), 2)
                por_cat[str(cat)] = {
                    "previsto": p,
                    "real": r,
                    "diferenca": round(r - p, 2),
                    "pct_variacao": round(((r - p) / p * 100) if p > 0 else 0, 1),
                }

    # --- Por grupo ---
    por_grp: dict = {}
    if not df_v.empty and "grupo" in df_v.columns:
        grp_sub = df_v[df_v["grupo"].fillna("").str.strip().str.len() > 0]
        for grp_name, grp in grp_sub.groupby("grupo"):
            por_grp[str(grp_name)] = {
                "previsto": round(float(grp["previsto"].sum()), 2),
                "real": round(float(grp["real"].sum()), 2),
            }

    # --- Top variações (maiores estouros e economias) ---
    top_variacoes = sorted(
        [{"cat": k, **v} for k, v in por_cat.items() if v["previsto"] > 0],
        key=lambda x: abs(x["diferenca"]), reverse=True,
    )[:7]

    # --- Parcelamentos com detalhes extras ---
    parcelas_list: list = []
    total_parcelas_restante = 0.0
    if not df_inst_mes.empty:
        for _, row in df_inst_mes.iterrows():
            p_atual = int(row.get("parcela_atual", 0))
            p_total = int(row.get("parcelas_total", 0))
            v_parcela = round(float(row.get("valor_parcela", 0)), 2)
            restante = (p_total - p_atual) * v_parcela
            total_parcelas_restante += restante
            parcelas_list.append({
                "descricao": str(row.get("descricao", "")),
                "parcela_str": str(row.get("parcela_str", "")),
                "valor": v_parcela,
                "parcela_atual": p_atual,
                "parcelas_total": p_total,
                "restante": round(restante, 2),
            })

    # --- Contas fixas (bills) ---
    bills = sync_bills_for_month(month)
    bills_list = []
    total_bills_pago = 0.0
    total_bills_pendente = 0.0
    for b in bills:
        valor = b.get("valor_real") if b.get("valor_real") is not None else b.get("valor", 0)
        pago = b.get("pago", False)
        if pago:
            total_bills_pago += valor
        else:
            total_bills_pendente += valor
        bills_list.append({
            "nome": b.get("nome", ""),
            "categoria": b.get("categoria", ""),
            "valor": round(valor, 2),
            "pago": pago,
            "dia": b.get("dia_vencimento", 0),
        })

    # --- Assinaturas ---
    subs = load_subscriptions()
    active_subs = [s for s in subs if s.get("ativo", True)]
    subs_list = []
    total_subs = 0.0
    for s in active_subs:
        v = float(s.get("valor", 0))
        total_subs += v
        subs_list.append({
            "nome": s.get("nome", ""),
            "valor": round(v, 2),
            "categoria": s.get("categoria", "Extra"),
        })

    # --- Top transações ---
    trans = load_transactions(month)
    top_trans = []
    if not trans.empty and "valor" in trans.columns:
        top_df = trans.nlargest(10, "valor")
        for _, t in top_df.iterrows():
            top_trans.append({
                "data": str(t.get("data", "")),
                "descricao": str(t.get("descricao", "")),
                "categoria": str(t.get("categoria", "")),
                "valor": round(float(t.get("valor", 0)), 2),
                "grupo": str(t.get("grupo", "")),
            })

    # --- Recorrentes (fixos vs variáveis) ---
    total_fixo = total_bills_pago + total_subs + sum(p["valor"] for p in parcelas_list)
    total_variavel = max(0, total_real - total_fixo)
    pct_fixo = (total_fixo / total_real * 100) if total_real > 0 else 0.0

    # --- Histórico (meses anteriores para tendência) ---
    historico_meses: list = []
    try:
        y, m = int(month[:4]), int(month[5:7])
        for i in range(3, 0, -1):
            pm = m - i
            py = y
            while pm < 1:
                pm += 12
                py -= 1
            prev_month = f"{py:04d}-{pm:02d}"
            prev_csv = safe_load_month_csv(prev_month, MONTH_DIR)
            if not prev_csv.empty and "real" in prev_csv.columns:
                prev_total = float(prev_csv["real"].sum())
                prev_cats = {}
                if "categoria" in prev_csv.columns:
                    for cat, grp in prev_csv.groupby("categoria"):
                        if str(cat).strip():
                            prev_cats[str(cat)] = round(float(grp["real"].sum()), 2)
                prev_receitas = load_receitas(RECEITAS_PATH)
                prev_rec = float(prev_receitas[prev_receitas["mes"] == prev_month]["valor"].sum()) if not prev_receitas.empty else 0.0
                historico_meses.append({
                    "mes": prev_month,
                    "total_real": round(prev_total, 2),
                    "receita": round(prev_rec, 2),
                    "por_categoria": prev_cats,
                })
    except Exception:
        pass

    # --- Mês anterior para comparação ---
    prev_month_total = historico_meses[-1]["total_real"] if historico_meses else 0.0
    prev_month_receita = historico_meses[-1]["receita"] if historico_meses else 0.0
    variacao_mensal = round(((total_real - prev_month_total) / prev_month_total * 100) if prev_month_total > 0 else 0, 1)

    # --- Insights automáticos ---
    insights: list = []
    # 1. Categoria com maior estouro
    estouros = [v for v in top_variacoes if v["diferenca"] > 0]
    if estouros:
        top_est = estouros[0]
        insights.append(
            f"{top_est['cat']} excedeu o orçamento em R$ {top_est['diferenca']:,.2f} "
            f"({top_est['pct_variacao']:+.0f}%). Considere revisar o limite mensal."
        )
    # 2. Gastos fixos altos
    if pct_fixo > 70:
        insights.append(
            f"Gastos fixos representam {pct_fixo:.0f}% do total. "
            f"Sua margem de manobra para variáveis é limitada a R$ {total_variavel:,.2f}."
        )
    # 3. Saldo negativo
    saldo = receita_mes - total_real
    if saldo < 0:
        insights.append(
            f"Você gastou R$ {abs(saldo):,.2f} a mais do que recebeu. "
            f"Avalie cortar gastos variáveis ou aumentar receita."
        )
    elif savings_rate > 20:
        insights.append(
            f"Taxa de poupança de {savings_rate:.0f}% — excelente! "
            f"Você poupou R$ {saldo:,.2f} este mês."
        )
    # 4. Tendência crescente
    if variacao_mensal > 15:
        insights.append(
            f"Gastos subiram {variacao_mensal:.0f}% vs. mês anterior. "
            f"Verifique se há despesas pontuais ou um padrão crescente."
        )
    # 5. Categorias não utilizadas
    nao_usadas = [k for k, v in por_cat.items() if v["previsto"] > 0 and v["real"] == 0]
    if nao_usadas and len(nao_usadas) <= 3:
        insights.append(
            f"Categorias orçadas mas não utilizadas: {', '.join(nao_usadas)}. "
            f"Considere ajustar o orçamento."
        )

    # --- Projeção próximo mês ---
    compromissos_prox = total_bills_pendente + total_subs
    for p in parcelas_list:
        if p["parcela_atual"] < p["parcelas_total"]:
            compromissos_prox += p["valor"]
    sobra_prox = receita_mes - compromissos_prox  # estimate using same receita

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
        "saldo": round(receita_mes - total_real, 2),
        "savings_rate": round(savings_rate, 1),
        "variacao_mensal": variacao_mensal,
        "prev_month_total": round(prev_month_total, 2),
        "por_categoria": por_cat,
        "por_grupo": por_grp,
        "top_variacoes": top_variacoes,
        "parcelamentos": parcelas_list,
        "total_parcelas_restante": round(total_parcelas_restante, 2),
        "bills": bills_list,
        "bills_pago": round(total_bills_pago, 2),
        "bills_pendente": round(total_bills_pendente, 2),
        "assinaturas": subs_list,
        "total_assinaturas": round(total_subs, 2),
        "total_assinaturas_anual": round(total_subs * 12, 2),
        "top_transacoes": top_trans,
        "fixo_vs_variavel": {
            "fixo": round(total_fixo, 2),
            "variavel": round(total_variavel, 2),
            "pct_fixo": round(pct_fixo, 1),
        },
        "historico": historico_meses,
        "recorrentes": {
            "total": round(total_fixo, 2),
            "pct_do_total": round(pct_fixo, 1),
        },
        "insights": insights,
        "projecao_proximo_mes": {
            "compromissos": round(compromissos_prox, 2),
            "sobra_estimada": round(sobra_prox, 2),
        },
    }


def save_month_snapshot(month: str, snapshot: dict) -> Path:
    """Salva snapshot em data/closed/{month}.json e retorna o Path."""
    p = Path("data/closed") / f"{month}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    _persist(p)
    return p


def generate_month_pdf(month: str, snapshot: dict) -> Path:
    """
    Gera PDF completo do relatório mensal (4 páginas).
    Página 1: Resumo executivo + donut
    Página 2: Análise detalhada + tendências
    Página 3: Contas, parcelamentos, assinaturas
    Página 4: Top transações, insights, projeção
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
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image, PageBreak, HRFlowable,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

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
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    _ss = getSampleStyleSheet()

    def _ps(name, **kw):
        kw.setdefault("fontName", _font_name)
        return ParagraphStyle(name, parent=_ss["Normal"], **kw)

    sty_title = _ps("rpt_t", fontSize=18, spaceAfter=2, fontName=_font_bold)
    sty_subtitle = _ps("rpt_st", fontSize=10, spaceAfter=8, textColor=rl_colors.HexColor("#666666"))
    sty_h2 = _ps("rpt_h2", fontSize=12, spaceBefore=12, spaceAfter=6, fontName=_font_bold,
                  textColor=rl_colors.HexColor("#1B5E40"))
    sty_h3 = _ps("rpt_h3", fontSize=10, spaceBefore=8, spaceAfter=4, fontName=_font_bold)
    sty_body = _ps("rpt_b", fontSize=9, spaceAfter=3, leading=13)
    sty_body_small = _ps("rpt_bs", fontSize=8, spaceAfter=2, leading=11)
    sty_caption = _ps("rpt_c", fontSize=7.5, textColor=rl_colors.HexColor("#999999"))
    sty_alert = _ps("rpt_alert", fontSize=9, spaceAfter=4, leading=13,
                     backColor=rl_colors.HexColor("#FFF3CD"), borderPadding=6)
    sty_insight = _ps("rpt_ins", fontSize=8.5, spaceAfter=3, leading=12,
                       leftIndent=10, bulletIndent=0)
    sty_page_hdr = _ps("rpt_ph", fontSize=8, textColor=rl_colors.HexColor("#AAAAAA"))

    _hdr_green = rl_colors.HexColor("#1B5E40")
    _hdr_blue = rl_colors.HexColor("#1A56DB")
    _row_alt = rl_colors.HexColor("#F0F7F0")
    _green_light = rl_colors.HexColor("#E8F5E9")
    _red_light = rl_colors.HexColor("#FFEBEE")
    _green_text = rl_colors.HexColor("#2E7D32")
    _red_text = rl_colors.HexColor("#C62828")

    def _make_table(data, col_widths, hdr_color=_hdr_green):
        t = Table(data, colWidths=col_widths)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), hdr_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _font_bold),
            ("FONTNAME", (0, 1), (-1, -1), _font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, _row_alt]),
            ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#CCCCCC")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        t.setStyle(TableStyle(style_cmds))
        return t

    def _make_chart(fig):
        buf = _bio.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return buf

    def _hr():
        return HRFlowable(width="100%", thickness=0.5, color=rl_colors.HexColor("#E0E0E0"),
                          spaceBefore=6, spaceAfter=6)

    story: list = []
    totals = snapshot.get("totals", {})
    receita = snapshot.get("receita", 0.0)
    saldo = snapshot.get("saldo", receita - totals.get("real", 0))
    por_cat = snapshot.get("por_categoria", {})

    try:
        from datetime import datetime as _dtt
        label = _dtt.strptime(month, "%Y-%m").strftime("%B/%Y").capitalize()
    except Exception:
        label = month

    # ===================================================================
    # PAGE 1: RESUMO EXECUTIVO
    # ===================================================================
    story.append(Paragraph(f"Relatório Financeiro — {label}", sty_title))
    story.append(Paragraph(
        f"Gerado em {snapshot['timestamp'][:19].replace('T', ' ')}",
        sty_subtitle,
    ))

    # --- KPI Cards as table ---
    variacao = snapshot.get("variacao_mensal", 0)
    var_str = f"{'↑' if variacao > 0 else '↓'} {abs(variacao):.0f}% vs mês anterior" if variacao != 0 else "—"
    savings = snapshot.get("savings_rate", 0)
    sav_color = _green_text if savings >= 0 else _red_text
    sal_color = _green_text if saldo >= 0 else _red_text

    kpi_data = [[
        Paragraph(f"<font size=7 color='#888888'>RECEITA</font><br/>"
                  f"<font size=14><b>R$ {receita:,.2f}</b></font>", _ps("k1")),
        Paragraph(f"<font size=7 color='#888888'>DESPESAS</font><br/>"
                  f"<font size=14 color='#C62828'><b>R$ {totals.get('real', 0):,.2f}</b></font><br/>"
                  f"<font size=7 color='#888888'>{var_str}</font>", _ps("k2")),
        Paragraph(f"<font size=7 color='#888888'>SALDO</font><br/>"
                  f"<font size=14 color='{'#2E7D32' if saldo >= 0 else '#C62828'}'>"
                  f"<b>R$ {saldo:,.2f}</b></font>", _ps("k3")),
        Paragraph(f"<font size=7 color='#888888'>POUPANÇA</font><br/>"
                  f"<font size=14 color='{'#2E7D32' if savings >= 0 else '#C62828'}'>"
                  f"<b>{savings:.1f}%</b></font>", _ps("k4")),
    ]]
    kpi_tbl = Table(kpi_data, colWidths=[4.2 * cm] * 4)
    kpi_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, rl_colors.HexColor("#E0E0E0")),
        ("BOX", (1, 0), (1, 0), 0.5, rl_colors.HexColor("#E0E0E0")),
        ("BOX", (2, 0), (2, 0), 0.5, rl_colors.HexColor("#E0E0E0")),
        ("BOX", (3, 0), (3, 0), 0.5, rl_colors.HexColor("#E0E0E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor("#FAFAFA")),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 0.4 * cm))

    # --- Alert box ---
    insights = snapshot.get("insights", [])
    if insights:
        story.append(Paragraph(f"<b>Destaque:</b> {insights[0]}", sty_alert))
        story.append(Spacer(1, 0.2 * cm))

    # --- Donut chart: spending distribution ---
    if por_cat:
        story.append(Paragraph("Distribuição de gastos", sty_h2))
        cats_sorted = sorted(por_cat.items(), key=lambda x: x[1]["real"], reverse=True)
        cat_labels = [c[0] for c in cats_sorted if c[1]["real"] > 0]
        cat_values = [c[1]["real"] for c in cats_sorted if c[1]["real"] > 0]
        if cat_labels:
            greens = ["#1B5E40", "#2E7D32", "#388E3C", "#43A047", "#4CAF50",
                      "#66BB6A", "#81C784", "#A5D6A7", "#C8E6C9", "#E8F5E9",
                      "#B0BEC5", "#90A4AE"]
            fig_donut, ax_donut = plt.subplots(figsize=(7, 4))
            wedges, texts, autotexts = ax_donut.pie(
                cat_values, labels=None, autopct="%1.1f%%",
                colors=greens[:len(cat_labels)], pctdistance=0.78,
                wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1.5),
                startangle=90,
            )
            for at in autotexts:
                at.set_fontsize(7)
                at.set_color("white")
                at.set_fontweight("bold")
            ax_donut.legend(
                [f"{l} — R$ {v:,.0f}" for l, v in zip(cat_labels, cat_values)],
                loc="center left", bbox_to_anchor=(1.05, 0.5), fontsize=7,
                frameon=False,
            )
            plt.tight_layout()
            buf_donut = _make_chart(fig_donut)
            story.append(Image(buf_donut, width=16.5 * cm, height=7.5 * cm))

    # --- Resumo table ---
    story.append(Spacer(1, 0.3 * cm))
    summary_data = [
        ["Métrica", "Valor"],
        ["Receita total", f"R$ {receita:,.2f}"],
        ["Total previsto", f"R$ {totals.get('previsto', 0):,.2f}"],
        ["Total real", f"R$ {totals.get('real', 0):,.2f}"],
        ["% orçamento usado", f"{totals.get('pct_usado', 0):.1f}%"],
        ["Saldo (receita - despesas)", f"R$ {saldo:,.2f}"],
    ]
    story.append(_make_table(summary_data, [10 * cm, 6.8 * cm]))

    # ===================================================================
    # PAGE 2: ANÁLISE DETALHADA
    # ===================================================================
    story.append(PageBreak())
    story.append(Paragraph("Análise detalhada", sty_title))
    story.append(_hr())

    # --- Previsto vs Real chart (semantic colors) ---
    if por_cat:
        story.append(Paragraph("Previsto vs real por categoria", sty_h2))
        cats_by_diff = sorted(por_cat.items(), key=lambda x: x[1].get("diferenca", 0), reverse=True)
        cat_names = [c[0] for c in cats_by_diff]
        prevs = [por_cat[c]["previsto"] for c in cat_names]
        reals = [por_cat[c]["real"] for c in cat_names]
        bar_colors = ["#E53935" if r > p else "#43A047" for p, r in zip(prevs, reals)]

        fig_bar, ax_bar = plt.subplots(figsize=(10, 4.5))
        x = range(len(cat_names))
        w = 0.35
        ax_bar.bar([i - w / 2 for i in x], prevs, w, label="Previsto", color="#90CAF9", alpha=0.9)
        bars_real = ax_bar.bar([i + w / 2 for i in x], reals, w, label="Real", color=bar_colors, alpha=0.9)
        ax_bar.set_xticks(list(x))
        ax_bar.set_xticklabels(cat_names, rotation=35, ha="right", fontsize=7)
        ax_bar.set_ylabel("R$", fontsize=8)
        ax_bar.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
        ax_bar.legend(fontsize=8)
        ax_bar.grid(axis="y", linestyle="--", alpha=0.3)
        ax_bar.spines["top"].set_visible(False)
        ax_bar.spines["right"].set_visible(False)
        plt.tight_layout()
        story.append(Image(_make_chart(fig_bar), width=16.5 * cm, height=7.5 * cm))
        story.append(Paragraph(
            "<font size=7 color='#888888'>Verde = dentro do orçamento | "
            "Vermelho = acima do orçamento</font>",
            sty_caption,
        ))

    # --- Top variacoes table ---
    top_var = snapshot.get("top_variacoes", [])
    if top_var:
        story.append(Paragraph("Maiores variações do mês", sty_h2))
        var_data = [["Categoria", "Previsto", "Real", "Diferença", "Variação"]]
        for v in top_var:
            diff_val = v.get("diferenca", 0)
            pct_val = v.get("pct_variacao", 0)
            var_data.append([
                v.get("cat", ""),
                f"R$ {v.get('previsto', 0):,.2f}",
                f"R$ {v.get('real', 0):,.2f}",
                f"R$ {diff_val:+,.2f}",
                f"{pct_val:+.0f}%",
            ])
        tbl_var = _make_table(var_data, [4.5 * cm, 3.2 * cm, 3.2 * cm, 3.2 * cm, 2.7 * cm])
        for i, v in enumerate(top_var):
            row_idx = i + 1
            c = _red_light if v.get("diferenca", 0) > 0 else _green_light
            tc = _red_text if v.get("diferenca", 0) > 0 else _green_text
            tbl_var.setStyle(TableStyle([
                ("BACKGROUND", (3, row_idx), (4, row_idx), c),
                ("TEXTCOLOR", (3, row_idx), (4, row_idx), tc),
            ]))
        story.append(tbl_var)

    # --- Trend chart (3 months) ---
    historico = snapshot.get("historico", [])
    if historico:
        story.append(Paragraph("Tendência de gastos (últimos meses)", sty_h2))
        trend_months = [h["mes"][-5:] for h in historico] + [month[-5:]]
        trend_totals = [h["total_real"] for h in historico] + [totals.get("real", 0)]
        trend_receitas = [h.get("receita", 0) for h in historico] + [receita]

        fig_trend, ax_trend = plt.subplots(figsize=(8, 3.5))
        ax_trend.plot(trend_months, trend_totals, "o-", color="#E53935", linewidth=2,
                      markersize=6, label="Despesas", zorder=3)
        ax_trend.plot(trend_months, trend_receitas, "s--", color="#43A047", linewidth=2,
                      markersize=6, label="Receita", zorder=3)
        ax_trend.fill_between(trend_months, trend_totals, alpha=0.08, color="#E53935")
        ax_trend.fill_between(trend_months, trend_receitas, alpha=0.08, color="#43A047")
        for i, (t, r) in enumerate(zip(trend_totals, trend_receitas)):
            ax_trend.annotate(f"R${t:,.0f}", (trend_months[i], t),
                              textcoords="offset points", xytext=(0, 10), ha="center", fontsize=7)
        ax_trend.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
        ax_trend.legend(fontsize=8, loc="upper left")
        ax_trend.grid(axis="y", linestyle="--", alpha=0.3)
        ax_trend.spines["top"].set_visible(False)
        ax_trend.spines["right"].set_visible(False)
        plt.tight_layout()
        story.append(Image(_make_chart(fig_trend), width=16 * cm, height=6.5 * cm))

    # --- Fixo vs Variável ---
    fv = snapshot.get("fixo_vs_variavel", {})
    if fv:
        story.append(Paragraph("Composição: fixo vs variável", sty_h2))
        fig_fv, ax_fv = plt.subplots(figsize=(6, 2))
        fixo_val = fv.get("fixo", 0)
        var_val = fv.get("variavel", 0)
        total = fixo_val + var_val
        if total > 0:
            ax_fv.barh([""], [fixo_val], color="#1B5E40", label=f"Fixo R$ {fixo_val:,.0f}", height=0.5)
            ax_fv.barh([""], [var_val], left=[fixo_val], color="#81C784",
                       label=f"Variável R$ {var_val:,.0f}", height=0.5)
            ax_fv.set_xlim(0, total * 1.05)
            ax_fv.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
            ax_fv.legend(fontsize=8, loc="upper right")
            ax_fv.spines["top"].set_visible(False)
            ax_fv.spines["right"].set_visible(False)
            ax_fv.spines["left"].set_visible(False)
            ax_fv.set_yticks([])
            plt.tight_layout()
            story.append(Image(_make_chart(fig_fv), width=14 * cm, height=3.5 * cm))
        else:
            plt.close(fig_fv)
        story.append(Paragraph(
            f"Gastos fixos representam <b>{fv.get('pct_fixo', 0):.0f}%</b> do total. "
            f"Margem para variáveis: <b>R$ {var_val:,.2f}</b>.",
            sty_body,
        ))

    # ===================================================================
    # PAGE 3: CONTAS E COMPROMISSOS
    # ===================================================================
    story.append(PageBreak())
    story.append(Paragraph("Contas e compromissos", sty_title))
    story.append(_hr())

    # --- Bills ---
    bills = snapshot.get("bills", [])
    if bills:
        story.append(Paragraph("Contas fixas", sty_h2))
        bills_data = [["Conta", "Categoria", "Dia", "Valor", "Status"]]
        for b in sorted(bills, key=lambda x: x.get("dia", 0)):
            status = "Pago" if b.get("pago") else "Pendente"
            bills_data.append([
                b.get("nome", ""),
                b.get("categoria", ""),
                str(b.get("dia", "")),
                f"R$ {b.get('valor', 0):,.2f}",
                status,
            ])
        bills_data.append([
            Paragraph(f"<b>Total</b>", _ps("bt")),
            "", "",
            Paragraph(f"<b>R$ {snapshot.get('bills_pago', 0) + snapshot.get('bills_pendente', 0):,.2f}</b>", _ps("bv")),
            Paragraph(f"<font color='#2E7D32'>Pago: R$ {snapshot.get('bills_pago', 0):,.2f}</font> | "
                      f"<font color='#C62828'>Pend: R$ {snapshot.get('bills_pendente', 0):,.2f}</font>",
                      _ps("bs", fontSize=7)),
        ])
        tbl_bills = _make_table(bills_data, [4.5 * cm, 3 * cm, 1.5 * cm, 3.5 * cm, 4.3 * cm])
        for i, b in enumerate(sorted(bills, key=lambda x: x.get("dia", 0))):
            if b.get("pago"):
                tbl_bills.setStyle(TableStyle([
                    ("TEXTCOLOR", (4, i + 1), (4, i + 1), _green_text),
                ]))
            else:
                tbl_bills.setStyle(TableStyle([
                    ("TEXTCOLOR", (4, i + 1), (4, i + 1), _red_text),
                ]))
        story.append(tbl_bills)

    # --- Installments ---
    parcelas = snapshot.get("parcelamentos", [])
    if parcelas:
        story.append(Paragraph("Parcelamentos ativos", sty_h2))
        parc_data = [["Descrição", "Parcela", "Valor", "Restante"]]
        for p_ in parcelas:
            parc_data.append([
                str(p_.get("descricao", "")),
                str(p_.get("parcela_str", "")),
                f"R$ {p_.get('valor', 0):,.2f}",
                f"R$ {p_.get('restante', 0):,.2f}",
            ])
        parc_data.append([
            Paragraph("<b>Total restante em parcelamentos</b>", _ps("pt")),
            "", "",
            Paragraph(f"<b>R$ {snapshot.get('total_parcelas_restante', 0):,.2f}</b>", _ps("pv")),
        ])
        story.append(_make_table(parc_data, [5.5 * cm, 3 * cm, 3.7 * cm, 4.6 * cm]))

    # --- Subscriptions ---
    subs = snapshot.get("assinaturas", [])
    if subs:
        story.append(Paragraph("Assinaturas e serviços", sty_h2))
        subs_data = [["Serviço", "Categoria", "Mensal", "Anual"]]
        for s in sorted(subs, key=lambda x: x.get("valor", 0), reverse=True):
            subs_data.append([
                s.get("nome", ""),
                s.get("categoria", ""),
                f"R$ {s.get('valor', 0):,.2f}",
                f"R$ {s.get('valor', 0) * 12:,.2f}",
            ])
        subs_data.append([
            Paragraph(f"<b>{len(subs)} assinaturas</b>", _ps("st")),
            "",
            Paragraph(f"<b>R$ {snapshot.get('total_assinaturas', 0):,.2f}</b>", _ps("sv")),
            Paragraph(f"<b>R$ {snapshot.get('total_assinaturas_anual', 0):,.2f}</b>", _ps("sa")),
        ])
        story.append(_make_table(subs_data, [5 * cm, 3.5 * cm, 4.1 * cm, 4.2 * cm]))

    # ===================================================================
    # PAGE 4: INSIGHTS E PROJEÇÃO
    # ===================================================================
    story.append(PageBreak())
    story.append(Paragraph("Insights e próximo mês", sty_title))
    story.append(_hr())

    # --- Top transactions ---
    top_trans = snapshot.get("top_transacoes", [])
    if top_trans:
        story.append(Paragraph("Maiores transações do mês", sty_h2))
        trans_data = [["Data", "Descrição", "Categoria", "Valor"]]
        for t in top_trans:
            trans_data.append([
                t.get("data", "")[-5:] if len(t.get("data", "")) >= 5 else t.get("data", ""),
                t.get("descricao", ""),
                t.get("categoria", ""),
                f"R$ {t.get('valor', 0):,.2f}",
            ])
        story.append(_make_table(trans_data, [2.5 * cm, 6.5 * cm, 4 * cm, 3.8 * cm]))

    # --- Real por Grupo ---
    por_grp = snapshot.get("por_grupo", {})
    grp_items = sorted(
        [(k, v["real"]) for k, v in por_grp.items() if v["real"] > 0],
        key=lambda x: x[1], reverse=True,
    )
    if grp_items:
        story.append(Paragraph("Gastos por grupo", sty_h2))
        glabels = [g[0] for g in grp_items]
        gvals = [g[1] for g in grp_items]
        fig_grp, ax_grp = plt.subplots(figsize=(8, max(2.5, len(glabels) * 0.4)))
        bars = ax_grp.barh(glabels[::-1], gvals[::-1], color="#1B5E40", alpha=0.85, height=0.6)
        for bar, val in zip(bars, gvals[::-1]):
            ax_grp.text(bar.get_width() + max(gvals) * 0.02, bar.get_y() + bar.get_height() / 2,
                        f"R$ {val:,.0f}", va="center", fontsize=7)
        ax_grp.set_xlim(0, max(gvals) * 1.2)
        ax_grp.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"R${v:,.0f}"))
        ax_grp.spines["top"].set_visible(False)
        ax_grp.spines["right"].set_visible(False)
        plt.tight_layout()
        h_grp = min(7, max(3, len(glabels) * 0.45 + 1))
        story.append(Image(_make_chart(fig_grp), width=15 * cm, height=h_grp * cm))

    # --- Insights ---
    if insights:
        story.append(Paragraph("Recomendações", sty_h2))
        for idx, ins in enumerate(insights):
            bullet = ["◆", "◇", "▸", "▹", "●"][idx % 5]
            story.append(Paragraph(f"{bullet}  {ins}", sty_insight))
        story.append(Spacer(1, 0.3 * cm))

    # --- Next month projection ---
    proj = snapshot.get("projecao_proximo_mes", {})
    if proj:
        story.append(Paragraph("Projeção para o próximo mês", sty_h2))
        proj_data = [
            ["", "Valor"],
            ["Compromissos já confirmados (contas + parcelas + assinaturas)",
             f"R$ {proj.get('compromissos', 0):,.2f}"],
            ["Sobra estimada para variáveis",
             f"R$ {proj.get('sobra_estimada', 0):,.2f}"],
            ["Receita base (mesmo mês atual)",
             f"R$ {receita:,.2f}"],
        ]
        story.append(_make_table(proj_data, [12.5 * cm, 4.3 * cm]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            "<i>Projeção baseada nos compromissos fixos atuais e receita do mês corrente. "
            "Valores podem variar com novas despesas ou alterações de receita.</i>",
            sty_caption,
        ))

    # --- Footer ---
    story.append(Spacer(1, 1 * cm))
    story.append(_hr())
    story.append(Paragraph(
        f"Relatório gerado automaticamente — Finanças Pessoais v12",
        sty_caption,
    ))

    doc.build(story)
    return pdf_path
