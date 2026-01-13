
from datetime import datetime, timedelta
import json

now = datetime.now()
chart_labels = []

print("--- Simulating Chart Labels ---")
for i in range(6, -1, -1):
    d = now - timedelta(days=i)
    label = d.strftime("%d/%m")
    chart_labels.append(label)
    print(f"Index {i}: {label}")

json_output = json.dumps(chart_labels)
print(f"\nJSON Output: {json_output}")
print(f"Length: {len(chart_labels)}")
