# python-url-fragment-extractor


# Description

very easy. starts an asyncio server and waits to serve 1 page on localhost. once it gets a 'GET' connection, it serves up a page with some javascript that sends a POST message that contains the url fragments (if any) of the url.
The server then shuts itself down.

## Usage

fecther = UrlFragmentFetchServer()
  - you can change the timeout from 120 seconds
  - you can change the port from the default (1000)

fragments = fetcher.start()

You can then read the fragments again using fetcher.data()

You can also read fetcher.msg to return a string status message.
