# Codex Review — Audit Log Design
**Date:** 2026-03-20
**Model:** gpt-5.4
**Subject:** AI Transparency Audit Log schema and "orchestrator invisible" principle

---

**Findings**
1. The biggest weakness is accountability ambiguity. If Claude is invisible, the log shows who commented but not who decided. In a disputed change, you need a record of the decision event: who accepted, rejected, or overrode reviewer input, when, and on what basis. Without that, the audit trail is incomplete even if the final itinerary is preserved.

2. `source: null` for "orchestrator implicit" is too ambiguous for production use. `null` can mean unknown, not applicable, missing data, or intentionally omitted. In an audit schema, those must not collapse into one value. If you keep the invisibility principle, use an explicit value like `source: orchestrator_derived` or separate `proposed_by` and `approved_by`.

3. The schema tracks accepted changes better than decision history. Auditors usually need both:
   - what changed
   - what was proposed but rejected
   - what remained unresolved
   - what evidence existed at decision time
   Right now rejected alternatives and override decisions are mostly invisible.

4. `consensus` is underdefined in this model. If Claude is not an actor, "unanimous" or "majority" only refers to external reviewers, but the actual system decision still belongs to Claude. That makes consensus sound stronger than it is.

5. The current model is missing artifact integrity and version lineage. You need stable IDs, timestamps, model/version metadata, and a pointer to the exact itinerary snapshot before and after the revision. Otherwise the log is descriptive, not strongly auditable.

**Answers**
1. "Orchestrator invisible" is not fully sound for transparency. It is sound if your goal is a lightweight review log. It is not sound if your goal is auditability, accountability, or post-incident reconstruction. The right compromise is: do not log Claude as a verbose actor for every step, but do log bounded orchestrator decision records such as `decision_summary`, `accepted_inputs`, `rejected_inputs`, and `final_rationale`.

2. Per-change granularity is mostly right. It is the minimum useful level for tracing why an itinerary changed. But you also need a revision-level summary because some decisions are cross-cutting and not reducible to single field diffs. So the right model is both revision-level and per-change, not one or the other.

3. Missing fields I would add:
- `revision_id` as an immutable UUID
- `created_at` and `resolved_at` timestamps
- `reviewer_model`, `model_version`, and possibly prompt/template version
- `status` on each change: `proposed | accepted | rejected | superseded`
- `decision_by` or `decision_mode`
- `rationale_summary`
- `evidence_refs` linking findings/reviews to changes
- `itinerary_before_ref` and `itinerary_after_ref`
- `confidence` only if operationally meaningful; otherwise it becomes fake precision
- `severity` or `impact` for findings
- `supersedes_change_id` for reversals/corrections

4. The 4-table Notion mapping is reasonable, but I would question the `Findings -> Reviewer Responses` relation being the only parent. Many findings will later map to multiple changes or remain unresolved across revisions. I would prefer:
- `Revisions`
- `Reviewer Responses`
- `Changes`
- `Findings`
And add explicit relations from `Findings` to both `Reviewer Responses` and `Changes`.
If you want stronger auditability, add a fifth table: `Artifacts` or `Evidence` for raw prompts, raw responses, itinerary snapshots, hashes, and attachments.

5. `raw_response_path` is better than storing full raw text inline in the main table. Inline text becomes noisy, hard to diff, and painful in Notion. Best practice is:
- store a short normalized summary in the table
- store the full raw artifact externally
- keep a stable path/URI plus checksum/hash if possible
If the external file can disappear or be edited, the audit trail weakens.

6. Other critique:
- Your trigger model is too narrow. Not all revisions come from `user_challenge`; some come from automated review, policy checks, stale data refresh, or logistics conflicts.
- `key_points` is useful, but you also need structured dispositions: which points were accepted, rejected, or deferred.
- `findings.status` should probably include `rejected` and `resolved`.
- `action_required: true/false` is too weak for prioritization; add `severity` or `blocking`.
- The schema should distinguish between factual issues, policy/safety issues, preference conflicts, and optimization suggestions.

**Recommendation**
Keep the "orchestrator invisible" principle only at the action-log level, not at the decision-log level. In practice: no step-by-step Claude trace, but a required orchestrator decision summary per revision and per disputed change. That preserves signal over noise without sacrificing auditability.
