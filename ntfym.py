"""Minimal ntfy client for MicroPython (also runs on CPython)."""
import json

try:
    import urequests as requests
except ImportError:
    import requests


def _quote(s):
    out = ""
    for b in str(s).encode():
        c = chr(b)
        if b < 128 and (c.isalpha() or c.isdigit() or c in "-_.~,"):
            out += c
        else:
            out += "%%%02X" % b
    return out


def _join(v):
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return v


class Ntfy:
    def __init__(self, topic, server="https://ntfy.sh", token=None):
        self.topics = [topic] if isinstance(topic, str) else list(topic)
        self.server = server.rstrip("/")
        self.headers = {"Authorization": "Bearer " + token} if token else {}

    def _url(self, topics, path="", **params):
        url = self.server + "/" + topics + path
        q = "&".join(
            k + "=" + _quote(_join(v)) for k, v in params.items() if v is not None
        )
        return url + "?" + q if q else url

    def publish(self, message, title=None, priority=None, tags=None,
                click=None, delay=None, actions=None):
        """Send a message to the first topic. Returns the HTTP status code."""
        h = dict(self.headers)
        if title:
            h["Title"] = title
        if priority:
            h["Priority"] = str(priority)
        if tags:
            h["Tags"] = _join(tags)
        if click:
            h["Click"] = click
        if delay:
            h["Delay"] = str(delay)
        if actions:
            h["Actions"] = "; ".join(actions)
        r = requests.post(self._url(self.topics[0]), data=message.encode(), headers=h)
        code = r.status_code
        r.close()
        return code

    def poll(self, since="latest", **filters):
        """Fetch cached messages and return them as a list of dicts."""
        url = self._url(",".join(self.topics), "/json", poll=1, since=since, **filters)
        r = requests.get(url, headers=self.headers)
        text = r.text
        r.close()
        msgs = [json.loads(line) for line in text.split("\n") if line]
        return [m for m in msgs if m.get("event") == "message"]

    def subscribe(self, since=None, keepalive=False, **filters):
        """Yield messages as they arrive. Ends when the connection drops.

        filters: priority, tags, title, message, id (str, or list for several values)
        keepalive: if True, yield None on each server keepalive (about every 45 s)
        """
        url = self._url(",".join(self.topics), "/json", since=since, **filters)
        r = requests.get(url, headers=self.headers, stream=True)
        try:
            while True:
                line = r.raw.readline()
                if not line:
                    break
                msg = json.loads(line)
                event = msg.get("event")
                if event == "message":
                    yield msg
                elif event == "keepalive" and keepalive:
                    yield None
        finally:
            r.close()