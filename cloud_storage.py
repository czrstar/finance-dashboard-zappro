"""
cloud_storage.py — Persistência de dados via branch 'data-store' no GitHub.

O Streamlit Cloud reseta o sistema de arquivos a cada deploy (branch main).
Este módulo salva/carrega arquivos de dados de/para a branch 'data-store'
do mesmo repositório, que NÃO dispara redeploy.

Configuração (Streamlit secrets ou variáveis de ambiente):
  GITHUB_TOKEN  — Personal Access Token com acesso ao repo
  GITHUB_REPO   — "owner/repo" (ex: "czrstar/finance-dashboard-zappro")
"""

import base64
import os
import json
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

_SYNC_FLAG = Path("/tmp/_finance_cloud_sync_done")
_BRANCH = "data-store"

# Arquivos individuais a persistir
_PERSIST_FILES = [
    "data/receitas.csv",
    "data/subscriptions.json",
    "data/bills_template.json",
    "data/budget_limits.json",
    "data/installments.csv",
    "data/settings.json",
]

# Diretórios cujos arquivos devem ser persistidos
_PERSIST_DIRS = [
    "data/monthly",
    "data/bills_status",
    "data/closed",
]

# Cache de SHAs para updates (Contents API precisa do SHA atual)
_sha_cache: dict[str, str] = {}


