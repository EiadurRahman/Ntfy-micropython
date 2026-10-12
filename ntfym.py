# ntfy.py - small async ntfy client for MicroPython (ESP32)
#
# Requires a MicroPython firmware with `asyncio.open_connection()` and TLS.
# API: Client.publish(), Client.poll(), Client.subscribe()
#
# This is a lightweight HTTP/1.1 implementation, not a general HTTP client.

import uasyncio as asyncio
import json

try:
    import ssl
except ImportError:
    ssl = None


class NtfyError(Exception):
    pass


class NtfyHTTPError(NtfyError):
    def __init__(self, status, reason, body=""):
        self.status = status
        self.reason = reason
        self.body = body
        NtfyError.__init__(
            self, "HTTP %s %s%s" % (
                status, reason, (": " + body) if body else ""
            )
        )


def _url_encode(value):
    """Small UTF-8 URL encoder suitable for query parameter values."""
    if not isinstance(value, bytes):
        value = str(value).encode("utf-8")
    out = []
    for b in value:
        if (48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122
                or b in (45, 46, 95, 126)):
            out.append(chr(b))
        elif b == 32:
            out.append("+")
        else:
            out.append("%%%02X" % b)
    return "".join(out)


def _header_value(value):
    """Encode ntfy metadata headers, including Unicode values."""
    if isinstance(value, (list, tuple)):
        value = ",".join(str(x) for x in value)
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class _ChunkedReader:
    """Decode HTTP chunked transfer encoding while exposing readline()."""

    def __init__(self, reader):
        self.reader = reader
        self.buf = b""
        self.done = False

    async def _next_chunk(self):
        if self.done:
            return
        line = await self.reader.readline()
        if not line:
            self.done = True
            return
        size_text = line.split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except Exception:
            raise NtfyError("Invalid HTTP chunk size")
        if size == 0:
            # Consume optional trailers and the final blank line.
            while True:
                trailer = await self.reader.readline()
                if not trailer or trailer in (b"\r\n", b"\n"):
                    break
            self.done = True
            return
        data = await self.reader.readexactly(size)
        ending = await self.reader.readexactly(2)
        if ending != b"\r\n":
            raise NtfyError("Invalid HTTP chunk terminator")
        self.buf += data

    async def readline(self):
        while b"\n" not in self.buf and not self.done:
            await self._next_chunk()
        if b"\n" in self.buf:
            pos = self.buf.find(b"\n") + 1
            line = self.buf[:pos]
            self.buf = self.buf[pos:]
            return line
        line = self.buf
        self.buf = b""
        return line


