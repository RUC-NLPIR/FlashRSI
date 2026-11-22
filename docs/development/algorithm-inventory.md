# Algorithm inventory

The [runner registry](../../flashrsi/runner.py) contains 14 methods. The resource and selection columns describe their FlashRSI implementations. Each guide documents configuration and any differences from upstream.

| Method | Editable resource | Feedback and selection | Worker |
| --- | --- | --- | --- |
| [OPRO](../opro.md) | Instruction | Rank accumulated candidates by train score and return the best. | Text proposal |
| [GEPA](../gepa.md) | Instruction | Reflect on trajectories and use per-task scores to guide candidate search. | Text proposal |
| [EvoPrompt](../evoprompt.md) | Instruction | Evolve a population with GA or DE and select using dev scores. | Text proposal |
| [ACE](../ace.md) | Prompt / playbook | Build and revise a playbook from feedback and reflections. | Text proposal |
| [SkillOpt](../skillopt.md) | Skills | Combine fast and slow updates and adopt strict dev gains. | Text proposal |
| [SkillAdam](../integrations/algorithms.md#skilladam) | One Markdown skill | Track issue history, adjust edit size using per-task score variance, and adopt strict dev gains. | Text proposal |
| [Evo-Harness](../evo-harness.md) | Native directory skills | Compile training failures into topic and general skills and retain valid updates. | File editing |
| [AHE](../ahe.md) | Harness resources | Diagnose train traces and retain valid edits for exploration; select the final dev-best version, including the seed. | File editing |
| [ADAS](../adas.md) | Harness resources | Archive measured designs and select the best dev candidate. | File editing |
| [DarwinX](../darwinx.md) | Harness resources | Screen and confirm branches, then evaluate complementary recombinations. | File editing |
| [Meta-Harness](../meta-harness.md) | Harness resources | Use historical sources, traces, and scores to propose edits and select on dev. | File editing |
| [ModularRSI](../modular-rsi.md) | Declared modules | Evolve module branches and integrate them through review and execution gates. | File editing |
| [RRSI](../rrsi.md) | Harness resources | Diagnose recurring failures and admit revisions using score and cost gates. | File editing |
| [Arbor](../arbor.md) | Harness resources | Explore a hypothesis tree and synthesize findings from measured branches. | File editing |

Text proposals use `worker.ask()` and can come from an LLM Worker or an Agent Worker. File editing requires an Agent Worker with `edit()` support. Each Target must expose the resources and runtime capabilities required by the method. See [algorithm configurations](../integrations/algorithms.md) and [harness capabilities](../integrations/harnesses.md).
