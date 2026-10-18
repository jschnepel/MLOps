"""Run explicitly after installing integration dependencies. Missing imports FAIL."""
import asyncio
from mcp import Client
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from integrations.mcp_tools import build_mcp
from integrations.langgraph_workflow import build_graph


def test_mcp_lists_and_calls(svc):
    async def check():
        server=build_mcp(svc,lambda ctx:'alex')
        async with Client(server) as client:
            listed=await client.list_tools()
            assert {t.name for t in listed.tools}=={'get_asset_status','search_procedures','get_recent_alerts','create_incident'}
            result=await client.call_tool('get_asset_status',{'asset_id':'A17'})
            assert not result.is_error
            assert result.structured_content is not None
            denied=await client.call_tool('get_asset_status',{'asset_id':'B22'})
            assert denied.is_error
    asyncio.run(check())


def test_graph_approval_reads_authoritative_record(svc):
    r=svc.create('alex','Review.','A17',24,'graph-contract-01')
    graph=build_graph(svc,'alex',InMemorySaver())  # Unit contract only, NOT durability evidence.
    cfg={'configurable':{'thread_id':r['id']}}
    result=graph.invoke({'run_id':r['id']},cfg)
    assert '__interrupt__' in result
    r=svc.get('alex',r['id'])
    svc.decide('sam',r['id'],r['proposal']['hash'],r['version'],'approve')
    result=graph.invoke(Command(resume={'event_id':'decision-recorded'}),cfg)
    assert result['status']=='SUCCEEDED'
    assert svc.ops.count_incidents()==1
