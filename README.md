# Dashboard Financeiro Pessoal

Streamlit app — source of truth para finanças pessoais com 3 fontes de dados, CRUD completo e parcelamentos como entidade própria.

## Estrutura

```
finance_dashboard/
├── app.py                  # app principal Streamlit
├── finance_utils.py        # funções utilitárias
├── requirements.txt
├── data/
│   ├── settings.json               # current_month persistido
│   ├── receitas.csv                # receitas lançadas
│   ├── installments.csv            # contratos de parcelamento
│   └── monthly/
│       ├── despesas_YYYY-MM.csv        # CSVs base (upload)
│       ├── overrides_YYYY-MM.csv       # overrides de recorrentes
│       └── transactions_YYYY-MM.csv    # lançamentos rápidos
└── .venv/
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Rodar

```bash
source .venv/bin/activate
streamlit run app.py
```

---

## Modelo de dados

### 3 fontes no Dashboard Mensal

| Fonte | Arquivo | Previsto | Real |
|-------|---------|----------|------|
| CSV Base | `despesas_YYYY-MM.csv` | ✓ | ✓ |
| Transactions | `transactions_YYYY-MM.csv` | — (0) | valor lançado |
| Parcelamentos | `installments.csv` (calculado) | — (0) | valor_parcela |

**Previsto total** = apenas CSV base.
**Real total** = real_base + sum(transactions.valor) + sum(parcelas.valor_parcela).

---

## Como usar

### Definir o mês atual

Sidebar → **⚙️ Config** → editar `YYYY-MM` → Salvar.
Persiste em `data/settings.json`. Padrão: mês atual (America/Sao_Paulo).

---

### Lançar gastos (⚡ Lançar Gasto)

Campos: data, descrição, nota, categoria, grupo, valor, conta/cartão, recorrente.

- **Criar**: preencher form → Salvar lançamento
- **Editar**: selecionar na tabela → Carregar para edição → alterar → Salvar alterações
- **Deletar**: selecionar → Deletar

Persiste em `data/monthly/transactions_YYYY-MM.csv` com `id` UUID.

---

### Parcelamentos (💳 Parcelamentos)

Parcelamento é um **contrato** independente, não um campo de transaction.

Campos do contrato:
| Campo | Descrição |
|-------|-----------|
| Descrição | Nome do bem/serviço |
| Nota | Loja, obs, etc. |
| Categoria / Grupo | Classificação |
| Conta / Cartão | Onde está sendo cobrado |
| Valor da parcela | Valor fixo por mês |
| Total de parcelas | ≥ 2 |
| Mês inicial | YYYY-MM da 1ª parcela |
| Ativo | true/false |

**Cálculo automático por mês:**
```
parcela_atual = diff_meses(mês_alvo, start_month) + 1
incluído se ativo=True e 1 ≤ parcela_atual ≤ parcelas_total
```

Exemplo: contrato `start_month=2026-03`, `parcelas_total=6`
- 2026-03 → `1/6`
- 2026-08 → `6/6`
- 2026-09 → não aparece

Persiste em `data/installments.csv`.

---

### Dashboard Mensal (📅 Mensal)

- Seletor de **ano + mês** independente de arquivos (pode selecionar mês futuro).
- Se o mês não tiver CSV base, ainda mostra parcelamentos e transações.
- Filtros sidebar: Recorrentes, Grupo, Conta/Cartão.
- Tab "💳 Parcelamentos" lista apenas contratos de `installments.csv`.
- Top Descrições: usa `descricao`; fallback para `nota` se vazio.

---

### Dashboard Anual (📆 Anual)

- Inclui meses com CSV base **ou** transactions.
- Total Real de cada mês = base + transactions + installments.
- Top Categorias inclui as 3 fontes.

---

## Formato do CSV de Despesas (Upload)

| Descrição | Categoria | Custo Previsto | Custo Real | Diferença |
|-----------|-----------|---------------|-----------|-----------|

- Valores: `R$ 1.234,56`, `1234,56`, `$ 117.00`, vazio (→ 0)
- Encoding: UTF-8, Latin-1, CP1252

---

## Testar localmente

```bash
# 1. Definir mês
# Sidebar → Config → "2026-03" → Salvar

# 2. Criar transaction
# ⚡ Lançar Gasto → preencher → Salvar lançamento

# 3. Editar transaction
# Selecionar na tabela → Carregar para edição → alterar → Salvar alterações

# 4. Criar installment 6x
# 💳 Parcelamentos → start_month=2026-03, parcelas=6, valor=500 → Criar
# Verificar: em 2026-03 aparece 1/6; em 2026-04 aparece 2/6

# 5. Ver no Dashboard Mensal
# 📅 Mensal → Ano=2026, Mês=Mar → ver cards + tab Parcelamentos
# Trocar Mês=Abr → parcela muda para 2/6 automaticamente
```

## Palavras-chave de Recorrentes (auto-detecção no CSV base)

`aluguel, iptu, internet, plano, spotify, academia, cloud, iptv, mei, chatgpt, apple, dentista, gympass`
