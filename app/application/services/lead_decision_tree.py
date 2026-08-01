from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.conversations import Handoff
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationArtifact,
    LeadStateClassificationOutcome,
)
from app.domain.workflows import LeadWorkflow, WorkflowState


class LeadDecisionTreeNodeKind(StrEnum):
    START = "start"
    PROCESS = "process"
    DECISION = "decision"
    OUTCOME = "outcome"
    STATE = "state"


class LeadDecisionTreeElementStatus(StrEnum):
    AVAILABLE = "available"
    TAKEN = "taken"
    CURRENT = "current"


@dataclass(frozen=True)
class LeadDecisionTreeNodeView:
    node_id: str
    kind: LeadDecisionTreeNodeKind
    label: str
    row: int
    column: int
    status: LeadDecisionTreeElementStatus
    description: str | None = None
    chips: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeadDecisionTreeEdgeView:
    edge_id: str
    from_node_id: str
    to_node_id: str
    status: LeadDecisionTreeElementStatus
    label: str | None = None
    description: str | None = None
    detail_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeadDecisionTreeView:
    title: str
    subtitle: str
    nodes: tuple[LeadDecisionTreeNodeView, ...]
    edges: tuple[LeadDecisionTreeEdgeView, ...]


@dataclass(frozen=True)
class PausedSearchBranchSpec:
    branch_key: str
    label: str
    edge_label: str
    column: int
    node_description: str
    edge_description: str
    chips: tuple[str, ...] = ()
    detail_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class PausedSearchTrackOptionSpec:
    track: PausedSearchTrack
    version: PausedSearchTrackVersion
    steps: tuple[PausedSearchTrackStep, ...]


def build_lead_decision_tree(
    *,
    lead: CanonicalLeadRecord,
    classification_artifact: LeadClassificationArtifact | None,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
    paused_search_track_options: tuple[PausedSearchTrackOptionSpec, ...],
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
) -> LeadDecisionTreeView:
    current_route = _current_route(lead, classification_artifact, latest_workflow, latest_handoff)

    nodes = (
        _node("known_lead", LeadDecisionTreeNodeKind.START, "Known lead", 0, 4, True, False),
        _node(
            "review_context",
            LeadDecisionTreeNodeKind.PROCESS,
            "Review + classify lead",
            1,
            4,
            True,
            False,
            description=(
                "Use lead facts, recent messages, and trusted product state before "
                "choosing a route."
            ),
        ),
        _node(
            "route_decision",
            LeadDecisionTreeNodeKind.DECISION,
            "Choose nurture route",
            2,
            4,
            True,
            current_route is None,
            description=(
                "The backend decides whether this lead belongs in paused-search, "
                "dormant nurture, review hold, handoff, or a blocked path."
            ),
        ),
        _route_node("dormant", "Dormant nurture", 3, 0, current_route == "dormant"),
        _route_node("review_hold", "Review hold", 3, 2, current_route == "review_hold"),
        _route_node("human_handoff", "Human handoff", 3, 4, current_route == "human_handoff"),
        _route_node("blocked", "Blocked", 3, 6, current_route == "blocked"),
        _route_node("paused_search", "Paused-search", 3, 8, current_route == "paused_search"),
    )

    edges = (
        _edge(
            "known_lead",
            "review_context",
            True,
            False,
            description=(
                "This lead is already known to the workspace, so it enters workflow "
                "review before any route is chosen."
            ),
        ),
        _edge(
            "review_context",
            "route_decision",
            True,
            current_route is None,
            description=(
                "The backend compares classification, workflow state, handoff status, "
                "suppression, and paused-search state before choosing a route."
            ),
            detail_lines=_review_context_detail_lines(
                classification_artifact,
                latest_workflow,
                latest_handoff,
            ),
        ),
        _route_edge(
            "dormant",
            current_route,
            lead,
            classification_artifact,
            latest_workflow,
            latest_handoff,
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        ),
        _route_edge(
            "review_hold",
            current_route,
            lead,
            classification_artifact,
            latest_workflow,
            latest_handoff,
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        ),
        _route_edge(
            "human_handoff",
            current_route,
            lead,
            classification_artifact,
            latest_workflow,
            latest_handoff,
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        ),
        _route_edge(
            "blocked",
            current_route,
            lead,
            classification_artifact,
            latest_workflow,
            latest_handoff,
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        ),
        _route_edge(
            "paused_search",
            current_route,
            lead,
            classification_artifact,
            latest_workflow,
            latest_handoff,
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        ),
    )

    extra_nodes: tuple[LeadDecisionTreeNodeView, ...] = ()
    extra_edges: tuple[LeadDecisionTreeEdgeView, ...] = ()
    if current_route == "paused_search" and latest_workflow is not None:
        extra_nodes, extra_edges = _build_paused_search_subtree(
            lead=lead,
            paused_search_track=paused_search_track,
            paused_search_track_version=paused_search_track_version,
            paused_search_steps=paused_search_steps,
            paused_search_current_step=paused_search_current_step,
            paused_search_track_options=paused_search_track_options,
            latest_workflow=latest_workflow,
        )
    elif current_route == "dormant" and latest_workflow is not None:
        dormant_state_node = LeadDecisionTreeNodeView(
            node_id="dormant_state",
            kind=LeadDecisionTreeNodeKind.STATE,
            label=_workflow_label(latest_workflow.state, paused_search=False),
            row=4,
            column=0,
            status=LeadDecisionTreeElementStatus.CURRENT,
        )
        dormant_state_edge = _edge(
            "dormant",
            "dormant_state",
            True,
            True,
            description="This lead is currently inside the dormant nurture workflow.",
            detail_lines=_workflow_state_detail_lines(latest_workflow),
        )
        extra_nodes = (dormant_state_node,)
        extra_edges = (dormant_state_edge,)

    return LeadDecisionTreeView(
        title="Decision flowchart",
        subtitle=(
            "The backend defines the full routing tree. The selected path is "
            "highlighted and the current step is shown below the chosen route."
        ),
        nodes=nodes + extra_nodes,
        edges=edges + extra_edges,
    )


