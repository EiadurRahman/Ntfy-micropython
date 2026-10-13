import json
import time
import ubinascii

try:
    import requests
except ImportError:
    import urequests as requests


class Ntfy:
    def __init__(self, topic, server="https://ntfy.sh", token=None, user=None, password=None):
        self.topic = topic
        self.server = server.rstrip("/")
        self.last_id = None
        self.auth = {}
        if token:
            self.auth["Authorization"] = "Bearer " + token
        elif user:
            cred = ubinascii.b2a_base64(("%s:%s" % (user, password)).encode()).decode().strip()
            self.auth["Authorization"] = "Basic " + cred

    def send(self, message, title=None, priority=None, tags=None, click=None, topic=None):
        headers = dict(self.auth)
        if title:
            headers["Title"] = title
        if priority:
            headers["Priority"] = str(priority)  # 1 (min) to 5 (urgent)
        if tags:
            headers["Tags"] = tags if isinstance(tags, str) else ",".join(tags)
        if click:
            headers["Click"] = click
        r = requests.post(
            "%s/%s" % (self.server, topic or self.topic),
            data=message.encode(),
            headers=headers,
        )
        status = r.status_code
        r.close()
        if status != 200:
            raise OSError("ntfy send failed: %d" % status)

    def poll(self, since=None):
        since = since or self.last_id or "all"
        r = requests.get(
            "%s/%s/json?poll=1&since=%s" % (self.server, self.topic, since),
            headers=self.auth,
        )
        if r.status_code != 200:
            status = r.status_code
            r.close()
            raise OSError("ntfy poll failed: %d" % status)
        text = r.text
        r.close()
        messages = []
        for line in text.split("\n"):
            if not line:
                continue
            msg = json.loads(line)
            self.last_id = msg["id"]
            if msg.get("event") == "message":
                messages.append(msg)
        return messages

