"""Modal app, pinned image, and shared resources for the B1 smoke.

The rLLM revision here must stay identical to
``integrations/rllm/constraints.txt`` and ``integrations/rllm/compat.json``.
"""

from __future__ import annotations

import modal

RLLM_REVISION = "1d1109a655e291b3001d8526d7c9ecc5b9328226"
RLLM_SPEC = f"rllm @ git+https://github.com/rllm-org/rllm.git@{RLLM_REVISION}"
GATEWAY_SPEC = (
    "rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git@"
    f"{RLLM_REVISION}#subdirectory=rllm-model-gateway"
)

# L40S (48 GiB, Ada SM 8.9) rather than A10G (22 GiB, Ampere SM 8.6). A 1.7B
# policy OOMs the A10 twice over at these sequence lengths: first the actor
# log-prob forward wanted 3.48 GiB with 3.36 GiB free, and after lowering
# vLLM's reserved share the actor simply grew into the freed space and died
# 194 MiB short with 19.47 GiB allocated by PyTorch alone. Moving to a
# larger card keeps every sequence-length and batch setting identical to the
# 0.5B run, so the two remain directly comparable; shrinking
# max_response_length instead would have confounded that comparison.
GPU = "L40S"
RUNS_DIR = "/runs"

app = modal.App("aeread-b1")

# CUDA *devel* base, not debian_slim. Two reasons, both established by real
# runs. First, verl 0.8.0 hard-requires flash_attn
# (verl/utils/attention_utils.py imports flash_attn.bert_padding with no
# fallback, reached regardless of use_dynamic_bsz or use_remove_padding), and
# no prebuilt flash-attn wheel exists for the torch 2.11.0+cu130 that
# vllm==0.22.1 resolves: upstream cp312 wheels stop at cu13torch2.9, and that
# wheel fails on this torch with "undefined symbol:
# _ZN3c104cuda29c10_cuda_check_implementationEiPKcS2_ib". So flash-attn must be
# built from source, which needs nvcc, which pip's torch wheels do not ship
# (they carry the CUDA runtime only: nvcc absent, CUDA_HOME unset). Second,
# debian_slim on the older image builder is bullseye (glibc 2.31), too old for
# these wheels, which want GLIBC_2.32 or newer. CUDA 13.0 matches torch's
# cu130 build; ubuntu24.04 carries glibc 2.39.
image = (
    modal.Image.from_registry(
        "nvidia/cuda:13.0.1-devel-ubuntu24.04", add_python="3.12"
    )
    # clang is required by the flash-attn compile, not optional. CUDA 13.0's
    # nvcc host-compiler check rejected the build with "The current installed
    # version of clang++ (0.0.0) is less than the minimum required version by
    # CUDA 13.0 (7.0)"; 0.0.0 means clang++ was absent entirely. Ubuntu 24.04
    # ships clang 18, inside nvcc's required >=7.0,<21.0 window.
    .apt_install("git", "build-essential", "clang")
    .pip_install("uv", "packaging", "ninja", "wheel", "setuptools")
    # Build attempt 1 put verl, vllm, transformers, ray, and qwen-vl-utils in
    # one pip_install layer with three of the five left unpinned. pip's
    # backtracking resolver hit "resolution-too-deep" on that combined graph
    # (recorded in task-2-report.md). The fix has two parts: split the layer
    # so vllm resolves its own torch, transformers, and xgrammar graph first,
    # then install verl alongside the remaining packages now pinned to the
    # exact versions pip's own resolver reported as satisfying every
    # constraint in that failed run. uv replaces pip for both layers because
    # its resolver handles this graph size without pip's fixed depth limit;
    # no explicit torch layer is needed first, since vllm pins its own torch
    # build.
    .run_commands("uv pip install --system vllm==0.22.1")
    .run_commands(
        "uv pip install --system verl==0.8.0 transformers==5.5.3 "
        "ray==2.56.0 qwen-vl-utils==0.0.13 tensordict==0.9.1"
    )
    # Source build, and deliberately NOT tolerated with "|| echo" any more.
    # The earlier tolerant form let the image build green while leaving verl
    # unable to import flash_attn at training time, which cost several runs to
    # diagnose. If this fails the image must fail with it.
    #
    # --no-build-isolation is required so the build sees the already-installed
    # torch. TORCH_CUDA_ARCH_LIST and FLASH_ATTN_CUDA_ARCHS are pinned to 8.6,
    # the A10's compute capability (Ampere GA102), because compiling every
    # supported architecture is what makes this build take an hour or more.
    # MAX_JOBS bounds parallel nvcc processes; too high exhausts builder RAM.
    # Both 8.6 (A10) and 8.9 (L40S) are built: a kernel compiled for one
    # Ampere/Ada arch will not load on the other, and keeping both means the
    # image still runs the earlier 0.5B A10 result as well as the L40S runs.
    .run_commands(
        "MAX_JOBS=16 TORCH_CUDA_ARCH_LIST='8.6;8.9' FLASH_ATTN_CUDA_ARCHS='86;89' "
        "pip install flash-attn==2.8.3 --no-build-isolation --verbose",
        gpu=None,
    )
    .pip_install(RLLM_SPEC, GATEWAY_SPEC)
    # copy=True is REQUIRED: with the default copy=False the tree is mounted at
    # container startup, not at build time, so the editable install below would
    # run against an empty /workspace/aeread. See modal/_image.py add_local_dir:
    # "it is required if you want to run additional build steps after this one".
    .add_local_dir(
        "/Users/lichenyu/aeread-public",
        remote_path="/workspace/aeread",
        copy=True,
        ignore=[
            ".git",
            "__pycache__",
            "*.pyc",
            ".superpowers",
            ".pytest_cache",
            "*.egg-info",
        ],
    )
    # Build attempt 2 let this layer resolve aeread's unpinned numpy/scipy
    # to the newest release, which uninstalled the numpy 1.26.4 that verl
    # 0.8.0 needs (verl requires numpy<2.0.0) and would have made the
    # training run in a later task import against an unsupported numpy.
    # Capping both here keeps the numpy verl already settled on and picks a
    # scipy release that still supports numpy 1.x.
    .run_commands(
        "cd /workspace/aeread && pip install -e '.[dev]' click "
        "'numpy<2.0.0' 'scipy<1.15'"
    )
)

