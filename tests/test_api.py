import hashlib
import pytest
from fastapi.testclient import TestClient
from operations_copilot.api import create_app

@pytest.fixture
def client(svc):
    tokens={hashlib.sha256(f'token-{who}'.encode()).hexdigest():who for who in ['alex','sam','riley','lee']}
    with TestClient(create_app(svc,tokens)) as c:yield c

def auth(who='alex'):return {'Authorization':f'Bearer token-{who}'}

def test_health(client):
    assert client.get('/health/live').status_code==200
    assert client.get('/health/ready').status_code==200

def test_auth_required(client):assert client.get('/api/me').status_code==401

def test_bad_token(client):assert client.get('/api/me',headers=auth('not-a-user')).status_code==401

def test_me(client):assert client.get('/api/me',headers=auth()).json()['role']=='operator'

def test_create_and_read(client):
    r=client.post('/api/runs',json={'message':'Review.','asset_id':'A17','hours':24},headers={**auth(),'Idempotency-Key':'api-request-0001'})
    assert r.status_code==201,r.text
    run=r.json()
    assert client.get('/api/runs/'+run['id'],headers=auth()).status_code==200
    assert client.get('/api/runs/'+run['id'],headers=auth('riley')).status_code==403
    assert client.get('/api/runs/'+run['id']+'/events',headers=auth('riley')).status_code==403

def test_cannot_supply_identity_or_approved_field(client):
    r=client.post('/api/runs',json={'message':'Review.','asset_id':'A17','hours':24,'actor':'sam','approved':True},headers={**auth(),'Idempotency-Key':'api-invalid-0001'})
    assert r.status_code==422

def test_bool_hours_rejected(client):
    r=client.post('/api/runs',json={'message':'Review.','asset_id':'A17','hours':True},headers={**auth(),'Idempotency-Key':'api-invalid-0002'})
    assert r.status_code==422

def test_cross_origin_mutation_rejected(client):
    r=client.post('/api/runs',json={'message':'Review.'},headers={**auth(),'Idempotency-Key':'api-origin-0001','Origin':'https://evil.invalid'})
    assert r.status_code==403

def test_host_restriction(client):assert client.get('/health/live',headers={'Host':'evil.invalid'}).status_code==400

def test_complete_api_workflow(client):
    r=client.post('/api/runs',json={'message':'Review.','asset_id':'A17','hours':24},headers={**auth(),'Idempotency-Key':'api-workflow-01'}).json()
    r=client.post(f"/api/runs/{r['id']}/prepare",headers=auth()).json()
    r=client.post(f"/api/runs/{r['id']}/decision",json={'decision':'approve','expected_version':r['version'],'proposal_hash':r['proposal']['hash']},headers=auth('sam')).json()
    response=client.post(f"/api/runs/{r['id']}/execute",headers=auth('sam'))
    assert response.status_code==200,response.text
    assert response.json()['status']=='SUCCEEDED'

def test_ui_served_with_security_headers(client):
    r=client.get('/')
    assert r.status_code==200
    assert 'Evidence before action' in r.text
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
