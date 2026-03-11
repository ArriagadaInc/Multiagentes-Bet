
import re

with open("pipeline_last_run.log", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

# YouTube Channel IDs start with UC followed by 22 chars
# They were URL encoded as %2C (comma) in the log
matches = re.findall(r"UC[a-zA-Z0-9_-]{22}", content)
unique_ids = list(set(matches))

print(f"Total unique channel IDs found in log: {len(unique_ids)}")
print("\nIDs for Whitelist:")
print(",".join(unique_ids))
