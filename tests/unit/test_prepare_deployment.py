import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_deployment.py"
SHA = "a" * 40


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_deployment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prep = load_script()


def compiled(**overrides: object) -> dict:
    values = {
        "environment": "tst",
        "instance": "01",
        "location": "canadacentral",
        "owner": "platform-team",
        "costCenter": "cc-1234",
        "foundryEndpoint": "https://psa.openai.azure.com/",
        "foundryChatDeployment": "gpt-5",
        "foundryEmbeddingDeployment": "text-embedding-3-small",
        "apiImage": "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest",
        "webImage": "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest",
        "deployApim": True,
        "apimPublisherEmail": "apim-owner@contoso.com",
    }
    values.update(overrides)
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {name: {"value": value} for name, value in values.items()},
    }


def run(document: dict, **options):
    defaults = {
        "stage": "platform",
        "image_tag": None,
        "registry": None,
        "documentdb_password": None,
    }
    defaults.update(options)
    return prep.prepare(document, **defaults)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("team-placeholder", True),
        ("https://<foundry-resource>.openai.azure.com/", True),
        ("apim-owner@example.invalid", True),
        ("TBD", True),
        ("", True),
        ("platform-team", False),
        ("https://psa.openai.azure.com/", False),
        (True, False),
    ],
)
def test_placeholder_detection(value: object, expected: bool) -> None:
    assert prep.is_placeholder(value) is expected


def test_platform_stage_needs_no_images_and_skips_workloads() -> None:
    parameters, secure, problems = run(compiled())

    assert problems == []
    assert parameters["deployWorkloads"] == {"value": False}
    assert secure is None


def test_workloads_stage_pins_images_to_the_commit_in_the_private_registry() -> None:
    parameters, _, problems = run(
        compiled(), stage="workloads", image_tag=SHA, registry="acrpsatst01abc"
    )

    assert problems == []
    assert parameters["deployWorkloads"] == {"value": True}
    assert parameters["apiImage"]["value"] == f"acrpsatst01abc.azurecr.io/product-support-api:{SHA}"
    assert parameters["webImage"]["value"] == f"acrpsatst01abc.azurecr.io/product-support-web:{SHA}"


@pytest.mark.parametrize(
    ("tag", "registry"),
    [(None, "acrpsatst01abc"), ("latest", "acrpsatst01abc"), (SHA, None), (SHA, "Bad-Name")],
)
def test_workloads_stage_refuses_missing_or_mutable_images(tag, registry) -> None:
    _, _, problems = run(compiled(), stage="workloads", image_tag=tag, registry=registry)

    assert problems


def test_committed_template_values_are_refused() -> None:
    _, _, problems = run(compiled(owner="team-placeholder", costCenter="TBD"))

    assert any("owner" in problem for problem in problems)
    assert any("costCenter" in problem for problem in problems)


def test_foundry_values_are_not_required_when_the_template_creates_foundry() -> None:
    document = compiled(
        deployFoundry=True,
        foundryEndpoint="https://<foundry-resource>.openai.azure.com/",
        foundryChatDeployment="chat-deployment-placeholder",
    )

    assert run(document)[2] == []
    assert run(compiled(foundryEndpoint="https://<foundry-resource>.openai.azure.com/"))[2]


def test_apim_publisher_email_is_checked_only_when_apim_is_deployed() -> None:
    placeholder = compiled(apimPublisherEmail="apim-owner@example.invalid")

    assert run(placeholder)[2] == []
    assert run(placeholder, stage="workloads", image_tag=SHA, registry="acrpsatst01abc")[2]
    no_apim = compiled(apimPublisherEmail="apim-owner@example.invalid", deployApim=False)
    assert run(no_apim, stage="workloads", image_tag=SHA, registry="acrpsatst01abc")[2] == []


def test_documentdb_free_tier_needs_a_password_kept_out_of_the_main_file() -> None:
    document = compiled(useDocumentDbFreeTier=True)

    assert run(document)[2]
    parameters, secure, problems = run(document, documentdb_password="s3cret-Value!")
    assert problems == []
    assert secure is not None
    assert secure["parameters"]["documentDbAdministratorPassword"]["value"] == "s3cret-Value!"
    assert "documentDbAdministratorPassword" not in parameters
    assert "s3cret-Value!" not in json.dumps(parameters)


def test_cli_writes_files_and_reports_the_location(tmp_path: Path, capsys, monkeypatch) -> None:
    source = tmp_path / "compiled.json"
    source.write_text(json.dumps(compiled(useDocumentDbFreeTier=True)), encoding="utf-8")
    monkeypatch.setenv("DOCUMENTDB_ADMIN_PASSWORD", "s3cret-Value!")
    out = tmp_path / "out"

    code = prep.main(["--compiled", str(source), "--stage", "platform", "--output-dir", str(out)])

    printed = capsys.readouterr().out
    assert code == 0
    assert "location=canadacentral" in printed
    assert "secure_parameters=true" in printed
    assert "s3cret-Value!" not in printed
    assert "s3cret-Value!" not in (out / "parameters.json").read_text(encoding="utf-8")
    assert (out / "secure.parameters.json").exists()


def test_cli_fails_with_annotations_and_writes_nothing(tmp_path: Path, capsys) -> None:
    source = tmp_path / "compiled.json"
    source.write_text(json.dumps(compiled(owner="team-placeholder")), encoding="utf-8")
    out = tmp_path / "out"

    code = prep.main(["--compiled", str(source), "--stage", "platform", "--output-dir", str(out)])

    assert code == 1
    assert "::error::owner" in capsys.readouterr().out
    assert not out.exists()


@pytest.mark.parametrize("name", ["dev", "tst", "prd"])
def test_committed_parameter_files_are_refused_until_customised(name: str) -> None:
    """The committed files are templates; the guard must stop a deployment until edited."""
    text = (SCRIPT.parents[1] / "infra" / "bicep" / "parameters" / f"{name}.bicepparam").read_text(
        encoding="utf-8"
    )
    values = dict(re.findall(r"^param (\w+) = '([^']*)'", text, flags=re.MULTILINE))
    document = compiled(**values)

    assert run(document)[2]
