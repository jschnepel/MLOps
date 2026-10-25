"""The orchestrator: one explicit LangGraph graph per run (AM-12 SA:207; docs/ARCHITECTURE.md §3).

`state` holds the graph's state and the per-run context, `nodes` the ten nodes, `build` the wiring generated from
the route table and the driver that stores each confirmed checkpoint id under the lease fence.
"""
