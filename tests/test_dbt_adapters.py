"""Guard the declared dbt role: adapter views only, never a second definition.

Migrations 002-004 own transaction classification and revenue arithmetic. The
dbt models must stay thin ``select * from {{ source(...) }}`` adapters so the
repository cannot drift into two competing transformation layers.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_ROOT = PROJECT_ROOT / "dbt"
MODELS_ROOT = DBT_ROOT / "models"
MODEL_CONFIG = re.compile(r"^\{\{\s*config\(alias='([^']+)'\)\s*\}\}\s*$", flags=re.MULTILINE)
ADAPTER_SELECT = re.compile(
    r"^select \* from \{\{\s*source\('([^']+)',\s*'([^']+)'\)\s*\}\}$",
    flags=re.DOTALL,
)
COMMENT = re.compile(r"--[^\n]*")


def model_files() -> list[Path]:
    return sorted(MODELS_ROOT.rglob("*.sql"))


def adapter_body(path: Path) -> str:
    """Return model SQL with the config block and comments removed."""

    return normalize_model_sql(path.read_text(encoding="utf-8"))


def normalize_model_sql(text: str) -> str:
    text = MODEL_CONFIG.sub("", text)
    text = COMMENT.sub("", text)
    return " ".join(text.split())


def is_adapter_sql(text: str) -> bool:
    return ADAPTER_SELECT.fullmatch(normalize_model_sql(text)) is not None


def model_alias(path: Path) -> str | None:
    match = MODEL_CONFIG.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


class DbtAdapterRoleTests(unittest.TestCase):
    def test_models_exist(self) -> None:
        self.assertTrue(model_files(), "dbt/models must contain the adapter models")

    def test_every_model_is_a_single_source_adapter(self) -> None:
        for path in model_files():
            with self.subTest(model=path.name):
                self.assertTrue(
                    is_adapter_sql(path.read_text(encoding="utf-8")),
                    f"{path.name} must stay 'select * from source(...)'; "
                    "add transformation logic to a migration instead",
                )

    def test_guard_rejects_reimplemented_logic(self) -> None:
        """The guard must catch a model that redefines the published contract."""

        example = """
        {{ config(alias='revenue_daily') }}

        -- copied business logic
        select
            source_file_id,
            invoice_at::date as event_date,
            sum(quantity * unit_price) as net_transaction_amount
        from {{ source('postgres_staging_contract', 'online_retail_transaction') }}
        group by 1, 2
        """
        self.assertFalse(is_adapter_sql(example))
        self.assertTrue(
            is_adapter_sql(
                "{{ config(alias='revenue_daily') }}\n"
                "select *\n"
                "from {{ source('postgres_mart_contract', 'revenue_daily') }}\n"
            )
        )

    def test_every_model_declares_a_distinct_contract_alias(self) -> None:
        aliases = {}
        for path in model_files():
            with self.subTest(model=path.name):
                alias = model_alias(path)
                self.assertIsNotNone(alias, f"{path.name}: missing config(alias='...')")
                self.assertNotIn(alias, aliases, f"{path.name}: duplicate alias {alias!r}")
                aliases[alias] = path
        self.assertEqual(len(aliases), len(model_files()))

    def test_each_source_contract_has_one_adapter(self) -> None:
        sources = []
        for path in model_files():
            match = ADAPTER_SELECT.fullmatch(adapter_body(path))
            self.assertIsNotNone(match)
            sources.append((match.group(1), match.group(2)))
        self.assertEqual(len(sources), len(set(sources)), "each source table needs exactly one adapter")

    def test_models_stay_views(self) -> None:
        project = (DBT_ROOT / "dbt_project.yml").read_text(encoding="utf-8")
        for layer in ("staging", "marts"):
            with self.subTest(layer=layer):
                self.assertRegex(
                    project,
                    rf"{layer}:\s*\n\s*\+materialized: view",
                    f"{layer} adapters must remain views, not a second stored copy",
                )
        self.assertNotRegex(project, r"\+materialized: (table|incremental|snapshot)")

    def test_singular_tests_only_reference_known_models(self) -> None:
        models = {path.stem for path in model_files()}
        declared = set()
        for line in (DBT_ROOT / "models" / "models.yml").read_text(encoding="utf-8").splitlines():
            match = re.match(r"^  - name: (\S+)\s*$", line)
            if match:
                declared.add(match.group(1))
        self.assertEqual(declared, models, "models.yml must document exactly the adapter models")
        for path in (DBT_ROOT / "tests").glob("*.sql"):
            for ref in re.findall(r"ref\('([^']+)'\)", path.read_text(encoding="utf-8")):
                self.assertIn(ref, declared, f"{path.name}: ref('{ref}') is not a declared model")


if __name__ == "__main__":
    unittest.main()
