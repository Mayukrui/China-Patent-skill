"""Local-only source-package and patent-case structural checks; no inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

MAX_FILES = 2000
MAX_TOTAL = 150 * 1024 * 1024
MAX_FILE = 50 * 1024 * 1024
MAX_RATIO = 200
MAX_DEPTH = 32
MAX_EXPANDED = 300_000
ALLOWED = {
    ".tex", ".bib", ".sty", ".cls", ".bst", ".pdf", ".png", ".jpg",
    ".jpeg", ".eps", ".svg", ".md", ".txt", ".docx", ".csv", ".json", ".py",
}
STATUSES = {"pass", "fail", "needs_human_review", "not_applicable", "not_assessed"}
ACTORS = {"rule_engine", "manual", "verified_local_model", "none"}
SUPPORT = {"explicit", "inherent", "needs_confirmation", "unsupported"}
APP_IDS = {f"APP-{number:02d}" for number in range(1, 9)}
SKILL_ROOT = Path(__file__).resolve().parents[1]


class GuardError(ValueError):
    """An intentionally non-sensitive error code."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise GuardError(code)


def checked_local(path: Path) -> Path:
    """Reject links/reparse points in the path AND its existing ancestors."""
    absolute = Path(os.path.abspath(path))
    require(not str(absolute).startswith(("\\\\", "//")), "NETWORK_PATH")
    for part in (*reversed(absolute.parents), absolute):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            require(
                not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400),
                "LINK_OR_REPARSE_POINT",
            )
    return absolute.resolve()


def case_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative), "BAD_RELATIVE_PATH")
    win = PureWindowsPath(relative)
    require(
        not win.drive and not win.is_absolute()
        and not PurePosixPath(relative).is_absolute()
        and ":" not in relative and "\\" not in relative,
        "ABSOLUTE_OR_SPECIAL_PATH",
    )
    require(".." not in PurePosixPath(relative).parts, "PATH_TRAVERSAL")
    candidate = checked_local(root / relative)
    require(candidate.is_relative_to(root), "PATH_TRAVERSAL")
    return candidate


def read_json(root: Path, relative: str) -> Any:
    path = case_path(root, relative)
    require(path.is_file() and path.stat().st_size <= MAX_FILE, "JSON_MISSING_OR_LARGE")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def privacy_gate(contract: dict[str, Any]) -> None:
    require(isinstance(contract, dict), "PRIVACY_CONTRACT_TYPE")
    require(contract.get("schema_version") == "patentclaw-local/privacy-1", "PRIVACY_VERSION")
    require(contract.get("upload_prohibited") is True, "UPLOAD_NOT_PROHIBITED")
    require(contract.get("cloud_content_processing") is False, "CLOUD_CONTENT_FORBIDDEN")
    require(
        contract.get("content_execution") in {"manual", "verified_local_model"},
        "EXECUTION_LOCATION_UNVERIFIED",
    )
    for key in (
        "egress_control_verified", "telemetry_and_sync_checked",
        "source_and_output_local_verified",
    ):
        require(contract.get(key) is True, "PRIVACY_NOT_VERIFIED")
    require(
        isinstance(contract.get("egress_control_record"), str)
        and bool(contract["egress_control_record"].strip()),
        "EGRESS_RECORD_MISSING",
    )


def check_name(name: str) -> str:
    require(isinstance(name, str) and bool(name), "BAD_MEMBER_NAME")
    require(
        not PureWindowsPath(name).drive and not name.startswith(("/", "\\"))
        and ":" not in name and "\\" not in name and "\x00" not in name,
        "ABSOLUTE_OR_SPECIAL_PATH",
    )
    parts = PurePosixPath(name).parts
    require(".." not in parts, "PATH_TRAVERSAL")
    require(
        not any(part.lower() in {".git", ".env", ".venv", "__pycache__"} for part in parts)
        and not PurePosixPath(name).name.lower().startswith(".env"),
        "UNRELATED_OR_SECRET_FILE",
    )
    return str(PurePosixPath(name))


def reference_target(parent: str, raw: str) -> str:
    raw = raw.strip()
    require(
        bool(raw) and not PureWindowsPath(raw).drive
        and not raw.startswith(("/", "\\"))
        and not any(char in raw for char in ("\\", ":", "$", "{", "}", "#", "~")),
        "UNSAFE_OR_DYNAMIC_TEX_REFERENCE",
    )
    target = posixpath.normpath(posixpath.join(parent, raw))
    require(target != ".." and not target.startswith("../"), "TEX_REFERENCE_ESCAPE")
    return target


