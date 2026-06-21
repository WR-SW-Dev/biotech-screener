# Review-Only Agent Policy

Review agents are read-only by default.

They may:

- inspect code, artifacts, tests, and CI logs
- run read-only static analysis
- summarize risks and missing tests
- propose patches in prose

They must not:

- edit files
- stage or commit changes
- modify production artifacts
- approve workflow continuation
- approve production deployment
- mark automation as human review

Write access requires an explicit user instruction such as `fix`, `implement`, `patch`, or `apply`. A request for `audit`, `review`, `investigate`, or `explain` is read-only unless the user later asks for changes.

When review findings are accepted, implementation should be done by a separate implementation step or agent with a filled agent change manifest.
