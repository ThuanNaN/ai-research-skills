import json


def test_manifests_agree():
    plugin = json.load(open(".claude-plugin/plugin.json"))
    market = json.load(open(".claude-plugin/marketplace.json"))
    entry = market["plugins"][0]
    assert plugin["name"] == entry["name"] == "ai-research"
    assert plugin["version"] == entry["version"] == "0.1.0"
    assert market["name"] == "ai-research-skills"
    assert entry["source"] == "./"
    assert market["owner"]["name"]