def check_tex(texts: dict[str, str], names: set[str]) -> None:
    graph: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    for name, text in texts.items():
        clean = re.sub(r"(?<!\\)%[^\n]*", "", text)
        require(
            not re.search(r"\\(?:write18|openin|openout|read|write|directlua|csname|catcode|scantokens|usepackage\s*\{shellesc\})", clean),
            "TEX_EXECUTION_COMMAND",
        )
        pattern = re.compile(r"\\(?:input|include)(?![A-Za-z@])\s*\{([^{}]+)\}")
        calls = list(pattern.finditer(clean))
        all_calls = list(re.finditer(r"\\(?:input|include)(?![A-Za-z@])", clean))
        require(len(calls) == len(all_calls), "UNSUPPORTED_TEX_REFERENCE")
        graph[name] = []
        sizes[name] = len(clean)
        for match in calls:
            target = reference_target(posixpath.dirname(name), match.group(1))
            if not PurePosixPath(target).suffix:
                target += ".tex"
            require(target in texts, "TEX_REFERENCE_MISSING")
            graph[name].append(target)
        graphics = list(re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^{}]+)\}", clean))
        require(len(graphics) == len(list(re.finditer(r"\\includegraphics(?![A-Za-z@])", clean))),
                "UNSUPPORTED_TEX_REFERENCE")
        for match in graphics:
            target = reference_target("", match.group(1))
            candidates = [target] if PurePosixPath(target).suffix else [
                target + suffix for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
            ]
            require(any(candidate in names for candidate in candidates), "GRAPHIC_MISSING")
        bibs = list(re.finditer(r"\\(?:bibliography|addbibresource)\s*\{([^{}]+)\}", clean))
        require(len(bibs) == len(list(re.finditer(r"\\(?:bibliography|addbibresource)(?![A-Za-z@])", clean))),
                "UNSUPPORTED_TEX_REFERENCE")
        for match in bibs:
            for raw in match.group(1).split(","):
                target = reference_target("", raw)
                if not PurePosixPath(target).suffix:
                    target += ".bib"
                require(target in names, "BIBLIOGRAPHY_MISSING")

    def expanded_size(name: str, stack: tuple[str, ...]) -> int:
        require(name not in stack, "TEX_REFERENCE_CYCLE")
        require(len(stack) < MAX_DEPTH, "TEX_DEPTH_LIMIT")
        total = sizes[name]
        require(total <= MAX_EXPANDED, "TEX_EXPANSION_LIMIT")
        for child in graph[name]:
            total += expanded_size(child, (*stack, name))
            require(total <= MAX_EXPANDED, "TEX_EXPANSION_LIMIT")
        return total

    for name in graph:
        expanded_size(name, ())


def inventory_source(source: Path) -> list[dict[str, Any]]:
    source = checked_local(source)
    require(source.exists(), "SOURCE_MISSING")
    items: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    seen: set[str] = set()
    total = 0

    def add(name: str, data: bytes) -> None:
        nonlocal total
        name = check_name(name)
        require(name.casefold() not in seen, "DUPLICATE_MEMBER")
        seen.add(name.casefold())
        require(PurePosixPath(name).suffix.lower() in ALLOWED, "FILE_TYPE_NOT_APPROVED")
        total += len(data)
        require(len(items) < MAX_FILES and total <= MAX_TOTAL, "PACKAGE_LIMIT")
        require(len(data) <= MAX_FILE, "FILE_LIMIT")
        items.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if PurePosixPath(name).suffix.lower() in {".tex", ".sty", ".cls", ".bst"}:
            texts[name] = data.decode("utf-8-sig")

    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            require(len(members) <= MAX_FILES, "PACKAGE_LIMIT")
            require(sum(item.file_size for item in members) <= MAX_TOTAL, "PACKAGE_LIMIT")
            member_names: set[str] = set()
            for member in members:
                name = check_name(member.filename)
                require(name.casefold() not in member_names, "DUPLICATE_MEMBER")
                member_names.add(name.casefold())
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                require(kind in (0, stat.S_IFREG, stat.S_IFDIR), "ZIP_SPECIAL_FILE")
                require(not member.flag_bits & 1, "ZIP_ENCRYPTED")
                if member.is_dir():
                    continue
                require(member.file_size <= MAX_FILE, "FILE_LIMIT")
                require(
                    member.file_size / max(1, member.compress_size) <= MAX_RATIO,
                    "ZIP_RATIO_LIMIT",
                )
                with archive.open(member) as handle:
                    data = handle.read(MAX_FILE + 1)
                require(len(data) == member.file_size, "ZIP_SIZE_MISMATCH")
                add(name, data)
    elif source.is_dir():
        paths: list[Path] = []
        for current, directories, files in os.walk(source, followlinks=False):
            for name in directories:
                checked_local(Path(current) / name)
                check_name((Path(current) / name).relative_to(source).as_posix())
            for name in files:
                path = checked_local(Path(current) / name)
                require(path.is_relative_to(source), "PATH_TRAVERSAL")
                paths.append(path)
                require(len(paths) <= MAX_FILES, "PACKAGE_LIMIT")
        require(sum(path.stat().st_size for path in paths) <= MAX_TOTAL, "PACKAGE_LIMIT")
        for path in sorted(paths):
            require(path.stat().st_size <= MAX_FILE, "FILE_LIMIT")
            with path.open("rb") as handle:
                add(path.relative_to(source).as_posix(), handle.read(MAX_FILE + 1))
    else:
        require(source.is_file() and source.stat().st_size <= MAX_FILE, "FILE_LIMIT")
        with source.open("rb") as handle:
            add(source.name, handle.read(MAX_FILE + 1))
    require(bool(items), "EMPTY_SOURCE")
    check_tex(texts, {item["path"] for item in items})
    return items


