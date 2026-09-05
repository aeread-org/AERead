"""Housing backend-qualified model-sensitivity campaign.

This campaign keeps the selected Housing cases and fixed minimal-chat harness
while assigning new model-profile identities to alternate pinned endpoints.
Profile admission is a mandatory gate before any live Housing trajectory.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread_families.housing import environment as hz

from aeread.shared_runner.task.execution import (
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
)

from .runner import (
    GLM_53_FLASH_MODEL,
    GLM_53_FLASH_REVISION,
    HOUSING_COMMIT_OUTPUT_SCHEMA,
    HOUSING_COMMIT_OUTPUT_SCHEMA_V2,
    HOUSING_CONTACT_OUTPUT_SCHEMA,
    HOUSING_CONTACT_OUTPUT_SCHEMA_V2,
    HOUSING_LANDLORD_PROMPT,
    HOUSING_RESPOND_OUTPUT_SCHEMA,
    HOUSING_RESPOND_OUTPUT_SCHEMA_V2,
    HOUSING_TENANT_PROMPT,
    OpenRouterRoutePin,
)
from .model_sensitivity import (
    CooldownProviderClient,
    PacedProviderClient,
    _exception_attribute,
    _read_sealed,
    _sealed,
    _selected_case_artifact,
    _sha256,
    _write_json,
    build_setups,
    design_artifact,
    provider_free_artifact,
    run_live,
)
from .population_campaign import (
    DEEPSEEK_MODEL,
    DEEPSEEK_REVISION,
    _validate_admission_action,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from . import provider_cooldown as provider_cooldown_module
from . import provider_pacing as provider_pacing_module


CONTRACT_SCHEMA_VERSION = "aeread.housing_backend_campaign/0.1"
CAMPAIGN_SPECS = {
    "housing_model_sensitivity_openrouter_alt_v2": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v2",
        "per_probe_cost_reserve_usd": 0.002,
        "admission_cost_ceiling_usd": 0.04,
        "providers": {
            "glm_53_flash": "Novita",
            "deepseek_v4_flash": "OpenInference",
        },
    },
    "housing_model_sensitivity_openrouter_alt_v3": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v3",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "providers": {
            "glm_53_flash": "Reka",
            "deepseek_v4_flash": "Parasail",
        },
    },
    "housing_model_sensitivity_openrouter_alt_v4": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v4",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "providers": {
            "glm_53_flash": "Phala",
            "deepseek_v4_flash": "Parasail",
        },
    },
    "housing_model_sensitivity_openrouter_alt_v5": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v5",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "providers": {
            "glm_53_flash": "NextBit",
            "deepseek_v4_flash": "Parasail",
        },
    },
    "housing_model_sensitivity_openrouter_alt_v6": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v6",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "providers": {
            "glm_53_flash": "NextBit",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
    },
    "housing_model_sensitivity_openrouter_alt_v7": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v7",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "providers": {
            "glm_53_flash": "NextBit",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
    },
    "housing_model_sensitivity_openrouter_alt_v8": {
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v8",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_cost_ceiling_usd": 0.10,
        "per_trajectory_cost_reserve_usd": 0.01,
        "providers": {
            "glm_53_flash": "NextBit",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
    },
    "housing_model_sensitivity_openrouter_alt_v9": {
        "claim_status": "exploratory_variance_pilot_only",
        "reasoning_condition_id": "model_sensitivity_openrouter_alt_low_v9",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_cost_ceiling_usd": 0.35,
        "per_trajectory_cost_reserve_usd": 0.01,
        "world_seeds": [1460378342, 981417412, 123194022, 145537168],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "NextBit",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
    },
    "housing_model_sensitivity_openrouter_morph_v10": {
        "claim_status": "exploratory_variance_pilot_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": "model_sensitivity_openrouter_morph_low_v10",
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_cost_ceiling_usd": 0.35,
        "per_trajectory_cost_reserve_usd": 0.01,
        "world_seeds": [1460378342, 981417412, 123194022, 145537168],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Morph",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
    },
    "housing_model_sensitivity_openrouter_deepinfra_v11": {
        "claim_status": "development_full_trajectory_gate_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_deepinfra_low_v11"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_stage": "full_trajectory",
        "execution_config_ids": ["moderate_cw085_r2"],
        "execution_cost_ceiling_usd": 0.08,
        "per_trajectory_cost_reserve_usd": 0.02,
        "world_seeds": [227922569],
        "condition_order": "listed",
        "analysis": {
            "primary_view": "full_trajectory_condition_coverage",
            "aggregation": "none_promotion_gate",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "DeepInfra",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "stopping_rule": (
            "profile_admission_must_pass_before_full_trajectory; stop_before_next_"
            "trajectory_when_remaining_campaign_budget_is_below_the_declared_"
            "reserve; stop_immediately_on_route_drift_or_replay_failure"
        ),
    },
    "housing_model_sensitivity_openrouter_deepinfra_v12": {
        "claim_status": "development_full_trajectory_gate_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_deepinfra_low_v12"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_stage": "full_trajectory",
        "execution_config_ids": ["moderate_cw085_r2"],
        "execution_cost_ceiling_usd": 0.08,
        "per_trajectory_cost_reserve_usd": 0.02,
        "world_seeds": [227922569],
        "condition_order": "listed",
        "analysis": {
            "primary_view": "full_trajectory_condition_coverage",
            "aggregation": "none_promotion_gate",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "DeepInfra",
            "deepseek_v4_flash": "Parasail",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_start_to_start",
            "minimum_interval_seconds_by_provider": {
                "DeepInfra": 15.0,
                "Parasail": 15.0,
            },
            "first_call_delay_seconds": 15.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "6e51c13330a2aa73e4b9f8e7610c0cc232873b1aecaf1b85960a3db2ab8790cd"
            ),
        },
        "stopping_rule": (
            "profile_admission_must_pass_before_full_trajectory; stop_before_next_"
            "trajectory_when_remaining_campaign_budget_is_below_the_declared_"
            "reserve; stop_immediately_on_route_drift_or_replay_failure"
        ),
    },
    "housing_model_sensitivity_openrouter_friendli_v13": {
        "claim_status": "development_full_trajectory_gate_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_friendli_low_v13"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_stage": "full_trajectory",
        "execution_config_ids": ["moderate_cw085_r2"],
        "execution_cost_ceiling_usd": 0.08,
        "per_trajectory_cost_reserve_usd": 0.02,
        "world_seeds": [227922569],
        "condition_order": "listed",
        "analysis": {
            "primary_view": "full_trajectory_condition_coverage",
            "aggregation": "none_promotion_gate",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Friendli",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "unknown",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Friendli": 10.0,
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
        "stopping_rule": (
            "profile_admission_must_pass_before_full_trajectory; stop_before_next_"
            "trajectory_when_remaining_campaign_budget_is_below_the_declared_"
            "reserve; stop_immediately_on_route_drift_or_replay_failure"
        ),
    },
    "housing_model_sensitivity_openrouter_friendli_v14": {
        "claim_status": "exploratory_variance_pilot_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_friendli_low_v14"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "execution_cost_ceiling_usd": 0.45,
        "per_trajectory_cost_reserve_usd": 0.01,
        "world_seeds": [264284765, 722524881, 1535604354, 366965770],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Friendli",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "unknown",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Friendli": 10.0,
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
    },
    "housing_model_sensitivity_openrouter_friendli_v15": {
        "claim_status": "exploratory_variance_pilot_only",
        "catalog_retrieved_at": "2026-09-03",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_friendli_low_v15"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "admission_attempt_limit": 4,
        "prerequisite_full_trajectory_gate": {
            "campaign_id": "housing_model_sensitivity_openrouter_friendli_v13",
            "qualification_path": (
                "evidence/housing_model_sensitivity_openrouter_friendli_v13/"
                "reports/qualification.json"
            ),
            "qualification_artifact_sha256": (
                "4a976375fbed6fb1dd1e0f2c14dceaaafa825a2209c17b3906841b05281c5605"
            ),
        },
        "execution_cost_ceiling_usd": 0.45,
        "per_trajectory_cost_reserve_usd": 0.01,
        "world_seeds": [264284765, 722524881, 1535604354, 366965770],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Friendli",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "unknown",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Friendli": 10.0,
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
    },
    "housing_model_sensitivity_openrouter_parasail_v16": {
        "claim_status": "development_full_trajectory_gate_only",
        "catalog_retrieved_at": "2026-09-05",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_parasail_low_v16"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "admission_attempt_limit": 4,
        "route_selection_probe": {
            "probe_id": "housing_glm_route_probe_2026-09-05",
            "summary_path": (
                "evidence/housing_glm_route_probe_2026-09-05/reports/summary.json"
            ),
            "summary_artifact_sha256": "54406a94d4dacc0d1c0b6533ff67cdcfbbc4a20b56fdb91d98a7a551ac8cb63c",
        },
        "execution_stage": "full_trajectory",
        "execution_config_ids": ["moderate_cw085_r2"],
        "execution_cost_ceiling_usd": 0.08,
        "per_trajectory_cost_reserve_usd": 0.02,
        "world_seeds": [227922569],
        "condition_order": "listed",
        "analysis": {
            "primary_view": "full_trajectory_condition_coverage",
            "aggregation": "none_promotion_gate",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Parasail",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "fp8",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
        "stopping_rule": (
            "profile_admission_must_pass_before_full_trajectory; stop_before_next_"
            "trajectory_when_remaining_campaign_budget_is_below_the_declared_"
            "reserve; stop_immediately_on_route_drift_or_replay_failure"
        ),
    },
    "housing_model_sensitivity_openrouter_parasail_v17": {
        "claim_status": "exploratory_variance_pilot_only",
        "catalog_retrieved_at": "2026-09-05",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_parasail_low_v17"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "admission_attempt_limit": 4,
        "prerequisite_full_trajectory_gate": {
            "campaign_id": "housing_model_sensitivity_openrouter_parasail_v16",
            "qualification_path": (
                "evidence/housing_model_sensitivity_openrouter_parasail_v16/"
                "reports/qualification.json"
            ),
            "qualification_artifact_sha256": (
                "221ebfa55ba6aecd89546f74b7851deac869a8f68277ed51b366ef13088a2abb"
            ),
        },
        "route_selection_probe": {
            "probe_id": "housing_glm_route_probe_2026-09-05",
            "summary_path": (
                "evidence/housing_glm_route_probe_2026-09-05/reports/summary.json"
            ),
            "summary_artifact_sha256": (
                "54406a94d4dacc0d1c0b6533ff67cdcfbbc4a20b56fdb91d98a7a551ac8cb63c"
            ),
        },
        "execution_cost_ceiling_usd": 0.45,
        "per_trajectory_cost_reserve_usd": 0.01,
        "world_seeds": [1063943031, 647986875, 1758927083, 237549679],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Parasail",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "fp8",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
    },
    "housing_model_sensitivity_openrouter_parasail_v18": {
        "claim_status": "development_full_trajectory_gate_only",
        "catalog_retrieved_at": "2026-09-05",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_parasail_low_v18"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "admission_attempt_limit": 4,
        "timeout_seconds": 300.0,
        "seat_max_cost_usd": 0.03,
        "route_selection_probe": {
            "probe_id": "housing_glm_route_probe_2026-09-05",
            "summary_path": (
                "evidence/housing_glm_route_probe_2026-09-05/reports/summary.json"
            ),
            "summary_artifact_sha256": "54406a94d4dacc0d1c0b6533ff67cdcfbbc4a20b56fdb91d98a7a551ac8cb63c",
        },
        "execution_stage": "full_trajectory",
        "execution_config_ids": ["moderate_cw085_r2"],
        "execution_cost_ceiling_usd": 0.30,
        "per_trajectory_cost_reserve_usd": 0.06,
        "world_seeds": [227922569],
        "condition_order": "listed",
        "analysis": {
            "primary_view": "full_trajectory_condition_coverage",
            "aggregation": "none_promotion_gate",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Parasail",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "fp8",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
        "stopping_rule": (
            "profile_admission_must_pass_before_full_trajectory; stop_before_next_"
            "trajectory_when_remaining_campaign_budget_is_below_the_declared_"
            "reserve; stop_immediately_on_route_drift_or_replay_failure"
        ),
    },
    "housing_model_sensitivity_openrouter_parasail_v19": {
        "claim_status": "exploratory_variance_pilot_only",
        "catalog_retrieved_at": "2026-09-05",
        "reasoning_condition_id": (
            "model_sensitivity_openrouter_parasail_low_v19"
        ),
        "per_probe_cost_reserve_usd": 0.003,
        "admission_cost_ceiling_usd": 0.06,
        "admission_attempt_limit": 4,
        "timeout_seconds": 300.0,
        "seat_max_cost_usd": 0.03,
        "prerequisite_full_trajectory_gate": {
            "campaign_id": "housing_model_sensitivity_openrouter_parasail_v18",
            "qualification_path": (
                "evidence/housing_model_sensitivity_openrouter_parasail_v18/"
                "reports/qualification.json"
            ),
            "qualification_artifact_sha256": (
                "061aab759f4a632e336546b8b0b1ea38caeead15c528b936534835d7dbfae43b"
            ),
        },
        "route_selection_probe": {
            "probe_id": "housing_glm_route_probe_2026-09-05",
            "summary_path": (
                "evidence/housing_glm_route_probe_2026-09-05/reports/summary.json"
            ),
            "summary_artifact_sha256": (
                "54406a94d4dacc0d1c0b6533ff67cdcfbbc4a20b56fdb91d98a7a551ac8cb63c"
            ),
        },
        "execution_cost_ceiling_usd": 1.0,
        "per_trajectory_cost_reserve_usd": 0.06,
        "world_seeds": [647986875, 1758927083, 237549679, 1515521562],
        "condition_order": "rotate_by_world_and_case_configuration",
        "analysis": {
            "primary_view": "paired_world_subject_mean_within_case_score",
            "aggregation": "equal_weight_configs_and_opponents_within_world",
            "primary_contrast": "glm_53_flash_minus_deepseek_v4_flash",
            "uncertainty": "sample_variance_over_world_level_paired_contrasts",
            "minimum_meaningful_effect": 0.05,
            "alpha": 0.05,
            "power": 0.8,
            "minimum_confirmatory_worlds": 30,
            "maximum_confirmatory_worlds": 100,
            "attrition_fraction": 0.1,
            "ranking_allowed": False,
        },
        "providers": {
            "glm_53_flash": "Parasail",
            "deepseek_v4_flash": "Parasail",
        },
        "quantizations": {
            "glm_53_flash": "fp8",
            "deepseek_v4_flash": "fp8",
        },
        "retryable_conditions": [
            "length",
            "rate_limit",
            "provider_5xx",
            "empty_response",
        ],
        "action_schema_version": "housing_actions/2.0",
        "wire_live_profile_controls": True,
        "verify_endpoint_snapshot": True,
        "call_pacing": {
            "clock": "monotonic_completion_to_start",
            "cooldown_seconds_by_provider": {
                "Parasail": 10.0,
            },
            "first_call_delay_seconds": 0.0,
            "scope": "shared_across_profile_admission_and_full_trajectory",
            "implementation_sha256": (
                "4dc67f4ae81395166264049bbf917d8d42e69c5d6069c97fea981c4b419415d3"
            ),
        },
        "admission_timeout_enforcement": (
            "asyncio_wait_for_controls_timeout_seconds"
        ),
    },
}
REQUIRED_ROUTE_PARAMETERS = {
    "max_tokens",
    "reasoning_effort",
    "response_format",
    "seed",
    "structured_outputs",
    "temperature",
    "top_p",
}
_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "claim_status",
    "question",
    "independent_cluster",
    "source_case_selection",
    "controls",
    "backend",
    "models",
    "conditions",
    "profile_admission",
    "execution",
    "analysis",
    "missingness",
    "stopping_rule",
}


def route_table(contract: Mapping[str, Any]) -> dict[str, OpenRouterRoutePin]:
    return {
        model_id: OpenRouterRoutePin(
            provider=model["provider"],
            quantization=model["quantization"],
            canonical_model=model["canonical_model"],
            input_per_million=model["input_per_million"],
            cached_input_per_million=model["cached_input_per_million"],
            output_per_million=model["output_per_million"],
            pricing_id=(
                f"openrouter_{model['provider'].lower()}_"
                f"{contract['backend']['catalog_retrieved_at']}_{model_id}"
            ),
        )
        for model_id, model in contract["models"].items()
    }


def _validate_models(value: Any, *, campaign_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "glm_53_flash",
        "deepseek_v4_flash",
    }:
        raise ValueError("backend campaign requires exactly GLM and DeepSeek")
    providers = CAMPAIGN_SPECS[campaign_id]["providers"]
    quantizations = CAMPAIGN_SPECS[campaign_id].get("quantizations", {})
    expected = {
        "glm_53_flash": (
            GLM_53_FLASH_MODEL,
            GLM_53_FLASH_REVISION,
            providers["glm_53_flash"],
        ),
        "deepseek_v4_flash": (
            DEEPSEEK_MODEL,
            DEEPSEEK_REVISION,
            providers["deepseek_v4_flash"],
        ),
    }
    fields = {
        "requested_model",
        "canonical_model",
        "provider",
        "quantization",
        "input_per_million",
        "cached_input_per_million",
        "output_per_million",
        "endpoint_snapshot_sha256",
        "tenant_profile_id",
        "landlord_profile_id",
    }
    for model_id, (requested, canonical, provider) in expected.items():
        model = value[model_id]
        if not isinstance(model, dict) or set(model) != fields:
            raise ValueError(f"model fields drifted for {model_id}")
        if (model["requested_model"], model["canonical_model"]) != (
            requested,
            canonical,
        ):
            raise ValueError(f"model identity drifted for {model_id}")
        if (model["provider"], model["quantization"]) != (
            provider,
            quantizations.get(model_id, "fp8"),
        ):
            raise ValueError(f"alternate route drifted for {model_id}")
        if any(
            isinstance(model[field], bool)
            or not isinstance(model[field], (int, float))
            or model[field] < 0
            for field in (
                "input_per_million",
                "cached_input_per_million",
                "output_per_million",
            )
        ):
            raise ValueError(f"pricing is invalid for {model_id}")
        if (
            not isinstance(model["endpoint_snapshot_sha256"], str)
            or len(model["endpoint_snapshot_sha256"]) != 64
        ):
            raise ValueError(f"endpoint snapshot identity is invalid for {model_id}")


def load_contract(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError("backend campaign fields are incomplete or unexpected")
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported backend campaign contract schema")
    campaign_id = value["campaign_id"]
    if campaign_id not in CAMPAIGN_SPECS:
        raise ValueError("this driver does not recognize the campaign identity")
    campaign_spec = CAMPAIGN_SPECS[campaign_id]
    if value["claim_status"] != campaign_spec.get(
        "claim_status", "development_backend_qualification_only"
    ):
        raise ValueError("backend qualification cannot support a performance claim")
    if value["independent_cluster"] != "world_seed":
        raise ValueError("world_seed must remain the independent cluster")
    _selected_case_artifact(value)

    controls = value["controls"]
    expected_controls = {
        "harness": "minimal_chat/1.0",
        "tools": "disabled",
        "memory": "disabled",
        "reasoning_condition_id": CAMPAIGN_SPECS[campaign_id]["reasoning_condition_id"],
        "reasoning_effort": "low",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 4096,
        "timeout_seconds": campaign_spec.get("timeout_seconds", 120.0),
        "sdk_retries": 0,
        "max_action_attempts": 4,
        "tenant_max_logical_actions": 48,
        "landlord_max_logical_actions": 16,
        "retryable_conditions": CAMPAIGN_SPECS[campaign_id].get(
            "retryable_conditions", ["length", "rate_limit", "provider_5xx"]
        ),
        "tenant_inference_seed_base": 87001,
        "landlord_inference_seed_base": 97001,
        "condition_order": campaign_spec.get(
            "condition_order", "rotate_by_case_configuration"
        ),
    }
    for optional_control in (
        "action_schema_version",
        "wire_live_profile_controls",
        "call_pacing",
        "admission_timeout_enforcement",
        "seat_max_cost_usd",
    ):
        if optional_control in CAMPAIGN_SPECS[campaign_id]:
            expected_controls[optional_control] = CAMPAIGN_SPECS[campaign_id][
                optional_control
            ]
    if controls != expected_controls:
        raise ValueError("fixed backend-campaign controls drifted")
    if value["backend"] != {
        "gateway": "openrouter",
        "api_base": "https://openrouter.ai/api/v1",
        "catalog_source": "https://openrouter.ai/api/v1/models/{model}/endpoints",
        "catalog_retrieved_at": campaign_spec.get(
            "catalog_retrieved_at", "2026-09-02"
        ),
        "allow_fallbacks": False,
        "require_parameters": True,
        "retry_owner": "aeread_action_attempt_policy",
        "raw_response_retention": "local_evidence_store",
    }:
        raise ValueError("backend contract drifted")
    _validate_models(value["models"], campaign_id=campaign_id)

    conditions = value["conditions"]
    identities = {
        (
            condition.get("subject"),
            condition.get("opponent"),
            condition.get("evaluation_kind"),
        )
        for condition in conditions
        if isinstance(condition, Mapping)
    }
    if len(conditions) != 4 or identities != {
        ("glm_53_flash", "glm_53_flash", "self_play"),
        ("glm_53_flash", "deepseek_v4_flash", "cross_play"),
        ("deepseek_v4_flash", "glm_53_flash", "cross_play"),
        ("deepseek_v4_flash", "deepseek_v4_flash", "self_play"),
    }:
        raise ValueError("model-to-model condition matrix drifted")

    admission = value["profile_admission"]
    if not isinstance(admission, dict) or set(admission) != {
        "probes_per_action_schema",
        "probe_seeds",
        "attempt_limit_per_probe",
        "sdk_retries",
        "hidden_repair_allowed",
        "per_probe_cost_reserve_usd",
        "cost_ceiling_usd",
        "profile_sha256s",
    }:
        raise ValueError("profile admission contract is invalid")
    if {
        key: admission[key]
        for key in (
            "probes_per_action_schema",
            "probe_seeds",
            "attempt_limit_per_probe",
            "sdk_retries",
            "hidden_repair_allowed",
            "per_probe_cost_reserve_usd",
            "cost_ceiling_usd",
        )
    } != {
        "probes_per_action_schema": 3,
        "probe_seeds": [103001, 103002, 103003],
        "attempt_limit_per_probe": CAMPAIGN_SPECS[campaign_id].get(
            "admission_attempt_limit", 1
        ),
        "sdk_retries": 0,
        "hidden_repair_allowed": False,
        "per_probe_cost_reserve_usd": CAMPAIGN_SPECS[campaign_id][
            "per_probe_cost_reserve_usd"
        ],
        "cost_ceiling_usd": CAMPAIGN_SPECS[campaign_id]["admission_cost_ceiling_usd"],
    }:
        raise ValueError("profile admission controls drifted")
    expected_profile_ids = {
        model[role]
        for model in value["models"].values()
        for role in ("tenant_profile_id", "landlord_profile_id")
    }
    if set(admission["profile_sha256s"]) != expected_profile_ids or any(
        not isinstance(digest, str) or len(digest) != 64
        for digest in admission["profile_sha256s"].values()
    ):
        raise ValueError("profile identities are incomplete")

    expected_execution = {
        "world_seeds": campaign_spec.get("world_seeds", [1971418798]),
        "replicates": 1,
        "attempt_limit": 1,
        "cost_ceiling_usd": campaign_spec.get("execution_cost_ceiling_usd", 0.05),
        "per_trajectory_cost_reserve_usd": campaign_spec.get(
            "per_trajectory_cost_reserve_usd", 0.02
        ),
        "winner_claim_allowed": False,
        "completeness_policy": "retain_typed_missingness_without_selective_retry",
    }
    if "execution_stage" in campaign_spec:
        expected_execution.update(
            {
                "stage": campaign_spec["execution_stage"],
                "config_ids": campaign_spec["execution_config_ids"],
            }
        )
    if value["execution"] != expected_execution:
        raise ValueError("live execution controls drifted")
    expected_analysis = campaign_spec.get(
        "analysis",
        {
            "primary_view": "condition_by_case_configuration_within_case_score",
            "aggregation": "none_single_world_integration_slice",
            "uncertainty": "not_estimable_from_one_world_cluster",
            "ranking_allowed": False,
        },
    )
    if value["analysis"] != expected_analysis:
        raise ValueError("development-only analysis contract drifted")
    if value["missingness"] != "typed_operational_missingness_reported_separately":
        raise ValueError("missingness policy drifted")
    expected_stopping_rule = campaign_spec.get(
        "stopping_rule",
        (
            "profile_admission_must_pass_before_live; stop_before_next_trajectory_"
            "when_remaining_campaign_budget_is_below_the_declared_reserve; stop_"
            "immediately_on_route_drift_or_replay_failure"
        ),
    )
    if value["stopping_rule"] != expected_stopping_rule:
        raise ValueError("stopping rule drifted")
    route_table(value)
    return value


def _catalog_url(contract: Mapping[str, Any], model: str) -> str:
    return contract["backend"]["catalog_source"].format(model=model)


def _endpoint_snapshot(endpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable, decision-relevant portion of one endpoint record."""

    return {
        "name": endpoint.get("name"),
        "provider_name": endpoint.get("provider_name"),
        "quantization": endpoint.get("quantization"),
        "pricing": endpoint.get("pricing"),
        "supported_parameters": sorted(endpoint.get("supported_parameters", [])),
        "status": endpoint.get("status"),
        "max_completion_tokens": endpoint.get("max_completion_tokens"),
    }