def _current_route(
    lead: CanonicalLeadRecord,
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
) -> str | None:
    if lead.do_not_contact or (
        latest_workflow and latest_workflow.state == WorkflowState.SUPPRESSED
    ):
        return "blocked"
    if latest_workflow and latest_workflow.state in {
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
    }:
        return "human_handoff"
    if (
        classification_artifact
        and classification_artifact.outcome == LeadStateClassificationOutcome.BLOCKED
    ):
        return "blocked"
    if (
        (latest_workflow is not None and latest_workflow.paused_search_track_version_id is not None)
        or lead.paused_search_active
        or (
            classification_artifact
            and classification_artifact.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH
        )
    ):
        return "paused_search"
    if latest_handoff is not None or (
        classification_artifact
        and classification_artifact.outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF
    ):
        return "human_handoff"
    if (
        classification_artifact
        and classification_artifact.outcome == LeadStateClassificationOutcome.REVIEW_HOLD
    ):
        return "review_hold"
    if latest_workflow is not None or (
        classification_artifact
        and classification_artifact.outcome == LeadStateClassificationOutcome.DORMANT
    ):
        return "dormant"
    return None


def _node(
    node_id: str,
    kind: LeadDecisionTreeNodeKind,
    label: str,
    row: int,
    column: int,
    taken: bool,
    current: bool,
    description: str | None = None,
    chips: tuple[str, ...] = (),
) -> LeadDecisionTreeNodeView:
    return LeadDecisionTreeNodeView(
        node_id=node_id,
        kind=kind,
        label=label,
        row=row,
        column=column,
        status=(
            LeadDecisionTreeElementStatus.CURRENT
            if current
            else (
                LeadDecisionTreeElementStatus.TAKEN
                if taken
                else LeadDecisionTreeElementStatus.AVAILABLE
            )
        ),
        description=description,
        chips=chips,
    )


def _route_node(
    node_id: str, label: str, row: int, column: int, current: bool
) -> LeadDecisionTreeNodeView:
    return _node(node_id, LeadDecisionTreeNodeKind.OUTCOME, label, row, column, current, current)


def _build_paused_search_subtree(
    *,
    lead: CanonicalLeadRecord,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
    paused_search_track_options: tuple[PausedSearchTrackOptionSpec, ...],
    latest_workflow: LeadWorkflow,
) -> tuple[tuple[LeadDecisionTreeNodeView, ...], tuple[LeadDecisionTreeEdgeView, ...]]:
    track_options = _normalized_paused_search_track_options(
        paused_search_track,
        paused_search_track_version,
        paused_search_steps,
        paused_search_track_options,
    )
    if track_options:
        return _build_paused_search_track_subtree(
            lead=lead,
            paused_search_track=paused_search_track,
            paused_search_track_version=paused_search_track_version,
            paused_search_steps=paused_search_steps,
            paused_search_current_step=paused_search_current_step,
            paused_search_track_options=track_options,
            latest_workflow=latest_workflow,
        )

    return _build_paused_search_phase_subtree(
        lead=lead,
        paused_search_track=paused_search_track,
        paused_search_track_version=paused_search_track_version,
        paused_search_steps=paused_search_steps,
        paused_search_current_step=paused_search_current_step,
        latest_workflow=latest_workflow,
        root_node_id="paused_search",
        decision_row=4,
        branch_row=5,
        state_row=6,
        center_column=8,
    )


