# ntfy for MicroPython

A single-file client for [ntfy](https://ntfy.sh), the HTTP pub/sub service. It can publish messages, fetch missed messages, and stream new messages live. That is enough to send alerts from a device and to control the device remotely.

## How ntfy works

A topic is just a URL: `https://ntfy.sh/<topic>`.

- POST to it to publish.
- GET `/json` on it to receive. The connection stays open and the server pushes messages as they arrive.

There is no account or setup on the public server. That also means **anyone who knows the topic name can read and publish to it.** Use a long random topic name, or self-host and use a token.

## Install

Copy `ntfy.py` to the board:

It needs `requests`. Most current firmware has it as `urequests`; if the import fails:

```python
import mip
mip.install("requests")
```

Connect to Wi-Fi before using it.

## Quick start

```python
from ntfy import Ntfy

n = Ntfy("my-device-8f3k2x9q")

n.publish("Boot complete")

for msg in n.subscribe():
    print(msg["message"])
```

## API

### `Ntfy(topic, server="https://ntfy.sh", token=None)`

| Argument | Description |
|----------|-------------|
| `topic` | A topic name, or a list of names to receive from several topics at once. `publish()` always sends to the first one. |
| `server` | Base URL. Change it to use a self-hosted server. Plain `http://` works and uses much less RAM than HTTPS. |
| `token` | Access token for servers with access control. Sent as a Bearer token. |

### `publish(message, title=None, priority=None, tags=None, click=None, delay=None, actions=None)`

Sends a message. Returns the HTTP status code (`200` means success).

| Argument | Description |
|----------|-------------|
| `message` | Message body (str). |
| `title` | Notification title. ASCII only. |
| `priority` | `1` (min) to `5` (max). Default is `3`. |
| `tags` | List of tags. Known emoji names such as `"warning"` show as emoji in the app. |
| `click` | URL opened when the notification is tapped. |
| `delay` | Deliver later: `"30m"`, `"2h"`, or a Unix timestamp. |
| `actions` | List of action buttons in ntfy's short format (see below). |

### `poll(since="latest", **filters)`

Fetches cached messages and returns a list of message dicts. Does not keep a connection open.

`since` accepts:

- `"latest"`: only the most recent message
- a duration such as `"10m"` or `"1h"`
- a Unix timestamp
- a message ID: everything after that message
- `"all"`: everything the server still has cached

Large histories use a lot of RAM on a microcontroller. Prefer a short duration or a message ID over `"all"`.

### `subscribe(since=None, keepalive=False, **filters)`

A generator. Yields message dicts as they arrive. It ends when the connection closes, so it needs a reconnect loop (see below).

- `since`: same values as `poll()`. Default is new messages only.
- `keepalive`: if `True`, yields `None` each time the server sends a keepalive (about every 45 seconds). Use it to feed a watchdog.

### Filters

Both `poll()` and `subscribe()` accept filters. The server applies them, so unwanted messages never reach the device.

| Filter | Example |
|--------|---------|
| `priority` | `priority=[4, 5]` |
| `tags` | `tags="alarm"` |
| `title` | `title="Reboot"` |
| `message` | `message="restart"` |
| `id` | `id="abc123"` |

### Message dict

Fields you will use most:

| Key | Meaning |
|-----|---------|
| `id` | Unique message ID. Store it to resume with `since=`. |
| `time` | Unix timestamp. |
| `topic` | Topic the message came from. Useful when subscribed to several. |
| `message` | Body text. |
| `title`, `priority`, `tags` | Present only if set by the sender. |

## Recipes

### Remote control

```python
import machine
from ntfy import Ntfy

n = Ntfy("my-device-8f3k2x9q")

for msg in n.subscribe():
    cmd = msg["message"].strip()
    if cmd == "reboot":
        machine.reset()
    elif cmd == "status":
        n.publish("uptime ok", title="status")
```

Send commands from your phone or any shell:

```
curl -d "reboot" ntfy.sh/my-device-8f3k2x9q
```

Anyone with the topic name can send commands. Do not use this on a public topic for anything that matters.

### Reconnect loop with catch-up

`subscribe()` ends on any network drop. Remember the last message ID so nothing is missed.

```python
import time
from ntfy import Ntfy

n = Ntfy("my-device-8f3k2x9q")
last = None

while True:
    try:
        for msg in n.subscribe(since=last):
            last = msg["id"]
            print(msg["message"])
    except Exception as e:
        print("ntfy error:", e)
    time.sleep(5)
```

### Catch up after a reboot

After a reset `last` is lost. Fetch recent messages first:

```python
for msg in n.poll(since="10m"):
    print(msg["message"])
```

### Watchdog

A connection can die without the socket noticing. The server sends a keepalive every 45 seconds, so a watchdog longer than that detects a dead connection:

```python
from machine import WDT
wdt = WDT(timeout=120000)

for msg in n.subscribe(keepalive=True):
    wdt.feed()
    if msg is None:
        continue
    print(msg["message"])
```

If the connection dies, the keepalives stop, the watchdog is not fed, and the board resets.

### Alert only on important messages

```python
for msg in n.subscribe(priority=[4, 5], tags="alarm"):
    print(msg["message"])
```

### Action buttons

Buttons appear on the notification in the ntfy app. The short format is `type, label, url, key=value`.

```python
n.publish(
    "Router is down",
    title="Alert",
    priority=4,
    actions=[
        "view, Open router, http://192.168.0.1",
        "http, Reboot ESP32, http://192.168.0.50/reboot, method=POST",
    ],
)
```

An `http` button makes the phone send the request when tapped. Your device needs to be reachable from the phone for that to work.

### Delayed message

```python
n.publish("Check the router", delay="30m")
```

## Limits

- Not tested on every port or firmware version. If `stream=True` is not supported by your `requests`, update it with `mip`.
- HTTPS streaming needs a lot of RAM. On `MemoryError`, call `gc.collect()` before connecting, or use `http://` with a self-hosted server on your LAN.
- Header values must be ASCII. Put non-ASCII text in the message body, not in `title`.
- `subscribe()` does not reconnect by itself.
- `poll()` loads the whole response into memory.
- Public ntfy.sh has rate limits.
- Attachments and email forwarding are not implemented.