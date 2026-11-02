"""Run with: python3 test_listener.py"""
import listener

seen = {"sha": "a", "trigger": 1, "reply": None}
assert not listener.due(seen, {"sha": "a", "trigger": 1, "reply": None})
assert listener.due(seen, {"sha": "b", "trigger": 1, "reply": None}), "new commit"
assert listener.due(seen, {"sha": "a", "trigger": 2, "reply": None}), "new mention of the app"
assert listener.due(seen, {"sha": "a", "trigger": 1, "reply": 7}), "new thread reply"
assert listener.due({}, {"sha": "a", "trigger": None, "reply": None}), "never reviewed"

assert listener.update_queue([], ["x", "y"]) == ["x", "y"]
assert listener.update_queue(["y", "x"], ["x", "y", "z"]) == ["y", "x", "z"], "waiting PRs keep their place"
assert listener.update_queue(["y", "x"], ["x"]) == ["x"], "closed or handled PRs leave"

assert listener.queued_label(0) == "Queued: next up"
assert listener.queued_label(1) == "Queued: 1 review ahead"
assert listener.queued_label(3) == "Queued: 3 reviews ahead"
import re
listener.OWNER = "me"
listener.MENTION_RE = re.compile(r"@(hawksight-bot|hawksightbot)\b", re.I)
view = listener.pr_view({"headRefOid": "a", "reviewThreads": {"nodes": []}, "comments": {"nodes": [
    {"databaseId": 1, "body": "@hawksight-bot please", "author": {"login": "me"}},
    {"databaseId": 2, "body": "@HawksightBot again", "author": {"login": "me"}},
    {"databaseId": 3, "body": "@hawksight-botany is someone else", "author": {"login": "me"}},
]}})
assert view["trigger"] == 2, view
print("ok")
