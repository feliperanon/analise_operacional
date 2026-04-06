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

API estável: `DEFAULT_SECRET_KEY_PLACEHOLDER`, `render_platform_active`, `validate_render_environment`.
A validação recebe valores explícitos (sem ler os.environ dentro da função), para testes e acoplamento mínimos.
"""

from __future__ import annotations

import logging

__all__ = (
    "DEFAULT_SECRET_KEY_PLACEHOLDER",
    "render_platform_active",
    "validate_render_environment",
)

# Fallback de desenvolvimento; em produção deve ser substituído por segredo forte no painel.
DEFAULT_SECRET_KEY_PLACEHOLDER = "your-secret-key-change-in-production"

_RENDER_TRUTHY = frozenset({"1", "true", "yes", "on"})


def render_platform_active(render_env_value: str | None) -> bool:
    """True se a variável de ambiente RENDER do painel indica execução na plataforma Render."""
    return (render_env_value or "").strip().lower() in _RENDER_TRUTHY


def validate_render_environment(
    logger: logging.Logger,
    is_render: bool,
    secret_key: str,
    default_secret_key_placeholder: str,
    import_auth_password: str,
    app_base_url: str,
    admin_pass: str,
) -> None:
    """
    No Render: avisa sobre configuração fraca ou incompleta.

    Não lê os.environ; não levanta exceção por configuração não fatal; não registra segredos.
    """
    if not is_render:
        return

    sk = (secret_key or "").strip()
    if not sk or sk == (default_secret_key_placeholder or "").strip():
        logger.critical(
            "Render: SECRET_KEY ausente, vazio ou ainda com o placeholder padrão — defina um valor "
            "forte em Environment. O app sobe, mas sessões ficam inseguras até corrigir."
        )

    if not (import_auth_password or "").strip():
        logger.critical(
            "Render: IMPORT_AUTH_PASSWORD vazio — o app sobe, mas importação para datas diferentes "
            "de hoje fica bloqueada. Defina no Environment ou use generateValue no blueprint."
        )

    base_url = (app_base_url or "").strip().lower()
    if not base_url:
        logger.warning(
            "Render: APP_BASE_URL vazio — defina https://<seu-serviço>.onrender.com para links e cookies seguros."
        )
    elif not base_url.startswith("https://"):
        logger.warning("Render: APP_BASE_URL deve usar https:// em produção.")

    weak = (admin_pass or "").strip().lower()
    if weak in ("admin", "admin123", ""):
        logger.critical(
            "Render: ADMIN_PASS fraco ou vazio — altere no painel imediatamente."
        )
