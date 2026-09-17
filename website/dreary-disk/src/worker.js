import { handle } from "@astrojs/cloudflare/handler";
import { withVersionMetadata } from "./version-metadata.mjs";

export default {
  async fetch(request, env, context) {
    const response = await handle(request, env, context);
    return withVersionMetadata(response, env.CF_VERSION_METADATA?.id);
  },
};
