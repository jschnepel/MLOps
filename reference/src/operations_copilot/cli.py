"""Run a deterministic, temporary, dependency-free reference demonstration."""
from pathlib import Path
import json
import tempfile
from .store import Store
from .synthetic import SyntheticOperations
from .service import ControlService

def main() -> None:
    with tempfile.TemporaryDirectory(prefix="operations-copilot-") as tmp:
        store = Store(Path(tmp) / "app.sqlite3")
        ops = SyntheticOperations(Path(tmp) / "destination.sqlite3")
        store.seed_actors(); ops.seed()
        svc = ControlService(store, ops)
        run = svc.create("alex", "Investigate A17 and prepare an incident.", "A17", None, "demo-request-001")
        print("1.", run["status"], "— time range needed")
        run = svc.clarify("alex", run["id"], "A17", 24, run["version"])
        run = svc.prepare("alex", run["id"])
        print("2.", run["status"], "— nothing submitted")
        run = svc.decide("sam", run["id"], run["proposal"]["hash"], run["version"], "approve")
        run = svc.execute("sam", run["id"], lose_response=True)
        print("3.", run["status"], "— response lost after destination commit")
        # Construct a new service instance to model restarting the application.
        svc = ControlService(Store(Path(tmp)/"app.sqlite3"), SyntheticOperations(Path(tmp)/"destination.sqlite3"))
        run = svc.reconcile("sam", run["id"])
        print("4.", run["status"], "—", run["result"]["incident_id"])
        print("5. Destination incident count:", ops.count_incidents())
        print(json.dumps({"mode": "deterministic test double", "events": svc.events("alex", run["id"])}, indent=2))

if __name__ == "__main__":
    main()
