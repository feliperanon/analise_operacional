"""
Validação de ambiente no Render (não fatal).

ÁREA CRÍTICA DE STARTUP — leia antes de editar:
- Mudanças aqui afetam todo deploy no Render; erro de sintaxe ou import quebra a subida.
- Não introduza `raise` para segredo fraco, URL incompleta ou variável opcional sem decisão
  explícita de produto e sem atualizar testes em tests/test_render_env_validation.py.
- Não misture `logger.*` e `raise` no mesmo fluxo de validação de configuração.
- Não duplique docstrings nem deixe parênteses/blocos ambíguos.
- Falha estrutural (sintaxe, import, bug real) deve falhar naturalmente; falha de configuração
  não essencial para subir o processo deve ser apenas log (critical/warning), não encerrar o app.

CHECKLIST RÁPIDO (humano / IA):
- [ ] Não alterar startup em main.py sem validar sintaxe (python -m py_compile main.py).
- [ ] Não editar validate_render_environment sem rever regra de produção e rodar testes.
- [ ] Não misturar log com raise no mesmo bloco de checagem de env.
- [ ] Não adicionar docstring duplicada na função.
- [ ] Não mudar comportamento crítico sem revisar diff e tests/test_render_env_validation.py.
"""

from __future__ import annotations

import logging
import os

# Deve coincidir com o fallback usado em main para SECRET_KEY (única fonte aqui; main importa isto).
DEFAULT_SECRET_KEY_PLACEHOLDER = "your-secret-key-change-in-production"

_RENDER_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_render_platform() -> bool:
    return (os.environ.get("RENDER") or "").strip().lower() in _RENDER_TRUTHY


def validate_render_environment(logger: logging.Logger) -> None:
    """
    No Render: avisa sobre configuração fraca ou incompleta.

    Não levanta exceção por configuração não fatal; não registra valores secretos.
    """
    if not _is_render_platform():
        return

    secret_raw = os.environ.get("SECRET_KEY")
    if secret_raw is None:
        effective_secret = DEFAULT_SECRET_KEY_PLACEHOLDER
    else:
        effective_secret = (secret_raw or "").strip() or DEFAULT_SECRET_KEY_PLACEHOLDER
    if effective_secret == DEFAULT_SECRET_KEY_PLACEHOLDER:
        logger.critical(
            "Render: SECRET_KEY ainda com o placeholder padrão — defina um valor forte em Environment. "
            "O app sobe, mas sessões ficam inseguras até corrigir."
        )

    import_auth = (os.environ.get("IMPORT_AUTH_PASSWORD") or "").strip()
    if not import_auth:
        logger.critical(
            "Render: IMPORT_AUTH_PASSWORD vazio — o app sobe, mas importação para datas diferentes "
            "de hoje fica bloqueada. Defina no Environment ou use generateValue no blueprint."
        )

    base_url = (os.environ.get("APP_BASE_URL") or "").strip().lower()
    if not base_url:
        logger.warning(
            "Render: APP_BASE_URL vazio — defina https://<seu-serviço>.onrender.com para links e cookies seguros."
        )
    elif not base_url.startswith("https://"):
        logger.warning("Render: APP_BASE_URL deve usar https:// em produção.")

    admin_pass = (os.environ.get("ADMIN_PASS") or "").strip().lower()
    if admin_pass in ("admin", "admin123", ""):
        logger.critical(
            "Render: ADMIN_PASS fraco ou vazio — altere no painel imediatamente."
        )
