#!/usr/bin/env python3
"""
Verificação rápida anti-regressão: testes de validate_render_environment + import de main.

Uso (na raiz do repositório):
  python scripts/render_env_startup_check.py

O import de main usa FORCE_LOCAL_DB=true para evitar exigência de Postgres em máquina local.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_render_env_validation", "-v"],
        cwd=ROOT,
        check=False,
    )
    if r.returncode != 0:
        return r.returncode

    env = {**os.environ, "FORCE_LOCAL_DB": "true", "REQUIRE_RENDER_DB": "false"}
    env.pop("RENDER", None)
    code = "import main\nprint('main import ok')\n"
    r2 = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        timeout=180,
    )
    return r2.returncode


if __name__ == "__main__":
    sys.exit(main())
