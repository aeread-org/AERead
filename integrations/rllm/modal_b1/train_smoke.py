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
    image,
    openrouter_secret,
    volume,
)
from integrations.rllm.modal_b1.probe import DEFAULT_MODEL

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
        "data.train_batch_size=4",
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
        "actor_rollout_ref.hybrid_engine=True",
        "actor_rollout_ref.actor.optim.lr=1e-6",
        "actor_rollout_ref.actor.ppo_mini_batch_size=4",
        "actor_rollout_ref.actor.use_dynamic_bsz=True",
        "actor_rollout_ref.actor.ppo_max_token_len_per_gpu=16384",
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
        "actor_rollout_ref.rollout.gpu_memory_utilization=0.55",
        "actor_rollout_ref.rollout.n=2",
        "actor_rollout_ref.rollout.val_kwargs.n=1",
        "actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1",
        f"rllm.workflow.n_parallel_tasks={N_PARALLEL_TASKS}",
        "rllm.workflow.retry_limit=3",
        # Environment-forced deviation, recorded in the report: a real
        # episode failed with "max_tokens=30720 cannot be greater than
        # max_model_len=8192" -- and the same 30720 persisted unchanged
        # after max_model_len was raised to 32768, so it was not derived
        # from max_model_len at all. Traced to
        # rllm/trainer/config/rllm/base.yaml's own max_response_length:
        # 30720 default, a namespace (rllm.max_response_length) separate
        # from data.max_response_length above and not auto-derived from
        # it (unlike actor_rollout_ref.rollout.response_length, which
        # does default from data.max_response_length via oc.select).
        # Setting it to the same 2048 the brief already intended for
        # data.max_response_length closes the gap: prompt (up to ~8200
        # tokens per Task 3's probe) plus a 2048-token response budget
        # stays safely under the model's 32768 context either way.
        "rllm.max_response_length=2048",
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
                    "rllm.max_response_length set to 2048 (rllm's own "
                    "config namespace, separate from data.max_response_length "
                    "above, defaults to 30720 and is not auto-derived from "
                    "it) because that 30720 default was requested as "
                    "max_tokens on a real episode regardless of prompt size "
                    "or max_model_len"
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