def _build_paused_search_track_subtree(
    *,
    lead: CanonicalLeadRecord,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
    paused_search_track_options: tuple[PausedSearchTrackOptionSpec, ...],
    latest_workflow: LeadWorkflow,
) -> tuple[tuple[LeadDecisionTreeNodeView, ...], tuple[LeadDecisionTreeEdgeView, ...]]:
    track_columns = _paused_search_track_columns(len(paused_search_track_options))
    selected_track_version_id = (
        paused_search_track_version.track_version_id
        if paused_search_track_version is not None
        else None
    )
    selected_option = next(
        (
            option
            for option in paused_search_track_options
            if option.version.track_version_id == selected_track_version_id
        ),
        paused_search_track_options[0],
    )
    selected_column = track_columns[paused_search_track_options.index(selected_option)]

    nodes: list[LeadDecisionTreeNodeView] = [
        _node(
            "paused_search_track_decision",
            LeadDecisionTreeNodeKind.DECISION,
            "Choose paused-search track",
            4,
            8,
            True,
            False,
            description=(
                "The backend shows the active admin-configured paused-search tracks "
                "before expanding the track pinned to this workflow."
            ),
        )
    ]
    edges: list[LeadDecisionTreeEdgeView] = [
        _edge(
            "paused_search",
            "paused_search_track_decision",
            True,
            False,
            description=(
                "Paused-search is active, so the backend first identifies which "
                "configured track is pinned to the lead workflow."
            ),
            detail_lines=_paused_search_track_catalog_detail_lines(
                paused_search_track_options,
                selected_option,
            ),
        )
    ]

    for index, option in enumerate(paused_search_track_options):
        selected = option.version.track_version_id == selected_option.version.track_version_id
        track_node_id = _paused_search_track_node_id(option)
        nodes.append(
            _node(
                track_node_id,
                LeadDecisionTreeNodeKind.OUTCOME,
                option.track.display_name,
                5,
                track_columns[index],
                selected,
                False,
                description=_paused_search_track_node_description(option, selected),
                chips=_paused_search_track_option_chips(lead, option),
            )
        )
        edges.append(
            _edge(
                "paused_search_track_decision",
                track_node_id,
                selected,
                False,
                option.track.display_name,
                description=_paused_search_track_edge_description(option, selected),
                detail_lines=_paused_search_track_option_detail_lines(lead, option),
            )
        )

    phase_nodes, phase_edges = _build_paused_search_phase_subtree(
        lead=lead,
        paused_search_track=paused_search_track,
        paused_search_track_version=paused_search_track_version,
        paused_search_steps=paused_search_steps,
        paused_search_current_step=paused_search_current_step,
        latest_workflow=latest_workflow,
        root_node_id=_paused_search_track_node_id(selected_option),
        decision_row=6,
        branch_row=7,
        state_row=8,
        center_column=selected_column,
    )
    nodes.extend(phase_nodes)
    edges.extend(phase_edges)
    return tuple(nodes), tuple(edges)


def _build_paused_search_phase_subtree(
    *,
    lead: CanonicalLeadRecord,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
    latest_workflow: LeadWorkflow,
    root_node_id: str,
    decision_row: int,
    branch_row: int,
    state_row: int,
    center_column: int,
) -> tuple[tuple[LeadDecisionTreeNodeView, ...], tuple[LeadDecisionTreeEdgeView, ...]]:
    branch_specs = _paused_search_branch_specs(
        paused_search_track_version,
        paused_search_steps,
        center_column,
    )
    if not branch_specs:
        state_node = LeadDecisionTreeNodeView(
            node_id="paused_search_state",
            kind=LeadDecisionTreeNodeKind.STATE,
            label=_workflow_label(latest_workflow.state, paused_search=True),
            row=decision_row,
            column=center_column,
            status=LeadDecisionTreeElementStatus.CURRENT,
            chips=_paused_search_chips(
                lead,
                paused_search_track,
                paused_search_track_version,
                paused_search_current_step,
                latest_workflow,
            ),
        )
        state_edge = _edge(
            root_node_id,
            "paused_search_state",
            True,
            True,
            description=_paused_search_state_description(latest_workflow),
            detail_lines=_paused_search_state_detail_lines(
                paused_search_track,
                paused_search_track_version,
                paused_search_steps,
                paused_search_current_step,
                latest_workflow,
            ),
        )
        return (state_node,), (state_edge,)

    selected_branch_key = _current_paused_search_branch_key(
        paused_search_track_version,
        paused_search_steps,
        paused_search_current_step,
    )
    available_branch_keys = {spec.branch_key for spec in branch_specs}
    if selected_branch_key not in available_branch_keys:
        selected_branch_key = branch_specs[0].branch_key
    path_decision_node = _node(
        "paused_search_path_decision",
        LeadDecisionTreeNodeKind.DECISION,
        "Choose phase within track",
        decision_row,
        center_column,
        True,
        False,
        description=(
            "The selected paused-search track chooses an internal phase based on "
            "timing windows, available steps, and fallback rules."
        ),
    )

    nodes: list[LeadDecisionTreeNodeView] = [path_decision_node]
    edges: list[LeadDecisionTreeEdgeView] = [
        _edge(
            root_node_id,
            "paused_search_path_decision",
            True,
            False,
            description=(
                "The selected track is pinned to this workflow, so the backend now "
                "resolves which internal phase should run."
            ),
            detail_lines=_paused_search_route_detail_lines(
                paused_search_track,
                paused_search_track_version,
                paused_search_steps,
                paused_search_current_step,
            ),
        )
    ]

    selected_column = center_column
    for spec in branch_specs:
        selected = spec.branch_key == selected_branch_key
        if selected:
            selected_column = spec.column
        branch_node_id = _paused_search_branch_node_id(spec.branch_key)
        nodes.append(
            _node(
                branch_node_id,
                LeadDecisionTreeNodeKind.OUTCOME,
                spec.label,
                branch_row,
                spec.column,
                selected,
                False,
                description=spec.node_description,
                chips=spec.chips,
            )
        )
        edges.append(
            _edge(
                "paused_search_path_decision",
                branch_node_id,
                selected,
                False,
                spec.edge_label,
                description=spec.edge_description,
                detail_lines=spec.detail_lines,
            )
        )

    selected_branch_node_id = _paused_search_branch_node_id(selected_branch_key)
    nodes.append(
        LeadDecisionTreeNodeView(
            node_id="paused_search_state",
            kind=LeadDecisionTreeNodeKind.STATE,
            label=_workflow_label(latest_workflow.state, paused_search=True),
            row=state_row,
            column=selected_column,
            status=LeadDecisionTreeElementStatus.CURRENT,
            chips=_paused_search_chips(
                lead,
                paused_search_track,
                paused_search_track_version,
                paused_search_current_step,
                latest_workflow,
            ),
        )
    )
    edges.append(
        _edge(
            selected_branch_node_id,
            "paused_search_state",
            True,
            True,
            description=_paused_search_state_description(latest_workflow),
            detail_lines=_paused_search_state_detail_lines(
                paused_search_track,
                paused_search_track_version,
                paused_search_steps,
                paused_search_current_step,
                latest_workflow,
            ),
        )
    )
    return tuple(nodes), tuple(edges)


