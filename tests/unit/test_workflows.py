"""Offline structural checks for the GitHub Actions workflows and the files they reference."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
UNTRUSTED_EXPRESSION = re.compile(r"\$\{\{[^}]*(github\.event|github\.head_ref|inputs\.|matrix\.)")
DEPLOY_COMMAND = re.compile(r"az (deployment sub create|containerapp (job )?update)")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as the boolean True.
    value = workflow.get("on", workflow.get(True))
    return value if isinstance(value, dict) else dict.fromkeys(value or [])


def steps(job: dict) -> list[dict]:
    return job.get("steps", [])


def named(path: Path) -> list[tuple[str, str, dict]]:
    return [(path.name, name, job) for name, job in load(path)["jobs"].items()]


ALL_JOBS = [item for path in WORKFLOWS for item in named(path)]
JOB_IDS = [f"{workflow}:{name}" for workflow, name, _ in ALL_JOBS]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_defaults_to_read_only_contents(path: Path) -> None:
    assert load(path)["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_jobs_have_timeouts(workflow: str, name: str, job: dict) -> None:
    if "uses" not in job:  # a reusable-workflow call takes its limits from the called jobs
        assert "timeout-minutes" in job, f"{workflow}:{name} has no timeout"


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_external_actions_are_pinned_to_full_commit_shas(
    workflow: str, name: str, job: dict
) -> None:
    for step in steps(job):
        used = step.get("uses")
        if used:
            assert PINNED.match(used), f"{workflow}:{name} uses unpinned action {used}"
    called = job.get("uses")
    if called:
        assert called.startswith("./.github/workflows/"), f"{workflow}:{name} calls {called}"


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_checkout_does_not_persist_credentials(workflow: str, name: str, job: dict) -> None:
    for step in steps(job):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, f"{workflow}:{name}"


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_scripts_never_interpolate_untrusted_expressions(
    workflow: str, name: str, job: dict
) -> None:
    for step in steps(job):
        assert not UNTRUSTED_EXPRESSION.search(step.get("run", "")), (
            f"{workflow}:{name} interpolates an expression into a shell script; "
            "pass it through env instead"
        )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_needs_refer_to_real_jobs_and_conditions_read_only_needed_jobs(path: Path) -> None:
    jobs = load(path)["jobs"]
    for name, job in jobs.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert set(needs) <= set(jobs), f"{path.name}:{name} needs an unknown job"
        referenced = set(re.findall(r"needs\.([\w-]+)\.", str(job.get("if", ""))))
        assert referenced <= set(needs), f"{path.name}:{name} reads a job it does not need"


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_azure_oidc_jobs_use_an_environment_and_actually_sign_in(
    workflow: str, name: str, job: dict
) -> None:
    if job.get("permissions", {}).get("id-token") != "write":
        return
    assert "environment" in job, f"{workflow}:{name} uses OIDC without an environment"
    signs_in = any(str(step.get("uses", "")).startswith("azure/login@") for step in steps(job))
    assert signs_in, f"{workflow}:{name} requests id-token but never signs in"


@pytest.mark.parametrize(("workflow", "name", "job"), ALL_JOBS, ids=JOB_IDS)
def test_deployments_run_only_manually_from_main(workflow: str, name: str, job: dict) -> None:
    commands = " ".join(step.get("run", "") for step in steps(job))
    if DEPLOY_COMMAND.search(commands):
        condition = str(job.get("if", ""))
        assert "workflow_dispatch" in condition, f"{workflow}:{name} can deploy on push"
        assert "refs/heads/main" in condition, f"{workflow}:{name} can deploy off main"


def test_validate_is_reusable_and_the_caller_grants_what_codeql_needs() -> None:
    validate = load(WORKFLOW_DIR / "validate.yml")
    app = load(WORKFLOW_DIR / "app.yml")

    assert "workflow_call" in triggers(validate)
    caller = app["jobs"]["validate"]
    assert caller["uses"] == "./.github/workflows/validate.yml"
    needs_write = [
        name
        for name, job in validate["jobs"].items()
        if job.get("permissions", {}).get("security-events") == "write"
    ]
    assert needs_write == ["codeql"]
    assert caller["permissions"]["security-events"] == "write"


def test_validation_runs_once_per_commit() -> None:
    assert "push" not in triggers(load(WORKFLOW_DIR / "validate.yml"))
    assert "push" in triggers(load(WORKFLOW_DIR / "app.yml"))


def test_images_are_deployed_by_commit_sha_never_latest() -> None:
    app = load(WORKFLOW_DIR / "app.yml")
    text = (WORKFLOW_DIR / "app.yml").read_text(encoding="utf-8")
    tags = [
        step["env"]["IMAGE_TAG"]
        for job in app["jobs"].values()
        for step in steps(job)
        if "IMAGE_TAG" in step.get("env", {})
    ]

    assert tags and all("github.sha" in tag for tag in tags)
    # An image reference ending in ":latest" (not the ubuntu-latest runner label).
    assert not re.search(r"product-support-\w+:latest", text)
    assert "docker tag" not in text


def test_every_pipeline_environment_has_a_parameter_file() -> None:
    infra = load(WORKFLOW_DIR / "infra.yml")
    dispatch = triggers(infra)["workflow_dispatch"]["inputs"]["environment"]
    matrix = set(infra["jobs"]["validate"]["strategy"]["matrix"]["environment"])
    files = {path.stem for path in (ROOT / "infra" / "bicep" / "parameters").glob("*.bicepparam")}

    # Extra files, such as a one-off smoke-test deployment, are allowed.
    assert set(dispatch["options"]) == matrix == {"dev", "tst", "prd"}
    assert matrix <= files


def test_files_the_workflows_build_exist() -> None:
    assert (ROOT / "Containerfile").exists()
    assert (ROOT / "apps" / "web" / "Containerfile").exists()
    assert (ROOT / "apps" / "web" / "package-lock.json").exists()
    assert (ROOT / "infra" / "bicep" / "main.bicep").exists()


def test_infra_deploy_refuses_placeholders_and_needs_a_successful_what_if() -> None:
    infra = load(WORKFLOW_DIR / "infra.yml")

    for name in ("what-if", "deploy"):
        job_steps = steps(infra["jobs"][name])
        guard = next(i for i, step in enumerate(job_steps) if "placeholder" in step["name"].lower())
        login = next(i for i, step in enumerate(job_steps) if "azure/login" in step.get("uses", ""))
        assert "scripts/prepare_deployment.py" in job_steps[guard]["run"]
        assert guard < login, f"{name}: placeholders must be refused before signing in to Azure"
    assert "needs.what-if.result == 'success'" in str(infra["jobs"]["deploy"]["if"])
    assert (ROOT / "scripts" / "prepare_deployment.py").exists()


def test_infra_deploys_in_two_stages_with_the_region_from_the_parameter_file() -> None:
    infra = load(WORKFLOW_DIR / "infra.yml")
    stage = triggers(infra)["workflow_dispatch"]["inputs"]["stage"]
    deploy_run = " ".join(step.get("run", "") for step in steps(infra["jobs"]["deploy"]))

    assert stage["options"] == ["platform", "workloads"]
    assert '--location "$LOCATION"' in deploy_run
    assert "canadacentral" not in (WORKFLOW_DIR / "infra.yml").read_text(encoding="utf-8")


def test_private_registry_access_runs_inside_the_virtual_network() -> None:
    app = load(WORKFLOW_DIR / "app.yml")
    configured = set(
        yaml.safe_load((ROOT / ".github" / "actionlint.yaml").read_text())["self-hosted-runner"][
            "labels"
        ]
    )

    for name in ("publish", "deploy"):
        labels = app["jobs"][name]["runs-on"]
        assert "self-hosted" in labels, f"{name} must run on a runner inside the VNet"
        assert any("-vnet" in str(label) for label in labels)
    assert {"dev-vnet", "tst-vnet", "prd-vnet"} <= configured


def test_deploy_environment_is_the_chosen_environment() -> None:
    infra = load(WORKFLOW_DIR / "infra.yml")

    assert infra["jobs"]["deploy"]["environment"] == "${{ inputs.environment }}"