volume = modal.Volume.from_name("aeread-b1-runs", create_if_missing=True)
openrouter_secret = modal.Secret.from_name("aeread-openrouter")


@app.function(image=image, gpu=GPU, timeout=900)
def image_smoke() -> dict[str, str]:
    """Prove the image resolves every pinned dependency on a real GPU.

    Every value in the returned dict is coerced to a plain ``str``.
    ``torch.__version__`` is a ``TorchVersion`` (a ``str`` subclass defined
    in ``torch.torch_version``), and Modal's pickle transport needs the
    local machine to import whatever module defines a returned object; this
    Mac has no torch installed, so an unwrapped version object fails to
    deserialize with a confusing DeserializationError instead of a clean
    string. The same problem applies to a raised exception carrying such an
    object, so each probe below is wrapped in its own try/except: a failure
    is reported as a string, never raised across the wire.
    """
    import json
    import subprocess

    result: dict[str, str] = {}

    def record(key: str, fn) -> None:
        try:
            result[key] = str(fn())
        except Exception as exc:  # the point is to never raise past this line
            result[key] = f"error: {exc}"

    def torch_version() -> str:
        import torch

        return torch.__version__

    def cuda_available() -> bool:
        import torch

        return torch.cuda.is_available()

    def numpy_version() -> str:
        import numpy

        version = numpy.__version__
        assert str(version).startswith("1."), (
            "numpy was upgraded past verl's <2.0.0 ceiling, got " + str(version)
        )
        return version

    def verl_version() -> str:
        import verl

        return getattr(verl, "__version__", "unknown")

    def rllm_version() -> str:
        import rllm

        from aeread.integrations.rllm_flow import aeread_flow

        assert hasattr(aeread_flow, "run"), "aeread_flow lost its .run seam"
        return getattr(rllm, "__version__", "unknown")

    def resolve_installed_revision(dist_name: str) -> tuple[bool, str]:
        """Read the VCS commit pip actually recorded for a direct git-URL install.

        pip writes the exact resolved commit into the installed distribution's
        ``direct_url.json`` metadata for a ``git+https://...@<rev>`` install. That
        is the only source that reflects what got installed in this container,
        as opposed to what the code merely asked for, so this is what a stale
        wheel, a cache hit, or a resolver substitution would actually corrupt.

        Returns ``(found, value)``. When ``found`` is False, ``value`` is not a
        commit: it describes exactly what metadata was available instead (the
        dist-info directory name and the metadata field names), so an absent
        ``direct_url.json`` is visible in the output rather than silently
        treated as a pass.
        """
        from importlib.metadata import PackageNotFoundError, distribution

        try:
            dist = distribution(dist_name)
        except PackageNotFoundError:
            return False, f"unavailable (distribution {dist_name!r} not installed)"

        raw = dist.read_text("direct_url.json")
        if not raw:
            dist_info_dir = getattr(getattr(dist, "_path", None), "name", "unknown")
            metadata_fields = sorted(set(dist.metadata.keys())) if dist.metadata else []
            return False, (
                "unavailable (no direct_url.json, not a direct-URL install); "
                f"dist-info dir: {dist_info_dir}; metadata fields: {metadata_fields}"
            )

        info = json.loads(raw)
        commit = info.get("vcs_info", {}).get("commit_id")
        if not commit:
            return False, f"unavailable (direct_url.json has no vcs_info.commit_id: {raw})"
        return True, str(commit)

    def rllm_installed_revision() -> str:
        found, value = resolve_installed_revision("rllm")
        if found:
            assert value == RLLM_REVISION, (
                f"installed rllm commit {value} does not match pinned {RLLM_REVISION}"
            )
        return value

    def gateway_installed_revision() -> str:
        found, value = resolve_installed_revision("rllm-model-gateway")
        if found:
            assert value == RLLM_REVISION, (
                f"installed rllm-model-gateway commit {value} does not match pinned "
                f"{RLLM_REVISION}"
            )
        return value

    def aeread_version() -> str:
        import aeread

        return getattr(aeread, "__version__", "unknown")

    def flash_attn_version() -> str:
        try:
            import flash_attn

            return flash_attn.__version__
        except ImportError:
            return "absent (fallback path)"

    def gpu_name() -> str:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

    record("torch", torch_version)
    record("cuda_available", cuda_available)
    record("numpy", numpy_version)
    record("verl", verl_version)
    record("rllm", rllm_version)
    record("rllm_installed_revision", rllm_installed_revision)
    record("gateway_installed_revision", gateway_installed_revision)
    record("aeread", aeread_version)
    record("flash_attn", flash_attn_version)
    record("gpu", gpu_name)

    return result


@app.local_entrypoint()
def main() -> None:
    for key, value in image_smoke.remote().items():
        print(f"{key}: {value}")
