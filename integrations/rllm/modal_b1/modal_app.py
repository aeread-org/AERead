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

GPU = "A10G"
RUNS_DIR = "/runs"

app = modal.App("aeread-b1")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "build-essential")
    .pip_install("uv")
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
    # flash-attn needs an already-installed torch and must not build in an
    # isolated env, so wheel isolation is disabled here rather than globally.
    .run_commands(
        "pip install flash-attn==2.8.3 --no-build-isolation || "
        "echo 'flash-attn unavailable, verl will fall back'"
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

        from aeread.integrations.rllm_flow import RLLM_PINNED_REVISION, aeread_flow

        assert RLLM_PINNED_REVISION == RLLM_REVISION, (
            f"adapter expects rLLM {RLLM_PINNED_REVISION}, image pinned {RLLM_REVISION}"
        )
        assert hasattr(aeread_flow, "run"), "aeread_flow lost its .run seam"
        return getattr(rllm, "__version__", "unknown")

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
    record("aeread", aeread_version)
    record("flash_attn", flash_attn_version)
    record("gpu", gpu_name)

    return result


@app.local_entrypoint()
def main() -> None:
    for key, value in image_smoke.remote().items():
        print(f"{key}: {value}")
