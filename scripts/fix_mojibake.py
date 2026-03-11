#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de correção estrutural de mojibake em arquivos .py.
Repara strings UTF-8 que foram salvas/interpretadas como Latin-1.
Execute UMA VEZ para corrigir o codebase. Após isso, use EditorConfig e UTF-8 no editor.
"""
from pathlib import Path
import re

# Mapeamento: padrão mojibake comum -> caractere correto UTF-8
MOJIBAKE_MAP = [
    ("Ã§", "ç"),
    ("Ã£", "ã"),
    ("Ã¡", "á"),
    ("Ã ", "à"),
    ("Ã¢", "â"),
    ("Ã©", "é"),
    ("Ã­", "í"),
    ("Ã³", "ó"),
    ("Ãº", "ú"),
    ("Ã±", "ñ"),
    ("Ã‡", "Ç"),
    ("ÃƒÂ§", "ç"),   # duplo
    ("ÃƒÂ£", "ã"),   # duplo
    ("ÃƒÂ¡", "á"),
    ("ÃƒÂ©", "é"),
    ("ÃƒÂ­", "í"),
    ("ÃƒÂ³", "ó"),
    ("ÃƒÂº", "ú"),
]

# Padrões complexos (multi-round mojibake) - substituição direta
COMPLEX_FIXES = [
    (r"SeparaÃ§Ã£o", "Separação"),
    (r"separaÃ§Ã£o", "separação"),
    (r"devoluÃ§Ãµes", "devoluções"),
    (r"DevoluÃ§Ãµes", "Devoluções"),
    (r"manutenÃ§Ã£o", "manutenção"),
    (r"ManutenÃ§Ã£o", "Manutenção"),
    (r"configuraÃ§Ã£o", "configuração"),
    (r"ConfiguraÃ§Ã£o", "Configuração"),
    (r"autorizaÃ§Ã£o", "autorização"),
    (r"substituiÃ§Ã£o", "substituição"),
    (r"substituiÃ§Ãµes", "substituições"),
    (r"admissÃ£o", "admissão"),
    (r"demissÃ£o", "demissão"),
    (r"transaÃ§Ã£o", "transação"),
    (r"TransaÃ§Ã£o", "Transação"),
    (r"disponÃ­vel", "disponível"),
    (r"disponíveis", "disponível"),
    (r"invÃ¡lido", "inválido"),
    (r"invÃ¡lida", "inválida"),
    (r"nÃ£o", "não"),
    (r"NÃ£o", "Não"),
    (r"estÃ¡", "está"),
    (r"EstÃ¡", "Está"),
    (r"jÃ¡", "já"),
    (r"JÃ¡", "Já"),
    (r"sÃ³", "só"),
    (r"SÃ³", "Só"),
    (r"rÃ³tulo", "rótulo"),
    (r"exibiÃ§Ã£o", "exibição"),
    (r"portuguÃªs", "português"),
    (r"PortuguÃªs", "Português"),
    (r"perÃ­odo", "período"),
    (r"PerÃ­odo", "Período"),
    (r"fÃ©rias", "férias"),
    (r"FÃ©rias", "Férias"),
    (r"MatrÃ­cula", "Matrícula"),
    (r"ObservaÃ§Ãµes", "Observações"),
    (r"SolicitaÃ§Ã£o", "Solicitação"),
    (r"DescriÃ§Ã£o", "Descrição"),
    (r"anÃ¡lise", "análise"),
    (r"AnÃ¡lise", "Análise"),
    (r"UsuÃ¡rio", "Usuário"),
    (r"usuÃ¡rio", "usuário"),
    (r"mÃ³dulo", "módulo"),
    (r"MÃ³dulo", "Módulo"),
    (r"variÃ¡veis", "variáveis"),
    (r"VariÃ¡veis", "Variáveis"),
    (r"responsÃ¡vel", "responsável"),
    (r"automÃ¡tico", "automático"),
    (r"automÃ¡tica", "automática"),
    (r"histÃ³rico", "histórico"),
    (r"HistÃ³rico", "Histórico"),
    (r"migraÃ§Ã£o", "migração"),
    (r"MigraÃ§Ã£o", "Migração"),
    (r"privilÃ©gios", "privilégios"),
    (r"NOTIFICAÃ‡ÃƒO", "NOTIFICAÇÃO"),
    (r"MANUTENÃ‡ÃƒO", "MANUTENÇÃO"),
    (r"AnÃ¡lise Operacional", "Análise Operacional"),
    # Padrões adicionais (mojibake em mais camadas)
    (r"Ã‡ÃÆâ€™O", "ÇÃO"),
    (r"Ã‡ÃÆâ€™", "Ç"),
    (r"NÃÆâ€™O", "NÃO"),
    (r"VISÃÆâ€™O", "VISÃO"),
    (r"AÃ‡ÃÆâ€™O", "AÇÃO"),
    (r"EVOLUÃ‡ÃÆâ€™O", "EVOLUÇÃO"),
    (r"AVALIAÃ‡ÃÆâ€™O", "AVALIAÇÃO"),
    (r"CORRELAÃ‡ÃÆâ€™O", "CORRELAÇÃO"),
    (r"VERIFICAÃ‡ÃÆâ€™O", "VERIFICAÇÃO"),
    (r"ATENÃ‡ÃÆâ€™O", "ATENÇÃO"),
    (r"SOLICITAÃ‡ÃÆâ€™O", "SOLICITAÇÃO"),
    (r"ENTÃÆâ€™O", "ENTÃO"),
    # Emojis corrompidos -> versão ASCII/neutra (evita lixo em logs)
    (r"ðŸâ€â€™", "[!]"),
    (r"ðŸâ€Â", "[i]"),
    (r"ðŸâ€˜Â¥", "[*]"),
    (r"ðŸâ€œâ€ž", "[>]"),
    (r"ðŸâ€œŠ", "[>]"),
    (r"ðŸâ€œâ€¹", "[>]"),
    (r"ðŸâ€œâ€°", "[>]"),
    (r"ðŸšâ'¬", "[!]"),
    (r"ðŸâ€œË†", "[i]"),
    (r"ðŸâ€œ¦", "[>]"),
    (r"ðŸâ€œâ€¦", "[>]"),
    (r"ðŸâ€™Â¡", "[!]"),
    (r"ðŸâ€Â§", "[>]"),
    (r"ðŸâ€œ¥", "[>]"),
    (r"ðŸâ€™Â¾", "[>]"),
    (r"ðŸâ€œ¤", "[>]"),
    (r"âÅ'", "[!]"),
]


def fix_mojibake(content: str) -> str:
    """Aplica correções de mojibake. Retorna conteúdo corrigido."""
    for wrong, right in COMPLEX_FIXES:
        content = content.replace(wrong, right)

    for wrong, right in MOJIBAKE_MAP:
        content = content.replace(wrong, right)

    try:
        import ftfy
        content = ftfy.fix_text(content)
    except ImportError:
        pass
    return content


def process_file(path: Path, dry_run: bool = False) -> int:
    """Processa um arquivo .py. Retorna 1 se alterou, 0 se não."""
    try:
        raw = path.read_bytes()
        content = raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [ERRO] {path}: {e}")
        return 0

    fixed = fix_mojibake(content)
    if fixed == content:
        return 0

    if not dry_run:
        path.write_text(fixed, encoding="utf-8", newline="")
    return 1


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Corrige mojibake em arquivos .py")
    parser.add_argument("--dry-run", action="store_true", help="Apenas listar arquivos que seriam alterados")
    parser.add_argument("--path", type=str, default=".", help="Diretório raiz (default: .)")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Diretório não encontrado: {root}")
        return 1

    # Incluir .py, .html e .jinja2
    all_files = []
    for ext in ["*.py", "*.html", "*.jinja2", "*.jinja"]:
        all_files.extend(root.rglob(ext))
    all_files = [
        f for f in all_files
        if "venv" not in str(f) and ".venv" not in str(f)
        and "__pycache__" not in str(f)
        and "node_modules" not in str(f)
        and "fix_mojibake.py" not in f.name
    ]
    # Remover duplicatas e ordenar
    files = sorted(set(all_files))

    modified = 0
    for f in files:
        n = process_file(f, dry_run=args.dry_run)
        if n > 0:
            print(f"  {'[DRY-RUN] ' if args.dry_run else ''}Corrigido: {f.relative_to(root)}")
            modified += 1

    print(f"\n{'Seria corrigido' if args.dry_run else 'Corrigido'}: {modified} arquivo(s)")
    return 0


if __name__ == "__main__":
    exit(main())
