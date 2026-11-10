"""Approve edits to the open Set (WavRead Bridge 0.4.0): a person reads the code from Live's status bar.
usage: python3 tests/approve.py request          -> asks Live to show a one-time code in its status bar
       python3 tests/approve.py confirm CODE     -> grants with that code (2 minutes, one attempt)
       python3 tests/approve.py status
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from lt import call

cmd = sys.argv[1]
if cmd == "request":
    i = call("get_set_identity")
    print(json.dumps(call("authorize_set", file_path=i["file_path"], set_id=i["set_id"]), indent=1))
elif cmd == "confirm":
    print(json.dumps(call("confirm_authorization", code=sys.argv[2]), indent=1))
else:
    print(json.dumps(call("write_status"), indent=1))
