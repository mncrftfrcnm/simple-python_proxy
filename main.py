import argparse
import asyncio
import urllib.parse

async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    # Read the request line from the client
    request_line = await client_reader.readline()
    if not request_line:
        client_writer.close()
        return

    method, path, version = request_line.decode().strip().split(' ', 2)

    # Read headers
    headers = []
    while True:
        line = await client_reader.readline()
        if not line or line == b"\r\n":
            break
        headers.append(line)

    # Handle HTTPS CONNECT method (tunneling)
    if method.upper() == 'CONNECT':
        host, port = path.split(':', 1)
        port = int(port)
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
            # Send 200 Connection Established
            client_writer.write(f"{version} 200 Connection established\r\n\r\n".encode())
            await client_writer.drain()

            # Tunnel data between client and remote
            await asyncio.gather(
                pipe(client_reader, remote_writer),
                pipe(remote_reader, client_writer)
            )
        except Exception:
            client_writer.write(f"{version} 502 Bad Gateway\r\n\r\n".encode())
            await client_writer.drain()

    # Handle regular HTTP requests
    else:
        url = urllib.parse.urlsplit(path)
        host = url.hostname
        port = url.port or 80

        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)

            # Build and send the request line (relative path)
            relative_path = urllib.parse.urlunsplit(('', '', url.path or '/', url.query, ''))
            remote_writer.write(f"{method} {relative_path} {version}\r\n".encode())

            # Forward headers (drop Proxy-Connection header)
            for header in headers:
                if header.lower().startswith(b"proxy-connection:"):
                    continue
                remote_writer.write(header)
            # Ensure connection closes when done
            remote_writer.write(b"Connection: close\r\n\r\n")
            await remote_writer.drain()

            # Pipe data between client and remote
            await asyncio.gather(
                pipe(client_reader, remote_writer),
                pipe(remote_reader, client_writer)
            )
        except Exception:
            client_writer.write(f"{version} 502 Bad Gateway\r\n\r\n".encode())
            await client_writer.drain()

    client_writer.close()


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Copy data from reader to writer."""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def main(host: str, port: int):
    server = await asyncio.start_server(handle_client, host, port)
    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"[*] Serving on {addrs}")
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simple HTTP/HTTPS Proxy Server')
    parser.add_argument('--host', default='0.0.0.0', help='Interface to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8888, help='Port to listen on (default: 8888)')
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print('\n[!] Proxy server shutting down')