def preflight(source: Path, case: Path) -> None:
    case = checked_local(case)
    require(case.is_dir(), "CASE_ROOT_MISSING")
    privacy_gate(read_json(case, "privacy_contract.json"))
    require(
        not source.resolve().is_dir() or not case.is_relative_to(source.resolve()),
        "CASE_INSIDE_SOURCE",
    )
    manifest = {"schema_version": "patentclaw-local/source-1",
                "source_root": str(checked_local(source)), "files": inventory_source(source)}
    path = case_path(case, "source_manifest.json")
    require(not path.exists(), "MANIFEST_ALREADY_FROZEN")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)


def validate_case(case: Path) -> None:
    case = checked_local(case)
    privacy_gate(read_json(case, "privacy_contract.json"))
    manifest = read_json(case, "source_manifest.json")
    require(isinstance(manifest, dict) and manifest.get("schema_version") == "patentclaw-local/source-1",
            "SOURCE_MANIFEST_VERSION")
    require(isinstance(manifest.get("files"), list) and bool(manifest["files"]), "SOURCE_MANIFEST_EMPTY")
    source_names: set[str] = set()
    for item in manifest["files"]:
        require(isinstance(item, dict), "SOURCE_MANIFEST_TYPE")
        name = check_name(item.get("path"))
        require(name not in source_names, "SOURCE_MANIFEST_DUPLICATE")
        require(isinstance(item.get("sha256"), str) and bool(re.fullmatch(r"[a-f0-9]{64}", item["sha256"])),
                "SOURCE_HASH_INVALID")
        require(isinstance(item.get("bytes"), int) and 0 <= item["bytes"] <= MAX_FILE, "SOURCE_SIZE_INVALID")
        source_names.add(name)
    require(isinstance(manifest.get("source_root"), str) and bool(manifest["source_root"]),
            "SOURCE_ROOT_MISSING")
    current = inventory_source(Path(manifest["source_root"]))
    require(sorted(current, key=lambda value: value["path"]) ==
            sorted(manifest["files"], key=lambda value: value["path"]), "SOURCE_CHANGED")
    evidence = read_json(case, "evidence.json")
    require(isinstance(evidence, list) and bool(evidence), "EVIDENCE_EMPTY")
    evidence_ids: set[str] = set()
    for item in evidence:
        require(isinstance(item, dict), "EVIDENCE_TYPE")
        evidence_id = item.get("evidence_id")
        require(isinstance(evidence_id, str) and bool(evidence_id), "EVIDENCE_ID_MISSING")
        require(evidence_id not in evidence_ids, "EVIDENCE_DUPLICATE")
        evidence_ids.add(evidence_id)
        require(all(isinstance(item.get(key), str) and item[key].strip()
                    for key in ("source_file", "locator", "text")), "EVIDENCE_LOCATION_MISSING")
        require(item["source_file"] in source_names, "EVIDENCE_SOURCE_UNKNOWN")
        require(item.get("kind") in {"text", "equation", "table", "algorithm", "figure", "code"},
                "EVIDENCE_KIND")

    def references(item: dict[str, Any], mandatory: bool = False) -> None:
        ids = item.get("evidence_ids", [])
        require(isinstance(ids, list) and all(isinstance(value, str) for value in ids),
                "EVIDENCE_REFERENCE_TYPE")
        require(not mandatory or bool(ids), "EVIDENCE_REFERENCE_EMPTY")
        require(set(ids) <= evidence_ids, "EVIDENCE_UNKNOWN")

    claims = read_json(case, "claim_support.json")
    require(isinstance(claims, list) and bool(claims), "CLAIMS_EMPTY")
    claim_ids = [item.get("claim_id") for item in claims if isinstance(item, dict)]
    require(len(claim_ids) == len(claims) and all(isinstance(value, str) and value for value in claim_ids)
            and len(claim_ids) == len(set(claim_ids)), "CLAIM_IDS_INVALID")
    earlier: set[str] = set()
    for claim in claims:
        require(isinstance(claim.get("topic"), str) and bool(claim["topic"].strip()), "CLAIM_TOPIC")
        parents = claim.get("depends_on", [])
        require(isinstance(parents, list) and all(parent in earlier for parent in parents),
                "CLAIM_DEPENDENCY")
        earlier.add(claim["claim_id"])
        features = claim.get("features")
        require(isinstance(features, list) and bool(features), "CLAIM_FEATURES_EMPTY")
        for feature in features:
            require(isinstance(feature, dict), "CLAIM_FEATURE_TYPE")
            require(isinstance(feature.get("feature_id"), str) and bool(feature["feature_id"]),
                    "FEATURE_ID_MISSING")
            require(feature.get("support") in {"explicit", "inherent"}, "CLAIM_UNSUPPORTED")
            if feature["support"] == "inherent":
                require(isinstance(feature.get("derivation"), str) and bool(feature["derivation"].strip()),
                        "INHERENT_DERIVATION_MISSING")
            references(feature, mandatory=True)
            locations = feature.get("specification_locators")
            require(isinstance(locations, list) and bool(locations)
                    and all(isinstance(value, str) and value.strip() for value in locations),
                    "SPECIFICATION_SUPPORT_MISSING")

    ledger = read_json(case, "feature_ledger.json")
    require(isinstance(ledger, list), "FEATURE_LEDGER_TYPE")
    known_features: set[str] = set()
    feature_by_id: dict[str, dict[str, Any]] = {}
    core_gaps = False
    for feature in ledger:
        require(isinstance(feature, dict), "FEATURE_LEDGER_TYPE")
        feature_id = feature.get("feature_id")
        require(isinstance(feature_id, str) and bool(feature_id) and feature_id not in known_features,
                "FEATURE_IDS_INVALID")
        known_features.add(feature_id)
        feature_by_id[feature_id] = feature
        require(feature.get("support") in SUPPORT, "FEATURE_SUPPORT_INVALID")
        require(feature.get("status") in {"supported", "blocked"}, "FEATURE_STATUS_INVALID")
        require(isinstance(feature.get("essential"), bool), "FEATURE_ESSENTIAL_TYPE")
        if feature["support"] == "inherent":
            require(isinstance(feature.get("derivation"), str) and bool(feature["derivation"].strip()),
                    "INHERENT_DERIVATION_MISSING")
        references(feature, mandatory=feature["support"] in {"explicit", "inherent"})
        core_gaps |= feature.get("essential") is True and (
            feature["status"] == "blocked" or feature["support"] in {"needs_confirmation", "unsupported"}
        )
    require(all(feature["feature_id"] in known_features for claim in claims
                for feature in claim["features"]), "FEATURE_UNKNOWN")
    for claim in claims:
        for feature in claim["features"]:
            known = feature_by_id[feature["feature_id"]]
            require(known["status"] == "supported" and known["support"] == feature["support"],
                    "CLAIM_LEDGER_MISMATCH")
            require(set(feature["evidence_ids"]) <= set(known.get("evidence_ids", [])),
                    "CLAIM_LEDGER_EVIDENCE_MISMATCH")

    fixed = json.loads((SKILL_ROOT / "references" / "checklist.json").read_text(encoding="utf-8"))
    specs = {item["check_id"]: item for item in fixed["checks"]}
    final = read_json(case, "review/final_review.json")
    app = read_json(case, "review/application_checks.json")

    def checklist(items: Any, expected: set[str], semantic: set[str]) -> bool:
        require(isinstance(items, list), "CHECKLIST_TYPE")
        ids = [item.get("check_id") for item in items if isinstance(item, dict)]
        require(len(ids) == len(items) and len(ids) == len(set(ids)) and set(ids) == expected,
                "CHECKLIST_INCOMPLETE_OR_DUPLICATE")
        complete = True
        for item in items:
            require(item.get("status") in STATUSES and item.get("assessed_by") in ACTORS,
                    "CHECK_STATUS_OR_ACTOR")
            require(isinstance(item.get("reason"), str) and bool(item["reason"].strip()), "CHECK_REASON")
            references(item)
            if item["status"] in {"pass", "not_applicable"}:
                require(item["assessed_by"] != "none", "ASSESSOR_MISSING")
                require(item["check_id"] not in semantic or item["assessed_by"] != "rule_engine",
                        "SEMANTIC_CHECK_NOT_ASSESSED")
            complete &= item["status"] in {"pass", "not_applicable"}
        return complete

    complete_fixed = checklist(final.get("checklist"), set(specs),
                               {key for key, value in specs.items() if value["evaluator"] == "llm"})
    complete_app = checklist(app.get("checks"), APP_IDS, APP_IDS)
    delivery = read_json(case, "delivery_status.json")
    require(delivery.get("status") in {"incomplete_draft", "ready_for_inventor_review"}, "DELIVERY_STATUS")
    if delivery["status"] == "ready_for_inventor_review":
        require(complete_fixed and complete_app, "REVIEW_INCOMPLETE")
        require(not core_gaps and delivery.get("unresolved_core_gaps") == [], "CORE_GAPS_REMAIN")
        require(delivery.get("semantic_review_complete") is True
                and delivery.get("export_consistency_checked") is True, "FINAL_CHECKS_MISSING")
        docs = delivery.get("documents")
        require(isinstance(docs, dict), "DOCUMENTS_MISSING")
        for key in ("claims", "specification", "abstract", "figures", "disclosure"):
            require(key in docs, "DOCUMENTS_MISSING")
            path = case_path(case, docs[key])
            require(path.exists(), "DOCUMENT_MISSING")
            if key != "figures":
                require(path.is_file() and path.stat().st_size > 0, "DOCUMENT_TYPE_INVALID")
            elif path.is_file():
                require(path.stat().st_size > 0 and path.suffix.lower() in {
                    ".png", ".jpg", ".jpeg", ".svg", ".pdf", ".mmd", ".zip", ".docx"
                }, "FIGURE_TYPE_INVALID")
            else:
                require(path.is_dir() and path != case, "FIGURE_TYPE_INVALID")
                figure_found = False
                for current_dir, directories, files in os.walk(path, followlinks=False):
                    for name in (*directories, *files):
                        asset = checked_local(Path(current_dir) / name)
                        require(asset.is_relative_to(path), "PATH_TRAVERSAL")
                        if asset.is_file() and asset.stat().st_size > 0 and asset.suffix.lower() in {
                            ".png", ".jpg", ".jpeg", ".svg", ".pdf", ".mmd"
                        }:
                            figure_found = True
                require(figure_found, "FIGURES_EMPTY")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    first = subparsers.add_parser("preflight")
    first.add_argument("--source", type=Path, required=True)
    first.add_argument("--case", type=Path, required=True)
    second = subparsers.add_parser("validate")
    second.add_argument("--case", type=Path, required=True)
    args = parser.parse_args()
    code = "OK"
    try:
        if args.command == "preflight":
            preflight(args.source, args.case)
        else:
            validate_case(args.case)
    except GuardError as exc:
        code = str(exc)
    except Exception:
        code = "LOCAL_CHECK_FAILED"
    # Never echo exception text, filenames, hashes, or protected document contents.
    try:
        root = checked_local(args.case)
        require(root.is_dir(), "CASE_ROOT_MISSING")
        report = case_path(root, "local_guard_report.json")
        report.write_text(json.dumps({"operation": args.command, "result": code,
                                     "scope": "structural_only"}, indent=2), encoding="utf-8")
    except Exception:
        pass
    print("LOCAL_CHECK_OK" if code == "OK" else "LOCAL_CHECK_BLOCKED")
    return 0 if code == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