def _normalized_paused_search_track_options(
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_track_options: tuple[PausedSearchTrackOptionSpec, ...],
) -> tuple[PausedSearchTrackOptionSpec, ...]:
    options_by_version_id = {
        option.version.track_version_id: option for option in paused_search_track_options
    }
    if (
        paused_search_track is not None
        and paused_search_track_version is not None
        and paused_search_track_version.track_version_id not in options_by_version_id
    ):
        options_by_version_id[paused_search_track_version.track_version_id] = (
            PausedSearchTrackOptionSpec(
                track=paused_search_track,
                version=paused_search_track_version,
                steps=paused_search_steps,
            )
        )
    return tuple(
        sorted(
            options_by_version_id.values(),
            key=lambda option: option.track.display_name.lower(),
        )
    )


def _paused_search_track_columns(count: int) -> tuple[int, ...]:
    if count <= 1:
        return (8,)
    start_column = 8 - count + 1
    return tuple(start_column + index * 2 for index in range(count))


def _paused_search_track_node_id(option: PausedSearchTrackOptionSpec) -> str:
    return f"paused_search_track_{str(option.track.track_id).replace('-', '')}"


def _paused_search_track_catalog_detail_lines(
    options: tuple[PausedSearchTrackOptionSpec, ...],
    selected_option: PausedSearchTrackOptionSpec,
) -> tuple[str, ...]:
    return (
        f"Configured active tracks shown: {len(options)}.",
        f"Selected track: {selected_option.track.display_name} "
        f"v{selected_option.version.version_number}.",
    )


def _paused_search_track_node_description(
    option: PausedSearchTrackOptionSpec,
    selected: bool,
) -> str:
    if selected:
        return "This admin-configured paused-search track is pinned to the lead's latest workflow."
    return "This is another active paused-search track configured by admins for the workspace."


def _paused_search_track_edge_description(
    option: PausedSearchTrackOptionSpec,
    selected: bool,
) -> str:
    if selected:
        return (
            f"The workflow selected {option.track.display_name} as this lead's paused-search track."
        )
    return (
        f"{option.track.display_name} exists as an active admin-created "
        "paused-search track, but it is not pinned to this lead."
    )


def _paused_search_track_option_chips(
    lead: CanonicalLeadRecord,
    option: PausedSearchTrackOptionSpec,
) -> tuple[str, ...]:
    chips = [f"Track v{option.version.version_number}"]
    if lead.pause_reason_code in option.version.default_for_reason_codes:
        chips.append("Mapped reason")
    chips.append(option.version.track_family.value.replace("_", " ").title())
    return tuple(chips)


def _paused_search_track_option_detail_lines(
    lead: CanonicalLeadRecord,
    option: PausedSearchTrackOptionSpec,
) -> tuple[str, ...]:
    lines = [
        f"Track key: {option.track.track_key}.",
        f"Version: v{option.version.version_number}.",
        f"Planned touches: {len(option.steps)}.",
    ]
    if lead.pause_reason_code in option.version.default_for_reason_codes:
        lines.append(f"Mapped to this lead's pause reason: {lead.pause_reason_code.value}.")
    return tuple(lines)


