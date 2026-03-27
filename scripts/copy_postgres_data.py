#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copia dados entre dois bancos PostgreSQL sem precisar de pg_dump/psql.

Uso:
  python scripts/copy_postgres_data.py --source-url "postgresql://..." --target-url "postgresql://..."

Ou via ambiente/.env:
  SOURCE_DATABASE_URL=postgresql://...
  TARGET_DATABASE_URL=postgresql://...
  python scripts/copy_postgres_data.py

Observações:
  - Pressupõe que o schema já exista no banco de destino.
  - Faz TRUNCATE CASCADE nas tabelas copiadas antes de carregar os dados.
  - Copia apenas tabelas do schema informado (padrão: public).
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _normalize_url(url: str | None) -> str:
    raw = str(url or "").strip()
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql://", 1)
    return raw


def _connect(db_url: str):
    return psycopg2.connect(db_url)


def _list_tables(conn, schema: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [row[0] for row in cur.fetchall()]


def _fk_edges(conn, schema: str) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tc.table_name AS child_table, ccu.table_name AS parent_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND ccu.table_schema = %s
            """,
            (schema, schema),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def _topological_tables(tables: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[str]:
    tables = list(dict.fromkeys(tables))
    incoming: dict[str, set[str]] = {table: set() for table in tables}
    outgoing: dict[str, set[str]] = defaultdict(set)

    for child, parent in edges:
        if child not in incoming or parent not in incoming or child == parent:
            continue
        incoming[child].add(parent)
        outgoing[parent].add(child)

    ready = deque(sorted(table for table in tables if not incoming[table]))
    ordered: list[str] = []

    while ready:
        table = ready.popleft()
        ordered.append(table)
        for child in sorted(outgoing.get(table, set())):
            incoming[child].discard(table)
            if not incoming[child]:
                ready.append(child)

    # Se houver ciclo, mantém as tabelas restantes em ordem alfabética no final.
    unresolved = [table for table in tables if table not in ordered]
    ordered.extend(sorted(unresolved))
    return ordered


def _list_columns(conn, schema: str, table: str) -> list[str]:
    return [column["name"] for column in _list_column_details(conn, schema, table)]


def _list_column_details(conn, schema: str, table: str) -> list[dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                column_name,
                is_nullable,
                column_default,
                is_identity,
                is_generated
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [
            {
                "name": row[0],
                "is_nullable": row[1] == "YES",
                "column_default": row[2],
                "is_identity": row[3] == "YES",
                "is_generated": (row[4] or "NEVER") != "NEVER",
            }
            for row in cur.fetchall()
        ]


def _build_copy_plan(
    source_columns: list[str],
    target_columns: list[dict[str, object]],
    *,
    schema: str,
    table: str,
) -> dict[str, list[str]]:
    target_by_name = {str(column["name"]): column for column in target_columns}
    source_set = set(source_columns)
    shared_columns = [name for name in source_columns if name in target_by_name]
    source_only = [name for name in source_columns if name not in target_by_name]
    target_only = [str(column["name"]) for column in target_columns if str(column["name"]) not in source_set]
    required_target_only = [
        str(column["name"])
        for column in target_columns
        if str(column["name"]) not in source_set
        and not bool(column["is_nullable"])
        and column["column_default"] is None
        and not bool(column["is_identity"])
        and not bool(column["is_generated"])
    ]

    if required_target_only:
        raise RuntimeError(
            f"{schema}.{table}: destino exige coluna(s) ausente(s) na origem: "
            + ", ".join(required_target_only)
        )
    if not shared_columns:
        raise RuntimeError(
            f"{schema}.{table}: nenhuma coluna em comum entre origem e destino para copiar dados."
        )

    return {
        "columns": shared_columns,
        "source_only": source_only,
        "target_only": target_only,
    }


def _resolve_copy_plan(source_conn, target_conn, schema: str, table: str) -> dict[str, list[str]]:
    source_columns = _list_columns(source_conn, schema, table)
    target_columns = _list_column_details(target_conn, schema, table)
    return _build_copy_plan(source_columns, target_columns, schema=schema, table=table)


def _quote_csv_identifiers(columns: list[str]) -> str:
    return ", ".join(f'"{col}"' for col in columns)


def _copy_table(source_conn, target_conn, schema: str, table: str, columns: list[str]) -> int:
    copied = 0
    col_csv = _quote_csv_identifiers(columns)
    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", newline="", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with source_conn.cursor() as src_cur, target_conn.cursor() as tgt_cur:
            export_sql = f'COPY "{schema}"."{table}" ({col_csv}) TO STDOUT WITH CSV'
            import_sql = f'COPY "{schema}"."{table}" ({col_csv}) FROM STDIN WITH CSV'
            count_sql = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            )

            with temp_path.open("w+", encoding="utf-8", newline="") as handle:
                src_cur.copy_expert(export_sql, handle)
                handle.flush()
                copied = int(src_cur.rowcount or 0)
                handle.seek(0)
                tgt_cur.copy_expert(import_sql, handle)

            src_cur.execute(count_sql)
            copied = int(src_cur.fetchone()[0] or 0)
    finally:
        temp_path.unlink(missing_ok=True)
    return copied


def _reset_sequences(conn, schema: str, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_default LIKE 'nextval%%'
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        serial_columns = [row[0] for row in cur.fetchall()]
        for column in serial_columns:
            cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f"{schema}.{table}", column))
            seq_name = cur.fetchone()[0]
            if not seq_name:
                continue
            stmt = sql.SQL(
                """
                SELECT setval(
                    %s,
                    COALESCE((SELECT MAX({column}) FROM {schema}.{table}), 1),
                    COALESCE((SELECT MAX({column}) IS NOT NULL FROM {schema}.{table}), FALSE)
                )
                """
            ).format(
                column=sql.Identifier(column),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table),
            )
            cur.execute(stmt, (seq_name,))


def _ensure_tables_exist(conn, schema: str, tables: list[str]) -> list[str]:
    existing = set(_list_tables(conn, schema))
    return [table for table in tables if table not in existing]


def copy_data(source_url: str, target_url: str, schema: str, *, verbose: bool = True) -> None:
    source_url = _normalize_url(source_url)
    target_url = _normalize_url(target_url)
    if not source_url or not target_url:
        raise ValueError("SOURCE_DATABASE_URL e TARGET_DATABASE_URL são obrigatórios.")

    with _connect(source_url) as source_conn, _connect(target_url) as target_conn:
        source_conn.autocommit = False
        target_conn.autocommit = False

        tables = _list_tables(source_conn, schema)
        if not tables:
            raise RuntimeError(f"Nenhuma tabela encontrada no schema '{schema}' do banco de origem.")

        missing = _ensure_tables_exist(target_conn, schema, tables)
        if missing:
            raise RuntimeError(
                "Banco de destino sem tabelas esperadas. Faltando: " + ", ".join(missing[:20])
            )

        # Em alguns bancos legados as FKs não estão declaradas na origem,
        # mas existem no destino recém-criado. Usamos as duas visões para
        # ordenar a carga sem violar constraints.
        source_edges = _fk_edges(source_conn, schema)
        target_edges = _fk_edges(target_conn, schema)
        edges = list(dict.fromkeys([*source_edges, *target_edges]))
        ordered = _topological_tables(tables, edges)
        copy_plans: dict[str, dict[str, list[str]]] = {}

        for table in ordered:
            plan = _resolve_copy_plan(source_conn, target_conn, schema, table)
            copy_plans[table] = plan
            if verbose and plan["source_only"]:
                skipped = ", ".join(plan["source_only"])
                print(f"[WARN] {schema}.{table}: ignorando coluna(s) só da origem: {skipped}")
            if verbose and plan["target_only"]:
                pending = ", ".join(plan["target_only"])
                print(
                    f"[WARN] {schema}.{table}: coluna(s) só do destino ficarão com NULL/default: {pending}"
                )

        with target_conn.cursor() as tgt_cur:
            truncate_stmt = sql.SQL("TRUNCATE TABLE {} CASCADE").format(
                sql.SQL(", ").join(
                    sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
                    for table in reversed(ordered)
                )
            )
            tgt_cur.execute(truncate_stmt)

        total_rows = 0
        for table in ordered:
            columns = copy_plans[table]["columns"]
            if not columns:
                continue
            copied = _copy_table(source_conn, target_conn, schema, table, columns)
            _reset_sequences(target_conn, schema, table)
            total_rows += copied
            if verbose:
                print(f"[OK] {schema}.{table}: {copied} linha(s)")

        target_conn.commit()
        source_conn.commit()
        if verbose:
            print(f"\nConcluído. Total de linhas copiadas: {total_rows}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Copia dados entre dois PostgreSQLs sem pg_dump.")
    parser.add_argument("--source-url", default=os.getenv("SOURCE_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--target-url", default=os.getenv("TARGET_DATABASE_URL"))
    parser.add_argument("--schema", default="public")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        copy_data(args.source_url, args.target_url, args.schema, verbose=not args.quiet)
        return 0
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
