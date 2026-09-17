import { withVersionMetadata } from "../../website/dreary-disk/src/version-metadata.mjs";

export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);
    return withVersionMetadata(response, env.CF_VERSION_METADATA?.id);
  },
};
