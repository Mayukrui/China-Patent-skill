"""Synthetic checks only: no protected papers, network, inference, or GPU."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import local_guard as guard


def privacy() -> dict:
    return {
        "schema_version": "patentclaw-local/privacy-1",
        "upload_prohibited": True,
        "content_execution": "manual",
        "egress_control_verified": True,
        "egress_control_record": "Synthetic test fixture; not a real isolation attestation.",
        "telemetry_and_sync_checked": True,
        "source_and_output_local_verified": True,
        "cloud_content_processing": False,
    }


def save(root: Path, name: str, data: object) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_case(root: Path) -> None:
    save(root, "privacy_contract.json", privacy())
    source = root.parent / "paper.tex"
    source.write_text("Synthetic source fact.", encoding="utf-8")
    save(root, "source_manifest.json", {
        "schema_version": "patentclaw-local/source-1",
        "source_root": str(source), "files": guard.inventory_source(source),
    })
    save(root, "evidence.json", [{"evidence_id": "E0001", "source_file": "paper.tex",
                                "locator": "Method paragraph 1", "kind": "text",
                                "text": "Synthetic source fact."}])
    feature = {"feature_id": "T001", "support": "explicit", "evidence_ids": ["E0001"],
               "specification_locators": ["paragraph 0001"]}
    save(root, "claim_support.json", [{"claim_id": "1", "topic": "method", "depends_on": [],
                                       "features": [feature]}])
    save(root, "feature_ledger.json", [{**feature, "essential": True, "status": "supported"}])
    specs = json.loads((guard.SKILL_ROOT / "references/checklist.json").read_text(encoding="utf-8"))
    final = [{"check_id": item["check_id"], "status": "pass", "reason": "Synthetic local review.",
              "evidence_ids": ["E0001"],
              "assessed_by": "manual" if item["evaluator"] == "llm" else "rule_engine"}
             for item in specs["checks"]]
    save(root, "review/final_review.json", {"checklist": final})
    save(root, "review/application_checks.json", {"checks": [
        {"check_id": check_id, "status": "pass", "reason": "Synthetic local review.",
         "evidence_ids": ["E0001"], "assessed_by": "manual"} for check_id in sorted(guard.APP_IDS)
    ]})
    documents = {}
    for key in ("claims", "specification", "abstract", "figures", "disclosure"):
        name = f"application/{key}.png" if key == "figures" else f"application/{key}.txt"
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("Synthetic fixture, not a patent.", encoding="utf-8")
        documents[key] = name
    save(root, "delivery_status.json", {
        "status": "ready_for_inventor_review", "unresolved_core_gaps": [],
        "semantic_review_complete": True, "export_consistency_checked": True,
        "documents": documents,
    })


class LocalGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="patentclaw-local-test-")
        self.root = Path(self.temporary.name).resolve()
        self.case = self.root / "case"
        self.case.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_code(self, code: str, function, *args) -> None:
        with self.assertRaises(guard.GuardError) as result:
            function(*args)
        self.assertEqual(str(result.exception), code)

    def read(self, name: str):
        return json.loads((self.case / name).read_text(encoding="utf-8"))

    def test_privacy_gate_precedes_paper_read(self) -> None:
        bad = privacy()
        bad["egress_control_verified"] = False
        save(self.case, "privacy_contract.json", bad)
        with patch.object(guard, "inventory_source") as inventory:
            self.assert_code("PRIVACY_NOT_VERIFIED", guard.preflight, self.root / "private.tex", self.case)
            inventory.assert_not_called()

    def test_cloud_processing_rejected(self) -> None:
        bad = privacy()
        bad["cloud_content_processing"] = True
        self.assert_code("CLOUD_CONTENT_FORBIDDEN", guard.privacy_gate, bad)

    def test_safe_source_and_frozen_manifest(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "main.tex").write_text(r"\documentclass{article}\input{part}", encoding="utf-8")
        (source / "part.tex").write_text("Synthetic methods.", encoding="utf-8")
        save(self.case, "privacy_contract.json", privacy())
        guard.preflight(source, self.case)
        self.assertEqual(len(self.read("source_manifest.json")["files"]), 2)
        self.assert_code("MANIFEST_ALREADY_FROZEN", guard.preflight, source, self.case)

    def test_cross_root_include_rejected(self) -> None:
        source = self.root / "main.tex"
        source.write_text(r"\input{../secret}", encoding="utf-8")
        self.assert_code("TEX_REFERENCE_ESCAPE", guard.inventory_source, source)

    def test_missing_and_dynamic_include_rejected(self) -> None:
        source = self.root / "main.tex"
        source.write_text(r"\input{missing}", encoding="utf-8")
        self.assert_code("TEX_REFERENCE_MISSING", guard.inventory_source, source)
        source.write_text(r"\input\macro", encoding="utf-8")
        self.assert_code("UNSUPPORTED_TEX_REFERENCE", guard.inventory_source, source)

    def test_repeated_expansion_budget(self) -> None:
        texts = {"main.tex": r"\input{part}\input{part}", "part.tex": "x" * 60}
        with patch.object(guard, "MAX_EXPANDED", 100):
            self.assert_code("TEX_EXPANSION_LIMIT", guard.check_tex, texts, set(texts))

    def test_cycle_rejected(self) -> None:
        texts = {"main.tex": r"\input{main}"}
        self.assert_code("TEX_REFERENCE_CYCLE", guard.check_tex, texts, set(texts))

    def test_style_and_dynamic_tex_commands_rejected(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "main.tex").write_text("Synthetic methods.", encoding="utf-8")
        (source / "style.sty").write_text(r"\write18{synthetic}", encoding="utf-8")
        self.assert_code("TEX_EXECUTION_COMMAND", guard.inventory_source, source)
        (source / "style.sty").write_text(r"\csname openin\endcsname", encoding="utf-8")
        self.assert_code("TEX_EXECUTION_COMMAND", guard.inventory_source, source)

    def test_zip_path_traversal_rejected(self) -> None:
        source = self.root / "bad.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("../secret.tex", "synthetic")
        self.assert_code("PATH_TRAVERSAL", guard.inventory_source, source)

    def test_zip_link_rejected(self) -> None:
        source = self.root / "link.zip"
        info = zipfile.ZipInfo("paper.tex")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr(info, "../secret")
        self.assert_code("ZIP_SPECIAL_FILE", guard.inventory_source, source)

    def test_zip_ratio_and_file_limit(self) -> None:
        source = self.root / "large.zip"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("paper.tex", "x" * 100000)
        self.assert_code("ZIP_RATIO_LIMIT", guard.inventory_source, source)
        with patch.object(guard, "MAX_FILE", 10):
            self.assert_code("FILE_LIMIT", guard.inventory_source, source)

    def test_safe_zip_inventory_no_extraction(self) -> None:
        source = self.root / "safe.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("main.tex", r"\input{section}")
            archive.writestr("section.tex", "Synthetic technical procedure.")
        result = guard.inventory_source(source)
        self.assertEqual(len(result), 2)
        self.assertFalse((self.root / "main.tex").exists())

    def test_secret_or_executable_source_rejected(self) -> None:
        source = self.root / ".env"
        source.write_text("SYNTHETIC_KEY=never-real", encoding="utf-8")
        self.assert_code("UNRELATED_OR_SECRET_FILE", guard.inventory_source, source)
        source = self.root / "run.exe"
        source.write_bytes(b"synthetic")
        self.assert_code("FILE_TYPE_NOT_APPROVED", guard.inventory_source, source)

    def test_complete_synthetic_contract_accepted(self) -> None:
        make_case(self.case)
        guard.validate_case(self.case)

    def test_unknown_evidence_rejected(self) -> None:
        make_case(self.case)
        claims = self.read("claim_support.json")
        claims[0]["features"][0]["evidence_ids"] = ["E9999"]
        save(self.case, "claim_support.json", claims)
        self.assert_code("EVIDENCE_UNKNOWN", guard.validate_case, self.case)

    def test_unsupported_claim_rejected(self) -> None:
        make_case(self.case)
        claims = self.read("claim_support.json")
        claims[0]["features"][0]["support"] = "needs_confirmation"
        save(self.case, "claim_support.json", claims)
        self.assert_code("CLAIM_UNSUPPORTED", guard.validate_case, self.case)

    def test_duplicate_checklist_rejected(self) -> None:
        make_case(self.case)
        report = self.read("review/final_review.json")
        report["checklist"].append(copy.deepcopy(report["checklist"][0]))
        save(self.case, "review/final_review.json", report)
        self.assert_code("CHECKLIST_INCOMPLETE_OR_DUPLICATE", guard.validate_case, self.case)

    def test_unassessed_semantics_cannot_be_ready(self) -> None:
        make_case(self.case)
        report = self.read("review/final_review.json")
        for item in report["checklist"]:
            if item["check_id"] == "EV-02":
                item["status"] = "not_assessed"
                item["assessed_by"] = "none"
        save(self.case, "review/final_review.json", report)
        self.assert_code("REVIEW_INCOMPLETE", guard.validate_case, self.case)
        delivery = self.read("delivery_status.json")
        delivery["status"] = "incomplete_draft"
        save(self.case, "delivery_status.json", delivery)
        guard.validate_case(self.case)

    def test_rule_engine_cannot_claim_semantic_pass(self) -> None:
        make_case(self.case)
        report = self.read("review/final_review.json")
        for item in report["checklist"]:
            if item["check_id"] == "EV-02":
                item["assessed_by"] = "rule_engine"
        save(self.case, "review/final_review.json", report)
        self.assert_code("SEMANTIC_CHECK_NOT_ASSESSED", guard.validate_case, self.case)

    def test_claim_cannot_override_blocked_ledger(self) -> None:
        make_case(self.case)
        ledger = self.read("feature_ledger.json")
        ledger[0]["status"] = "blocked"
        save(self.case, "feature_ledger.json", ledger)
        self.assert_code("CLAIM_LEDGER_MISMATCH", guard.validate_case, self.case)

    def test_delivery_path_cannot_escape_case(self) -> None:
        make_case(self.case)
        delivery = self.read("delivery_status.json")
        delivery["documents"]["claims"] = "../secret.txt"
        save(self.case, "delivery_status.json", delivery)
        self.assert_code("PATH_TRAVERSAL", guard.validate_case, self.case)

    def test_directory_cannot_impersonate_document(self) -> None:
        make_case(self.case)
        delivery = self.read("delivery_status.json")
        delivery["documents"]["claims"] = "."
        save(self.case, "delivery_status.json", delivery)
        self.assert_code("DOCUMENT_TYPE_INVALID", guard.validate_case, self.case)

    def test_source_changed_since_freeze_rejected(self) -> None:
        make_case(self.case)
        (self.root / "paper.tex").write_text("Changed synthetic fact.", encoding="utf-8")
        self.assert_code("SOURCE_CHANGED", guard.validate_case, self.case)

    def test_cli_does_not_print_secret_exception(self) -> None:
        save(self.case, "privacy_contract.json", privacy())
        captured = io.StringIO()
        arguments = ["local_guard.py", "preflight", "--source", "synthetic.tex", "--case", str(self.case)]
        with patch("sys.argv", arguments), patch.object(
            guard, "preflight", side_effect=RuntimeError("private paper text MUST NOT APPEAR")
        ), contextlib.redirect_stdout(captured):
            self.assertEqual(guard.main(), 2)
        self.assertEqual(captured.getvalue(), "LOCAL_CHECK_BLOCKED\n")
        self.assertNotIn("private paper", (self.case / "local_guard_report.json").read_text())


if __name__ == "__main__":
    unittest.main()