def _endpoint_snapshot_sha256(endpoint: Mapping[str, Any]) -> str:
    return _sha256(_endpoint_snapshot(endpoint))


def catalog_preflight(contract: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for model_id, model in contract["models"].items():
        with urllib.request.urlopen(
            _catalog_url(contract, model["requested_model"]), timeout=30
        ) as response:
            payload = json.load(response)
        endpoints = payload.get("data", {}).get("endpoints", [])
        matches = [
            endpoint
            for endpoint in endpoints
            if endpoint.get("provider_name") == model["provider"]
            and endpoint.get("quantization") == model["quantization"]
            and model["canonical_model"] in str(endpoint.get("name"))
        ]
        if len(matches) != 1:
            raise ValueError(f"catalog route did not resolve uniquely for {model_id}")
        endpoint = matches[0]
        pricing = endpoint.get("pricing", {})
        actual_prices = {
            "input_per_million": float(pricing["prompt"]) * 1_000_000,
            "cached_input_per_million": float(pricing["input_cache_read"]) * 1_000_000,
            "output_per_million": float(pricing["completion"]) * 1_000_000,
        }
        if any(
            abs(actual_prices[field] - float(model[field])) > 1e-12
            for field in actual_prices
        ):
            raise ValueError(f"catalog pricing drifted for {model_id}")
        supported = set(endpoint.get("supported_parameters", []))
        if not REQUIRED_ROUTE_PARAMETERS <= supported:
            raise ValueError(f"catalog parameter support drifted for {model_id}")
        if endpoint.get("status") != 0:
            raise ValueError(f"catalog route is not active for {model_id}")
        if (
            endpoint.get("max_completion_tokens", 0)
            < contract["controls"]["max_output_tokens"]
        ):
            raise ValueError(f"catalog completion limit is too small for {model_id}")
        endpoint_snapshot_sha256 = _endpoint_snapshot_sha256(endpoint)
        if (
            CAMPAIGN_SPECS[contract["campaign_id"]].get(
                "verify_endpoint_snapshot", False
            )
            and endpoint_snapshot_sha256 != model["endpoint_snapshot_sha256"]
        ):
            raise ValueError(f"catalog endpoint snapshot drifted for {model_id}")
        rows.append(
            {
                "model_id": model_id,
                "requested_model": model["requested_model"],
                "canonical_model": model["canonical_model"],
                "provider": model["provider"],
                "quantization": model["quantization"],
                "pricing": actual_prices,
                "required_parameters_present": True,
                "max_completion_tokens": endpoint["max_completion_tokens"],
                "status": endpoint["status"],
                "uptime_last_5m": endpoint.get("uptime_last_5m"),
                "uptime_last_30m": endpoint.get("uptime_last_30m"),
                "uptime_last_1d": endpoint.get("uptime_last_1d"),
                "endpoint_snapshot_sha256": endpoint_snapshot_sha256,
            }
        )
    return _sealed(
        {
            "schema_version": "aeread.housing_backend_catalog_preflight/0.1",
            "campaign_id": contract["campaign_id"],
            "status": "passed",
            "provider_inference_calls": 0,
            "routes": rows,
        }
    )


def _admission_observations(seed: int) -> dict[str, Mapping[str, Any]]:
    world = hz.make_bid_world(6, 4, seed, 0.6)
    market = hz.HousingMarket(world, rounds=4)
    contact = market.tenant_observation(0)
    contact_result = market.submit_offers({0: (0, world.ask[0])})
    respond = market.landlord_observation(0)
    response_result = market.submit_responses(
        hz.scripted_landlord_responses(market, contact_result.inbox)
    )
    commit = market.tenant_observation(0)
    if 0 not in response_result.holds:
        raise ValueError("admission fixture did not create the expected tenant hold")
    return {
        "housing_contact_v1": contact,
        "housing_respond_v1": respond,
        "housing_commit_v1": commit,
    }


def _profile_request(
    *,
    contract: Mapping[str, Any],
    model_id: str,
    role: str,
    action_schema: str,
    observation: Mapping[str, Any],
    probe_index: int,
) -> ProviderRequest:
    model = contract["models"][model_id]
    route = route_table(contract)[model_id]
    prompt = HOUSING_TENANT_PROMPT if role == "tenant" else HOUSING_LANDLORD_PROMPT
    if contract["controls"].get("action_schema_version") == "housing_actions/2.0":
        output_schemas = {
            "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA_V2,
            "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA_V2,
            "housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA_V2,
        }
    else:
        output_schemas = {
            "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
            "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
            "housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA,
        }
    output_schema = output_schemas[action_schema]
    phase_id = {
        "housing_contact_v1": "contact",
        "housing_commit_v1": "commit",
        "housing_respond_v1": "respond",
    }[action_schema]
    seat_id = "tenant_0" if role == "tenant" else "landlord_0"
    input_text = canonical_json_bytes(
        {
            "phase_id": phase_id,
            "seat_id": seat_id,
            "role": role,
            "observation_schema": f"housing_{role}_{phase_id}_observation_v1",
            "action_schema": action_schema,
            "observation": observation,
        }
    ).decode("utf-8")
    return ProviderRequest(
        provider_call_id=f"admission_{model_id}_{role}_{phase_id}_{probe_index}",
        provider="openrouter",
        base_url=contract["backend"]["api_base"],
        model=model["requested_model"],
        revision=model["canonical_model"],
        instructions=prompt,
        input_text=input_text,
        temperature=contract["controls"]["temperature"],
        top_p=contract["controls"]["top_p"],
        max_output_tokens=contract["controls"]["max_output_tokens"],
        reasoning_effort=contract["controls"]["reasoning_effort"],
        timeout_seconds=contract["controls"]["timeout_seconds"],
        request_sha256="",
        max_cost_usd=contract["profile_admission"]["per_probe_cost_reserve_usd"],
        output_schema=output_schema,
        provider_metadata=route.provider_metadata(),
        seed=contract["profile_admission"]["probe_seeds"][probe_index],
    ).with_computed_hash()


def _admission_specs(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for probe_index in range(contract["profile_admission"]["probes_per_action_schema"]):
        for model_id in contract["models"]:
            for role, schemas in (
                ("tenant", ("housing_contact_v1", "housing_commit_v1")),
                ("landlord", ("housing_respond_v1",)),
            ):
                for action_schema in schemas:
                    specs.append(
                        {
                            "model_id": model_id,
                            "role": role,
                            "action_schema": action_schema,
                            "probe_index": probe_index,
                        }
                    )
    return specs


def _campaign_provider_client(contract: Mapping[str, Any]) -> Any:
    client: Any = OpenRouterChatClient()
    pacing = contract["controls"].get("call_pacing")
    if pacing is None:
        return client
    clock = pacing.get("clock")
    if clock == "monotonic_start_to_start":
        module_path = Path(provider_pacing_module.__file__)
    elif clock == "monotonic_completion_to_start":
        module_path = Path(provider_cooldown_module.__file__)
    else:
        raise ValueError(f"unsupported provider pacing clock {clock!r}")
    implementation_sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
    if implementation_sha256 != pacing["implementation_sha256"]:
        raise ValueError(
            "provider pacing implementation differs from the frozen campaign pin"
        )
    if clock == "monotonic_start_to_start":
        return PacedProviderClient(
            client,
            minimum_interval_seconds_by_provider=pacing[
                "minimum_interval_seconds_by_provider"
            ],
            first_call_delay_seconds=pacing["first_call_delay_seconds"],
        )
    return CooldownProviderClient(
        client,
        cooldown_seconds_by_provider=pacing["cooldown_seconds_by_provider"],
        first_call_delay_seconds=pacing["first_call_delay_seconds"],
    )


async def _admission_complete(
    contract: Mapping[str, Any], client: Any, request: ProviderRequest
) -> Any:
    """Delegate one admission call under the same wall-time budget as execution.

    Campaigns before V13 invoked the adapter directly, so a probe could exceed
    ``controls.timeout_seconds`` without a typed failure. When the contract
    freezes ``admission_timeout_enforcement`` the call is wrapped in the same
    ``asyncio.wait_for`` budget that the shared-runner attempt loop applies.
    """

    if contract["controls"].get("admission_timeout_enforcement") is None:
        return await client.complete(request)
    try:
        return await asyncio.wait_for(
            client.complete(request), timeout=request.timeout_seconds
        )
    except asyncio.TimeoutError as error:
        raise ProviderFailure(
            "timeout",
            f"admission call exceeded {request.timeout_seconds} seconds",
            retryable=True,
        ) from error


async def run_profile_admission(
    contract: Mapping[str, Any], *, output_root: Path, provider_client: Any | None = None
) -> dict[str, Any]:
    summary_path = output_root / "summary.json"
    if summary_path.exists():
        return _read_sealed(summary_path)
    client = provider_client or _campaign_provider_client(contract)
    rows: list[dict[str, Any]] = []
    admission = contract["profile_admission"]
    for spec in _admission_specs(contract):
        result_path = (
            output_root
            / spec["model_id"]
            / spec["role"]
            / spec["action_schema"]
            / f"probe_{spec['probe_index']}.json"
        )
        if result_path.exists():
            rows.append(_read_sealed(result_path))
            continue
        attempted_upper_bound = (len(rows) + 1) * admission[
            "per_probe_cost_reserve_usd"
        ]
        if attempted_upper_bound > admission["cost_ceiling_usd"] + 1e-12:
            break
        observations = _admission_observations(73001 + spec["probe_index"])
        request = _profile_request(
            contract=contract,
            observation=observations[spec["action_schema"]],
            **spec,
        )
        started = time.perf_counter()
        pacing_observation_index = (
            client.observation_count
            if isinstance(client, (PacedProviderClient, CooldownProviderClient))
            else None
        )
        attempt_limit = int(admission["attempt_limit_per_probe"])
        retryable_conditions = (
            set(contract["controls"]["retryable_conditions"])
            if attempt_limit > 1
            else set()
        )
        attempts: list[dict[str, Any]] = []
        for ordinal in range(attempt_limit):
            attempt_started = time.perf_counter()
            result = None
            try:
                result = await _admission_complete(contract, client, request)
                raw_path = result_path.with_name(
                    f"probe_{spec['probe_index']}_raw.json"
                )
                _write_json(
                    raw_path,
                    _sealed(
                        {
                            "request_sha256": request.request_sha256,
                            "raw_response": result.raw_response,
                        }
                    ),
                )
                action = _validate_admission_action(
                    spec["action_schema"],
                    result.output_text,
                    observations[spec["action_schema"]],
                )
                if result.cost_usd is None:
                    raise ValueError("admission call omitted provider billing")
                attempts.append(
                    {
                        "attempt": ordinal + 1,
                        "status": "passed",
                        "cost_usd": result.cost_usd,
                        "billing_status": "provider_reported",
                        "elapsed_seconds": time.perf_counter() - attempt_started,
                    }
                )
                billed = [
                    attempt
                    for attempt in attempts
                    if attempt["billing_status"] == "provider_reported"
                ]
                row = {
                    **spec,
                    "status": "passed",
                    "request_sha256": request.request_sha256,
                    "response_id": result.response_id,
                    "resolved_model": result.resolved_model,
                    "action_sha256": _sha256(action),
                    "raw_response_sha256": _sha256(result.raw_response),
                    "input_tokens": result.input_tokens,
                    "cached_input_tokens": result.cached_input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_usd": sum(float(attempt["cost_usd"]) for attempt in billed),
                    "billing_status": (
                        "provider_reported"
                        if len(billed) == len(attempts)
                        else "provider_reported_with_unbilled_failed_attempts"
                    ),
                    "elapsed_seconds": time.perf_counter() - started,
                    "route_verified": True,
                    "sdk_retries": 0,
                }
                break
            except Exception as error:
                provider_completed = result is not None
                failure_condition = _exception_attribute(error, "condition")
                if provider_completed and isinstance(error, ValueError):
                    failure_condition = "invalid_admission_action"
                failure_condition = failure_condition or "execution_error"
                attempt_row = {
                    "attempt": ordinal + 1,
                    "status": "operational_failure",
                    "failure_type": type(error).__name__,
                    "failure_condition": failure_condition,
                    "failure_status_code": _exception_attribute(
                        error, "status_code"
                    ),
                    "cost_usd": result.cost_usd if provider_completed else None,
                    "billing_status": (
                        "provider_reported"
                        if provider_completed and result.cost_usd is not None
                        else "unavailable_on_failed_call"
                    ),
                    "elapsed_seconds": time.perf_counter() - attempt_started,
                }
                retry = (
                    failure_condition in retryable_conditions
                    and ordinal + 1 < attempt_limit
                )
                if retry:
                    attempt_row["retry_delay_seconds"] = 2.0 * (2**ordinal)
                attempts.append(attempt_row)
                if retry:
                    await asyncio.sleep(attempt_row["retry_delay_seconds"])
                    continue
                row = {
                    **spec,
                    "status": "operational_failure",
                    "request_sha256": request.request_sha256,
                    "failure_type": type(error).__name__,
                    "failure_condition": failure_condition,
                    "failure_status_code": _exception_attribute(error, "status_code"),
                    "raw_response_sha256": (
                        _sha256(result.raw_response) if provider_completed else None
                    ),
                    "cost_usd": result.cost_usd if provider_completed else None,
                    "billing_status": (
                        "provider_reported"
                        if provider_completed and result.cost_usd is not None
                        else "unavailable_on_failed_call"
                    ),
                    "elapsed_seconds": time.perf_counter() - started,
                    "route_verified": provider_completed,
                    "sdk_retries": 0,
                }
                break
        if attempt_limit > 1:
            row["visible_attempt_count"] = len(attempts)
            row["effective_retry_count"] = len(attempts) - 1
            row["attempts"] = attempts
        if pacing_observation_index is not None:
            row["call_pacing"] = client.pacing_summary_since(
                pacing_observation_index
            )
        sealed = _sealed(row)
        _write_json(result_path, sealed)
        rows.append(sealed)

    expected = len(_admission_specs(contract))
    passed = [row for row in rows if row["status"] == "passed"]
    failures = [row for row in rows if row["status"] != "passed"]
    actual_cost = sum(
        float(row["cost_usd"])
        for row in rows
        if isinstance(row.get("cost_usd"), (int, float))
        and not isinstance(row.get("cost_usd"), bool)
    )
    artifact = _sealed(
        {
            "schema_version": "aeread.housing_backend_profile_admission/0.1",
            "campaign_id": contract["campaign_id"],
            "status": (
                "passed" if len(passed) == expected else "failed_with_typed_missingness"
            ),
            "expected_probe_count": expected,
            "attempted_probe_count": len(rows),
            "passed_probe_count": len(passed),
            "operational_failures": len(failures),
            "not_started_probe_count": expected - len(rows),
            "hidden_retry_count": 0,
            "observed_cost_usd": actual_cost,
            "attempted_cost_upper_bound_usd": len(rows)
            * admission["per_probe_cost_reserve_usd"],
            "cost_ceiling_usd": admission["cost_ceiling_usd"],
            "provider_cost_complete": all(
                row["billing_status"] == "provider_reported" for row in rows
            ),
            "profile_sha256s": admission["profile_sha256s"],
            "rows": rows,
        }
    )
    _write_json(summary_path, artifact)
    return artifact


async def execute_campaign(
    *, contract_path: str | Path, output_root: str | Path, through: str
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    terminal_stage = CAMPAIGN_SPECS[contract["campaign_id"]].get(
        "execution_stage", "live"
    )
    stages = {"design", "provider_free", "profile_admission", terminal_stage}
    if through not in stages:
        raise ValueError(f"through must be one of {sorted(stages)}")
    routes = route_table(contract)
    root = Path(output_root)
    design = design_artifact(contract, routes=routes)
    _write_json(root / "design" / "summary.json", design)
    result: dict[str, Any] = {"design": design}
    if through in {"provider_free", "profile_admission", terminal_stage}:
        provider_free = provider_free_artifact(contract)
        catalog_path = root / "catalog_preflight" / "summary.json"
        catalog = (
            _read_sealed(catalog_path)
            if catalog_path.exists()
            else catalog_preflight(contract)
        )
        _write_json(root / "provider_free" / "summary.json", provider_free)
        _write_json(catalog_path, catalog)
        result.update(provider_free=provider_free, catalog_preflight=catalog)
    if through in {"profile_admission", terminal_stage}:
        if not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError(
                "OPENROUTER_API_KEY is required for the profile-admission stage"
            )
        provider_client = _campaign_provider_client(contract)
        admission = await run_profile_admission(
            contract,
            output_root=root / "profile_admission",
            provider_client=provider_client,
        )
        result["profile_admission"] = admission
        if through == terminal_stage:
            if admission["status"] != "passed":
                blocked = _sealed(
                    {
                        "schema_version": (
                            "aeread.housing_backend_live_block/0.1"
                            if terminal_stage == "live"
                            else "aeread.housing_full_trajectory_block/0.1"
                        ),
                        "campaign_id": contract["campaign_id"],
                        "status": "blocked_by_profile_admission",
                        "gate_id": terminal_stage,
                        "profile_admission_sha256": admission["artifact_sha256"],
                        "provider_calls": 0,
                        "cost_usd": 0.0,
                    }
                )
                _write_json(root / terminal_stage / "blocked.json", blocked)
                result[terminal_stage] = blocked
            else:
                result[terminal_stage] = await run_live(
                    contract,
                    output_root=root,
                    routes=routes,
                    stage_id=terminal_stage,
                    provider_client=provider_client,
                )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify alternate model endpoints before Housing execution"
    )
    parser.add_argument(
        "--contract",
        default="configs/housing_model_sensitivity_openrouter_alt_v2.json",
    )
    parser.add_argument(
        "--run-root",
        "--output",
        dest="run_root",
        default="runs/housing_model_sensitivity_openrouter_alt_v2",
    )
    parser.add_argument(
        "--through",
        choices=(
            "design",
            "provider_free",
            "profile_admission",
            "full_trajectory",
            "live",
        ),
        default="provider_free",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(
        execute_campaign(
            contract_path=args.contract,
            output_root=args.run_root,
            through=args.through,
        )
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
