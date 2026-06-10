# Agent Prompt Template

This template defines the common execution prompt shape for baseline and Context Pack runs.

The prompt must keep the task intent, output format, Agent/model, and scorer expectations stable across both groups. The only intended difference is the context source:

- `baseline`: original files are provided directly to the Agent.
- `context_pack`: the Agent receives the generated Context Pack.

Do not include scorer-only fields in the Agent prompt:

- `gold_answer_points`
- `required_constraints`
- `expected_evidence`

Those fields are used by the scorer through `scoring-rubric.md`, not by the Agent during execution.

## Output Shape

```text
## Answer

## Evidence
| Claim | Source document | Version/scope | Page/section/span | Support |

## Gaps Or Assumptions

## Follow-up Needed
```
