"""`python -m ops_worker`: poll jobs; health on 127.0.0.1:OPS_WORKER_HEALTH_PORT (default 8070)."""

from ops_worker.main import main

if __name__ == "__main__":
    main()