def _paused_search_branch_specs(
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    center_column: int,
) -> tuple[PausedSearchBranchSpec, ...]:
    phases = tuple(
        phase
        for phase in (
            PausedSearchTrackStepPhase.MAINTENANCE,
            PausedSearchTrackStepPhase.REACTIVATION,
        )
        if any(step.phase == phase for step in paused_search_steps)
    )
    include_review_fallback = (
        paused_search_track_version is not None
        and paused_search_track_version.fallback_timing_policy
        == PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW
    )
    columns = _paused_search_branch_columns(
        len(phases) + (1 if include_review_fallback else 0),
        center_column,
    )
    specs: list[PausedSearchBranchSpec] = []
    column_index = 0

    for phase in phases:
        phase_steps = tuple(
            sorted(
                (step for step in paused_search_steps if step.phase == phase),
                key=lambda step: step.step_order,
            )
        )
        if phase == PausedSearchTrackStepPhase.MAINTENANCE:
            specs.append(
                PausedSearchBranchSpec(
                    branch_key="maintenance",
                    label="Maintenance path",
                    edge_label="Maintenance",
                    column=columns[column_index],
                    node_description=(
                        "Use maintenance touches while the lead is still in a "
                        "longer waiting period."
                    ),
                    edge_description=(
                        "The maintenance path keeps light check-ins running until "
                        "the lead gets closer to reactivation timing."
                    ),
                    chips=(
                        f"{len(phase_steps)} planned touch{'es' if len(phase_steps) != 1 else ''}",
                    ),
                    detail_lines=_paused_search_phase_detail_lines(phase_steps),
                )
            )
        else:
            specs.append(
                PausedSearchBranchSpec(
                    branch_key="reactivation",
                    label="Reactivation path",
                    edge_label="Reactivation",
                    column=columns[column_index],
                    node_description=(
                        "Use reactivation touches when the lead is inside the "
                        "configured re-engagement window."
                    ),
                    edge_description=(
                        "The reactivation path resumes outreach as the lead "
                        "approaches the allowed re-engagement window."
                    ),
                    chips=(
                        f"{len(phase_steps)} planned touch{'es' if len(phase_steps) != 1 else ''}",
                    ),
                    detail_lines=_paused_search_phase_detail_lines(phase_steps),
                )
            )
        column_index += 1

    if include_review_fallback:
        specs.append(
            PausedSearchBranchSpec(
                branch_key="review",
                label="Review fallback",
                edge_label="Review",
                column=columns[column_index],
                node_description=(
                    "Fall back to human review when the track cannot resolve a valid timed step."
                ),
                edge_description=(
                    "This fallback path prevents automated sends when paused-search "
                    "timing does not resolve cleanly."
                ),
                chips=("Operator review fallback",),
                detail_lines=(
                    "Used when no paused-search step can be scheduled safely from "
                    "the current timing context.",
                ),
            )
        )

    return tuple(specs)


def _paused_search_phase_detail_lines(
    phase_steps: tuple[PausedSearchTrackStep, ...],
) -> tuple[str, ...]:
    return tuple(f"Step {step.step_order}: {step.message_goal}" for step in phase_steps[:3])


def _paused_search_branch_columns(count: int, center_column: int) -> tuple[int, ...]:
    if count <= 1:
        return (center_column,)
    if count == 2:
        return (center_column - 1, center_column + 1)
    return (center_column - 2, center_column, center_column + 2)


def _current_paused_search_branch_key(
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
) -> str:
    if paused_search_current_step is not None:
        return paused_search_current_step.phase.value
    if len({step.phase for step in paused_search_steps}) == 1 and paused_search_steps:
        return paused_search_steps[0].phase.value
    if (
        paused_search_track_version is not None
        and paused_search_track_version.fallback_timing_policy
        == PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW
    ):
        return "review"
    return "maintenance"


def _paused_search_branch_node_id(branch_key: str) -> str:
    return f"paused_search_{branch_key}_path"


def _route_edge(
    route_node_id: str,
    current_route: str | None,
    lead: CanonicalLeadRecord,
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
) -> LeadDecisionTreeEdgeView:
    description, detail_lines = _route_edge_details(
        route_node_id,
        current_route,
        lead,
        classification_artifact,
        latest_workflow,
        latest_handoff,
        paused_search_track,
        paused_search_track_version,
        paused_search_steps,
        paused_search_current_step,
    )
    return LeadDecisionTreeEdgeView(
        edge_id=f"route_decision->{route_node_id}",
        from_node_id="route_decision",
        to_node_id=route_node_id,
        status=(
            LeadDecisionTreeElementStatus.CURRENT
            if current_route == route_node_id
            else LeadDecisionTreeElementStatus.AVAILABLE
        ),
        label=_route_branch_label(route_node_id),
        description=description,
        detail_lines=detail_lines,
    )


