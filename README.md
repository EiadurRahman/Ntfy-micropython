# MicroPython Ntfy Client

A lightweight, robust MicroPython client class for [ntfy.sh](https://ntfy.sh/) (or self-hosted ntfy servers). It allows microcontrollers (like ESP32, ESP8266, or Raspberry Pi Pico W running MicroPython) to easily send push notifications and poll for incoming messages.

## Features

- **Lightweight & Compatible:** Works seamlessly with standard `requests` or MicroPython's `urequests`.
- **Rich Notifications:** Support for custom titles, priorities (1 to 5), emojis/tags, and click-through URLs.
- **Authentication Support:** Secure your requests using Access Tokens (Bearer) or Username/Password (Basic Auth).
- **Polling Capability:** Fetch recent or unread messages from a topic directly on your device.

---

## Installation

Simply copy the `Ntfy` class code into a file on your MicroPython device (e.g., `ntfy.py`) and import it when needed.

Ensure your microcontroller is connected to Wi-Fi and has access to `urequests` (usually built-in or installable via `upip`/`mip`).

---

## Quick Start

### 1. Sending a Simple Notification

```python
from ntfy import Ntfy

# Initialize with your topic name
client = Ntfy(topic="my_device_alerts")

# Send a basic message
client.send("Hello from MicroPython!")
```

### 2. Sending Advanced Notifications

You can customize titles, priorities, tags, and click actions:

```python
client.send(
    message="Sensor temperature exceeded threshold: 42°C",
    title="Warning: High Temp",
    priority=4,                # Priority ranges from 1 (min) to 5 (urgent)
    tags=["fire", "warning"],  # Emojis or keywords supported by ntfy
)
```

### 3. Polling for Messages

You can check your topic for incoming messages:

```python
messages = client.poll()
for msg in messages:
    print("Received:", msg.get("message"))
```

---

## API Reference

### `Ntfy(topic, server="https://ntfy.sh", token=None, user=None, password=None)`

Initializes the client.

- **`topic`** *(str)*: The default ntfy topic to publish/poll.
- **`server`** *(str, optional)*: Base URL of the ntfy server (defaults to `"https://ntfy.sh"`).
- **`token`** *(str, optional)*: Bearer token for authentication.
- **`user`** *(str, optional)*: Username for basic authentication.
- **`password`** *(str, optional)*: Password for basic authentication.

---

### `send(message, title=None, priority=None, tags=None, click=None, topic=None)`

Publishes a push notification to the server.

- **`message`** *(str)*: The body of the notification message.
- **`title`** *(str, optional)*: Title of the notification.
- **`priority`** *(int, optional)*: Priority level from `1` (min) to `5` (urgent).
- **`tags`** *(str or list, optional)*: Tags or emojis (e.g., `"warning"` or `["rotating_light", "alert"]`).
- **`click`** *(str, optional)*: URL to open when the notification is clicked.
- **`topic`** *(str, optional)*: Override the default topic for this specific message.

---

### `poll(since=None)`

Polls the topic for new messages.

- **`since`** *(str, optional)*: Timestamp or message ID to poll since (defaults to tracking the last seen message ID).
- **Returns:** A list of message dictionaries.

---

## License

This project is open-source and free to use under the MIT License.