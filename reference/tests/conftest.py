from pathlib import Path
import pytest
from operations_copilot.store import Store
from operations_copilot.synthetic import SyntheticOperations
from operations_copilot.service import ControlService

@pytest.fixture
def svc(tmp_path):
    store=Store(tmp_path/'app.sqlite3'); store.seed_actors()
    ops=SyntheticOperations(tmp_path/'destination.sqlite3'); ops.seed()
    return ControlService(store,ops)

@pytest.fixture
def proposed(svc):
    run=svc.create('alex','Review the warning.','A17',24,'request-00001')
    return svc.prepare('alex',run['id'])

@pytest.fixture
def approved(svc,proposed):
    return svc.decide('sam',proposed['id'],proposed['proposal']['hash'],proposed['version'],'approve')
