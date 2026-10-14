import json

with open("data/resume_ready.json", "r") as f:
    profile = json.load(f)

# The logic of coverage_data
resume_json = {"skills": {"Frontend": [{"name": "React"}]}} # What if resume_json has dicts?

# Let's run a curl again and check the console output using a bash redirect!
