"""PADIEM Agent Resident — direct alias of the existing single kagent runner."""
from kagent.local_agent_resident_process import main

if __name__ == "__main__":
    raise SystemExit(main())
