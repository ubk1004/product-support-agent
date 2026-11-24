"""Prepare the ARM parameters for one stage of the Azure deployment, and refuse unsafe values.

The infrastructure workflow compiles `infra/bicep/parameters/<env>.bicepparam` with
`az bicep build-params`, then runs this script, which writes:

* `parameters.json` - the compiled parameters plus the stage overrides (no secrets).
* `secure.parameters.json` - only when a DocumentDB administrator password is supplied through
  the `DOCUMENTDB_ADMIN_PASSWORD` environment variable. The value never appears in logs.

Stages:

* `platform` - network, platform, data, identity, and the optional Foundry and secret
  bootstrap. Sets `deployWorkloads=false`, so no container images are needed.
* `workloads` - adds Container Apps and the optional API Management. Images come from the
  private registry, tagged with the given commit SHA.

The deployment is refused while a value that must be environment-specific is still a template
placeholder. The Azure region of the deployment is printed as `location=<region>` so the
workflow can pass it to `az deployment sub`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_MARKERS = ("placeholder", "example.invalid", "containerapps-helloworld")
_ANGLE_PLACEHOLDER = re.compile(r"<[^>]+>")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REGISTRY_NAME = re.compile(r"^[a-z0-9]{5,50}$")


def is_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    lowered = text.lower()
    return (
        not text
        or text == "TBD"
        or any(marker in lowered for marker in PLACEHOLDER_MARKERS)
        or bool(_ANGLE_PLACEHOLDER.search(text))
    )


def _value(parameters: dict[str, Any], name: str, default: object = None) -> object:
    entry = parameters.get(name)
    return entry.get("value", default) if isinstance(entry, dict) else default


def prepare(
    compiled: dict[str, Any],
    *,
    stage: str,
    image_tag: str | None,
    registry: str | None,
    documentdb_password: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
    """Return the effective parameters, the secure parameters (or None), and any problems."""
    parameters: dict[str, Any] = json.loads(json.dumps(compiled.get("parameters", {})))
    problems: list[str] = []

    if stage not in ("platform", "workloads"):
        problems.append(f"unknown stage {stage!r}; use platform or workloads")
        return parameters, None, problems

    parameters["deployWorkloads"] = {"value": stage == "workloads"}

    if stage == "workloads":
        if not image_tag or not _COMMIT_SHA.match(image_tag):
            problems.append("the workloads stage needs image-tag: a full 40-character commit SHA")
        elif not registry or not _REGISTRY_NAME.match(registry):
            problems.append("the workloads stage needs the ACR_NAME variable for the environment")
        else:
            server = f"{registry}.azurecr.io"
            parameters["apiImage"] = {"value": f"{server}/product-support-api:{image_tag}"}
            parameters["webImage"] = {"value": f"{server}/product-support-web:{image_tag}"}

    required = ["environment", "location", "owner", "costCenter"]
    if not _value(parameters, "deployFoundry", False):
        required += ["foundryEndpoint", "foundryChatDeployment", "foundryEmbeddingDeployment"]
    if stage == "workloads" and _value(parameters, "deployApim", False):
        required.append("apimPublisherEmail")
    for name in required:
        if name in parameters and is_placeholder(_value(parameters, name)):
            problems.append(f"{name} is still a template placeholder; set a real value")
        elif name in ("environment", "location", "owner", "costCenter") and name not in parameters:
            problems.append(f"{name} must be set in the parameter file")

    secure: dict[str, Any] | None = None
    if _value(parameters, "useDocumentDbFreeTier", False):
        if not documentdb_password:
            problems.append(
                "useDocumentDbFreeTier is true: set the DOCUMENTDB_ADMIN_PASSWORD environment "
                "secret, and keep the same value for every deployment of this environment"
            )
        else:
            secure = {
                "$schema": compiled.get("$schema"),
                "contentVersion": "1.0.0.0",
                "parameters": {"documentDbAdministratorPassword": {"value": documentdb_password}},
            }

    return parameters, secure, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--compiled", type=Path, required=True, help="output of az bicep build-params"
    )
    parser.add_argument("--stage", required=True, choices=["platform", "workloads"])
    parser.add_argument("--image-tag", default=None, help="commit SHA of the images in ACR")
    parser.add_argument("--registry", default=None, help="ACR name, without .azurecr.io")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    compiled = json.loads(args.compiled.read_text(encoding="utf-8"))
    parameters, secure, problems = prepare(
        compiled,
        stage=args.stage,
        image_tag=(args.image_tag or "").strip() or None,
        registry=(args.registry or "").strip() or None,
        documentdb_password=os.environ.get("DOCUMENTDB_ADMIN_PASSWORD") or None,
    )
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = {**compiled, "parameters": parameters}
    (args.output_dir / "parameters.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    secure_path = args.output_dir / "secure.parameters.json"
    if secure is not None:
        secure_path.write_text(json.dumps(secure), encoding="utf-8")
        secure_path.chmod(0o600)
    elif secure_path.exists():
        secure_path.unlink()
    print(f"location={_value(parameters, 'location')}")
    print(f"secure_parameters={'true' if secure is not None else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
