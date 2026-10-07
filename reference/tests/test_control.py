from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from operations_copilot.domain import Conflict, Forbidden, InvalidInput, NotFound, UncertainOutcome, digest, validate_hours, validate_draft
from operations_copilot.models import DeterministicModel
from operations_copilot.service import ControlService
from operations_copilot.store import Store
from operations_copilot.synthetic import SyntheticOperations

@pytest.mark.parametrize('hours',[None,0,169,-1,True,1.5,'24'])
def test_invalid_hours(hours):
    with pytest.raises(InvalidInput):validate_hours(hours)

@pytest.mark.parametrize('hours',[1,24,168])
def test_valid_hours(hours):assert validate_hours(hours)==hours

def test_canonical_hash_order():assert digest({'b':1,'a':2})==digest({'a':2,'b':1})

def test_clarification_then_proposal(svc):
    r=svc.create('alex','Review warnings.','A17',None,'request-clarify')
    assert r['status']=='AWAITING_INPUT'
    r=svc.clarify('alex',r['id'],'A17',24,r['version'])
    r=svc.prepare('alex',r['id'])
    assert r['status']=='AWAITING_APPROVAL'
    assert svc.ops.count_incidents()==0

def test_stale_clarification(svc):
    r=svc.create('alex','Review.','A17',None,'request-stale-input')
    svc.clarify('alex',r['id'],'A17',24,r['version'])
    with pytest.raises(Conflict):svc.clarify('alex',r['id'],'A17',48,r['version'])

def test_success(svc,approved):
    r=svc.execute('sam',approved['id'])
    assert r['status']=='SUCCEEDED'
    assert r['result']['incident_id'].startswith('INC-')
    assert svc.ops.count_incidents()==1

def test_no_write_without_approval(svc,proposed):
    with pytest.raises(Forbidden):svc.execute('alex',proposed['id'])
    assert svc.ops.count_incidents()==0

def test_operator_cannot_approve(svc,proposed):
    with pytest.raises(Forbidden):svc.decide('alex',proposed['id'],proposed['proposal']['hash'],proposed['version'],'approve')

def test_reader_cannot_create(svc):
    with pytest.raises(Forbidden):svc.create('lee','Review.','A17',24,'reader-request')

def test_cross_team_asset_hidden(svc):
    with pytest.raises(NotFound):svc.create('riley','Review.','A17',24,'wrong-team-asset')

def test_cross_team_run_denied(svc,proposed):
    with pytest.raises(Forbidden):svc.get('riley',proposed['id'])

def test_cross_team_events_denied(svc,proposed):
    with pytest.raises(Forbidden):svc.events('jordan',proposed['id'])

def test_self_approval_denied(svc):
    r=svc.create('sam','Review.','A17',24,'self-approve-key');r=svc.prepare('sam',r['id'])
    with pytest.raises(Forbidden):svc.decide('sam',r['id'],r['proposal']['hash'],r['version'],'approve')

def test_proposal_hash_mismatch(svc,proposed):
    with pytest.raises(Conflict):svc.decide('sam',proposed['id'],'0'*64,proposed['version'],'approve')

def test_stale_version(svc,proposed):
    with pytest.raises(Conflict):svc.decide('sam',proposed['id'],proposed['proposal']['hash'],1,'approve')

def test_expired_proposal(svc,proposed):
    svc.clock=lambda:proposed['proposal']['expires_at']+1
    with pytest.raises(Conflict):svc.decide('sam',proposed['id'],proposed['proposal']['hash'],proposed['version'],'approve')

def test_expired_approval(svc,approved):
    svc.clock=lambda:approved['approval']['expires_at']+1
    with pytest.raises(Conflict):svc.execute('sam',approved['id'])
    assert svc.ops.count_incidents()==0

def test_approver_revoked_before_execution(svc,approved):
    with svc.store.tx() as db:db.execute("UPDATE actors SET role='reader' WHERE id='sam'")
    with pytest.raises(Forbidden):svc.execute('alex',approved['id'])
    assert svc.ops.count_incidents()==0

def test_requester_revoked_before_execution(svc,approved):
    with svc.store.tx() as db:db.execute("UPDATE actors SET active=0 WHERE id='alex'")
    with pytest.raises(Forbidden):svc.execute('sam',approved['id'])

def test_changed_evidence(svc,approved):
    svc.ops.change_asset_revision_for_test('A17','alpha')
    with pytest.raises(Conflict):svc.execute('sam',approved['id'])
    assert svc.ops.count_incidents()==0

def test_mutated_proposal(svc,approved):
    with svc.store.tx() as db:
        r=svc.store.run(db,approved['id']);r['proposal']['body']['asset_id']='B22';svc.store.save(db,r)
    with pytest.raises(Conflict):svc.execute('sam',approved['id'])

def test_duplicate_decision_and_execute(svc,proposed):
    r=svc.decide('sam',proposed['id'],proposed['proposal']['hash'],proposed['version'],'approve')
    again=svc.decide('sam',proposed['id'],proposed['proposal']['hash'],proposed['version'],'approve')
    assert r['version']==again['version']
    first=svc.execute('sam',r['id']);second=svc.execute('sam',r['id'])
    assert first['result']==second['result'];assert svc.ops.count_incidents()==1

