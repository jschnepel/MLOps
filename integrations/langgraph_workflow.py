"""LangGraph integration example. Requires the integration extras; not executed here.

The authenticated API records clarifications/decisions in ControlService BEFORE
resuming the graph. A resume payload is a wake-up signal, not an approval grant.
The caller must serialize this graph per run and use run_id as thread_id.
"""
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt
from operations_copilot.service import ControlService
from operations_copilot.domain import Conflict

class RunState(TypedDict, total=False):
    run_id: str
    status: str


def build_graph(service: ControlService, requester_id: str, checkpointer):
    # requester_id is supplied by trusted application context, NEVER model output.
    def inspect(state):
        run=service.get(requester_id,state['run_id'])
        return {'status':run['status']}

    def await_input(state):
        interrupt({'kind':'clarification','run_id':state['run_id'],
                   'message':'Provide the asset and time range through the authenticated API.'})
        run=service.get(requester_id,state['run_id'])
        if run['status'] not in {'READY_TO_DRAFT','CANCELLED'}:
            raise Conflict('No authoritative clarification was recorded.')
        return {'status':run['status']}

    def prepare(state):
        run=service.prepare(requester_id,state['run_id'])
        return {'status':run['status']}

    def await_decision(state):
        run=service.get(requester_id,state['run_id'])
        interrupt({'kind':'approval','run_id':run['id'],'proposal':run['proposal']})
        # Deliberately ignore resume content. Authorization lives in the database.
        run=service.get(requester_id,state['run_id'])
        if run['status'] not in {'APPROVED','REJECTED','CANCELLED','SUCCEEDED'}:
            raise Conflict('No authoritative decision was recorded.')
        return {'status':run['status']}

    def execute(state):
        run=service.execute(requester_id,state['run_id'])
        return {'status':run['status']}

    graph=StateGraph(RunState)
    for name,fn in [('inspect',inspect),('await_input',await_input),('prepare',prepare),
                    ('await_decision',await_decision),('execute',execute)]:graph.add_node(name,fn)
    graph.add_edge(START,'inspect')
    graph.add_conditional_edges('inspect',lambda s:s['status'],{
        'AWAITING_INPUT':'await_input','READY_TO_DRAFT':'prepare',
        'AWAITING_APPROVAL':'await_decision','APPROVED':'execute',
        'CANCELLED':END,'REJECTED':END,'SUCCEEDED':END,'INSUFFICIENT_EVIDENCE':END,
    })
    graph.add_conditional_edges('await_input',lambda s:s['status'],{'READY_TO_DRAFT':'prepare','CANCELLED':END})
    graph.add_conditional_edges('prepare',lambda s:s['status'],{'AWAITING_APPROVAL':'await_decision','INSUFFICIENT_EVIDENCE':END})
    graph.add_conditional_edges('await_decision',lambda s:s['status'],{'APPROVED':'execute','REJECTED':END,'CANCELLED':END,'SUCCEEDED':END})
    graph.add_edge('execute',END)
    return graph.compile(checkpointer=checkpointer)