def _route_edge_details(
    route_node_id: str,
    current_route: str | None,
    lead: CanonicalLeadRecord,
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
) -> tuple[str, tuple[str, ...]]:
    chosen = current_route == route_node_id
    trace_lines = _classification_trace_detail_lines(route_node_id, classification_artifact)
    base_lines = tuple(
        line
        for line in (
            _current_route_detail_line(current_route),
            _route_generic_detail_line(route_node_id),
        )
        if line is not None
    )

    if route_node_id == "dormant":
        description = (
            (
                _classification_route_description(route_node_id, classification_artifact)
                or (
                    "This lead followed dormant nurture because no higher-priority "
                    "blocked, human, paused-search, or review-hold path overrode it."
                )
            )
            if chosen
            else (
                "This lead did not take dormant nurture. Dormant nurture is the "
                "standard AI follow-up path for leads ready for re-engagement."
            )
        )
        return description, base_lines + trace_lines

    if route_node_id == "review_hold":
        description = (
            (
                _classification_route_description(route_node_id, classification_artifact)
                or (
                    "This lead is on review hold, so automated nurture should stay "
                    "stopped until an operator resolves the issue."
                )
            )
            if chosen
            else (
                "This lead did not go to review hold. Review hold is used when a "
                "human should inspect the situation before automation continues."
            )
        )
        return description, base_lines + trace_lines

    if route_node_id == "human_handoff":
        description = (
            _human_route_chosen_reason(classification_artifact, latest_workflow, latest_handoff)
            if chosen
            else (
                "This lead did not take the human handoff route. Human handoff is "
                "used when AI must yield to a person."
            )
        )
        return description, base_lines + trace_lines

    if route_node_id == "blocked":
        description = (
            _blocked_route_chosen_reason(lead, latest_workflow)
            if chosen
            else (
                "This lead was not blocked. Blocked routes are used when "
                "suppression or do-not-contact rules stop automated outreach."
            )
        )
        return description, base_lines + trace_lines

    if route_node_id == "paused_search":
        paused_search_lines = _paused_search_route_detail_lines(
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        )
        description = (
            _paused_search_chosen_reason(lead, classification_artifact, latest_workflow)
            if chosen
            else (
                "This lead did not take paused-search. Paused-search is used when "
                "the lead should rest until a planned re-engagement window or "
                "maintenance cadence applies."
            )
        )
        return description, base_lines + trace_lines + paused_search_lines

    description = (
        "This lead is on a blocked or special route chosen by backend workflow rules."
        if chosen
        else "This branch was not chosen for this lead."
    )
    return description, base_lines


def _review_context_detail_lines(
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
) -> tuple[str, ...]:
    lines: list[str] = []
    if classification_artifact is not None:
        lines.append(
            "Latest classification outcome: "
            f"{classification_artifact.outcome.value.replace('_', ' ')}."
        )
    if latest_workflow is not None:
        lines.append(f"Latest workflow state: {latest_workflow.state.value.replace('_', ' ')}.")
    if latest_handoff is not None:
        lines.append("A handoff record exists for this lead and influences route selection.")
    return tuple(lines)


def _route_branch_label(route_node_id: str) -> str:
    if route_node_id == "review_hold":
        return "Hold"
    if route_node_id == "human_handoff":
        return "Human"
    if route_node_id == "paused_search":
        return "Paused-search"
    return route_node_id.replace("_", " ").title()


def _current_route_detail_line(current_route: str | None) -> str | None:
    if current_route is None:
        return "This lead has not been routed to a final nurture branch yet."
    return f"This lead currently follows the {_route_display_name(current_route)} branch."


def _route_generic_detail_line(route_node_id: str) -> str:
    if route_node_id == "dormant":
        return (
            "Dormant nurture is the standard AI follow-up path once the lead is "
            "eligible for outreach."
        )
    if route_node_id == "review_hold":
        return (
            "Review hold keeps the lead out of automation until an operator resolves the blocker."
        )
    if route_node_id == "human_handoff":
        return "Human handoff pauses AI and transfers the next move to a person."
    if route_node_id == "blocked":
        return (
            "Blocked means suppression, do-not-contact, or a similar hard rule "
            "prevents automated outreach."
        )
    if route_node_id == "paused_search":
        return (
            "Paused-search keeps the lead on a structured wait-and-reengage path "
            "instead of immediate nurture."
        )
    return "This branch exists in the workflow routing tree."


def _route_display_name(route_node_id: str) -> str:
    return {
        "dormant": "Dormant nurture",
        "review_hold": "Review hold",
        "human_handoff": "Human handoff",
        "blocked": "Blocked",
        "paused_search": "Paused-search",
    }.get(route_node_id, route_node_id.replace("_", " ").title())