def _get_config() -> tuple[str, str]:
    """Obtém token e repo de st.secrets ou env vars."""
    token, repo = "", ""
    try:
        import streamlit as st
        # Bracket access is more reliable across Streamlit versions
        try:
            token = st.secrets["GITHUB_TOKEN"]
        except (KeyError, AttributeError):
            pass
        try:
            repo = st.secrets["GITHUB_REPO"]
        except (KeyError, AttributeError):
            pass
    except Exception:
        pass
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "")
    if not repo:
        repo = os.environ.get("GITHUB_REPO", "czrstar/finance-dashboard")
    return str(token).strip(), str(repo).strip()


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _api(token: str, repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/contents"


def is_enabled() -> bool:
    """Verifica se o armazenamento em nuvem está configurado."""
    token, repo = _get_config()
    return bool(token and repo and _requests)


def _ensure_branch_exists(token: str, repo: str) -> bool:
    """Garante que a branch data-store existe. Cria a partir de main se não existir."""
    url = f"https://api.github.com/repos/{repo}/git/ref/heads/{_BRANCH}"
    resp = _requests.get(url, headers=_headers(token), timeout=10)
    if resp.status_code == 200:
        return True
    # Branch não existe — criar a partir de main
    main_url = f"https://api.github.com/repos/{repo}/git/ref/heads/main"
    main_resp = _requests.get(main_url, headers=_headers(token), timeout=10)
    if main_resp.status_code != 200:
        print(f"[cloud_storage] main branch not found: {main_resp.status_code}")
        return False
    sha = main_resp.json().get("object", {}).get("sha", "")
    if not sha:
        return False
    create_resp = _requests.post(
        f"https://api.github.com/repos/{repo}/git/refs",
        headers=_headers(token),
        json={"ref": f"refs/heads/{_BRANCH}", "sha": sha},
        timeout=10,
    )
    ok = create_resp.status_code in (200, 201)
    print(f"[cloud_storage] create branch {_BRANCH}: {create_resp.status_code} ok={ok}")
    return ok


def diagnose() -> dict:
    """Retorna informações de diagnóstico sobre o cloud storage."""
    token, repo = _get_config()
    info = {
        "has_token": bool(token),
        "token_prefix": token[:8] + "..." if token else "",
        "repo": repo,
        "requests_available": bool(_requests),
        "sync_done": _SYNC_FLAG.exists(),
        "branch": _BRANCH,
    }
    if token and repo and _requests:
        # Testar acesso à API
        try:
            resp = _requests.get(
                f"https://api.github.com/repos/{repo}",
                headers=_headers(token),
                timeout=10,
            )
            info["api_status"] = resp.status_code
            if resp.status_code == 200:
                info["repo_full_name"] = resp.json().get("full_name", "")
            # Verificar branch
            br = _requests.get(
                f"https://api.github.com/repos/{repo}/git/ref/heads/{_BRANCH}",
                headers=_headers(token),
                timeout=10,
            )
            info["branch_exists"] = br.status_code == 200
        except Exception as e:
            info["api_error"] = str(e)
    return info


# ---------------------------------------------------------------------------
# Sync (download da branch data-store → filesystem local)
# ---------------------------------------------------------------------------

def sync_from_cloud(force: bool = False) -> bool:
    """
    Baixa todos os arquivos de dados da branch data-store para o filesystem.
    Roda apenas uma vez por deployment (usa flag em /tmp).
    """
    if not force and _SYNC_FLAG.exists():
        return True

    token, repo = _get_config()
    if not token or not repo or not _requests:
        return False

    try:
        # Garantir que a branch data-store existe
        _ensure_branch_exists(token, repo)

        # Listar toda a árvore da branch data-store
        tree_url = (
            f"https://api.github.com/repos/{repo}"
            f"/git/trees/{_BRANCH}?recursive=1"
        )
        resp = _requests.get(tree_url, headers=_headers(token), timeout=20)
        if resp.status_code != 200:
            print(f"[cloud_storage] tree falhou: {resp.status_code}")
            return False

        tree = resp.json().get("tree", [])
        cloud_paths = set()

        for item in tree:
            path = item.get("path", "")
            if item.get("type") != "blob":
                continue
            if not path.startswith("data/"):
                continue

            cloud_paths.add(path)

            # Baixar conteúdo do arquivo
            file_url = f"{_api(token, repo)}/{path}?ref={_BRANCH}"
            file_resp = _requests.get(
                file_url, headers=_headers(token), timeout=15
            )
            if file_resp.status_code != 200:
                continue

            file_data = file_resp.json()
            content_b64 = file_data.get("content", "")
            sha = file_data.get("sha", "")

            # Decodificar conteúdo (base64)
            try:
                content = base64.b64decode(content_b64).decode("utf-8")
            except Exception:
                continue

            # Salvar localmente
            local_path = Path(path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Cache do SHA para futuras atualizações
            _sha_cache[path] = sha

        # Semear: enviar arquivos locais que não estão na branch
        _seed_missing(token, repo, cloud_paths)

        _SYNC_FLAG.touch()
        return True

    except Exception as e:
        print(f"[cloud_storage] sync_from_cloud erro: {e}")
        return False


def _seed_missing(token: str, repo: str, cloud_paths: set):
    """Envia arquivos locais que ainda não existem na branch data-store."""
    local_files = _collect_local_files()

    for local_path in local_files:
        path_str = str(local_path)
        if path_str in cloud_paths:
            continue
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                continue
            _upload_file(token, repo, path_str, content)
        except Exception as e:
            print(f"[cloud_storage] seed erro ({path_str}): {e}")


def _collect_local_files() -> list[Path]:
    """Coleta todos os arquivos de dados que devem ser persistidos."""
    files = []
    for fp in _PERSIST_FILES:
        p = Path(fp)
        if p.exists() and p.stat().st_size > 0:
            files.append(p)
    for d in _PERSIST_DIRS:
        dp = Path(d)
        if dp.exists():
            for f in dp.iterdir():
                if f.is_file():
                    files.append(f)
    return files


# ---------------------------------------------------------------------------
# Upload / Persist
# ---------------------------------------------------------------------------

def _upload_file(token: str, repo: str, path: str, content: str) -> bool:
    """Cria ou atualiza um arquivo na branch data-store."""
    url = f"{_api(token, repo)}/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    payload = {
        "message": f"auto: update {path}",
        "content": encoded,
        "branch": _BRANCH,
    }

    # Se temos o SHA em cache, é update; senão tenta buscar
    sha = _sha_cache.get(path)
    if not sha:
        # Tenta buscar o SHA atual
        check = _requests.get(
            f"{url}?ref={_BRANCH}",
            headers=_headers(token),
            timeout=10,
        )
        if check.status_code == 200:
            sha = check.json().get("sha", "")

    if sha:
        payload["sha"] = sha

    resp = _requests.put(
        url,
        headers=_headers(token),
        json=payload,
        timeout=15,
    )

    if resp.status_code in (200, 201):
        # Atualiza cache do SHA
        new_sha = resp.json().get("content", {}).get("sha", "")
        if new_sha:
            _sha_cache[path] = new_sha
        return True

    # Se deu 409 (conflict), tenta buscar SHA atualizado e retry
    if resp.status_code == 409:
        check = _requests.get(
            f"{url}?ref={_BRANCH}",
            headers=_headers(token),
            timeout=10,
        )
        if check.status_code == 200:
            sha = check.json().get("sha", "")
            payload["sha"] = sha
            resp2 = _requests.put(
                url,
                headers=_headers(token),
                json=payload,
                timeout=15,
            )
            if resp2.status_code in (200, 201):
                new_sha = resp2.json().get("content", {}).get("sha", "")
                if new_sha:
                    _sha_cache[path] = new_sha
                return True

    print(f"[cloud_storage] upload falhou ({path}): {resp.status_code} — {resp.text[:200]}")
    return False


def persist(filepath) -> bool:
    """
    Envia um arquivo local para a branch data-store após escrita local.
    Chamado automaticamente por finance_utils após cada save.
    """
    token, repo = _get_config()
    if not token or not repo or not _requests:
        print(f"[cloud_storage] persist SKIP — token={bool(token)} repo={bool(repo)} requests={bool(_requests)}")
        return False

    try:
        p = Path(filepath)
        if not p.exists():
            print(f"[cloud_storage] persist SKIP — file not found: {p} (cwd={Path.cwd()})")
            return False

        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        # Normalize path: always use relative 'data/...' for the API
        path_str = str(filepath)
        # Strip any absolute prefix to ensure we get 'data/...'
        if "/" in path_str:
            idx = path_str.find("data/")
            if idx >= 0:
                path_str = path_str[idx:]

        print(f"[cloud_storage] persist uploading: {path_str} ({len(content)} bytes)")
        result = _upload_file(token, repo, path_str, content)
        print(f"[cloud_storage] persist result: {result} for {path_str}")
        return result

    except Exception as e:
        print(f"[cloud_storage] persist erro ({filepath}): {e}")
        return False


def delete_file(filepath) -> bool:
    """Remove um arquivo da branch data-store."""
    token, repo = _get_config()
    if not token or not repo or not _requests:
        return False

    try:
        path = str(filepath)
        url = f"{_api(token, repo)}/{path}"

        # Buscar SHA atual
        sha = _sha_cache.get(path)
        if not sha:
            check = _requests.get(
                f"{url}?ref={_BRANCH}",
                headers=_headers(token),
                timeout=10,
            )
            if check.status_code == 200:
                sha = check.json().get("sha", "")

        if not sha:
            return False

        resp = _requests.delete(
            url,
            headers=_headers(token),
            json={
                "message": f"auto: delete {path}",
                "sha": sha,
                "branch": _BRANCH,
            },
            timeout=15,
        )

        if resp.status_code == 200:
            _sha_cache.pop(path, None)
            return True

        return False

    except Exception as e:
        print(f"[cloud_storage] delete erro ({filepath}): {e}")
        return False
