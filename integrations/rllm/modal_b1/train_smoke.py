"""Stage 1: the actual B1 claim, a real GRPO optimizer step on AERead.

Scaled down from cookbooks/frozenlake/train_verl.sh, which runs a 4B policy
with LoRA across eight GPUs. Group size and rejection sampling match
integrations/rllm/prototype_train.yaml so this exercises the shipped
training contract rather than a bespoke one.

Task 3's probe stage was superseded by a user decision: the manual
aeread_flow.run() + aeread_evaluator() chain it used never creates a
gateway session, so episodes are never enriched and every episode fails
with CandidateTraceMismatch, independent of model. AgentTrainer drives
AgentFlowEngine natively, which does create the gateway session, so this
stage both answers B1 (did an optimizer step execute) and, by capturing
each episode's AER as it is produced, answers the variance question the
probe would have answered: are advantages actually non-zero anywhere.

This module does NOT call probe.py's _serve_vllm. A real run traced the
reason: with hybrid_engine=True and actor_rollout_ref.rollout.name=vllm,
verl's own AgentTrainer launches and manages its own internal vLLM
rollout engine (visible in the trace as a vLLMHttpServer Ray actor) at
training time; nothing in the trainer path ever reads VLLM_BASE_URL or
otherwise talks to an externally pre-served instance. Calling
_serve_vllm here launched a second, redundant vLLM server on the same
single A10 at the same gpu_memory_utilization as verl's internal one,
and the first one to start starved the second: "ValueError: Free memory
on device cuda:0 (6.67/22.06 GiB) on startup is less than desired GPU
memory utilization (0.55, 12.13 GiB)." Removing the external server
call is the fix, not a workaround; probe.py's own use of _serve_vllm
(driving aeread_flow.run() directly, with no trainer in the loop at
all) still needs it, and probe.py itself is unchanged.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import modal

# Modal automounts the local entrypoint script itself as a flat file at
# /root/train_smoke.py in the remote container -- a separate, un-packaged
# copy from the full repo baked into the image at /workspace/aeread by
# modal_app.py's add_local_dir(copy=True) step. Without this, the
# container's reimport of this module (to reconstruct the decorated
# train_smoke function) cannot resolve the package-relative import below,
# because /root has no integrations/ package alongside it. Same guard
# probe.py already carries for the same reason; this path does not exist
# on the local machine, so it is a no-op locally.
if "/workspace/aeread" not in sys.path:
    sys.path.insert(0, "/workspace/aeread")

from integrations.rllm.modal_b1.modal_app import (
    GPU,
    RUNS_DIR,
    app,
    openrouter_secret,
    volume,
)
from integrations.rllm.modal_b1.modal_app import image as _base_image
from integrations.rllm.modal_b1.probe import DEFAULT_MODEL

# Environment-forced deviation, recorded in the report: a real training
# batch reached verl's own DataProto.to_tensordict() and failed with
# "AssertionError: Convert DataProto to TensorDict at least requires
# tensordict version 0.10" -- the pinned image (modal_app.py, unmodified)
# installs tensordict==0.9.1 alongside verl==0.8.0 in one combined `uv
# pip install`, which only proves 0.9.1 satisfied verl's declared install
# -time constraint, not its runtime assertion in protocol.py. This is not
# altering the verl==0.8.0 or vllm==0.22.1 pins, or the rLLM revision --
# it is one additional layer on top of the already-built, cached base
# image, scoped to this function only; modal_app.py itself is untouched
# and image_smoke/probe still build and run against the original image.
# verl 0.8.0 hard-requires flash_attn: verl/utils/attention_utils.py
# _get_attention_functions() imports flash_attn.bert_padding with no fallback,
# and it is reached on the log-prob path regardless of use_dynamic_bsz or
# use_remove_padding (both were tried and both still hit it). Upstream ships no
# wheel for our torch 2.11.0+cu130; the closest is this cu13torch2.9 build.
# PyTorch does not promise C++ ABI stability across minor versions, so this may
# fail to import with an undefined symbol. flash_check below tests exactly that
# before a training run pays for the discovery.
FLASH_ATTN_WHEEL = (
    "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post1/"
    "flash_attn-2.8.3+cu13torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
)

image = _base_image.pip_install("tensordict==0.10.0")  # exact: verl 0.8.0 declares
# tensordict!=0.9.0,<=0.10.0,>=0.8.0 but asserts >=0.10 at runtime in
# protocol.py, so 0.10.0 is the only version satisfying both. An
# unpinned ">=0.10" resolved to 0.13.0 and violated verl's ceiling..pip_install(FLASH_ATTN_WHEEL)


@app.function(image=image, gpu=GPU, timeout=900)
def flash_check() -> dict[str, str]:
    """Report whether the torch2.9-built flash_attn imports on torch 2.11."""

    def record(name, fn):
        try:
            return str(fn())
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    out = {}
    out["torch"] = record("torch", lambda: __import__("torch").__version__)
    out["flash_attn"] = record(
        "flash_attn", lambda: __import__("flash_attn").__version__
    )

    def bert_padding():
        from flash_attn.bert_padding import unpad_input  # noqa: F401

        return "importable"

    out["bert_padding"] = record("bert_padding", bert_padding)

    def verl_path():
        from verl.utils.attention_utils import _get_attention_functions

        _get_attention_functions()
        return "resolved"

    out["verl_attention_utils"] = record("verl_attention_utils", verl_path)

    # A source build of flash-attn needs nvcc, which the pip torch wheels do
    # NOT provide: they ship CUDA runtime libraries only. If nvcc is absent the
    # build requires re-basing the whole image on a CUDA devel image, which is
    # a much larger change than adding one build layer.
    import shutil
    import subprocess

    nvcc = shutil.which("nvcc")
    out["nvcc_path"] = str(nvcc or "absent")
    if nvcc:
        out["nvcc_version"] = record(
            "nvcc",
            lambda: subprocess.run(
                [nvcc, "--version"], capture_output=True, text=True, check=False
            ).stdout.strip().splitlines()[-1],
        )
    out["cuda_home"] = str(os.environ.get("CUDA_HOME", "unset"))
    return out


@app.local_entrypoint(name="flash_check_main")
def flash_check_entry() -> None:
    for key, value in flash_check.remote().items():
        print(f"{key}: {value}")

# The image_smoke log showed "You are sending unauthenticated requests to the
# HF Hub" during the cold-container weight download; this raises the rate
# limit and speeds the download. The secret holds one key, HF_TOKEN, read
# from the project's local .env and created once via `modal secret create`;
# its value is never printed, logged, or committed anywhere in this repo.
hf_secret = modal.Secret.from_name("aeread-hf")

# One deliberate deviation from prototype_train.yaml, recorded in the report:
# n_parallel_tasks is raised from 2 to 4. The 2 guards against training
# defaults amplifying calls to the external scoring services; at roughly two
# dozen episodes the amplification is immaterial and this halves wall clock.
N_PARALLEL_TASKS = 4


@app.function(
    image=image,
    gpu=GPU,
    timeout=7200,
    volumes={RUNS_DIR: volume},
    secrets=[openrouter_secret, hf_secret],
)
def train_smoke(model: str = DEFAULT_MODEL, steps: int = 3) -> dict[str, Any]:
    """Run a bounded GRPO training loop and report what actually happened."""
    os.chdir("/workspace/aeread")

    # Cache HF downloads (base model weights, tokenizer) in the same runs
    # volume so a rerun does not pay the cold-container download again. Both
    # the vLLM subprocess (which inherits this process's environ) and this
    # process's own huggingface_hub calls (verl's FSDP actor loading the same
    # base model) read HF_HOME, so setting it once here covers both. The
    # directory is committed to the volume in the finally block below,
    # alongside the run report.
    hf_cache_dir = f"{RUNS_DIR}/hf_cache"
    os.makedirs(hf_cache_dir, exist_ok=True)
    os.environ.setdefault("HF_HOME", hf_cache_dir)

    from omegaconf import OmegaConf
    from rllm.data import DatasetRegistry
    from rllm.trainer.unified_trainer import AgentTrainer

    import aeread.integrations.rllm_flow as rllm_flow_module
    from aeread.integrations.rllm_dataset import register
    from aeread.integrations.rllm_eval import aeread_evaluator
    from aeread.integrations.rllm_flow import (
        aeread_flow,
        get_flow_telemetry,
        reset_flow_telemetry,
    )

    from integrations.rllm.modal_b1.report import (
        ESTIMATED_USD_PER_EPISODE,
        build_run_report,
        format_cost_line,
        variance_verdict,
        write_report,
    )

    register()
    train_dataset = DatasetRegistry.load_dataset("aeread", "train")
    val_dataset = DatasetRegistry.load_dataset("aeread", "dev")
    if train_dataset is None or len(list(train_dataset)) == 0:
        raise RuntimeError("aeread train split is empty; --register did not resolve")

    overrides = [
        "rllm/backend=verl",
        "algorithm.adv_estimator=grpo",
        "algorithm.norm_adv_by_std_in_grpo=true",
        "rllm.algorithm.use_rllm=true",
        "data.train_batch_size=16",
        "data.val_batch_size=4",
        "data.max_prompt_length=4096",
        "data.max_response_length=2048",
        f"+model.name={model}",
        f"actor_rollout_ref.model.path={model}",
        "actor_rollout_ref.model.lora.rank=32",
        "actor_rollout_ref.model.lora.alpha=32",
        "actor_rollout_ref.model.lora.merge=true",
        # Environment-forced deviation, recorded in the report: the image's
        # flash-attn build failed (documented in modal_app.py's own image
        # comments; image_smoke's own probe reports it "absent, fallback
        # path"). The FSDP actor's HF model load defaults override_config's
        # attn_implementation to "flash_attention_2" regardless
        # (verl/workers/config/model.py), which raised ImportError on the
        # first real train_smoke run: "FlashAttention2 has been toggled on,
        # but ... the package ... doesn't seem to be installed." vLLM's own
        # rollout engine is unaffected (it ships its own attention kernels,
        # not the standalone pip package), so only the actor side needs this.
        # sdpa is verl's other fully supported path (verl/models/transformers
        # /qwen2.py dispatches through ALL_ATTENTION_FUNCTIONS for it) and
        # needs no extra package.
        "+actor_rollout_ref.model.override_config.attn_implementation=sdpa",
        # verl's attention_utils.unpad_input imports flash_attn.bert_padding
        # unconditionally, and the sequence-packing path reaches it whenever
        # remove-padding is on. rLLM's _generated_agent_ppo_trainer.yaml
        # defaults this to false, but that file is not necessarily merged
        # into the composed "unified" config, in which case verl's own
        # default wins. Set it explicitly rather than trusting the default.
        "actor_rollout_ref.model.use_remove_padding=False",
        "actor_rollout_ref.hybrid_engine=True",
        "actor_rollout_ref.actor.optim.lr=1e-6",
        "actor_rollout_ref.actor.ppo_mini_batch_size=4",
        # use_dynamic_bsz packs variable-length sequences, and verl's packing
        # path calls verl/utils/attention_utils.py unpad_input, whose
        # _get_attention_functions() imports flash_attn.bert_padding
        # unconditionally. That import is NOT gated by use_remove_padding
        # (already false by default here) and has no fallback, so with
        # flash-attn absent the run dies with ModuleNotFoundError inside the
        # Ray actor. Disabling dynamic batching keeps the fixed-size micro
        # batch path, which does not unpad. Sequence packing is a throughput
        # optimization and this run is a correctness smoke, so the loss is
        # only speed.
        "actor_rollout_ref.actor.use_dynamic_bsz=False",
        "actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1",
        "actor_rollout_ref.actor.fsdp_config.param_offload=true",
        "actor_rollout_ref.actor.fsdp_config.optimizer_offload=true",
        "actor_rollout_ref.actor.use_kl_loss=False",
        "actor_rollout_ref.rollout.tensor_model_parallel_size=1",
        "actor_rollout_ref.rollout.name=vllm",
        "actor_rollout_ref.rollout.mode=async",
        # 8192 (the brief's literal value) blocked a real episode with
        # "max_tokens=30720 cannot be greater than max_model_len=8192":
        # the gateway session computed its default sampling budget from
        # Qwen2.5-0.5B-Instruct's published 32768-token context, not from
        # this override, and separately, Task 3's probe already found one
        # AERead case's prompt alone exceeds 8193 tokens. Task 3 fixed the
        # identical mismatch for the standalone probe server the same way,
        # by raising to the model's real context; that value is reused here
        # for verl's internal rollout engine. Removing the redundant
        # external server (above) frees the GPU memory this needs.
        "actor_rollout_ref.rollout.max_model_len=32768",
        "actor_rollout_ref.rollout.temperature=0.7",
        # 0.55 works for a 0.5B policy but OOMs a 1.7B one: the actor's
        # log-prob forward asked for 3.48 GiB with only 3.36 GiB free on the
        # A10 (22.06 GiB total, 18.67 GiB already in use), a shortfall of
        # roughly 120 MB. Lowering vLLM's reserved share frees about 3.3 GiB
        # for the FSDP actor, well clear of that gap, and still leaves vLLM
        # ample KV cache at this model size.
        "actor_rollout_ref.rollout.gpu_memory_utilization=0.40",
        "actor_rollout_ref.rollout.n=2",
        "actor_rollout_ref.rollout.val_kwargs.n=1",
        # With use_dynamic_bsz=False verl no longer derives these from the
        # token budget, so both the rollout and the ref worker need an
        # explicit micro batch size or config validation rejects the run.
        "actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1",
        "actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1",
        f"rllm.workflow.n_parallel_tasks={N_PARALLEL_TASKS}",
        "rllm.workflow.retry_limit=3",
        # Environment-forced deviation, recorded in the report: a real
        # episode failed with "max_tokens=30720 cannot be greater than
        # max_model_len=8192" -- and the same 30720 persisted unchanged
        # after max_model_len was raised to 32768, so it was not derived
        # from max_model_len at all. Traced to
        # rllm/trainer/config/rllm/base.yaml, whose data: block (nested
        # under the rllm: root, not a flat rllm.max_response_length field)
        # sets max_response_length: 30720. rllm.rollout.train.max_tokens
        # and rollout.val.max_tokens both interpolate from this exact
        # nested path (${rllm.data.max_response_length}), so this is the
        # key that actually needs setting -- a first attempt at
        # +rllm.max_response_length=2048 (without the data. segment)
        # composed without error but created an unrelated, unread key;
        # the max_tokens=30720 error still reproduced on the next run,
        # which is what exposed the wrong path. Separately, the same
        # rllm.data.* block also holds train_batch_size (default 64) and
        # val_batch_size (default -1), neither auto-derived from the
        # data.* overrides above; left at 64 against a 16-example train
        # split, the dataloader silently yielded zero batches on the next
        # run (confirmed: telemetry showed 0 episodes attempted after a
        # clean exit, no exception). All four rllm.data.* fields are set
        # here to the same values the brief already intended for data.*.
        "rllm.data.train_batch_size=16",
        "rllm.data.val_batch_size=4",
        "rllm.data.max_prompt_length=4096",
        "rllm.data.max_response_length=2048",
        # Same dual-namespace pattern once more: rllm.rollout.n (the
        # group size build_train_schedule actually reads, per
        # unified_trainer.py) defaults to 8, independent of
        # actor_rollout_ref.rollout.n=2 above (the verl-native field that
        # controls how many completions vLLM actually generates per
        # prompt). Left mismatched, the training schedule would expect
        # groups of 8 while only 2 rollouts per task are ever produced.
        "rllm.rollout.n=2",
        "rllm.rollout.n_val=1",
        "rllm.compact_filtering.enable=true",
        "rllm.compact_filtering.mask_error=true",
        "rllm.rejection_sample.min_trajs_per_group=2",
        "trainer.logger=['console']",
        "trainer.project_name=aeread-b1",
        "trainer.experiment_name=micro-grpo-smoke",
        "trainer.val_before_train=false",
        "trainer.n_gpus_per_node=1",
        "trainer.nnodes=1",
        "trainer.save_freq=-1",
        "trainer.test_freq=-1",
        "trainer.total_epochs=1",
        f"trainer.total_training_steps={steps}",
        "trainer.resume_mode=disable",
        "trainer.default_hdfs_dir=null",
        # Environment-forced deviation, recorded in the report: the eight
        # trainer.* overrides directly above are the verl-native namespace
        # (they correctly configure verl's own FSDP/PPO backend and its LR
        # scheduler -- verl_backend.py reads trainer.total_training_steps
        # from exactly this node). But unified_trainer.py's own OWN loop
        # control (_fit_on_policy: which epoch/batch to stop at, whether to
        # run a final validation) reads a SEPARATE, parallel node,
        # rllm.trainer.*, which was never touched by the eight overrides
        # above and so kept rllm/trainer/config/rllm/base.yaml's own
        # defaults: total_epochs=10, total_batches=-1 (no early stop),
        # test_freq=5 (validates on step 0 and unconditionally once more
        # after the loop ends, which is exactly what produced the
        # "max_tokens=30720" failure inside _validate_async on a run where
        # training itself had not even started yet). Left unfixed, a
        # requested --steps 1 would not actually have bounded how many
        # optimizer steps ran: total_training_steps only feeds the LR
        # schedule, not the loop that decides how many batches to consume.
        # rllm.trainer.total_batches is the field _fit_on_policy actually
        # checks (trainer_state.global_step >= rllm.trainer.total_batches)
        # to stop early, so it is set to the same requested step count.
        f"rllm.trainer.total_batches={steps}",
        "rllm.trainer.total_epochs=1",
        "rllm.trainer.test_freq=-1",
    ]

    from hydra import compose, initialize_config_dir
    from rllm.trainer import config as rllm_trainer_config

    config_dir = os.path.dirname(rllm_trainer_config.__file__)
    with initialize_config_dir(config_dir=config_dir, version_base=None):
        config = compose(config_name="unified", overrides=overrides)

    print(OmegaConf.to_yaml(config.rllm))

    # Episode-level AER capture, folded in from the superseded Task 3
    # variance probe. GRPO computes an advantage within a group of
    # same-task rollouts (rollout.n=2 samples per task here), so grouping
    # captured AERs by task id answers the same question the probe would
    # have answered, at zero extra cost: is there any group where the
    # rollouts actually differ, so the resulting advantage is non-zero.
    #
    # This wraps aeread.integrations.rllm_flow._build_measured_episode, the
    # module-level function _aeread_flow_impl calls by name (resolved via
    # the module's globals at call time, not bound at definition time), so
    # replacing the module attribute here changes what every subsequent
    # call sees without editing the file on disk. No file under src/aeread/
    # is modified; this is a runtime wrapper installed and removed inside
    # this Modal function's own process.
    episode_records: list[dict[str, Any]] = []
    original_build_episode = rllm_flow_module._build_measured_episode

    def _capturing_build_episode(task: Any, cfg: Any) -> Any:
        episode = original_build_episode(task, cfg)
        task_metadata = getattr(task, "metadata", None) or task
        task_id = (
            task_metadata.get("id", "unknown")
            if hasattr(task_metadata, "get")
            else "unknown"
        )
        episode_records.append(
            {"task_id": task_id, "aer": episode.artifacts.get("aer")}
        )
        return episode

    rllm_flow_module._build_measured_episode = _capturing_build_episode

    reset_flow_telemetry()
    started = time.time()
    error: str | None = None
    try:
        trainer = AgentTrainer(
            config=config,
            agent_flow=aeread_flow,
            evaluator=aeread_evaluator,
            backend="verl",
            train_dataset=train_dataset,
            val_dataset=val_dataset,
        )
        trainer.train()
    except Exception as exc:  # reported, never silently swallowed
        error = f"{type(exc).__name__}: {exc}"
        print(f"TRAINING FAILED: {error}")
        raise
    finally:
        rllm_flow_module._build_measured_episode = original_build_episode
        gpu_seconds = time.time() - started
        telemetry = get_flow_telemetry()

        groups: dict[str, list[float]] = {}
        for record in episode_records:
            aer = record["aer"]
            if aer is None:
                continue
            groups.setdefault(str(record["task_id"]), []).append(float(aer))
        group_variance = {
            task_id: variance_verdict(aers) for task_id, aers in groups.items()
        }
        any_group_nondegenerate = any(
            not verdict["degenerate"] for verdict in group_variance.values()
        )

        report = build_run_report(
            stage="train_smoke",
            rows=[],
            telemetry=telemetry,
            gpu_seconds=gpu_seconds,
            openrouter_usd=telemetry["attempted"] * ESTIMATED_USD_PER_EPISODE,
            live_calls=telemetry["attempted"],
            cached_calls=0,
            total_tokens=0,
            extra={
                "model": model,
                "requested_steps": steps,
                "n_parallel_tasks": N_PARALLEL_TASKS,
                "deviation_note": (
                    "n_parallel_tasks raised from prototype_train.yaml's 2 to 4; "
                    "actor_rollout_ref.model.override_config.attn_implementation "
                    "forced to sdpa because the image's flash-attn build failed "
                    "(vLLM's own rollout kernels are unaffected, only the FSDP "
                    "actor's HF model load needed this); the brief's probe.py "
                    "_serve_vllm call was dropped from this trainer path because "
                    "verl's own hybrid engine launches its own internal vLLM "
                    "rollout server, and running both on one A10 starved the "
                    "second server of GPU memory; "
                    "actor_rollout_ref.rollout.max_model_len raised from the "
                    "brief's 8192 to 32768 (the model's real published "
                    "context, and the same value Task 3's probe already "
                    "needed) because a real episode's gateway session "
                    "computed a default sampling budget against the model's "
                    "true context and exceeded 8192; "
                    "rllm.data.train_batch_size/val_batch_size/"
                    "max_prompt_length/max_response_length set to the same "
                    "values already intended for data.* above (rllm's own "
                    "nested data: block, defaults 64/-1/2048/30720, is not "
                    "auto-derived from data.*; a first attempt at a flat "
                    "rllm.max_response_length key composed without error "
                    "but was unread, and left at 64 the train dataloader "
                    "silently yielded zero batches against the 16-example "
                    "train split); rllm.rollout.n/n_val set to match "
                    "actor_rollout_ref.rollout.n=2 and val_kwargs.n=1 "
                    "(rllm.rollout.n independently feeds the training "
                    "schedule's group size and defaults to 8); the image "
                    "adds one derived layer, tensordict>=0.10 on top of "
                    "the pinned base image's tensordict==0.9.1, because a "
                    "real batch reached verl's own "
                    "DataProto.to_tensordict() and failed an internal "
                    "assertion requiring >=0.10 -- 0.9.1 only satisfied "
                    "verl 0.8.0's declared install-time constraint, not "
                    "this runtime one; verl==0.8.0, vllm==0.22.1, and the "
                    "rLLM revision are unchanged, and modal_app.py itself "
                    "is untouched; "
                    "rllm.trainer.total_batches set to the requested step "
                    "count (and rllm.trainer.total_epochs=1, "
                    "rllm.trainer.test_freq=-1) because unified_trainer.py's "
                    "own loop control reads rllm.trainer.*, a namespace "
                    "separate from the eight verl-native trainer.* overrides "
                    "above; left unset it defaults to total_epochs=10, "
                    "total_batches=-1 (no early stop), so the brief's "
                    "trainer.total_training_steps override (which only feeds "
                    "verl's LR scheduler) would not actually have bounded "
                    "how many optimizer steps this run performed"
                ),
                "error": error,
                "episode_records": episode_records,
                "group_variance": group_variance,
                "any_group_nondegenerate": any_group_nondegenerate,
            },
        )
        write_report(f"{RUNS_DIR}/train_smoke.json", report)
        volume.commit()
        print(format_cost_line(report))
        print(f"episode records: {episode_records}")
        print(f"group variance: {group_variance}")
        print(f"any group non-degenerate (non-zero advantage possible): {any_group_nondegenerate}")

    return report


@app.local_entrypoint(name="train_smoke_main")
def main(model: str = DEFAULT_MODEL, steps: int = 3) -> None:
    report = train_smoke.remote(model=model, steps=steps)
    telemetry = report["telemetry"]
    print(f"\nepisodes attempted: {telemetry['attempted']}")
    print(f"episodes measured:  {telemetry['measured']}")
    print(f"failures by class:  {telemetry['failed_by_class']}")
    print(f"episode records: {report.get('episode_records')}")
    print(f"group variance: {report.get('group_variance')}")
    print(f"any group non-degenerate: {report.get('any_group_nondegenerate')}")