def _classification_route_description(
    route_node_id: str,
    classification_artifact: LeadClassificationArtifact | None,
) -> str | None:
    if classification_artifact is None:
        return None
    expected_outcome = _route_classification_outcome(route_node_id)
    if expected_outcome is None or classification_artifact.outcome != expected_outcome:
        return None

    confidence_text = (
        f" at {round(classification_artifact.confidence * 100)}% confidence"
        if classification_artifact.confidence > 0
        else ""
    )
    return (
        f"This lead follows the {_route_display_name(route_node_id)} branch because the "
        f"latest classifier returned {classification_artifact.outcome.value}{confidence_text}."
    )


def _route_classification_outcome(
    route_node_id: str,
) -> LeadStateClassificationOutcome | None:
    return {
        "dormant": LeadStateClassificationOutcome.DORMANT,
        "review_hold": LeadStateClassificationOutcome.REVIEW_HOLD,
        "human_handoff": LeadStateClassificationOutcome.HUMAN_HANDOFF,
        "blocked": LeadStateClassificationOutcome.BLOCKED,
        "paused_search": LeadStateClassificationOutcome.PAUSED_SEARCH,
    }.get(route_node_id)


def _classification_trace_detail_lines(
    route_node_id: str,
    classification_artifact: LeadClassificationArtifact | None,
) -> tuple[str, ...]:
    expected_outcome = _route_classification_outcome(route_node_id)
    if (
        classification_artifact is None
        or expected_outcome is None
        or classification_artifact.outcome != expected_outcome
    ):
        return ()

    lines: list[str] = []
    if classification_artifact.summary:
        lines.append(f"Classifier summary: {classification_artifact.summary}")
    if classification_artifact.evidence:
        for evidence in classification_artifact.evidence[:2]:
            lines.append(f"Evidence: {evidence}")

    conversation_summary = classification_artifact.input_context.get("conversation_summary")
    if isinstance(conversation_summary, str) and conversation_summary:
        lines.append(f"LLM input summary: {conversation_summary}")

    recent_messages = classification_artifact.input_context.get("recent_messages")
    if isinstance(recent_messages, list):
        lines.append(
            f"LLM input included {len(recent_messages)} recent CRM message"
            f"{'s' if len(recent_messages) != 1 else ''}."
        )
        latest_message = next(
            (
                item.get("content")
                for item in recent_messages
                if isinstance(item, dict)
                and isinstance(item.get("content"), str)
                and item.get("content")
            ),
            None,
        )
        if isinstance(latest_message, str):
            lines.append(f"Latest input message: {latest_message}")

    if classification_artifact.parsed_llm_response:
        lines.append(
            "LLM output: "
            + json.dumps(dict(classification_artifact.parsed_llm_response), sort_keys=True)
        )
    elif classification_artifact.raw_llm_response_text:
        lines.append(f"Raw model output: {classification_artifact.raw_llm_response_text}")

    return tuple(lines)


def _blocked_route_chosen_reason(
    lead: CanonicalLeadRecord,
    latest_workflow: LeadWorkflow | None,
) -> str:
    if lead.do_not_contact:
        return "This lead is blocked because do-not-contact is set on the lead record."
    if latest_workflow is not None and latest_workflow.state == WorkflowState.SUPPRESSED:
        return "This lead is blocked because the latest workflow is suppressed."
    return "This lead is blocked by a backend suppression or compliance rule."


def _human_route_chosen_reason(
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
    latest_handoff: Handoff | None,
) -> str:
    if latest_workflow is not None and latest_workflow.state in {
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
    }:
        return (
            "This lead followed the human route because the workflow is already "
            "in human handoff or human-owned state."
        )
    if latest_handoff is not None:
        return (
            "This lead followed the human route because a handoff record already "
            "exists for the lead."
        )
    if (
        classification_artifact is not None
        and classification_artifact.outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF
    ):
        return (
            "This lead followed the human route because the latest classification "
            "required human handoff."
        )
    return "This lead followed the human route because backend rules required human ownership."


def _paused_search_chosen_reason(
    lead: CanonicalLeadRecord,
    classification_artifact: LeadClassificationArtifact | None,
    latest_workflow: LeadWorkflow | None,
) -> str:
    if latest_workflow is not None and latest_workflow.paused_search_track_version_id is not None:
        return (
            "This lead followed paused-search because the latest workflow is "
            "pinned to a paused-search track version."
        )
    if lead.paused_search_active:
        return (
            "This lead followed paused-search because the lead record is marked "
            "as actively paused-search."
        )
    if (
        classification_artifact is not None
        and classification_artifact.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH
    ):
        return (
            "This lead followed paused-search because the latest classification "
            "explicitly routed it to paused-search."
        )
    return (
        "This lead followed paused-search because backend routing treated it as "
        "a wait-and-reengage lead."
    )


def _paused_search_route_detail_lines(
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
) -> tuple[str, ...]:
    lines: list[str] = []
    if paused_search_track is not None and paused_search_track_version is not None:
        lines.append(
            f"Pinned track: {paused_search_track.display_name} "
            f"v{paused_search_track_version.version_number}."
        )
    phases = _phase_labels(paused_search_steps)
    if phases:
        lines.append(f"Possible paused-search phases on this track: {', '.join(phases)}.")
    if paused_search_current_step is not None:
        lines.append(f"Current planned step: {paused_search_current_step.message_goal}")
    if paused_search_track_version is not None:
        lines.extend(_paused_search_fallback_lines(paused_search_track_version))
    return tuple(lines)


