import requests
import json

BASE_URL = "http://localhost:8000/api/v1/commitments"

print("1. Ingesting emails...")
res = requests.post(f"{BASE_URL}/ingest")
print(res.json())

print("\n2. Fetching pending queue...")
pending = requests.get(f"{BASE_URL}/pending").json()
for action in pending:
    print(f"{action['commitment']['email_id']} -> {action['action']} | Review? {action['requires_human_approval']}")

print("\n3. Approving ID 1...")
approve = requests.post(f"{BASE_URL}/1/approve", json={"approved_by": "hari", "decision": "APPROVED"})
print(f"Status code: {approve.status_code}")

print("\n4. Testing double-approval lock (should fail)...")
fail_approve = requests.post(f"{BASE_URL}/1/approve", json={"approved_by": "hari", "decision": "APPROVED"})
print(f"Status code: {fail_approve.status_code} (Expected 409)")