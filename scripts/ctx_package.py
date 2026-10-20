"""Build, scan and validate an E11 container archive. Never deploy or provision hosts.

Archive bytes, image ID, SBOM and configuration are bound to the same candidate.
CI artifacts hold the image; no registry or cloud credential is needed. The
staging validation uses ephemeral secrets/mounts and disables outbound networking.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tarfile
import tempfile

from ctx_source_security import (Blocked, ROOT, application, artifact_link, check_version, finding, identity,
                                 read_json, require, run, safe_path, scanner_report, trivy_results, unique_object, utc_time, write_json)

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ARCHIVE = ".ctx/package/habitat-image.tar"
SBOM = ".ctx/security/gl-sbom-container.cdx.json"
SECRET_NAMES = ("AICL_SESSION_SECRET", "AICL_IDENTITY_HMAC_KEY", "AICL_SECRET_ENCRYPTION_KEY")


def file_digest(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def archive_config_id(archive, source_sha, expected_tag=None):
    """Docker's daemon ID may be a manifest ID; Trivy's ImageID is the config digest.

    Derive the latter from the exact archive bytes, without extracting archive paths.
    A single image and the reviewed build's source label are mandatory.
    """
    with tarfile.open(archive, "r") as contents:
        def member_bytes(name):
            require(isinstance(name, str) and not Path(name).is_absolute() and ".." not in Path(name).parts,
                    "unsafe archive metadata path")
            matches = [item for item in contents.getmembers() if item.name == name]
            require(len(matches) == 1 and matches[0].isfile() and matches[0].size <= 1024 * 1024,
                    "invalid or duplicate archive metadata")
            return contents.extractfile(matches[0]).read()

        manifest = json.loads(member_bytes("manifest.json"), object_pairs_hook=unique_object)
        require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
                "archive must contain one candidate image")
        if expected_tag is not None:
            require(manifest[0].get("RepoTags") == [expected_tag], "archive candidate tag mismatch")
        config_bytes = member_bytes(manifest[0].get("Config"))
        config = json.loads(config_bytes, object_pairs_hook=unique_object)
        require(config.get("architecture") == "amd64" and config.get("os") == "linux",
                "archive runtime platform differs from reviewed target")
        require(config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision") == source_sha,
                "archive was built from another source candidate")
        return "sha256:" + hashlib.sha256(config_bytes).hexdigest()


def package(root, env):
    base = identity(env)
    application(root)
    check_version("trivy", root, env)
    require(safe_path(root, "Dockerfile").is_file(), "reviewed Dockerfile required")
    archive = safe_path(root, ARCHIVE)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    image_file = safe_path(root, ".ctx/package/image-id.txt")
    image_file.unlink(missing_ok=True)
    tag = "habitat-ci:" + base["source_sha"] + "-" + env["CI_PIPELINE_ID"] + "-" + env["CI_JOB_ID"]
    run(["docker", "build", "--platform", "linux/amd64", "--iidfile", str(image_file), "--tag", tag,
         "--build-arg", "SOURCE_SHA=" + base["source_sha"], "."], root, env, timeout=840)
    image_id = image_file.read_text().strip()
    require(DIGEST.fullmatch(image_id), "build returned no immutable image ID")
    run(["docker", "save", "--output", str(archive), tag], root, env)
    require(archive.is_file() and archive.stat().st_size > 0, "container archive missing or empty")
    sbom = safe_path(root, SBOM)
    sbom.parent.mkdir(parents=True, exist_ok=True)
    sbom.unlink(missing_ok=True)
    run(["trivy", "image", "--input", str(archive), "--format", "cyclonedx", "--output", str(sbom)], root, env)
    data = read_json(sbom)
    require(data.get("bomFormat") == "CycloneDX" and isinstance(data.get("components"), list) and data["components"],
            "container SBOM missing or empty")
    return {**base, "artifact_digest": file_digest(archive), "artifact_kind": "docker-image-archive",
            "artifact_path": ARCHIVE, "image_id": image_id, "image_tag": tag,
            "image_config_id": archive_config_id(archive, base["source_sha"], tag), "artifact_url": artifact_link(env, ARCHIVE),
            "sbom_url": artifact_link(env, SBOM), "sbom_sha256": file_digest(sbom).removeprefix("sha256:")}


def prior_package(root, env):
    receipt = read_json(safe_path(root, ".ctx/reports/package.json"))
    require(receipt.get("step") == "package" and receipt.get("status") == "passed", "package prerequisite not passed")
    for field, variable in (("source_sha", "CTX_SOURCE_SHA"), ("project_id", "CI_PROJECT_ID"), ("pipeline_id", "CI_PIPELINE_ID")):
        require(receipt.get(field) == env.get(variable), "package belongs to another candidate or pipeline")
    evidence = receipt.get("evidence", {})
    require(evidence.get("artifact_kind") == "docker-image-archive" and evidence.get("artifact_path") == ARCHIVE,
            "unexpected candidate artifact kind or path")
    require(DIGEST.fullmatch(evidence.get("image_id", "")), "package image identity missing")
    tag = evidence.get("image_tag", "")
    require(re.fullmatch("habitat-ci:" + env["CTX_SOURCE_SHA"] + "-" + env["CI_PIPELINE_ID"] + "-[1-9][0-9]*", tag),
            "package candidate tag is not pipeline bound")
    archive = safe_path(root, ARCHIVE)
    require(archive.is_file() and file_digest(archive) == evidence.get("artifact_digest"), "candidate archive digest mismatch")
    require(archive_config_id(archive, env["CTX_SOURCE_SHA"], tag) == evidence.get("image_config_id"),
            "candidate image config digest mismatch")
    require(file_digest(safe_path(root, SBOM)).removeprefix("sha256:") == evidence.get("sbom_sha256"), "candidate SBOM digest mismatch")
    return evidence


def container_findings(data, image_config_id):
    results = trivy_results(data, "container_image")
    metadata = data.get("Metadata", {})
    require(metadata.get("ImageID") == image_config_id, "scanner inspected another image")
    os_info = metadata.get("OS", {})
    require(os_info.get("Family") and os_info.get("Name") and not os_info.get("EOSL"), "unsupported or unidentified container OS")
    require(any(item.get("Class") == "os-pkgs" for item in results), "container OS packages were not scanned")
    require(any(item.get("Type") == "python-pkg" for item in results), "container Python packages were not scanned")
    findings = []
    for item in results:
        for vulnerability in item.get("Vulnerabilities", []):
            location = {"image": image_config_id, "operating_system": os_info["Family"] + " " + os_info["Name"],
                        "dependency": {"package": {"name": vulnerability["PkgName"]}, "version": vulnerability["InstalledVersion"]}}
            findings.append(finding("container_scanning", vulnerability["VulnerabilityID"], location,
                                    vulnerability["Severity"], "Trivy identified a published vulnerability in the candidate image."))
    return findings


def artifact_security(root, env):
    base = identity(env)
    target = ".ctx/security/gl-container-scanning-report.json"
    safe_path(root, target).unlink(missing_ok=True)
    packaged = prior_package(root, env)
    check_version("trivy", root, env)
    started = utc_time()
    with tempfile.TemporaryDirectory(prefix="ctx-container-scan-") as directory:
        raw = Path(directory)
        (raw / "empty.yaml").write_text("{}\n")
        (raw / "empty.ignore").write_text("")
        run(["trivy", "image", "--input", str(safe_path(root, ARCHIVE)), "--config", str(raw / "empty.yaml"),
             "--ignorefile", str(raw / "empty.ignore"), "--scanners", "vuln", "--format", "json", "--exit-code", "0",
             "--output", str(raw / "image.json")], root, env)
        findings = container_findings(read_json(raw / "image.json"), packaged["image_config_id"])
    write_json(root, target, scanner_report("container_scanning", "trivy", findings, started))
    require(not findings, "blocking container vulnerabilities; inspect the native security report")
    return {**base, "artifact_digest": packaged["artifact_digest"], "passed": True, "blocking_findings": 0}


def configuration(packaged, source_sha):
    return {"schema_version": 1, "environment": "staging", "source_sha": source_sha,
            "artifact_digest": packaged["artifact_digest"], "image_id": packaged["image_id"],
            "validation_only": True, "applied": False, "validation_network": "none",
            "env": {"AICL_ENVIRONMENT": "production", "AICL_TEST_MODE": "0",
                    "AICL_PUBLIC_BASE_URL": "https://localhost", "AICL_DATABASE_URL": "sqlite:////data/habitat.sqlite",
                    "AICL_PRICE_TABLE_PATH": "/app/backend/aicl/price_table.example.json",
                    "AICL_PROVIDER_MODE": "fake", "AICL_EXECUTOR_MODE": "fake", "AICL_CHAT_MODEL_MODE": "fake",
                    "AICL_SMTP_HOST": "localhost", "AICL_SMTP_FROM": "habitat@localhost"},
            "secret_references": {name: "runtime-env:" + name for name in SECRET_NAMES},
            "volume": {"path": "/data", "uid": 10001, "validation": "temporary",
                       "deployment_requirement": "persistent volume with backup and restore"},
            "not_verified": ["cloud provisioning", "TLS ingress", "SMTP delivery", "live providers", "host secret references"]}


def configure(root, env):
    base = identity(env)
    packaged = prior_package(root, env)
    configured = configuration(packaged, base["source_sha"])
    run(["docker", "load", "--input", str(safe_path(root, ARCHIVE))], root, env)
    # Random validation-only secrets are supplied by a private temporary file, never CLI argv or reports.
    with tempfile.TemporaryDirectory(prefix="ctx-runtime-smoke-") as directory:
        # Classic Docker and containerd stores may report different daemon IDs.
        # Resolve the loaded tag, then verify its exact config bytes by a round trip.
        loaded_id = run(["docker", "image", "inspect", "--format", "{{.Id}}", packaged["image_tag"]],
                        root, env).stdout.strip()
        require(DIGEST.fullmatch(loaded_id), "loaded image has no immutable daemon ID")
        loaded_archive = Path(directory) / "loaded.tar"
        run(["docker", "save", "--output", str(loaded_archive), loaded_id], root, env)
        require(archive_config_id(loaded_archive, base["source_sha"]) == packaged["image_config_id"],
                "loaded image config differs from scanned candidate")
        loaded_archive.unlink()
        configured["validated_image_id"] = loaded_id
        path = write_json(root, ".ctx/deploy/staging.json", configured)
        secret_env = {**configured["env"], "AICL_SESSION_SECRET": secrets.token_urlsafe(40),
                      "AICL_IDENTITY_HMAC_KEY": secrets.token_urlsafe(40),
                      "AICL_SECRET_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode()}
        env_file = Path(directory) / "runtime.env"
        env_file.write_text("".join(name + "=" + value + "\n" for name, value in secret_env.items()))
        env_file.chmod(0o600)
        # Runtime imports, settings validation, migrations and all composition hooks must actually run.
        smoke = ("from aicl.runtime import create_app; from fastapi.testclient import TestClient; "
                 "app=create_app(); "
                 "assert app.state.ctx.settings.test_mode is False; "
                 "assert app.state.ctx.settings.provider_mode == 'fake'; "
                 "paths={getattr(r,'path','') for r in app.routes}; "
                 "assert {'/auth/sign-in','/workspace','/chat'} <= paths; "
                 "assert not any(p.startswith('/__test__') for p in paths); "
                 "client=TestClient(app,base_url='https://localhost'); "
                 "assert client.get('/auth/sign-in').status_code == 200; "
                 "assert client.get('/workspace',follow_redirects=False).status_code == 303; "
                 "print('packaged runtime composition validated')")
        run(["docker", "run", "--rm", "--pull=never", "--platform", "linux/amd64", "--network", "none", "--read-only",
             "--tmpfs", "/data:rw,noexec,nosuid,uid=10001,gid=10001,mode=0700", "--env-file", str(env_file),
             loaded_id, "python", "-c", smoke], root, env, timeout=120)
    return {**base, "artifact_digest": packaged["artifact_digest"], "environment": "staging", "passed": True,
            "configuration_revision": file_digest(path).removeprefix("sha256:"), "configuration_path": ".ctx/deploy/staging.json",
            "validation_only": True, "applied": False, "not_verified": configured["not_verified"]}


ADAPTERS = {"package": package, "artifact-security": artifact_security, "configure": configure}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=ADAPTERS)
    step = parser.parse_args().step
    try:
        env = dict(os.environ)
        output = safe_path(ROOT, ".ctx/outputs/" + step + ".json")
        require(env.get("CTX_OUTPUT") == str(output), "adapter requires workflow-owned output path")
        output.unlink(missing_ok=True)
        result = ADAPTERS[step](ROOT, env)
        write_json(ROOT, ".ctx/outputs/" + step + ".json", result)
        print(json.dumps({"step": step, "status": "passed"}))
        return 0
    except Blocked as exc:
        print(json.dumps({"step": step, "status": "blocked", "reason": str(exc)}))
        return 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError):
        print(json.dumps({"step": step, "status": "blocked", "reason": "invalid or unavailable package evidence"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