def _paused_search_state_description(latest_workflow: LeadWorkflow) -> str:
    if latest_workflow.state == WorkflowState.QUEUED:
        return (
            "The lead is queued on the paused-search track and is waiting for "
            "the next allowed send window."
        )
    if latest_workflow.state == WorkflowState.WAITING_FOR_RESPONSE:
        return (
            "A paused-search touch has already gone out and the workflow is "
            "waiting for the lead to respond."
        )
    if latest_workflow.state == WorkflowState.ACTIVE_NURTURE:
        return "The paused-search track is actively working the current nurture step."
    if latest_workflow.state == WorkflowState.PAUSED:
        return (
            "The paused-search workflow is manually paused and will not continue "
            "until a user resumes it."
        )
    return "This is the workflow state currently active under the paused-search route."


def _paused_search_state_detail_lines(
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_steps: tuple[PausedSearchTrackStep, ...],
    paused_search_current_step: PausedSearchTrackStep | None,
    latest_workflow: LeadWorkflow,
) -> tuple[str, ...]:
    lines = list(_workflow_state_detail_lines(latest_workflow))
    lines.extend(
        _paused_search_route_detail_lines(
            paused_search_track,
            paused_search_track_version,
            paused_search_steps,
            paused_search_current_step,
        )
    )
    return tuple(lines)


def _workflow_state_detail_lines(latest_workflow: LeadWorkflow) -> tuple[str, ...]:
    lines: list[str] = [f"Workflow state: {latest_workflow.state.value.replace('_', ' ')}."]
    if latest_workflow.next_action_at is not None:
        lines.append(f"Next planned action: {latest_workflow.next_action_at.isoformat()}.")
    return tuple(lines)


def _phase_labels(paused_search_steps: tuple[PausedSearchTrackStep, ...]) -> tuple[str, ...]:
    labels: list[str] = []
    for phase in (
        PausedSearchTrackStepPhase.MAINTENANCE,
        PausedSearchTrackStepPhase.REACTIVATION,
    ):
        if any(step.phase == phase for step in paused_search_steps):
            labels.append(phase.value.replace("_", " ").title())
    return tuple(labels)


def _paused_search_fallback_lines(
    paused_search_track_version: PausedSearchTrackVersion,
) -> tuple[str, ...]:
    if (
        paused_search_track_version.fallback_timing_policy
        == PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW
    ):
        return (
            "If timing does not resolve to a valid step, this track falls back to operator review.",
        )
    if (
        paused_search_track_version.fallback_timing_policy
        == PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE
    ):
        return (
            "If a re-engagement date exists, the track can move from maintenance "
            "into reactivation as that window approaches.",
        )
    return (
        "If no re-engagement date is available, this track can continue on its "
        "maintenance cadence.",
    )


def _edge(
    from_node_id: str,
    to_node_id: str,
    taken: bool,
    current: bool,
    label: str | None = None,
    description: str | None = None,
    detail_lines: tuple[str, ...] = (),
) -> LeadDecisionTreeEdgeView:
    return LeadDecisionTreeEdgeView(
        edge_id=f"{from_node_id}->{to_node_id}",
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        status=(
            LeadDecisionTreeElementStatus.CURRENT
            if current
            else (
                LeadDecisionTreeElementStatus.TAKEN
                if taken
                else LeadDecisionTreeElementStatus.AVAILABLE
            )
        ),
        label=label,
        description=description,
        detail_lines=detail_lines,
    )


def _workflow_label(state: WorkflowState, *, paused_search: bool) -> str:
    if paused_search and state == WorkflowState.ACTIVE_NURTURE:
        return "Paused-search track active"
    return state.value.replace("_", " ").title()


def _paused_search_chips(
    lead: CanonicalLeadRecord,
    paused_search_track: PausedSearchTrack | None,
    paused_search_track_version: PausedSearchTrackVersion | None,
    paused_search_current_step: PausedSearchTrackStep | None,
    latest_workflow: LeadWorkflow,
) -> tuple[str, ...]:
    chips: list[str] = []
    if lead.pause_reason_code is not None:
        chips.append(lead.pause_reason_code.value.replace("_", " ").title())
    if lead.reengagement_window_label:
        chips.append(lead.reengagement_window_label)
    if paused_search_track is not None:
        chips.append(paused_search_track.display_name)
    if paused_search_track_version is not None:
        chips.append(f"Track v{paused_search_track_version.version_number}")
    if paused_search_current_step is not None:
        chips.append(paused_search_current_step.phase.value.replace("_", " ").title())
    if latest_workflow.next_action_at is not None:
        chips.append(f"Next action {latest_workflow.next_action_at.isoformat()}")
    return tuple(chips)
