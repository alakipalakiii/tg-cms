// Placeholder only.
// Actual Worker source must be copied here from Cloudflare.

export default {
  async fetch(): Promise<Response> {
    return new Response("Mahoon API Worker source placeholder.", {
      status: 501,
      headers: {
        "content-type": "text/plain; charset=utf-8"
      }
    });
  }
};