def test_concurrent_destination_dedup(svc):
    body={'synthetic':True,'asset_id':'A17'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:svc.ops.create_incident('same-key',body),range(24)))
    assert len({r['incident_id'] for r in results})==1
    assert svc.ops.count_incidents()==1

def test_destination_idempotency_key_content_conflict(svc):
    svc.ops.create_incident('same-key',{'a':1})
    with pytest.raises(Conflict):svc.ops.create_incident('same-key',{'a':2})

def test_lost_response_restart_and_reconcile(svc,approved):
    r=svc.execute('sam',approved['id'],lose_response=True)
    assert r['status']=='OUTCOME_UNKNOWN'
    assert svc.ops.count_incidents()==1
    new=ControlService(Store(svc.store.path),SyntheticOperations(svc.ops.path))
    recovered=new.reconcile('sam',r['id'])
    assert recovered['status']=='SUCCEEDED';assert new.ops.count_incidents()==1

def test_unknown_cannot_blind_retry(svc,approved):
    r=svc.execute('sam',approved['id'],lose_response=True)
    with pytest.raises(Conflict):svc.execute('sam',r['id'])

def test_executing_without_receipt_stays_unknown(svc,approved):
    with svc.store.tx() as db:
        r=svc.store.run(db,approved['id']);r.update(status='EXECUTING',action_key='not-yet-committed');svc.store.save(db,r)
    with pytest.raises(UncertainOutcome):svc.reconcile('sam',r['id'])
    assert svc.ops.count_incidents()==0

def test_cancel_before_write(svc,approved):
    r=svc.cancel('alex',approved['id'],approved['version'])
    assert r['status']=='CANCELLED'
    with pytest.raises(Forbidden):svc.execute('sam',r['id'])

def test_cancel_does_not_undo_commit(svc,approved):
    r=svc.execute('sam',approved['id'])
    with pytest.raises(Conflict):svc.cancel('alex',r['id'],r['version'])
    assert svc.ops.count_incidents()==1

def test_rejection(svc,proposed):
    r=svc.decide('sam',proposed['id'],proposed['proposal']['hash'],proposed['version'],'reject')
    assert r['status']=='REJECTED'
    with pytest.raises(Forbidden):svc.execute('sam',r['id'])

def test_duplicate_request_key(svc):
    first=svc.create('alex','Review.','A17',24,'duplicate-request')
    second=svc.create('alex','Review.','A17',24,'duplicate-request')
    assert first['id']==second['id']
    with pytest.raises(Conflict):svc.create('alex','Changed.','A17',24,'duplicate-request')

def test_request_key_scoped_by_identity(svc):
    one=svc.create('alex','Review.','A17',24,'shared-request-key')
    two=svc.create('riley','Review.','B22',24,'shared-request-key')
    assert one['id']!=two['id']

def test_unknown_citation_rejected(svc):
    class BadModel:
        def draft(self,*args):return {'summary':'unsupported','evidence_refs':['PRIVATE:DOC'],'limitations':[]}
    svc.model=BadModel();r=svc.create('alex','Review.','A17',24,'bad-citation-key')
    with pytest.raises(InvalidInput):svc.prepare('alex',r['id'])
    assert svc.get('alex',r['id'])['status']=='READY_TO_DRAFT'

def test_model_cannot_add_authorization_field(svc):
    class BadModel:
        def draft(self,*args):return {'summary':'fine','evidence_refs':['SOP-014:v1:4.2'],'limitations':[],'approved':True}
    svc.model=BadModel();r=svc.create('alex','Review.','A17',24,'bad-permission-key')
    with pytest.raises(InvalidInput):svc.prepare('alex',r['id'])
    assert svc.ops.count_incidents()==0

def test_missing_documents_abstains(svc):
    with svc.ops.connect() as db:db.execute('DELETE FROM documents')
    r=svc.create('alex','Review.','A17',24,'missing-docs-key');r=svc.prepare('alex',r['id'])
    assert r['status']=='INSUFFICIENT_EVIDENCE';assert r['proposal'] is None

def test_cancellation_during_generation_discards_output(svc):
    r=svc.create('alex','Review.','A17',24,'cancel-during-model')
    class BlockingModel:
        def draft(self,message,evidence):
            svc.cancel('alex',r['id'],r['version'])
            return DeterministicModel().draft(message,evidence)
    svc.model=BlockingModel()
    with pytest.raises(Conflict):svc.prepare('alex',r['id'])
    assert svc.get('alex',r['id'])['status']=='CANCELLED'

def test_event_cursor(svc,approved):
    before=svc.events('alex',approved['id']);cursor=before[-1]['id']
    svc.execute('sam',approved['id'])
    after=svc.events('alex',approved['id'],cursor)
    assert all(e['id']>cursor for e in after)
    assert after[-1]['kind']=='action.committed'

def test_empty_and_oversize_message(svc):
    for text in ['', ' ', 'a'*4001]:
        with pytest.raises(InvalidInput):svc.create('alex',text,'A17',24,'bad-message-key')


def test_reader_cannot_reconcile(svc,approved):
    r=svc.execute('sam',approved['id'],lose_response=True)
    with pytest.raises(Forbidden):svc.reconcile('lee',r['id'])
