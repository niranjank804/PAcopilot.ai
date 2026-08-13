# IBM Planning Analytics MCP — commercial assessment

**Conclusion: `KEEP_AS_OPTIONAL_ADAPTER`**

Not because MCP is judged to be of low value — it has not been measured
— but because the evidence needed to promote it does not exist, and the
cost of keeping the adapter small is near zero while the cost of
building on it prematurely is high.

## The decision, stated plainly

| Option | Verdict |
|---|---|
| `PROMOTE_TO_CORE_CAPABILITY` | **No.** Nothing measured. Every capability the product ships is already validated on TM1 REST |
| `DISCOVERY_ONLY` | **Too weak.** Discovery already works and the adapter is written; deleting the invoke path buys nothing |
| `DEFER` | **No.** That would discard a working, security-reviewed adapter that costs nothing to keep |
| **`KEEP_AS_OPTIONAL_ADAPTER`** | **Yes.** Optional, off by default, licence-gated, blocked from writes, ~700 lines |

## Customer prerequisites

Every one of these must hold before a customer sees any MCP value:

1. Planning Analytics **3.1+** with the MCP server available.
2. **IBM Planning Analytics Assistant licence** — the repository states
   "Requires PA Agent feature addon entitlement". This is a separate
   purchase, not part of a standard PA licence.
3. OAuth configured, with an issuer PA-Copilot can reach.
4. Network path from PA-Copilot's cloud to the MCP endpoint — which for
   PA Local means opening an inbound route that does not exist today.
5. An administrator to configure and enable the connection.

**Item 2 is the commercially decisive one.** It means MCP can never be a
baseline PA-Copilot feature: any capability built on it is unavailable to
every customer without the addon. Anything positioned as core must
therefore work on TM1 REST regardless, which makes MCP an enhancement
path, not a foundation.

## Overlap with what already works

PA-Copilot's TM1 REST integration is validated and covers cube,
dimension, element, process, rule, dependency and security-group reads,
plus MDX. IBM's advertised MCP capabilities that overlap this set are
**redundant** — and worse than redundant, because they add an OAuth
dependency, a licence dependency, a network dependency and a second
latency profile to answer questions that are already answered.

The non-overlapping candidates are narrow but real:

- outlier detection
- impact analysis (PA-Copilot has a dependency graph, not statistical impact)
- asynchronous process execution and monitoring
- natural-language cube exploration as an IBM-side primitive

Whether IBM's versions beat PA-Copilot's own agent doing the same work
over TM1 REST is **unmeasured**. That is the entire remaining question.

## Operational cost of keeping it

Small and bounded, which is why the recommendation is to keep rather than
defer:

- Off unless an organization creates and enables a connection.
- No credentials in memory when unconfigured — the registry holds
  classes, not instances.
- Writes structurally impossible: no write capability exists in the enum.
- Unknown tools fail closed.
- ~700 lines with a security test suite already written.

## Support burden if promoted

This is what makes premature promotion expensive. Supporting MCP means
owning: OAuth token lifecycle and refresh, four deployment models with
different network topologies, IBM-side tool changes between releases
(with no published manifest to diff against), a second latency and
failure profile in every incident, and entitlement failures that look
like auth failures to customers.

None of that is worth taking on before knowing whether the four
non-overlapping capabilities are actually better.

## What would change the verdict

A single live, entitled environment and one afternoon:

1. Discover the real tool list.
2. Diff it against `src/tm1/` capabilities.
3. Benchmark the four non-overlapping capabilities against PA-Copilot's
   own agent output for the same question.
4. Measure latency and record permission differences.

If IBM's outlier detection and impact analysis are materially better
than what the agent produces over MDX, promote *those specific
capabilities* — not MCP wholesale. If they are comparable, MCP is
redundant and this adapter stays exactly as it is.
