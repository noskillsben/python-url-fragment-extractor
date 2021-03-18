import asyncio
import time
from urllib.parse import urlparse, unquote


class UrlFragmentFetchServer:
    """
    A module that runs a bare bones temporary localhost server to retrieve OAuth tokens in redirect urls

    This module was created for the use case of a Twitch.com streamer registering their own app with a localhost
    redirect. The Streamer then needs to authenticates themselves as a user of the app to access the api.
    With this module, the process is seamless from the end user as they authorize on twitch.com and then are redirected
    to a page that tells them if the app grabbed the token. no need to copy/paste the url or anything else.

    The value returned is a dict of url fragments.
    """
    def __init__(self, timeout: int = 120, port: int = 1000):

        """
        Use of an instance is url = .start() (results also in .data, you can check .msg() for status update in async

        Keyword arguments:
        timeout -- How long should the server stay open (in seconds) the default is 2 minutes.
        port -- which port to use for localhost. THIS MUST BE THE SAME PORT AS IN THE OAUTH's SERVICES registered url.
        """

        # self._keep_running is used for async server shutdown from multiple methods
        # self _connected keeps the server from timing out if there is an active connection
        # _timeout_time is just a timestamp to check against.
        # port is used in the html block and when starting the server.
        # registering the server as a variable lets a separate coroutine shut the server down.
        # data will contain the raw url parameters
        # msg is used for status messages since the module runs async
        self._keep_running = True
        self._connected = False
        self._timeout_time = time.time() + timeout
        self._port = port
        self._server = None
        self.data = None
        self.msg = None

    async def __time_out_shutdown(self):
        # TODO Check to make sure this ends when the server shutdown ends. else run it in another loop on another thread
        """Simple function that ensures the server shuts down if there is no connection for a while"""

        # loops until it times out but stays in the loop if there's a connection even after the timeout time.
        # self._connected should be set to False at the end of the connection handler.
        while self._keep_running or self._connected:
            await asyncio.sleep(1)
            if time.time() >= self._timeout_time:
                self.msg = 'Took too long to be redirected to the localhost page.'
                self._keep_running = False

        self._server.close()
        await self._server.wait_closed()

    def __get_html_block(self):
        """Just holds the html string for easy editing in the future."""
        # if multiple html pages are needed in the future this can be used as a template
        # FYI {{ }} to avoid having the javascript think it's a python var. Also no need to do anything else to remove
        # the double curly brackets.
        html_string = f"""
                                <html>
                                <head>
                                    <!-- import jquery to send info back to server -->
                                    <script
                                        src="https://code.jquery.com/jquery-3.6.0.min.js"
                                        integrity="sha256-/xUj+3OJU5yExlq6GSYGSHk7tPXikynS7ogEvDej/m4="
                                        crossorigin="anonymous">
                                    </script>
                                    <script type="text/javascript">
                                        $(document).ready(function(){{
                                            // Incredibly simple, simply grabs the whole url, posts it and replace the
                                            // test in the p tag with the response from the server.
                                            params = window.location.href;
                                            $.post("http://localhost:{self._port}", params,function(status){{
                                                $("#msg").text(status);
                                            }});
                                            
                                        }});
                                            
                                    </script>
                                </head>
                                <body>
                                <p id="msg">Retrieving token.</p>
                                </body>
                                </html>
                            """
        html_byte = html_string.encode()
        return html_byte

    async def __handle_connection(self, reader, writer):
        """
        Function that checks conn to browser, sends html, receives the url then sends a message back to the page.

        Keyword arguments:
            reader -- asyncio StreamReader object auto generated when _connected
            writer -- asyncio StreamWriter object auto generated when _connected
        """
        # flip the _connected flag
        self._connected = True

        # Start by awaiting some data and seeing if it's a Get request (browser connecting) or POST (page sending url)
        data = await reader.readline()
        msg = data.decode()
        # print(data)
        if msg.startswith('GET'):
            # TODO Check to make sure reader needs to be read to empty the buffer.
            await reader.readuntil(b'\r\n')
            # print(data)

            # send the simplest headers possible
            writer.write(b'HTTP/1.0 200 OK\n')
            writer.write(b'Content-Type: text/html\n')
            writer.write(b'\n')

            # get and send the html block.
            writer.write(self.__get_html_block())

            # wind down the writer.
            # TODO double check to see if the writer actually needs to be closed at this spot.
            await writer.drain()
            writer.close()
            # flip the _connected flag
            self._connected = False

        elif msg.startswith('POST'):
            # if the request is a post, drain reader into data.
            # TODO maybe make this more robust than just read(). Not really needed though
            data = await reader.read(4096)

            # we then try to get the fragments so we know to return a success or failure message as a response to the
            # post request.
            response_msg = b''
            try:
                # The data should be after a \r\n\r\n so we split and pick the last split up.
                returned_url = urlparse(data.split(b'\r\n\r\n')[-1])
                # Then it's split the fragments into lists. ALso turned from byte to string at the same time
                returned_fragments = returned_url.fragment.decode().split('&')

                # Final data is a dictionary of fragments so it will be easy for the app to verify the correct data
                # was returned.
                final_data = {}
                for fragment in returned_fragments:
                    decoded_fragment = unquote(fragment)
                    fragment_pair = decoded_fragment.split('=')
                    final_data[fragment_pair[0]] = fragment_pair[1]

                self.data = final_data
                self.msg = 'Successfully obtained url fragments'

                # A successful message is sent back in response to the POST
                response_msg = b'Information has been retrieved. You can now close this page.'
            except:
                # TODO better exception handling.
                # If anything fails a failure is sent back to the POST request (The POST is successful but whatever we
                # got was wrong)
                response_msg = b'Something went wrong. See application for detail\nYou can now close this page.'
                self.msg = 'Something went wrong when retrieving the url fragments'
            finally:
                # Response to the POST request.
                writer.write(b'HTTP/1.1 200 OK\nContent-Type: text/html\n\n' + response_msg)

            # The writer is closed and drained and flip the flags to stop the server
            await writer.drain()
            writer.close()
            self._keep_running = False
            self._connected = False

    async def __start_server(self):
        """Asyncio "main" async coroutine starts the server in server_forever mode"""

        # start the server on localhost with the port.
        server = await asyncio.start_server(
            client_connected_cb=self.__handle_connection,
            host='localhost',
            port=self._port
        )

        # save the server to self.
        self._server = server

        # register the auto shutdown coroutine.
        asyncio.ensure_future(self.__time_out_shutdown())

        # The serve forever needs to be in a try to avoid the futures error when shutting down (might be windows bug)
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass

    def start(self):
        """Starts listening on localhost until it times out or until it returns Url fragments in a dict."""
        asyncio.run(self.__start_server())
        return self.data


if __name__ == '__main__':
    print('http://localhost:1000/#test=1&test2=True')
    urlfragmentfetcher = UrlFragmentFetchServer()
    fragments = urlfragmentfetcher.start()
    print(urlfragmentfetcher.msg, fragments, sep='\n')