class _BodyReader:
    def __init__(self, reader, headers):
        self.reader = reader
        self.headers = headers
        transfer = headers.get("transfer-encoding", "").lower()
        self.chunked = "chunked" in transfer
        self.remaining = None
        if "content-length" in headers:
            try:
                self.remaining = int(headers["content-length"])
            except Exception:
                self.remaining = None
        self.chunk_reader = _ChunkedReader(reader) if self.chunked else None

    async def readall(self, limit=65536):
        if self.chunked:
            parts = []
            total = 0
            while True:
                line = await self.chunk_reader.readline()
                if not line:
                    break
                total += len(line)
                if total > limit:
                    raise NtfyError("HTTP response exceeded body limit")
                parts.append(line)
            return b"".join(parts)

        if self.remaining is not None:
            if self.remaining > limit:
                raise NtfyError("HTTP response exceeded body limit")
            data = await self.reader.readexactly(self.remaining)
            self.remaining = 0
            return data

        # Connection-close-delimited body.
        parts = []
        total = 0
        while True:
            chunk = await self.reader.read(1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise NtfyError("HTTP response exceeded body limit")
            parts.append(chunk)
        return b"".join(parts)

    async def readline(self, max_line=8192):
        if self.chunked:
            line = await self.chunk_reader.readline()
        elif self.remaining is not None:
            if self.remaining <= 0:
                return b""
            line = await self.reader.readline()
            if not line:
                self.remaining = 0
            else:
                self.remaining -= len(line)
        else:
            line = await self.reader.readline()
        if len(line) > max_line:
            raise NtfyError("Stream line exceeded maximum length")
        return line


class Client:
    """
    Async ntfy client.

    Example:
        client = Client("my-topic", token="tk_...", base_url="https://ntfy.sh")
        await client.publish("ESP32 online", title="Workshop", priority=3)
        messages = await client.poll(since="10m")

        async def on_message(event):
            print(event.get("message"))

        await client.subscribe(on_message)
    """

    def __init__(
        self,
        topic,
        base_url="https://ntfy.sh",
        token=None,
        username=None,
        password=None,
        timeout=15,
        reconnect_min=1,
        reconnect_max=60,
        max_body=65536,
    ):
        if not topic or "/" in topic or " " in topic:
            raise ValueError("topic must be a non-empty topic name, not a URL")
        if not base_url.startswith("http://") and not base_url.startswith("https://"):
            raise ValueError("base_url must start with http:// or https://")
        self.topic = topic
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.username = username
        self.password = password
        self.timeout = timeout
        self.reconnect_min = reconnect_min
        self.reconnect_max = reconnect_max
        self.max_body = max_body

        rest = self.base_url.split("://", 1)
        self.scheme = rest[0].lower()
        host_path = rest[1].split("/", 1)
        authority = host_path[0]
        self.base_path = "/" + host_path[1].rstrip("/") if len(host_path) > 1 else ""
        if ":" in authority:
            self.host, port_text = authority.rsplit(":", 1)
            self.port = int(port_text)
        else:
            self.host = authority
            self.port = 443 if self.scheme == "https" else 80

    def _auth_headers(self):
        if self.token:
            return {"Authorization": "Bearer " + self.token}
        if self.username is not None:
            raw = (str(self.username) + ":" + str(self.password or "")).encode("utf-8")
            import ubinascii
            return {"Authorization": "Basic " + ubinascii.b2a_base64(raw).strip().decode()}
        return {}

    async def _wait(self, awaitable):
        if self.timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, self.timeout)

    async def _open(self):
        tls = False
        if self.scheme == "https":
            if ssl is None:
                raise NtfyError("This firmware has no ssl module; HTTPS is unavailable")
            # MicroPython TLS support and certificate verification vary by firmware.
            # ssl=True asks the port for its default TLS configuration.
            tls = True
        try:
            return await self._wait(asyncio.open_connection(self.host, self.port, ssl=tls))
        except Exception as exc:
            raise NtfyError("Connection failed: %s" % exc)

    async def _request(self, method, path, body=b"", headers=None, stream=False):
        reader = writer = None
        headers = dict(headers or {})
        headers.update(self._auth_headers())
        if not isinstance(body, bytes):
            body = str(body).encode("utf-8")

        headers.setdefault("Host", self.host)
        headers.setdefault("User-Agent", "micropython-ntfy/0.1")
        headers.setdefault("Connection", "keep-alive" if stream else "close")
        if body:
            headers.setdefault("Content-Length", str(len(body)))
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        try:
            reader, writer = await self._open()
            request_path = self.base_path + path
            request = "%s %s HTTP/1.1\r\n" % (method, request_path)
            for key, value in headers.items():
                request += "%s: %s\r\n" % (key, _header_value(value))
            request += "\r\n"
            writer.write(request.encode("utf-8"))
            if body:
                writer.write(body)
            await self._wait(writer.drain())

            status_line = await self._wait(reader.readline())
            if not status_line:
                raise NtfyError("Server closed before sending an HTTP status")
            try:
                parts = status_line.decode().strip().split(" ", 2)
                status = int(parts[1])
                reason = parts[2] if len(parts) > 2 else ""
            except Exception:
                raise NtfyError("Invalid HTTP status line")

            response_headers = {}
            while True:
                line = await self._wait(reader.readline())
                if not line or line in (b"\r\n", b"\n"):
                    break
                if b":" in line:
                    key, value = line.split(b":", 1)
                    response_headers[key.decode().strip().lower()] = value.decode().strip()

            body_reader = _BodyReader(reader, response_headers)
            return status, reason, response_headers, body_reader, reader, writer
        except Exception:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
            raise

    async def publish(
        self, message, title=None, priority=None, tags=None,
        click=None, attach=None, filename=None, actions=None,
        icon=None, delay=None, email=None, markdown=None,
        headers=None
    ):
        """Publish a message. Raises NtfyHTTPError for non-2xx responses."""
        path = "/" + self.topic
        h = dict(headers or {})
        if title is not None:
            h["Title"] = title
        if priority is not None:
            if int(priority) < 1 or int(priority) > 5:
                raise ValueError("priority must be between 1 and 5")
            h["Priority"] = str(priority)
        if tags:
            h["Tags"] = tags
        if click:
            h["Click"] = click
        if attach:
            h["Attach"] = attach
        if filename:
            h["Filename"] = filename
        if actions:
            h["Actions"] = actions
        if icon:
            h["Icon"] = icon
        if delay:
            h["Delay"] = delay
        if email:
            h["Email"] = email
        if markdown is not None:
            h["Markdown"] = "yes" if markdown else "no"

        status, reason, rh, br, reader, writer = await self._request(
            "POST", path, body=message, headers=h
        )
        try:
            body = await self._wait(br.readall(self.max_body))
            if status < 200 or status >= 300:
                raise NtfyHTTPError(status, reason, body.decode("utf-8", "replace"))
            return {"status": status, "reason": reason, "body": body}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def poll(self, since="10m", limit=None):
        """
        Fetch cached messages and return parsed JSON event dictionaries.
        Defaults to the last 10 minutes to avoid downloading the entire cache.
        """
        query = "poll=1&since=" + _url_encode(since)
        if limit is not None:
            query += "&limit=" + _url_encode(limit)
        path = "/" + self.topic + "/json?" + query
        status, reason, rh, br, reader, writer = await self._request("GET", path)
        try:
            body = await self._wait(br.readall(self.max_body))
            if status < 200 or status >= 300:
                raise NtfyHTTPError(status, reason, body.decode("utf-8", "replace"))
            events = []
            for line in body.splitlines():
                if line.strip():
                    try:
                        events.append(json.loads(line.decode("utf-8")))
                    except Exception:
                        # Ignore malformed lines rather than losing all messages.
                        continue
            return events
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def subscribe(self, callback, since=None):
        """
        Subscribe forever and call callback(event) for each JSON event.
        Callback may be synchronous or async. Reconnects after network errors.
        Cancel the task running subscribe() to stop it.
        """
        delay = self.reconnect_min
        while True:
            writer = None
            try:
                path = "/" + self.topic + "/json"
                if since is not None:
                    path += "?since=" + _url_encode(since)
                status, reason, rh, br, reader, writer = await self._request(
                    "GET", path, stream=True
                )
                if status < 200 or status >= 300:
                    body = await self._wait(br.readall(self.max_body))
                    raise NtfyHTTPError(status, reason, body.decode("utf-8", "replace"))

                delay = self.reconnect_min
                while True:
                    # A quiet topic can legitimately send no event for a while;
                    # do not apply the short request timeout to this long-lived stream.
                    line = await br.readline()
                    if not line:
                        raise NtfyError("Subscription stream ended")
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    result = callback(event)
                    if hasattr(result, "__await__"):
                        await result
            except Exception as exc:
                print("ntfy subscription error:", exc)
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass

            await asyncio.sleep(delay)
            delay = min(delay * 2, self.reconnect_max)
